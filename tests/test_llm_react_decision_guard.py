from dl_op_to_hls.llm.guards import LLMGuard


def test_llm_react_rejects_disallowed_tool():
    decision = {"decision": "direct_tool_only_when_no_specialist", "action": {"tool_name": "vivado.run_csynth"}}
    result = LLMGuard().validate_react_decision(
        decision,
        allowed_tools=["hls4ml.check_support"],
        allowed_actions=["direct_tool_only_when_no_specialist"],
    )
    assert result["status"] == "invalid"


def test_llm_react_rejects_tool_call_for_specialist_owned_todo():
    decision = {"decision": "direct_tool_only_when_no_specialist", "action": {"tool_name": "hls4ml.check_support"}}
    result = LLMGuard().validate_react_decision(
        decision,
        allowed_tools=[],
        allowed_actions=["delegate_to_specialist", "request_replan", "mark_blocked", "mark_failed"],
    )
    assert result["status"] == "invalid"
