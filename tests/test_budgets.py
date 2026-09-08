"""Test contracts and regression checks for test_budgets.py.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from dl_op_to_hls.core.budgets import RunBudget


def test_run_budget_round_trip_preserves_usage_for_session_resume():
    """Verify the test_run_budget_round_trip_preserves_usage_for_session_resume contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    budget = RunBudget(max_llm_calls=7, max_tool_calls=11, max_total_tokens=2000)
    budget.reserve_llm_call(100)
    budget.record_llm_usage(120, 30)
    budget.reserve_tool_call()
    budget.record_cache_hit()

    restored = RunBudget.from_dict(budget.to_dict())

    assert restored.to_dict() == budget.to_dict()
