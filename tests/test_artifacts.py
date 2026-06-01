import json

from dl_op_to_hls.core.artifacts import ArtifactManager
from dl_op_to_hls.core.config import DEFAULT_PERMISSIONS
from dl_op_to_hls.core.permissions import PermissionGate


def test_artifact_manifest_written(tmp_path):
    run_dir = tmp_path / "runs" / "r1"
    run_dir.mkdir(parents=True, exist_ok=True)
    gate = PermissionGate(DEFAULT_PERMISSIONS, tmp_path)
    manager = ArtifactManager("r1", run_dir, gate)
    manager.write_text("hello.txt", "hello", "summary")
    manifest = json.loads((run_dir / "artifacts.json").read_text(encoding="utf-8"))
    assert manifest["artifacts"][0]["type"] == "summary"

