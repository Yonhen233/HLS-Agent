from dl_op_to_hls.main_agent.agent import MainAgent
from dl_op_to_hls.main_agent.workflow import run_task, run_task_llm


def test_llm_disabled_run_llm_fails_cleanly(temp_workspace, monkeypatch):
    monkeypatch.setenv("DL_OP_TO_HLS_LLM_ENABLED", "0")
    monkeypatch.delenv("DL_OP_TO_HLS_LLM_API_KEY", raising=False)
    agent = MainAgent(temp_workspace, console=False)
    state = run_task_llm(str(temp_workspace / "examples" / "dense_operator.json"), agent=agent)
    assert state.status == "failed"
    assert any("LLM is not enabled or API key is missing." in item.get("message", "") for item in state.errors)


def test_llm_disabled_regular_run_still_works(temp_workspace, monkeypatch):
    monkeypatch.setenv("DL_OP_TO_HLS_LLM_ENABLED", "0")
    monkeypatch.delenv("DL_OP_TO_HLS_LLM_API_KEY", raising=False)
    agent = MainAgent(temp_workspace, console=False)
    state = run_task(str(temp_workspace / "examples" / "dense_operator.json"), agent=agent)
    assert state.status in {"success", "partial_success"}
