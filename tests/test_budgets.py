from dl_op_to_hls.core.budgets import RunBudget


def test_run_budget_round_trip_preserves_usage_for_session_resume():
    budget = RunBudget(max_llm_calls=7, max_tool_calls=11, max_total_tokens=2000)
    budget.reserve_llm_call(100)
    budget.record_llm_usage(120, 30)
    budget.reserve_tool_call()
    budget.record_cache_hit()

    restored = RunBudget.from_dict(budget.to_dict())

    assert restored.to_dict() == budget.to_dict()
