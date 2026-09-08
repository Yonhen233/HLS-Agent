"""Test contracts and regression checks for test_permissions.py.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from dl_op_to_hls.core.config import DEFAULT_PERMISSIONS
from dl_op_to_hls.core.permissions import PermissionGate


def test_permission_allows_runs_write(tmp_path):
    """Verify the test_permission_allows_runs_write contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    gate = PermissionGate(DEFAULT_PERMISSIONS, tmp_path)
    decision = gate.check_write_path(str(tmp_path / "runs" / "demo.txt"))
    assert decision["decision"] == "allow"


def test_permission_denies_rm(tmp_path):
    """Verify the test_permission_denies_rm contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    gate = PermissionGate(DEFAULT_PERMISSIONS, tmp_path)
    decision = gate.check_command(["rm", "-rf", "runs"])
    assert decision["decision"] == "deny"


def test_permission_allows_vitis_run(tmp_path):
    """Verify the test_permission_allows_vitis_run contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    gate = PermissionGate(DEFAULT_PERMISSIONS, tmp_path)
    decision = gate.check_command(["vitis-run", "--mode", "hls"])
    assert decision["decision"] == "allow"
