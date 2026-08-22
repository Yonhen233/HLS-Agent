from __future__ import annotations

from .agent import MainAgent
from .llm_runtime import LLMFirstRuntime
from .runtime import PlanExecuteReactRuntime
from .state import AgentState


def run_task(task_path: str, agent: MainAgent | None = None) -> AgentState:
    runtime = PlanExecuteReactRuntime(agent or MainAgent())
    return runtime.run(task_path)


def run_task_llm(
    task_input: str | dict,
    agent: MainAgent | None = None,
    llm_client=None,
    session_id: str | None = None,
    user_id: str = "local-user",
    project_id: str | None = None,
) -> AgentState:
    runtime = LLMFirstRuntime(
        agent or MainAgent(),
        llm_client=llm_client,
        session_id=session_id,
        user_id=user_id,
        project_id=project_id,
    )
    return runtime.run(task_input)


def resume_task_llm(session_id: str, agent: MainAgent | None = None, llm_client=None) -> AgentState:
    runtime = LLMFirstRuntime(agent or MainAgent(), llm_client=llm_client, session_id=session_id)
    return runtime.resume(session_id)
