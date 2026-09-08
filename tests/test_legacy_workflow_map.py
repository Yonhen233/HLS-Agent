"""Test contracts and regression checks for test_legacy_workflow_map.py.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from pathlib import Path


def test_legacy_workflow_map_exists():
    """Verify the test_legacy_workflow_map_exists contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    assert Path("docs/legacy_workflow_map.md").exists()
