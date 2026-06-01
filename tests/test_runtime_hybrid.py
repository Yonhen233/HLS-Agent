from pathlib import Path

from dl_op_to_hls.main_agent.agent import MainAgent
from dl_op_to_hls.main_agent.workflow import run_task


def test_runtime_plan_execute_react_flow(temp_workspace):
    state = run_task(str(temp_workspace / "examples" / "dense_operator.json"), agent=MainAgent(temp_workspace, console=False))
    assert (temp_workspace / "runs" / state.run_id / "todos.json").exists()
    assert state.todos


def test_runtime_react_step_recorded(temp_workspace):
    state = run_task(str(temp_workspace / "examples" / "dense_operator.json"), agent=MainAgent(temp_workspace, console=False))
    assert any(item.react_steps for item in state.todos)


def test_runtime_reflector_adds_fallback_todo(temp_workspace):
    state = run_task(str(temp_workspace / "examples" / "dense_operator.json"), agent=MainAgent(temp_workspace, console=False))
    assert any(item.title == "Generate fallback HLS template" for item in state.todos)


def test_runtime_vivado_missing_marks_todo_skipped(temp_workspace, monkeypatch):
    monkeypatch.setenv("DL_OP_TO_HLS_MOCK_VIVADO", "0")
    agent = MainAgent(temp_workspace, console=False)
    state = run_task(str(temp_workspace / "examples" / "dense_operator.json"), agent=agent)
    synth_todo = next(item for item in state.todos if item.title == "Run Vivado HLS synthesis")
    assert synth_todo.status == "skipped"


def test_runtime_partial_success(temp_workspace, monkeypatch):
    monkeypatch.setenv("DL_OP_TO_HLS_MOCK_VIVADO", "0")
    agent = MainAgent(temp_workspace, console=False)
    state = run_task(str(temp_workspace / "examples" / "dense_operator.json"), agent=agent)
    assert state.status == "partial_success"

