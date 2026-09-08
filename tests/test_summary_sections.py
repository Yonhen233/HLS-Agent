"""Test contracts and regression checks for test_summary_sections.py.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from dl_op_to_hls.main_agent.agent import MainAgent
from dl_op_to_hls.main_agent.workflow import run_task


def test_summary_contains_todo_section(temp_workspace):
    """Verify the test_summary_contains_todo_section contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        temp_workspace: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    state = run_task(str(temp_workspace / "examples" / "dense_operator.json"), agent=MainAgent(temp_workspace, console=False))
    summary = (temp_workspace / "runs" / state.run_id / "summary.md").read_text(encoding="utf-8")
    assert "Todo Execution Summary" in summary


def test_summary_contains_memory_section(temp_workspace):
    """Verify the test_summary_contains_memory_section contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        temp_workspace: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    state = run_task(str(temp_workspace / "examples" / "dense_operator.json"), agent=MainAgent(temp_workspace, console=False))
    summary = (temp_workspace / "runs" / state.run_id / "summary.md").read_text(encoding="utf-8")
    assert "Memory Summary" in summary

