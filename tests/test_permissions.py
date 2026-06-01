from dl_op_to_hls.core.config import DEFAULT_PERMISSIONS
from dl_op_to_hls.core.permissions import PermissionGate


def test_permission_allows_runs_write(tmp_path):
    gate = PermissionGate(DEFAULT_PERMISSIONS, tmp_path)
    decision = gate.check_write_path(str(tmp_path / "runs" / "demo.txt"))
    assert decision["decision"] == "allow"


def test_permission_denies_rm(tmp_path):
    gate = PermissionGate(DEFAULT_PERMISSIONS, tmp_path)
    decision = gate.check_command(["rm", "-rf", "runs"])
    assert decision["decision"] == "deny"

