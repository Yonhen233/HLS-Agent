"""main_agent layer implementation for workflow.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

from .agent import MainAgent
from .llm_runtime import LLMFirstRuntime
from .runtime import PlanExecuteReactRuntime
from .state import AgentState


def run_task(task_path: str, agent: MainAgent | None = None) -> AgentState:
    """Execute run_task at the workflow boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Args:
        task_path: Value supplied by the caller and validated by the surrounding schema.
        agent: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
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
    """Execute run_task_llm at the workflow boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Args:
        task_input: Value supplied by the caller and validated by the surrounding schema.
        agent: Value supplied by the caller and validated by the surrounding schema.
        llm_client: Value supplied by the caller and validated by the surrounding schema.
        session_id: Value supplied by the caller and validated by the surrounding schema.
        user_id: Value supplied by the caller and validated by the surrounding schema.
        project_id: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    active_agent = agent or MainAgent()
    runtime = LLMFirstRuntime(
        active_agent,
        llm_client=llm_client or active_agent.llm_client,
        session_id=session_id,
        user_id=user_id,
        project_id=project_id,
    )
    return runtime.run(task_input)


def resume_task_llm(session_id: str, agent: MainAgent | None = None, llm_client=None) -> AgentState:
    """Execute resume_task_llm at the workflow boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Args:
        session_id: Value supplied by the caller and validated by the surrounding schema.
        agent: Value supplied by the caller and validated by the surrounding schema.
        llm_client: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    active_agent = agent or MainAgent()
    runtime = LLMFirstRuntime(active_agent, llm_client=llm_client or active_agent.llm_client, session_id=session_id)
    return runtime.resume(session_id)
