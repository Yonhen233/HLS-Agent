from dl_op_to_hls.main_agent.state import AgentState
from dl_op_to_hls.main_agent.todo import TodoItem
from dl_op_to_hls.specialists.context import ContextBuilder


def test_context_builder_enforces_token_budget():
    state = AgentState(
        run_id="r1",
        task={
            "task_type": "operator",
            "name": "dense_budget",
            "op_type": "Dense",
            "target": {"part": "xc7z020clg400-1", "clock_period": 5},
        },
        objective="latency",
    )
    state.report = {"status": "success", "latency": {"min_cycles": 10, "max_cycles": 10}}
    state.rag_context = [{"summary": "rag " + "x" * 6000, "text": "history " + "y" * 6000}]
    state.retrieved_memories = [{"summary": "memory " + "z" * 6000, "text": "memory text " + "w" * 6000}]
    todo = TodoItem(
        id="todo_001",
        title="Generate optimization suggestions",
        description="Generate optimization suggestions",
        status="pending",
        priority=1,
        dependencies=[],
        assigned_tool="suggestion.suggest_optimization",
        assigned_specialist="OptimizationSpecialist",
        inputs={},
        outputs=None,
        error=None,
        context_scope={"max_context_tokens": 700},
    )

    envelope = ContextBuilder().build_for_specialist(state, todo, "OptimizationSpecialist")
    budget = envelope.constraints["token_budget"]

    assert budget["truncated"] is True
    assert budget["estimated_input_tokens_before"] > budget["estimated_input_tokens"]
    assert budget["estimated_input_tokens"] <= envelope.max_context_tokens
    assert len(envelope.retrieved_memory_refs[0]["summary"]) < 400
