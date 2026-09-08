"""Test contracts and regression checks for test_context_compression.py.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from dl_op_to_hls.core.context import ContextCompressor


def test_context_compression_log(tmp_path):
    """Verify the test_context_compression_log contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    log_path = tmp_path / "csynth.log"
    log_path.write_text("WARNING: demo warning\n", encoding="utf-8")
    compressor = ContextCompressor()
    summary = compressor.compress_vivado_log(str(log_path))
    assert "warning" in summary["summary"].lower()

