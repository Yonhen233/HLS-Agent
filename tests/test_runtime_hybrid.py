from pathlib import Path

from dl_op_to_hls.main_agent.agent import MainAgent
from dl_op_to_hls.main_agent.reflector import update_status_from_todos
from dl_op_to_hls.main_agent.runtime import PlanExecuteReactRuntime, _load_json
from dl_op_to_hls.main_agent.state import AgentState
from dl_op_to_hls.main_agent.todo import TodoItem
from dl_op_to_hls.main_agent.workflow import run_task


def test_runtime_plan_execute_react_flow(temp_workspace):
    state = run_task(str(temp_workspace / "examples" / "dense_operator.json"), agent=MainAgent(temp_workspace, console=False))
    assert (temp_workspace / "runs" / state.run_id / "todos.json").exists()
    assert state.todos


def test_runtime_load_json_accepts_utf8_bom(tmp_path):
    task_path = tmp_path / "task.json"
    task_path.write_text('{"task_type": "operator", "name": "dense"}', encoding="utf-8-sig")

    assert _load_json(task_path)["task_type"] == "operator"


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
    monkeypatch.setattr(
        "dl_op_to_hls.adapters.vivado_hls_adapter.VivadoHLSAdapter._resolve_vivado_executable",
        lambda self, configured_path=None: None,
    )
    agent = MainAgent(temp_workspace, console=False)
    state = run_task(str(temp_workspace / "examples" / "dense_operator.json"), agent=agent)
    synth_todo = next(item for item in state.todos if item.title == "Run Vivado HLS synthesis")
    assert synth_todo.status == "skipped"


def test_runtime_partial_success(temp_workspace, monkeypatch):
    monkeypatch.setenv("DL_OP_TO_HLS_MOCK_VIVADO", "0")
    monkeypatch.setattr(
        "dl_op_to_hls.adapters.vivado_hls_adapter.VivadoHLSAdapter._resolve_vivado_executable",
        lambda self, configured_path=None: None,
    )
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


def test_pipeline_status_distinguishes_synthesis_and_functional_ready():
    from dl_op_to_hls.main_agent.status import compute_pipeline_status

    state = AgentState(run_id="r1", task={"task_type": "operator", "name": "matmul"}, status="partial_success")
    state.selected_path = "fallback_template_path"
    state.hls_project_dir = "runs/r1/generated"
    state.report = {"status": "success", "timing": {"met": False}}
    state.verification = {"status": "csim_passed", "passed": True, "mode": "golden_testbench"}

    pipeline = compute_pipeline_status(state)

    assert pipeline["conversion_success"] is True
    assert pipeline["synthesis_success"] is True
    assert pipeline["functional_verified"] is True
    assert pipeline["deployment_ready_candidate"] is False
    assert pipeline["level"] == "functional_verified"


def test_superseded_repair_cancellations_do_not_downgrade_deployment_ready_status():
    state = AgentState(run_id="r1", task={"task_type": "operator", "name": "matmul"}, status="partial_success")
    state.selected_path = "llm_candidate_path"
    state.report = {"status": "success", "timing": {"met": True}}
    state.verification = {"status": "csim_passed", "passed": True, "mode": "golden_testbench"}
    state.pipeline_status = {
        "deployment_ready_candidate": True,
        "timing_met": True,
    }
    state.todos = [
        TodoItem(
            id="todo_001",
            title="Old Vivado synthesis",
            description="Old chain.",
            status="cancelled",
            priority=1,
            dependencies=[],
            assigned_tool="vivado.run_csynth",
            assigned_specialist="VivadoSpecialist",
            inputs={},
            outputs=None,
            error={"message": "Verification failed; a repaired LLM candidate must be generated before synthesis."},
        ),
        TodoItem(
            id="todo_002",
            title="Repaired synthesis",
            description="New chain.",
            status="completed",
            priority=2,
            dependencies=[],
            assigned_tool="vivado.run_csynth",
            assigned_specialist="VivadoSpecialist",
            inputs={},
            outputs={"status": "success"},
            error=None,
        ),
    ]

    update_status_from_todos(state)

    assert state.status == "success"


