from dl_op_to_hls.main_agent.agent import MainAgent
from dl_op_to_hls.main_agent.workflow import run_task


def test_summary_contains_todo_section(temp_workspace):
    state = run_task(str(temp_workspace / "examples" / "dense_operator.json"), agent=MainAgent(temp_workspace, console=False))
    summary = (temp_workspace / "runs" / state.run_id / "summary.md").read_text(encoding="utf-8")
    assert "Todo Execution Summary" in summary


def test_summary_contains_memory_section(temp_workspace):
    state = run_task(str(temp_workspace / "examples" / "dense_operator.json"), agent=MainAgent(temp_workspace, console=False))
    summary = (temp_workspace / "runs" / state.run_id / "summary.md").read_text(encoding="utf-8")
    assert "Memory Summary" in summary

