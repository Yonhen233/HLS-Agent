"""Test contracts and regression checks for test_state.py.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

import json

from dl_op_to_hls.main_agent.state import AgentState


def test_agent_state_serialized(tmp_path):
    """Verify the test_agent_state_serialized contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    state = AgentState(run_id="r1", task={"task_type": "operator", "name": "demo"})
    state_path = state.save(tmp_path / "state.json")
    loaded = json.loads(state_path.read_text(encoding="utf-8"))
    assert loaded["run_id"] == "r1"

