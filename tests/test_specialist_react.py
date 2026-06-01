from __future__ import annotations

import pytest

from dl_op_to_hls.core.errors import AgentRuntimeError
from dl_op_to_hls.main_agent.state import AgentState
from dl_op_to_hls.main_agent.todo import TodoItem
from dl_op_to_hls.specialists import ContextBuilder, SpecialistReActDecider, SpecialistReActGuard


def _todo() -> TodoItem:
    return TodoItem(
        id="todo_001",
        title="Run Vivado HLS synthesis",
        description="Run Vivado HLS synthesis",
        status="pending",
        priority=1,
        dependencies=[],
        assigned_tool="vivado.run_csynth",
        assigned_specialist="VivadoSpecialist",
        inputs={},
        outputs=None,
        error=None,
    )


def _envelope() -> object:
    state = AgentState(
        run_id="r1",
        task={
            "task_type": "operator",
            "name": "dense_16x32",
            "op_type": "Dense",
            "target": {"part": "xc7z020clg400-1", "clock_period": 5},
        },
    )
    state.hls_project_dir = "runs/r1/generated"
    return ContextBuilder().build_for_specialist(state, _todo(), "VivadoSpecialist")


def test_specialist_react_guard_rejects_disallowed_tool():
    guard = SpecialistReActGuard()
    result = guard.validate(
        {"reason_summary": "try unrelated tool", "decision": "call_tool", "action": {"tool_name": "hls4ml.inspect_model"}},
        ["vivado.run_csynth"],
    )
    assert result["status"] == "invalid"


def test_specialist_react_guard_accepts_finish_with_result():
    guard = SpecialistReActGuard()
    result = guard.validate({"reason_summary": "done", "decision": "finish_with_result", "action": {}}, ["vivado.run_csynth"])
    assert result["status"] == "valid"


def test_specialist_react_decider_blocks_missing_input():
    decision = SpecialistReActDecider().decide(
        envelope=_envelope(),
        allowed_tools=["vivado.run_csynth"],
        recent_observations=[],
        preferred_tool="vivado.run_csynth",
        arguments={"work_dir": None, "tcl_path": "run_hls.tcl"},
    )
    assert decision["decision"] == "mark_blocked"
    assert "work_dir" in decision["action"]["missing_inputs"]


def test_specialist_react_decider_rejects_private_tool_escape():
    with pytest.raises(AgentRuntimeError):
        SpecialistReActDecider().decide(
            envelope=_envelope(),
            allowed_tools=["vivado.run_csynth"],
            recent_observations=[],
            preferred_tool="hls4ml.inspect_model",
            arguments={},
        )
