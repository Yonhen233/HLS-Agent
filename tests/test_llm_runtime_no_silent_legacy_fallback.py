from pathlib import Path

from dl_op_to_hls.llm.client import FakeLLMClient
from dl_op_to_hls.main_agent.agent import MainAgent
from dl_op_to_hls.main_agent.workflow import run_task_llm


def test_run_llm_does_not_silently_fallback_to_legacy_planner(temp_workspace, monkeypatch):
    monkeypatch.setenv("DL_OP_TO_HLS_LLM_ENABLED", "1")
    monkeypatch.setenv("DL_OP_TO_HLS_LLM_API_KEY", "fake")
    invalid_plan = {
        "selected_skill": "operator_fallback_flow",
        "skill_usage": "adapted",
        "reason_summary": "invalid",
        "todos": [{"title": "Bad", "assigned_tool": "unknown.tool", "dependencies": [], "inputs": {}}],
    }
    fake = FakeLLMClient(json_responses=[invalid_plan, invalid_plan])
    agent = MainAgent(temp_workspace, console=False)
    state = run_task_llm(str(temp_workspace / "examples" / "dense_operator.json"), agent=agent, llm_client=fake)
    assert state.status == "failed"
    assert not any(todo.title == "Check hls4ml support" for todo in state.todos)
    trace_path = Path(temp_workspace / "runs" / state.run_id / "trace.jsonl")
    trace = trace_path.read_text(encoding="utf-8")
    assert "LLMPlanRejected" in trace
