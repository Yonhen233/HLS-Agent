from pathlib import Path


def test_legacy_workflow_map_exists():
    assert Path("docs/legacy_workflow_map.md").exists()
