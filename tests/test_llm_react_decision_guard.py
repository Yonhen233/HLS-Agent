"""Test contracts and regression checks for test_llm_react_decision_guard.py.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from dl_op_to_hls.llm.guards import LLMGuard
from dl_op_to_hls.llm.client import FakeLLMClient
from dl_op_to_hls.llm.react import LLMReActDecider


def test_llm_react_rejects_disallowed_tool():
    """Verify the test_llm_react_rejects_disallowed_tool contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    decision = {"decision": "direct_tool_only_when_no_specialist", "action": {"tool_name": "vivado.run_csynth"}}
    result = LLMGuard().validate_react_decision(
        decision,
        allowed_tools=["hls4ml.check_support"],
        allowed_actions=["direct_tool_only_when_no_specialist"],
    )
    assert result["status"] == "invalid"


def test_llm_react_rejects_tool_call_for_specialist_owned_todo():
    """Verify the test_llm_react_rejects_tool_call_for_specialist_owned_todo contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    decision = {"decision": "direct_tool_only_when_no_specialist", "action": {"tool_name": "hls4ml.check_support"}}
    result = LLMGuard().validate_react_decision(
        decision,
        allowed_tools=[],
        allowed_actions=["delegate_to_specialist", "request_replan", "mark_blocked", "mark_failed"],
    )
    assert result["status"] == "invalid"


def test_llm_react_fills_delegate_specialist_from_todo():
    """Verify the test_llm_react_fills_delegate_specialist_from_todo contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    fake = FakeLLMClient(
        json_responses=[
            {
                "reason_summary": "Delegate to the assigned specialist.",
                "decision": "delegate_to_specialist",
            }
        ]
    )
    decision = LLMReActDecider().decide(
        todo={"id": "todo_001", "assigned_specialist": "VivadoSpecialist"},
        scoped_state={},
        allowed_tools=[],
        allowed_actions=["delegate_to_specialist", "mark_failed"],
        recent_observations=[],
        client=fake,
    )
    assert decision["action"]["specialist_name"] == "VivadoSpecialist"
    assert LLMGuard().validate_react_decision(
        decision,
        allowed_tools=[],
        allowed_actions=["delegate_to_specialist", "mark_failed"],
    )["status"] == "valid"