def test_parameter_advice_applies_missing_values_without_overriding_existing_values():
    from dl_op_to_hls.main_agent.runtime import PlanExecuteReactRuntime

    state = AgentState(
        run_id="r1",
        task={
            "task_type": "model",
            "name": "mnist_mlp_demo",
            "hls4ml": {"precision": "fixed<12,4>"},
            "target": {},
        },
    )
    state.parameter_advice = {
        "recommended_updates": {
            "hls4ml": {"precision": "fixed<8,3>", "reuse_factor": 512, "strategy": "Resource"},
            "target": {"clock_period": 10},
        }
    }

    runtime = PlanExecuteReactRuntime.__new__(PlanExecuteReactRuntime)
    runtime._apply_parameter_advice(state)

    assert state.task["hls4ml"]["precision"] == "fixed<12,4>"
    assert state.task["hls4ml"]["reuse_factor"] == 512
    assert state.task["hls4ml"]["strategy"] == "Resource"
    assert state.task["target"]["clock_period"] == 10
    assert state.parameter_advice["proposed_updates"]["hls4ml"]["precision"] == "fixed<8,3>"


def test_candidate_repair_attempts_read_task_override(monkeypatch):
    from dl_op_to_hls.main_agent.runtime import PlanExecuteReactRuntime

    monkeypatch.setenv("DL_OP_TO_HLS_LLM_MAX_REPAIR_ATTEMPTS", "2")
    runtime = PlanExecuteReactRuntime.__new__(PlanExecuteReactRuntime)
    state = AgentState(
        run_id="r1",
        task={
            "task_type": "operator",
            "name": "scale_shift_llm",
            "llm_candidate": {"max_repair_attempts": 6},
        },
    )

    assert runtime._max_candidate_repair_attempts(state) == 6


def test_llm_candidate_timing_failure_appends_repair_chain(temp_workspace):
    agent = MainAgent(temp_workspace, console=False)
    runtime = PlanExecuteReactRuntime(agent)
    state = runtime.initialize(str(temp_workspace / "examples" / "dense_llm_candidate.json"))
    runtime.todo_manager.create_from_plan(state.run_id, ["Seed"], state.task)
    initial = runtime.todo_manager.append_item(
        title="Generate LLM candidate HLS",
        description="Initial candidate.",
        priority=1,
        assigned_tool="llm.generate_hls_candidate",
        dependencies=[],
        inputs={},
    )
    initial.status = "completed"
    synth = runtime.todo_manager.append_item(
        title="Run Vivado synthesis",
        description="Synthesis produced timing warning.",
        priority=2,
        assigned_tool="vivado.run_csynth",
        assigned_specialist="VivadoSpecialist",
        dependencies=[initial.id],
        inputs={},
    )
    parse = runtime.todo_manager.append_item(
        title="Parse Vivado synthesis report",
        description="Old parse todo should be cancelled.",
        priority=3,
        assigned_tool="vivado.parse_report",
        assigned_specialist="VivadoSpecialist",
        dependencies=[synth.id],
        inputs={},
    )
    memory = runtime.todo_manager.append_item(
        title="Promote successful run to long-term memory",
        description="Memory must wait for repaired parse.",
        priority=4,
        assigned_tool="memory.promote_to_long_term",
        assigned_specialist="MemorySpecialist",
        dependencies=[parse.id],
        inputs={},
    )
    state.todos = runtime.todo_manager.todo_list.items
    state.selected_path = "llm_candidate_path"
    state.hls_project_dir = str(temp_workspace / "runs" / state.run_id / "candidate")
    state.report = {
        "status": "success",
        "timing": {"target_ns": 8.0, "estimated_ns": 9.4, "met": False},
    }

    runtime.reflect(
        state,
        synth,
        {
            "status": "completed_with_warning",
            "observation": {"summary": "timing was not met"},
        },
    )

    repair = next(item for item in runtime.todo_manager.todo_list.items if item.title == "Repair LLM candidate after timing failure")
    repaired_parse = next(item for item in runtime.todo_manager.todo_list.items if item.title == "Parse repaired synthesis report")
    assert repair.inputs["repair_reason"] == "timing_not_met"
    assert parse.status == "cancelled"
    assert repaired_parse.id in memory.dependencies


