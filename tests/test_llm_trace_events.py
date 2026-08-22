from pathlib import Path

from dl_op_to_hls.llm.client import FakeLLMClient
from dl_op_to_hls.main_agent.agent import MainAgent
from dl_op_to_hls.main_agent.workflow import run_task_llm


def test_llm_runtime_records_llm_trace(temp_workspace):
    fake = FakeLLMClient(
        json_responses=[
            {
                "selected_skill": "operator_fallback_flow",
                "skill_usage": "strict",
                "reason_summary": "single-step smoke",
                "todos": [
                    {
                        "title": "Validate task schema",
                        "assigned_tool": "task.validate_schema",
                        "assigned_specialist": None,
                        "dependencies": [],
                        "inputs": {},
                    }
                ],
            },
            {
                "reason_summary": "execute validation",
                "decision": "direct_tool_only_when_no_specialist",
                "action": {"tool_name": "task.validate_schema"},
                "expected_observation": "schema ok",
                "fallback_if_failed": "mark_failed",
            },
        ]
    )
    agent = MainAgent(temp_workspace, console=False)
    state = run_task_llm(str(temp_workspace / "examples" / "dense_operator.json"), agent=agent, llm_client=fake)
    trace = Path(temp_workspace / "runs" / state.run_id / "trace.jsonl").read_text(encoding="utf-8")
    assert "LLMSkillContextBuilt" in trace
    assert "LLMPlanGenerated" in trace
    assert "LLMPlanAccepted" in trace
    assert "LLMReActAutoDirect" in trace
    assert "SessionCheckpointCreated" in trace
    assert state.session_id
    session = agent.session_manager.get(state.session_id)
    assert session["status"] == "completed"
    assert agent.session_manager.list_checkpoints(state.session_id)
