"""Test contracts and regression checks for test_hooks.py.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from dl_op_to_hls.core.hooks import HookManager


def test_hooks_emit_events():
    """Verify the test_hooks_emit_events contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    hooks = HookManager()
    seen = []
    hooks.register("RunStarted", lambda payload: seen.append(payload["event"]))
    hooks.emit("RunStarted", {"run_id": "r1"})
    assert seen == ["RunStarted"]

