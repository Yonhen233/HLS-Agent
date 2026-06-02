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
