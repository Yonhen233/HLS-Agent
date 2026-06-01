from __future__ import annotations

import json
from typing import Any

from . import prompts
from .schemas import REFLECTION_DECISION_SCHEMA
from .trace import emit_llm_event


class LLMReflectionEngine:
    def reflect(
        self,
        *,
        current_todo: dict[str, Any],
        observation: dict[str, Any],
        current_skill: str | None,
        state_summary: dict[str, Any],
        client,
    ) -> dict[str, Any]:
        payload = {
            "current_todo": current_todo,
            "observation": observation,
            "current_skill": current_skill,
            "state_summary": state_summary,
        }
        result = client.complete_json(
            system_prompt=prompts.REFLECTION_SYSTEM_PROMPT,
            user_prompt=json.dumps(payload, ensure_ascii=False),
            schema=REFLECTION_DECISION_SCHEMA,
            temperature=0.0,
        )
        emit_llm_event(
            client.context,
            "LLMReflectionDecision",
            {
                "run_id": client.context.get("run_id"),
                "todo_id": current_todo.get("id"),
                "decision": result.get("decision"),
                "todo_status": result.get("todo_status"),
            },
        )
        return result
