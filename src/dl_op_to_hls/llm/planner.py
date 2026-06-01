from __future__ import annotations

import json
from typing import Any

from . import prompts
from .schemas import TODO_PLAN_SCHEMA
from .trace import emit_llm_event


class LLMTodoPlanner:
    def plan(
        self,
        *,
        task: dict[str, Any],
        skill_context: dict[str, Any],
        available_tools: list[str],
        available_specialists: list[str],
        retrieved_memories: list[dict[str, Any]],
        client,
        layered_tool_view: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        layered_tool_view = layered_tool_view or {}
        candidate_skill_tools = {
            tool
            for skill in skill_context.get("available_skills", [])
            for tool in skill.get("allowed_tools", [])
        }
        candidate_skill_specialists = {
            specialist
            for skill in skill_context.get("available_skills", [])
            for specialist in skill.get("allowed_specialists", [])
        }
        direct_tools = [
            tool
            for tool in layered_tool_view.get("direct_tools", available_tools)
            if not candidate_skill_tools or tool in candidate_skill_tools
        ]
        specialists = []
        for item in layered_tool_view.get("specialists", available_specialists):
            specialist_name = item.get("name") if isinstance(item, dict) else item
            if not candidate_skill_specialists or specialist_name in candidate_skill_specialists:
                specialists.append(item)
        user_payload = {
            "task": task,
            "skill_context": skill_context,
            "main_agent_actions": layered_tool_view.get("main_agent_actions"),
            "direct_tools": direct_tools,
            "available_specialists": specialists,
            "skill_tool_contracts": [
                {
                    "skill": skill.get("name"),
                    "allowed_tools": skill.get("allowed_tools", []),
                    "allowed_specialists": skill.get("allowed_specialists", []),
                }
                for skill in skill_context.get("available_skills", [])
            ],
            "retrieved_memories": retrieved_memories[:6],
            "instructions": [
                "Return selected_skill, skill_usage, reason_summary, and todos.",
                "Each todo should include title, assigned_tool, assigned_specialist, dependencies, and inputs.",
                "Main Agent can only directly use direct_tools and tools listed in the selected skill contract.",
                "For specialist-owned work, assign the specialist and the intended tool, but do not expose or invoke specialist private tools from Main Agent ReAct.",
                "Boundary/not-recommended demos should select unsupported_boundary_flow and only use that skill contract.",
            ],
        }
        result = client.complete_json(
            system_prompt=prompts.TODO_PLANNER_SYSTEM_PROMPT,
            user_prompt=json.dumps(user_payload, ensure_ascii=False),
            schema=TODO_PLAN_SCHEMA,
            temperature=0.0,
        )
        emit_llm_event(
            client.context,
            "LLMPlanGenerated",
            {
                "run_id": client.context.get("run_id"),
                "selected_skill": result.get("selected_skill"),
                "skill_usage_mode": result.get("skill_usage"),
                "todo_count": len(result.get("todos", [])),
            },
        )
        return result
