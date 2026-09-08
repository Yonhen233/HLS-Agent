"""Test contracts and regression checks for test_specialist_react.py.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

import pytest

from dl_op_to_hls.core.errors import AgentRuntimeError
from dl_op_to_hls.main_agent.state import AgentState
from dl_op_to_hls.main_agent.todo import TodoItem
from dl_op_to_hls.specialists import ContextBuilder, SpecialistReActDecider, SpecialistReActGuard


class _FinishClient:
    """Coordinate _FinishClient within the test_specialist_react boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    context = {}

    def is_enabled(self):
        """Verify the is_enabled contract.

        The test should fail on a real contract regression rather than hide an unsupported path.

        Returns:
            The structured value promised by the function signature.
        """
        return True

    def complete_json(self, **kwargs):
        """Verify the complete_json contract.

        The test should fail on a real contract regression rather than hide an unsupported path.

        Returns:
            The structured value promised by the function signature.
        """
        return {"reason_summary": "done without tool", "decision": "finish_with_result", "action": {}}


class _WrongToolClient:
    """Coordinate _WrongToolClient within the test_specialist_react boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    context = {}

    def is_enabled(self):
        """Verify the is_enabled contract.

        The test should fail on a real contract regression rather than hide an unsupported path.

        Returns:
            The structured value promised by the function signature.
        """
        return True

    def complete_json(self, **kwargs):
        """Verify the complete_json contract.

        The test should fail on a real contract regression rather than hide an unsupported path.

        Returns:
            The structured value promised by the function signature.
        """
        return {
            "reason_summary": "try a neighboring tool",
            "decision": "call_tool",
            "action": {"tool_name": "hls4ml.check_support", "arguments": {"task": {}}},
        }


class _BadArgsClient:
    """Coordinate _BadArgsClient within the test_specialist_react boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    context = {}

    def is_enabled(self):
        """Verify the is_enabled contract.

        The test should fail on a real contract regression rather than hide an unsupported path.

        Returns:
            The structured value promised by the function signature.
        """
        return True

    def complete_json(self, **kwargs):
        """Verify the complete_json contract.

        The test should fail on a real contract regression rather than hide an unsupported path.

        Returns:
            The structured value promised by the function signature.
        """
        return {
            "reason_summary": "call required tool with incomplete args",
            "decision": "call_tool",
            "action": {"tool_name": "vivado.run_csynth", "arguments": {}},
        }


def _todo() -> TodoItem:
    """Verify the _todo contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
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
    """Verify the _envelope contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
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
    """Verify the test_specialist_react_guard_rejects_disallowed_tool contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    guard = SpecialistReActGuard()
    result = guard.validate(
        {"reason_summary": "try unrelated tool", "decision": "call_tool", "action": {"tool_name": "hls4ml.inspect_model"}},
        ["vivado.run_csynth"],
    )
    assert result["status"] == "invalid"


def test_specialist_react_guard_accepts_finish_with_result():
    """Verify the test_specialist_react_guard_accepts_finish_with_result contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    guard = SpecialistReActGuard()
    result = guard.validate({"reason_summary": "done", "decision": "finish_with_result", "action": {}}, ["vivado.run_csynth"])
    assert result["status"] == "valid"


def test_specialist_react_guard_rejects_finish_when_tool_required():
    """Verify the test_specialist_react_guard_rejects_finish_when_tool_required contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    guard = SpecialistReActGuard()
    result = guard.validate(
        {"reason_summary": "done", "decision": "finish_with_result", "action": {}},
        ["vivado.run_csynth"],
        preferred_tool="vivado.run_csynth",
    )
    assert result["status"] == "invalid"


def test_specialist_react_decider_blocks_missing_input():
    """Verify the test_specialist_react_decider_blocks_missing_input contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    decision = SpecialistReActDecider().decide(
        envelope=_envelope(),
        allowed_tools=["vivado.run_csynth"],
        recent_observations=[],
        preferred_tool="vivado.run_csynth",
        arguments={"work_dir": None, "tcl_path": "run_hls.tcl"},
    )
    assert decision["decision"] == "mark_blocked"
    assert "work_dir" in decision["action"]["missing_inputs"]


def test_specialist_react_decider_repairs_finish_when_tool_required():
    """Verify the test_specialist_react_decider_repairs_finish_when_tool_required contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    decision = SpecialistReActDecider().decide(
        envelope=_envelope(),
        allowed_tools=["vivado.run_csynth"],
        recent_observations=[],
        preferred_tool="vivado.run_csynth",
        arguments={"work_dir": "w", "tcl_path": "run_hls.tcl"},
        client=_FinishClient(),
    )
    assert decision["decision"] == "call_tool"
    assert decision["action"]["tool_name"] == "vivado.run_csynth"


def test_specialist_react_decider_repairs_wrong_tool_when_tool_required():
    """Verify the test_specialist_react_decider_repairs_wrong_tool_when_tool_required contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    decision = SpecialistReActDecider().decide(
        envelope=_envelope(),
        allowed_tools=["vivado.run_csynth", "hls4ml.check_support"],
        recent_observations=[],
        preferred_tool="vivado.run_csynth",
        arguments={"work_dir": "w", "tcl_path": "run_hls.tcl"},
        client=_WrongToolClient(),
    )
    assert decision["decision"] == "call_tool"
    assert decision["action"]["tool_name"] == "vivado.run_csynth"
    assert decision["action"]["arguments"] == {"work_dir": "w", "tcl_path": "run_hls.tcl"}


def test_specialist_react_decider_preserves_canonical_arguments_when_tool_required():
    """Verify the test_specialist_react_decider_preserves_canonical_arguments_when_tool_required contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    decision = SpecialistReActDecider().decide(
        envelope=_envelope(),
        allowed_tools=["vivado.run_csynth"],
        recent_observations=[],
        preferred_tool="vivado.run_csynth",
        arguments={"work_dir": "w", "tcl_path": "run_hls.tcl"},
        client=_BadArgsClient(),
    )
    assert decision["decision"] == "call_tool"
    assert decision["action"]["tool_name"] == "vivado.run_csynth"
    assert decision["action"]["arguments"] == {"work_dir": "w", "tcl_path": "run_hls.tcl"}


def test_specialist_react_decider_rejects_private_tool_escape():
    """Verify the test_specialist_react_decider_rejects_private_tool_escape contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    with pytest.raises(AgentRuntimeError):
        SpecialistReActDecider().decide(
            envelope=_envelope(),
            allowed_tools=["vivado.run_csynth"],
            recent_observations=[],
            preferred_tool="hls4ml.inspect_model",
            arguments={},
        )
