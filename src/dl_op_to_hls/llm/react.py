from __future__ import annotations

import json
from typing import Any

from . import prompts
from .schemas import REACT_DECISION_SCHEMA
from .trace import emit_llm_event


class LLMReActDecider:
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
        payload = {
            "todo": todo,
            "scoped_state": scoped_state,
            "allowed_actions": allowed_actions,
            "direct_tools": allowed_tools,
            "recent_observations": recent_observations[-5:],
        }
        result = client.complete_json(
            system_prompt=prompts.REACT_SYSTEM_PROMPT,
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
