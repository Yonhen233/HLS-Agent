from pathlib import Path

from dl_op_to_hls.main_agent.agent import MainAgent
from dl_op_to_hls.main_agent.runtime import PlanExecuteReactRuntime
from dl_op_to_hls.main_agent.workflow import run_task


def test_runtime_plan_execute_react_flow(temp_workspace):
    state = run_task(str(temp_workspace / "examples" / "dense_operator.json"), agent=MainAgent(temp_workspace, console=False))
    assert (temp_workspace / "runs" / state.run_id / "todos.json").exists()
    assert state.todos


def test_runtime_react_step_recorded(temp_workspace):
    state = run_task(str(temp_workspace / "examples" / "dense_operator.json"), agent=MainAgent(temp_workspace, console=False))
    assert any(item.react_steps for item in state.todos)


def test_runtime_reflector_adds_fallback_todo(temp_workspace):
    state = run_task(str(temp_workspace / "examples" / "dense_operator.json"), agent=MainAgent(temp_workspace, console=False))
    assert any(item.title == "Generate fallback HLS template" for item in state.todos)


def test_runtime_fallback_success_not_downgraded_by_hls4ml_warning(temp_workspace):
    state = run_task(str(temp_workspace / "examples" / "dense_operator.json"), agent=MainAgent(temp_workspace, console=False))
    assert state.selected_path == "fallback_template_path"
    assert state.report["status"] == "success"
    assert state.status == "success"


def test_runtime_vivado_missing_marks_todo_skipped(temp_workspace, monkeypatch):
    monkeypatch.setenv("DL_OP_TO_HLS_MOCK_VIVADO", "0")
    agent = MainAgent(temp_workspace, console=False)
    state = run_task(str(temp_workspace / "examples" / "dense_operator.json"), agent=agent)
    synth_todo = next(item for item in state.todos if item.title == "Run Vivado HLS synthesis")
    assert synth_todo.status == "skipped"


def test_runtime_partial_success(temp_workspace, monkeypatch):
    monkeypatch.setenv("DL_OP_TO_HLS_MOCK_VIVADO", "0")
    agent = MainAgent(temp_workspace, console=False)
    state = run_task(str(temp_workspace / "examples" / "dense_operator.json"), agent=agent)
    assert state.status == "partial_success"


def test_runtime_reflects_hls4ml_failure_by_assigned_tool_not_title(temp_workspace):
    agent = MainAgent(temp_workspace, console=False)
    runtime = PlanExecuteReactRuntime(agent)
    state = runtime.initialize(str(temp_workspace / "examples" / "mnist_tiny_cnn.json"))
    runtime.todo_manager.create_from_plan(state.run_id, ["Validate task schema"], state.task)
    config_todo = runtime.todo_manager.append_item(
        title="Generate hls4ml configuration",
        description="LLM-authored title variant.",
        priority=2,
        assigned_tool="hls4ml.generate_config",
        dependencies=[],
        inputs={"task": state.task},
    )
    runtime.todo_manager.append_item(
        title="Create Vivado HLS project",
        description="Should be blocked by graph rewrite recovery.",
        priority=3,
        assigned_tool="vivado.create_project",
        dependencies=[config_todo.id],
        inputs={"task": state.task},
    )
    state.todos = runtime.todo_manager.todo_list.items

    runtime.reflect(
        state,
        config_todo,
        {
            "status": "completed_with_warning",
            "error_type": "HLS4MLConversionError",
            "observation": {"errors": [{"message": "ERROR: Unsupported operation type: Shape"}]},
        },
    )

    assert any(item.assigned_tool == "graph_rewrite.rewrite" for item in runtime.todo_manager.todo_list.items)
    assert any(
        item.assigned_tool == "vivado.create_project" and item.status == "cancelled"
        for item in runtime.todo_manager.todo_list.items
    )


def test_runtime_executes_graph_rewrite_by_assigned_tool_not_title(temp_workspace):
    agent = MainAgent(temp_workspace, console=False)
    runtime = PlanExecuteReactRuntime(agent)
    state = runtime.initialize(str(temp_workspace / "examples" / "resnet18_boundary.json"))
    runtime.todo_manager.create_from_plan(state.run_id, ["Validate task schema"], state.task)
    todo = runtime.todo_manager.append_item(
        title="Rewrite graph to detect unsupported operators",
        description="LLM-authored title variant.",
        priority=2,
        assigned_tool="graph_rewrite.rewrite",
        dependencies=[],
        inputs={"task": state.task},
    )
    state.todos = runtime.todo_manager.todo_list.items

    observation = runtime._execute_todo_actions(state, todo)

    assert observation["status"] == "completed"
    assert observation["action"]["tool"] == "graph_rewrite.rewrite"
    assert todo.status == "completed"


def test_runtime_reuses_existing_unsupported_report_todo_after_graph_rewrite(temp_workspace):
    agent = MainAgent(temp_workspace, console=False)
    runtime = PlanExecuteReactRuntime(agent)
    state = runtime.initialize(str(temp_workspace / "examples" / "resnet18_boundary.json"))
    runtime.todo_manager.create_from_plan(state.run_id, ["Validate task schema"], state.task)
    graph_todo = runtime.todo_manager.append_item(
        title="Attempt graph rewriting to prepare unsupported handling",
        description="LLM-authored boundary title.",
        priority=2,
        assigned_tool="graph_rewrite.rewrite",
        dependencies=[],
        inputs={"task": state.task},
    )
    report_todo = runtime.todo_manager.append_item(
        title="Write detailed unsupported report",
        description="LLM-authored report title.",
        priority=3,
        assigned_tool="report.write_unsupported",
        dependencies=[],
        inputs={},
    )
    state.todos = runtime.todo_manager.todo_list.items

    runtime.reflect(
        state,
        graph_todo,
        {
            "status": "completed",
            "action": {"tool": "graph_rewrite.rewrite"},
            "observation": {
                "status": "success",
                "implemented": False,
                "recommendation": "No rewrite rule matched.",
            },
        },
    )

    report_todos = [
        item for item in runtime.todo_manager.todo_list.items if item.assigned_tool == "report.write_unsupported"
    ]
    assert report_todos == [report_todo]
    assert graph_todo.id in report_todo.dependencies
    assert report_todo.inputs["reason"] == "No rewrite rule matched."
