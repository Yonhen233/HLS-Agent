"""Test contracts and regression checks for test_demo_boundary_reports.py.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

from pathlib import Path

from dl_op_to_hls.main_agent.agent import MainAgent
from dl_op_to_hls.main_agent.workflow import run_task


def _run_boundary(temp_workspace: Path, filename: str):
    """Verify the _run_boundary contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        temp_workspace: Value supplied by the caller and validated by the surrounding schema.
        filename: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    agent = MainAgent(temp_workspace, console=False)
    state = run_task(str(temp_workspace / "examples" / filename), agent=agent)
    run_dir = temp_workspace / "runs" / state.run_id
    return state, run_dir


def test_tiny_residual_generates_partial_support_report(temp_workspace):
    """Verify the test_tiny_residual_generates_partial_support_report contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        temp_workspace: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    state, run_dir = _run_boundary(temp_workspace, "tiny_residual_block.json")
    assert state.hls4ml_support
    assert state.hls4ml_support["status"] == "partially_supported"
    assert (run_dir / "unsupported_report.md").exists()


def test_resnet18_generates_unsupported_report(temp_workspace):
    """Verify the test_resnet18_generates_unsupported_report contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        temp_workspace: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    state, run_dir = _run_boundary(temp_workspace, "resnet18_boundary.json")
    report_path = run_dir / "unsupported_report.md"
    assert state.hls4ml_support
    assert state.hls4ml_support["status"] == "not_recommended"
    assert report_path.exists()
    content = report_path.read_text(encoding="utf-8")
    assert "Unsupported / Not Recommended Report" in content
    assert "Full ResNet-18 is outside the recommended scope for this MVP." in content


def test_resnet18_does_not_attempt_full_synthesis(temp_workspace):
    """Verify the test_resnet18_does_not_attempt_full_synthesis contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        temp_workspace: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    state, run_dir = _run_boundary(temp_workspace, "resnet18_boundary.json")
    trace = (run_dir / "trace.jsonl").read_text(encoding="utf-8")
    assert '"tool":"vivado.run_csynth"' not in trace
    synth_todo = next(item for item in state.todos if item.title == "Run Vivado HLS synthesis")
    assert synth_todo.status == "skipped"


def test_boundary_summary_has_alternatives(temp_workspace):
    """Verify the test_boundary_summary_has_alternatives contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        temp_workspace: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    _, run_dir = _run_boundary(temp_workspace, "resnet18_boundary.json")
    content = (run_dir / "unsupported_report.md").read_text(encoding="utf-8")
    assert "Use tiny_residual_block demo." in content
    assert "Use mnist_tiny_cnn demo." in content
    assert "Synthesize one subgraph at a time." in content
