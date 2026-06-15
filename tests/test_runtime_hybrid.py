from pathlib import Path

from dl_op_to_hls.main_agent.agent import MainAgent
from dl_op_to_hls.main_agent.reflector import update_status_from_todos
from dl_op_to_hls.main_agent.runtime import PlanExecuteReactRuntime
from dl_op_to_hls.main_agent.state import AgentState
from dl_op_to_hls.main_agent.todo import TodoItem
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


def test_runtime_timing_failed_is_partial_success_even_when_function_verified():
    state = AgentState(
        run_id="timing_failed",
        task={"task_type": "operator", "name": "matmul"},
        status="initialized",
        plan=[],
        selected_path="fallback_template_path",
        report={"status": "success", "timing": {"met": False}},
        verification={"status": "csim_passed", "passed": True, "mode": "golden_testbench"},
    )
    state.todos = [
        TodoItem(
            id="todo_001",
            title="Run Vivado HLS synthesis",
            description="Run synthesis",
            status="completed_with_warning",
            priority=1,
            dependencies=[],
            assigned_tool="vivado.run_csynth",
            assigned_specialist="VivadoSpecialist",
            inputs={},
            outputs={"summary": "timing was not met"},
            error=None,
        )
    ]
    update_status_from_todos(state)
    assert state.status == "partial_success"


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


def test_unsupported_path_completed_workflow_remains_partial_success():
    state = AgentState(run_id="r1", task={"task_type": "model", "name": "resnet"}, status="initialized")
    state.selected_path = "unsupported_path"
    state.report = {"status": "missing"}
    state.todos = [
        TodoItem(
            id="todo_001",
            title="Write Unsupported Report",
            description="Write Unsupported Report",
            status="completed",
            priority=1,
            dependencies=[],
            assigned_tool="report.write_unsupported",
            assigned_specialist=None,
            inputs={},
            outputs={"status": "success"},
            error=None,
        )
    ]

    update_status_from_todos(state)

    assert state.status == "partial_success"


def test_completed_model_without_selected_path_is_not_success():
    state = AgentState(run_id="r1", task={"task_type": "model", "name": "qonnx"}, status="initialized")
    state.report = {"status": "missing"}
    state.todos = [
        TodoItem(
            id="todo_001",
            title="Generate suggestions only",
            description="Invalid shortcut plan.",
            status="completed",
            priority=1,
            dependencies=[],
            assigned_tool="suggestion.suggest_optimization",
            assigned_specialist="OptimizationSpecialist",
            inputs={},
            outputs={"status": "success"},
            error=None,
        )
    ]

    update_status_from_todos(state)

    assert state.status == "partial_success"


def test_hls4ml_path_with_missing_report_is_partial_success():
    state = AgentState(run_id="r1", task={"task_type": "model", "name": "mlp"}, status="initialized")
    state.selected_path = "hls4ml_path"
    state.report = {"status": "missing"}
    state.todos = [
        TodoItem(
            id="todo_001",
            title="Convert with hls4ml",
            description="Converted model.",
            status="completed",
            priority=1,
            dependencies=[],
            assigned_tool="hls4ml.convert",
            assigned_specialist="HLS4MLSpecialist",
            inputs={},
            outputs={"status": "success"},
            error=None,
        )
    ]

    update_status_from_todos(state)

    assert state.status == "partial_success"
