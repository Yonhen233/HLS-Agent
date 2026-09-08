"""Test contracts and regression checks for test_artifacts.py.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

import json

from dl_op_to_hls.core.artifacts import ArtifactManager
from dl_op_to_hls.core.config import DEFAULT_PERMISSIONS
from dl_op_to_hls.core.permissions import PermissionGate


def test_artifact_manifest_written(tmp_path):
    """Verify the test_artifact_manifest_written contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    run_dir = tmp_path / "runs" / "r1"
    run_dir.mkdir(parents=True, exist_ok=True)
    gate = PermissionGate(DEFAULT_PERMISSIONS, tmp_path)
    manager = ArtifactManager("r1", run_dir, gate)
    manager.write_text("hello.txt", "hello", "summary")
    manifest = json.loads((run_dir / "artifacts.json").read_text(encoding="utf-8"))
    assert manifest["artifacts"][0]["type"] == "summary"

