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
