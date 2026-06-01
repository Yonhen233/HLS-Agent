from dl_op_to_hls.llm.guards import LLMGuard


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
