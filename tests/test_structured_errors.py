"""Test contracts and regression checks for test_structured_errors.py.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from dl_op_to_hls.core.errors import build_error


def test_structured_error_format():
    """Verify the test_structured_error_format contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    error = build_error("VivadoNotFoundError", "missing", recoverable=True, source="vivado.run_csynth")
    payload = error.to_dict()
    assert payload["error_type"] == "VivadoNotFoundError"
    assert payload["recoverable"] is True

