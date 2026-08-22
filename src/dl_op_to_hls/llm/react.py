from __future__ import annotations

import json
from typing import Any

from ..core.context_window import ContextWindowManager
from ..core.context_pack import ContextBlock, ContextPack
from . import prompts
from .schemas import REACT_DECISION_SCHEMA
from .trace import emit_llm_event


class LLMReActDecider:
    def __init__(self):
        self.context_window = ContextWindowManager()

    def decide(
        self,
        *,
        todo: dict[str, Any],
        scoped_state: dict[str, Any],
        allowed_tools: list[str],
        allowed_actions: list[str] | None = None,
        recent_observations: list[dict[str, Any]],
        client,
    ) -> dict[str, Any]:
        allowed_actions = allowed_actions or ["direct_tool_only_when_no_specialist", "mark_blocked", "mark_failed"]
        compiled = ContextPack(
            blocks=[
                ContextBlock("todo", todo, priority=100, pinned=True, source="plan"),
                ContextBlock("allowed_actions", allowed_actions, priority=100, pinned=True, source="policy"),
                ContextBlock("direct_tools", allowed_tools, priority=100, pinned=True, source="policy"),
                ContextBlock("scoped_state", scoped_state, priority=80, source="state"),
                ContextBlock(
                    "recent_observations",
                    self.context_window.compact_recent_observations(recent_observations),
                    priority=85,
                    source="trace",
                ),
            ],
            token_budget=3000,
            query=str(todo.get("title") or ""),
        ).compile()
        payload = {item["category"]: item["content"] for item in compiled["blocks"]}
        payload["context_ledger"] = compiled["ledger"]
        emit_llm_event(client.context, "ContextPackBuilt", {"run_id": client.context.get("run_id"), "phase": "react", **compiled["ledger"]})
        result = client.complete_json(
            system_prompt=prompts.resolve_prompt(client.context, "react"),
            user_prompt=json.dumps(payload, ensure_ascii=False),
            schema=REACT_DECISION_SCHEMA,
            temperature=0.0,
        )
        if result.get("decision") == "direct_tool_only_when_no_specialist":
            action = result.get("action")
            if not isinstance(action, dict):
                action = {}
            if not action.get("tool_name") and allowed_tools:
                action["tool_name"] = allowed_tools[0]
            result["action"] = action
        if result.get("decision") == "delegate_to_specialist":
            action = result.get("action")
            if not isinstance(action, dict):
                action = {}
            if not action.get("specialist_name") and todo.get("assigned_specialist"):
                action["specialist_name"] = todo["assigned_specialist"]
            result["action"] = action
        emit_llm_event(
            client.context,
            "LLMReActDecision",
            {
                "run_id": client.context.get("run_id"),
                "todo_id": todo.get("id"),
                "decision": result.get("decision"),
                "reason_summary": result.get("reason_summary"),
            },
        )
        return result
