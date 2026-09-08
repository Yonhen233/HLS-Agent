"""Test contracts and regression checks for test_llm_runtime_disabled.py.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from dl_op_to_hls.main_agent.agent import MainAgent
from dl_op_to_hls.main_agent.workflow import run_task, run_task_llm


def test_llm_disabled_run_llm_fails_cleanly(temp_workspace, monkeypatch):
    """Verify the test_llm_disabled_run_llm_fails_cleanly contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        temp_workspace: Value supplied by the caller and validated by the surrounding schema.
        monkeypatch: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    monkeypatch.setenv("DL_OP_TO_HLS_LLM_ENABLED", "0")
    monkeypatch.delenv("DL_OP_TO_HLS_LLM_API_KEY", raising=False)
    agent = MainAgent(temp_workspace, console=False)
    state = run_task_llm(str(temp_workspace / "examples" / "dense_operator.json"), agent=agent)
    assert state.status == "failed"
    assert any("LLM is not enabled or API key is missing." in item.get("message", "") for item in state.errors)


def test_llm_disabled_regular_run_still_works(temp_workspace, monkeypatch):
    """Verify the test_llm_disabled_regular_run_still_works contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        temp_workspace: Value supplied by the caller and validated by the surrounding schema.
        monkeypatch: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    monkeypatch.setenv("DL_OP_TO_HLS_LLM_ENABLED", "0")
    monkeypatch.delenv("DL_OP_TO_HLS_LLM_API_KEY", raising=False)
    agent = MainAgent(temp_workspace, console=False)
    state = run_task(str(temp_workspace / "examples" / "dense_operator.json"), agent=agent)
    assert state.status in {"success", "partial_success"}