def test_llm_candidate_generation_failure_schedules_repair(temp_workspace):
    agent = MainAgent(temp_workspace, console=False)
    runtime = PlanExecuteReactRuntime(agent)
    state = runtime.initialize(str(temp_workspace / "examples" / "dense_llm_candidate.json"))
    runtime.todo_manager.create_from_plan(state.run_id, ["Seed"], state.task)
    generate = runtime.todo_manager.append_item(
        title="Generate HLS candidate",
        description="Initial LLM candidate generation.",
        priority=1,
        assigned_tool="llm.generate_hls_candidate",
        dependencies=[],
        inputs={},
    )
    verify = runtime.todo_manager.append_item(
        title="Verify candidate",
        description="Waits for a valid candidate.",
        priority=2,
        assigned_tool="verify_candidate.run",
        assigned_specialist="VerificationSpecialist",
        dependencies=[generate.id],
        inputs={},
    )
    error = {
        "error_type": "LLMGenerationError",
        "message": "CandidateSandbox rejected generated HLS code.",
        "source": "llm_candidate.generate",
        "details": {"violations": [{"rule": "system_call"}]},
    }
    state.errors.append(error)
    state.todos = runtime.todo_manager.todo_list.items

    runtime.reflect(
        state,
        generate,
        {
            "status": "failed",
            "observation": {"status": "failed", "error": error},
        },
    )

    retry = next(item for item in runtime.todo_manager.todo_list.items if item.title == "Repair LLM candidate generation")
    assert retry.inputs["repair_reason"] == "candidate_generation_failed"
    assert verify.dependencies == [retry.id]
    assert generate.status == "completed_with_warning"
    assert state.errors == []


def test_llm_candidate_verification_failure_uses_assigned_tool_not_title(temp_workspace):
    agent = MainAgent(temp_workspace, console=False)
    runtime = PlanExecuteReactRuntime(agent)
    state = runtime.initialize(str(temp_workspace / "examples" / "matmul_llm_candidate.json"))
    runtime.todo_manager.create_from_plan(state.run_id, ["Seed"], state.task)
    verify = runtime.todo_manager.append_item(
        title="Verify HLS candidate",
        description="LLM-authored verification title variant.",
        priority=1,
        assigned_tool="verify_candidate.run",
        assigned_specialist="VerificationSpecialist",
        dependencies=[],
        inputs={},
    )
    old_synth = runtime.todo_manager.append_item(
        title="Run Vivado C Synthesis",
        description="Must be cancelled until repaired candidate passes verification.",
        priority=2,
        assigned_tool="vivado.run_csynth",
        assigned_specialist="VivadoSpecialist",
        dependencies=[verify.id],
        inputs={},
    )
    state.selected_path = "llm_candidate_path"
    error = {
        "error_type": "VivadoSynthesisError",
        "message": "csim_design failed",
        "source": "vivado.run_csynth",
    }
    state.errors.append(error)
    state.todos = runtime.todo_manager.todo_list.items

    runtime.reflect(
        state,
        verify,
        {
            "status": "failed",
            "observation": {"status": "failed", "error": error},
        },
    )

    repair = next(item for item in runtime.todo_manager.todo_list.items if item.title == "Repair LLM candidate after verification failure")
    repaired_verify = next(item for item in runtime.todo_manager.todo_list.items if item.title == "Verify repaired LLM candidate")
    assert repair.inputs["repair_reason"] == "verification_failed"
    assert repaired_verify.dependencies == [repair.id]
    assert old_synth.status == "cancelled"
    assert verify.status == "completed_with_warning"
    assert state.errors == []
