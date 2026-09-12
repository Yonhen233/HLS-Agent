"""Regression tests for the LLM-candidate-only execution policy."""

from pathlib import Path
from types import SimpleNamespace

from dl_op_to_hls.core.config import AppConfig
from dl_op_to_hls.main_agent.agent import MainAgent
from dl_op_to_hls.main_agent.llm_runtime import LLMFirstRuntime
from dl_op_to_hls.main_agent.state import AgentState
from dl_op_to_hls.main_agent.status import build_failure_diagnosis
from dl_op_to_hls.main_agent.todo import TodoItem


def test_main_agent_does_not_register_retired_generation_paths(tmp_path):
    agent = MainAgent(tmp_path, console=False)
    try:
        names = {item.name for item in agent.registry.list_tools()}
        assert not any(name.startswith(("hls4ml.", "fallback.", "graph_rewrite.")) for name in names)
    finally:
        agent.close()


def test_model_policy_is_an_honest_capability_boundary(tmp_path):
    config = AppConfig.load(Path.cwd())
    runtime = SimpleNamespace(agent=SimpleNamespace(config=config))
    normalized = LLMFirstRuntime._apply_generation_policy(runtime, {"task_type": "model", "name": "mnist"})
    assert normalized["generation_policy"]["primary_path"] == "capability_gate"
    assert normalized["generation_policy"]["hls4ml_allowed"] is False
    assert normalized["demo"]["expected_path"] == "unsupported_report"


def test_candidate_only_plan_removes_retired_tools(tmp_path):
    config = AppConfig.load(Path.cwd())
    runtime = SimpleNamespace(agent=SimpleNamespace(config=config))
    task = {
        "task_type": "operator",
        "op_type": "Dense",
        "name": "dense",
        "generation_policy": {"primary_path": "llm_candidate"},
    }
    plan, removed = LLMFirstRuntime._enforce_candidate_only_plan(
        runtime,
        {
            "todos": [
                {"title": "old", "assigned_tool": "hls4ml.convert"},
                {"title": "fallback", "assigned_tool": "fallback.generate_operator_hls"},
            ]
        },
        task,
    )
    tools = {item["assigned_tool"] for item in plan["todos"]}
    assert removed == ["fallback.generate_operator_hls", "hls4ml.convert"]
    assert "llm.generate_candidate" in tools
    assert "verify_candidate.run" in tools
    assert "hls4ml.convert" not in tools


def test_failure_diagnosis_reuses_trace_as_source_of_truth(tmp_path):
    trace = tmp_path / "trace.jsonl"
    trace.write_text(
        '{"event":"ToolFailed","todo_id":"todo_1","tool_name":"verify_candidate.run","error_type":"CsimError","message":"golden mismatch"}\n',
        encoding="utf-8",
    )
    todo = TodoItem(
        id="todo_1",
        title="Verify LLM candidate",
        description="",
        status="failed",
        priority=1,
        dependencies=[],
        assigned_tool="verify_candidate.run",
        assigned_specialist="VerificationSpecialist",
        inputs={},
        outputs=None,
        error={"message": "golden mismatch", "recoverable": True},
    )
    state = AgentState(run_id="r1", task={"task_type": "operator"}, todos=[todo])
    diagnosis = build_failure_diagnosis(state, str(trace))
    assert diagnosis["primary_stage"] == "Verify LLM candidate"
    assert diagnosis["next_action"] == "repair_candidate_then_reverify"
    assert diagnosis["trace"]["source_of_truth"] == "trace.jsonl"
