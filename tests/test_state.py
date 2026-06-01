import json

from dl_op_to_hls.main_agent.state import AgentState


def test_agent_state_serialized(tmp_path):
    state = AgentState(run_id="r1", task={"task_type": "operator", "name": "demo"})
    state_path = state.save(tmp_path / "state.json")
    loaded = json.loads(state_path.read_text(encoding="utf-8"))
    assert loaded["run_id"] == "r1"

