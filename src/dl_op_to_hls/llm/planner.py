from __future__ import annotations

import json
from typing import Any

from ..core.context_window import ContextWindowManager
from ..core.context_pack import ContextBlock, ContextPack
from . import prompts
from .schemas import TODO_PLAN_SCHEMA
from .trace import emit_llm_event


class LLMTodoPlanner:
    def __init__(self):
        self.context_window = ContextWindowManager()

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
        goal_contract: dict[str, Any] | None = None,
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
        blocks = [
            ContextBlock("task", task, priority=100, pinned=True, source="user"),
            ContextBlock("goal_contract", goal_contract or {}, priority=100, pinned=True, source="acceptance_gate"),
            ContextBlock("skill_context", skill_context, priority=90, pinned=True, source="skill_registry"),
            ContextBlock("main_agent_actions", layered_tool_view.get("main_agent_actions"), priority=80),
            ContextBlock("direct_tools", direct_tools, priority=85),
            ContextBlock("direct_tool_contracts", [
                item
                for item in layered_tool_view.get("direct_tool_specs", [])
                if item.get("name") in direct_tools
            ], priority=75),
            ContextBlock("available_specialists", specialists, priority=80),
            ContextBlock("skill_tool_contracts", [
                {
                    "skill": skill.get("name"),
                    "allowed_tools": skill.get("allowed_tools", []),
                    "allowed_specialists": skill.get("allowed_specialists", []),
                }
                for skill in skill_context.get("available_skills", [])
            ], priority=75),
            ContextBlock(
                "retrieved_memories",
                self.context_window.compact_records(retrieved_memories, max_items=6, max_tokens=1200),
                priority=60,
                source="memory",
            ),
            ContextBlock("instructions", [
                "Return selected_skill, skill_usage, reason_summary, and todos.",
                "Each todo should include title, assigned_tool, assigned_specialist, dependencies, and inputs.",
                "Main Agent can only directly use direct_tools and tools listed in the selected skill contract.",
                "For specialist-owned work, assign the specialist and the intended tool, but do not expose or invoke specialist private tools from Main Agent ReAct.",
                "Boundary/not-recommended demos should select unsupported_boundary_flow and only use that skill contract.",
                "Every plan_required Goal Contract requirement must be covered by at least one todo; the runtime will reject or repair incomplete plans.",
            ], priority=100, pinned=True, source="system"),
        ]
        max_context_tokens = min(
            [
                int(skill.get("context_policy", {}).get("max_context_tokens", 6000))
                for skill in skill_context.get("available_skills", [])
            ]
            or [6000]
        )
        compiled = ContextPack(blocks=blocks, token_budget=max_context_tokens, query=json.dumps(task, ensure_ascii=False)).compile()
        user_payload = {item["category"]: item["content"] for item in compiled["blocks"]}
        user_payload["context_ledger"] = compiled["ledger"]
        emit_llm_event(client.context, "ContextPackBuilt", {"run_id": client.context.get("run_id"), "phase": "plan", **compiled["ledger"]})
        result = client.complete_json(
            system_prompt=prompts.resolve_prompt(client.context, "todo_planner"),
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
