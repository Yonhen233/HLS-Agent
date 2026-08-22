import json

from dl_op_to_hls.llm.client import FakeLLMClient
from dl_op_to_hls.main_agent.agent import MainAgent
from dl_op_to_hls.main_agent.llm_runtime import LLMFirstRuntime
from dl_op_to_hls.main_agent.state import AgentState
from dl_op_to_hls.main_agent.todo import TodoItem


def test_llm_runtime_resumes_from_durable_checkpoint(temp_workspace):
    agent = MainAgent(temp_workspace, console=False)
    task = json.loads((temp_workspace / "examples" / "dense_operator.json").read_text(encoding="utf-8"))
    session = agent.session_manager.create("resume dense", "session_resume")
    agent.session_manager.bind_run(session["session_id"], "resume_run")
    todo = TodoItem(
        id="todo_001",
        title="Validate task schema",
        description="Validate task schema",
        status="pending",
        priority=1,
        dependencies=[],
        assigned_tool="task.validate_schema",
        assigned_specialist=None,
        inputs={},
        outputs=None,
        error=None,
    )
    state = AgentState(
        run_id="resume_run",
        task=task,
        session_id=session["session_id"],
        status="interrupted",
        selected_path="fallback_template_path",
        selected_skill="operator_fallback_flow",
        todos=[todo],
    )
    agent.session_manager.create_checkpoint(session["session_id"], state.to_dict(), "interrupted")
    agent.session_manager.mark_interrupted(session["session_id"], "pause")
    fake = FakeLLMClient(
        json_responses=[
            {
                "reason_summary": "resume validation",
                "decision": "direct_tool_only_when_no_specialist",
                "action": {"tool_name": "task.validate_schema"},
                "expected_observation": "schema ok",
                "fallback_if_failed": "mark_failed",
            }
        ]
    )

    resumed = LLMFirstRuntime(agent, llm_client=fake).resume(session["session_id"])

    assert resumed.todos[0].status == "completed"
    assert agent.session_manager.get(session["session_id"])["status"] == "completed"
