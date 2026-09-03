from pathlib import Path

from dl_op_to_hls.main_agent.agent import MainAgent
from dl_op_to_hls.main_agent.workflow import run_task


def test_main_agent_dense_operator_fallback_path(temp_workspace):
    agent = MainAgent(temp_workspace, console=False)
    state = run_task(str(temp_workspace / "examples" / "dense_operator.json"), agent=agent)
    assert state.selected_path == "fallback_template_path"


def test_main_agent_model_hls4ml_mock_path(temp_workspace):
    agent = MainAgent(temp_workspace, console=False)
    state = run_task(str(temp_workspace / "examples" / "mlp_onnx_example.json"), agent=agent)
    assert state.selected_path == "hls4ml_path"


def test_main_agent_existing_hls_project_mock_path(temp_workspace):
    agent = MainAgent(temp_workspace, console=False)
    state = run_task(str(temp_workspace / "examples" / "existing_hls_project.json"), agent=agent)
    assert state.selected_path == "existing_hls_project_path"


def test_main_agent_writes_summary(temp_workspace):
    agent = MainAgent(temp_workspace, console=False)
    state = run_task(str(temp_workspace / "examples" / "dense_operator.json"), agent=agent)
    assert (temp_workspace / "runs" / state.run_id / "summary.md").exists()


def test_main_agent_writes_suggestions(temp_workspace):
    agent = MainAgent(temp_workspace, console=False)
    state = run_task(str(temp_workspace / "examples" / "dense_operator.json"), agent=agent)
    assert (temp_workspace / "runs" / state.run_id / "suggestions.md").exists()


def test_main_agent_writes_trace(temp_workspace):
    agent = MainAgent(temp_workspace, console=False)
    state = run_task(str(temp_workspace / "examples" / "dense_operator.json"), agent=agent)
    assert (temp_workspace / "runs" / state.run_id / "trace.jsonl").exists()


def test_main_agent_indexes_rag(temp_workspace):
    agent = MainAgent(temp_workspace, console=False)
    state = run_task(str(temp_workspace / "examples" / "dense_operator.json"), agent=agent)
    results = agent.rag_memory.retrieve("Dense reuse factor DSP", top_k=5)
    assert results


def test_main_agent_allows_only_configured_external_runs_root(temp_workspace, monkeypatch):
    external_runs = temp_workspace.parent / "short_execution_root"
    monkeypatch.setenv("DL_OP_TO_HLS_RUNS_ROOT", str(external_runs))
    monkeypatch.setenv("DL_OP_TO_HLS_DB_PATH", str(external_runs / "metadata.db"))

    agent = MainAgent(temp_workspace, console=False)
    try:
        allowed = agent.permission_gate.check_write_path(str(external_runs / "run_001" / "state.json"))
        unrelated = agent.permission_gate.check_write_path(str(temp_workspace.parent / "unrelated" / "state.json"))
        assert allowed["decision"] == "allow"
        assert unrelated["decision"] == "deny"
        assert agent.permission_gate.check_url("https://llmapi.paratera.com/v1/chat/completions")["decision"] == "allow"
    finally:
        agent.close()
