from dl_op_to_hls.llm.guards import LLMGuard
from dl_op_to_hls.main_agent.agent import MainAgent
from dl_op_to_hls.main_agent.llm_runtime import LLMFirstRuntime


def test_llm_reflector_adds_valid_todo():
    reflection = {
        "reason_summary": "vivado missing",
        "decision": "mark_skipped_and_continue",
        "todo_status": "skipped",
        "run_status": "partial_success",
        "new_todos": [{"title": "Write run summary", "assigned_tool": "summary.write_summary"}],
        "memory_candidates": [],
    }
    result = LLMGuard().validate_reflection(reflection, current_skill="operator_fallback_flow")
    assert result["status"] == "valid"


def test_llm_reflection_rejects_unknown_tool_and_specialist(temp_workspace):
    agent = MainAgent(temp_workspace, console=False)
    runtime = LLMFirstRuntime(agent)
    runtime.context = agent.create_run_context("reflection_guard")
    runtime.specialist_router = runtime._build_router()

    result = runtime._validate_reflection_todo(
        {
            "title": "Rewrite with hallucinated tool",
            "assigned_tool": "onnx_graph_rewrite",
            "assigned_specialist": "GraphRewriteSpecialist",
        }
    )

    assert result["status"] == "invalid"
    assert any("Unknown tool" in item for item in result["errors"])
    assert any("Unknown specialist" in item for item in result["errors"])


def test_llm_reflection_rejects_specialist_tool_mismatch(temp_workspace):
    agent = MainAgent(temp_workspace, console=False)
    runtime = LLMFirstRuntime(agent)
    runtime.context = agent.create_run_context("reflection_mismatch_guard")
    runtime.specialist_router = runtime._build_router()

    result = runtime._validate_reflection_todo(
        {
            "title": "Bad specialist",
            "assigned_tool": "task.validate_schema",
            "assigned_specialist": "HLS4MLSpecialist",
        }
    )

    assert result["status"] == "invalid"
    assert any("outside allowed_tools" in item for item in result["errors"])


def test_contained_invalid_reflection_todo_does_not_pollute_run_errors(temp_workspace, monkeypatch):
    agent = MainAgent(temp_workspace, console=False)
    runtime = LLMFirstRuntime(agent)
    state = runtime.initialize(str(temp_workspace / "examples" / "dense_llm_candidate.json"))
    runtime.todo_manager.create_from_plan(state.run_id, ["Seed"], state.task)
    todo = runtime.todo_manager.append_item(
        title="Run synthesis",
        description="Trigger reflection after a recoverable timing observation.",
        priority=1,
        assigned_tool="vivado.run_csynth",
        assigned_specialist="VivadoSpecialist",
        dependencies=[],
        inputs={},
    )
    runtime.selected_skill = "operator_llm_candidate_flow"
    state.selected_skill = runtime.selected_skill
    reflection = {
        "reason_summary": "Try an optimization action.",
        "decision": "add_todos",
        "todo_status": "completed_with_warning",
        "run_status": "partial_success",
        "new_todos": [
            {
                "title": "Optimize HLS code",
                "assigned_tool": "hls_code_optimizer",
                "assigned_specialist": "HLSDeveloperSpecialist",
            }
        ],
        "memory_candidates": [],
    }
    monkeypatch.setattr(runtime.controller.reflector, "reflect", lambda **_: reflection)

    runtime.reflect(
        state,
        todo,
        {
            "status": "failed",
            "error_type": "VivadoSynthesisError",
            "observation": {"status": "failed", "error": {"error_type": "VivadoSynthesisError"}},
        },
    )

    assert not any(item.get("source") == "llm_runtime.reflect" for item in state.errors)
    rejected = [item for item in state.llm_decisions if item.get("decision") == "reject_invalid_todo"]
    assert rejected and rejected[-1]["status"] == "contained"
    trace = (runtime.context["run_dir"] / "trace.jsonl").read_text(encoding="utf-8")
    assert '"event": "LLMReflectionTodoRejected"' in trace
