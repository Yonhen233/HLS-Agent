"""llm layer implementation for reflector.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

import json
from typing import Any

from . import prompts
from .schemas import REFLECTION_DECISION_SCHEMA
from .trace import emit_llm_event


class LLMReflectionEngine:
    """Coordinate LLMReflectionEngine within the reflector boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    def reflect(
        self,
        *,
        current_todo: dict[str, Any],
        observation: dict[str, Any],
        current_skill: str | None,
        state_summary: dict[str, Any],
        client,
    ) -> dict[str, Any]:
        """Execute reflect at the reflector boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            current_todo: Value supplied by the caller and validated by the surrounding schema.
            observation: Value supplied by the caller and validated by the surrounding schema.
            current_skill: Value supplied by the caller and validated by the surrounding schema.
            state_summary: Value supplied by the caller and validated by the surrounding schema.
            client: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        payload = {
            "current_todo": current_todo,
            "observation": observation,
            "current_skill": current_skill,
            "state_summary": state_summary,
        }
        result = client.complete_json(
            system_prompt=prompts.resolve_prompt(client.context, "reflection"),
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
