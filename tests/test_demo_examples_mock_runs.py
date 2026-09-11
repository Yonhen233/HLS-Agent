"""Test contracts and regression checks for test_demo_examples_mock_runs.py.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

from pathlib import Path

from dl_op_to_hls.main_agent.agent import MainAgent
from dl_op_to_hls.main_agent.workflow import run_task


def _run_demo(temp_workspace: Path, filename: str):
    """Verify the _run_demo contract.

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


def _assert_common_outputs(run_dir: Path) -> None:
    """Verify the _assert_common_outputs contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        run_dir: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    assert (run_dir / "state.json").exists()
    assert (run_dir / "todos.json").exists()
    assert (run_dir / "trace.jsonl").exists()
    assert (run_dir / "artifacts.json").exists()
    assert (run_dir / "summary.md").exists()


def test_dense_operator_mock_run(temp_workspace):
    """Verify the test_dense_operator_mock_run contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        temp_workspace: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    state, run_dir = _run_demo(temp_workspace, "dense_operator.json")
    _assert_common_outputs(run_dir)
    assert (run_dir / "suggestions.md").exists()
    assert state.selected_path == "fallback_template_path"
    assert (run_dir / "generated" / "dense_16x32.cpp").exists()
    assert (run_dir / "generated" / "dense_16x32.h").exists()
    assert (run_dir / "generated" / "testbench.cpp").exists()
    assert (run_dir / "generated" / "run_hls.tcl").exists()


def test_matmul_resource_mock_run(temp_workspace):
    """Verify the test_matmul_resource_mock_run contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        temp_workspace: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    state, run_dir = _run_demo(temp_workspace, "matmul_resource.json")
    _assert_common_outputs(run_dir)
    assert (run_dir / "suggestions.md").exists()
    assert state.selected_path == "fallback_template_path"
    summary = (run_dir / "summary.md").read_text(encoding="utf-8")
    assert "fallback_template_path" in summary


def test_mnist_mlp_mock_run(temp_workspace):
    """Verify the test_mnist_mlp_mock_run contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        temp_workspace: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    state, run_dir = _run_demo(temp_workspace, "mnist_mlp_hls4ml.json")
    _assert_common_outputs(run_dir)
    assert (run_dir / "suggestions.md").exists()
    assert state.selected_path == "hls4ml_path"
    summary = (run_dir / "summary.md").read_text(encoding="utf-8")
    assert "hls4ml_path" in summary


def test_mnist_tiny_cnn_mock_run(temp_workspace):
    """Verify the test_mnist_tiny_cnn_mock_run contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        temp_workspace: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    state, run_dir = _run_demo(temp_workspace, "mnist_tiny_cnn.json")
    _assert_common_outputs(run_dir)
    assert (run_dir / "suggestions.md").exists()
    assert state.selected_path == "hls4ml_path"
    trace = (run_dir / "trace.jsonl").read_text(encoding="utf-8")
    assert "HLS4MLSpecialist" in trace


def test_qkeras_cnn_mock_run(temp_workspace):
    """Verify the test_qkeras_cnn_mock_run contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        temp_workspace: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    state, run_dir = _run_demo(temp_workspace, "mnist_qkeras_cnn.json")
    _assert_common_outputs(run_dir)
    assert (run_dir / "suggestions.md").exists()
    assert state.selected_path == "hls4ml_path"
    summary = (run_dir / "summary.md").read_text(encoding="utf-8")
    assert "hls4ml_path" in summary


def test_qonnx_cnn_mock_run(temp_workspace):
    """Verify the test_qonnx_cnn_mock_run contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        temp_workspace: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    state, run_dir = _run_demo(temp_workspace, "mnist_qonnx_cnn.json")
    _assert_common_outputs(run_dir)
    assert (run_dir / "suggestions.md").exists()
    assert state.selected_path == "hls4ml_path"
    summary = (run_dir / "summary.md").read_text(encoding="utf-8")
    assert "hls4ml_path" in summary


def test_tiny_residual_boundary_mock_run(temp_workspace):
    """Verify the test_tiny_residual_boundary_mock_run contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        temp_workspace: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    state, run_dir = _run_demo(temp_workspace, "tiny_residual_block.json")
    _assert_common_outputs(run_dir)
    assert (run_dir / "suggestions.md").exists()
    assert (run_dir / "unsupported_report.md").exists()
    assert state.selected_path is None
    assert state.terminal_outcome == "blocked"
    assert state.status in {"partial_success", "completed_with_warning"}
    summary = (run_dir / "summary.md").read_text(encoding="utf-8")
    assert "partially_supported" in summary


def test_resnet18_boundary_mock_run(temp_workspace):
    """Verify the test_resnet18_boundary_mock_run contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        temp_workspace: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    state, run_dir = _run_demo(temp_workspace, "resnet18_boundary.json")
    _assert_common_outputs(run_dir)
    assert (run_dir / "unsupported_report.md").exists()
    assert state.selected_path is None
    assert state.terminal_outcome == "blocked"
    trace = (run_dir / "trace.jsonl").read_text(encoding="utf-8")
    assert '"tool":"vivado.run_csynth"' not in trace
