"""llm layer implementation for optimizer.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from . import prompts
from .schemas import OPTIMIZATION_SUGGESTION_SCHEMA
from .trace import emit_llm_event


class LLMOptimizationEngine:
    """Coordinate LLMOptimizationEngine within the optimizer boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    def generate(
        self,
        *,
        report: dict[str, Any],
        objective: str | None,
        rag_context: list[dict[str, Any]],
        state_summary: dict[str, Any],
        client,
        fallback: Callable[[], dict[str, Any]],
        allow_rule_fallback: bool = True,
    ) -> dict[str, Any]:
        """Execute generate at the optimizer boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            report: Value supplied by the caller and validated by the surrounding schema.
            objective: Value supplied by the caller and validated by the surrounding schema.
            rag_context: Value supplied by the caller and validated by the surrounding schema.
            state_summary: Value supplied by the caller and validated by the surrounding schema.
            client: Value supplied by the caller and validated by the surrounding schema.
            fallback: Value supplied by the caller and validated by the surrounding schema.
            allow_rule_fallback: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        if not client.is_enabled():
            if not allow_rule_fallback:
                raise RuntimeError("LLM optimization is disabled and rule fallback is not allowed in strict mode.")
            result = fallback()
            result["llm_fallback_used"] = True
            return result
        payload = {
            "report": report,
            "objective": objective,
            "rag_context": rag_context[:6],
            "state_summary": state_summary,
        }
        try:
            result = client.complete_json(
                system_prompt=prompts.resolve_prompt(client.context, "optimizer"),
                user_prompt=json.dumps(payload, ensure_ascii=False),
                schema=OPTIMIZATION_SUGGESTION_SCHEMA,
                temperature=0.2,
            )
            emit_llm_event(
                client.context,
                "LLMOptimizationGenerated",
                {
                    "run_id": client.context.get("run_id"),
                    "suggestion_count": len(result.get("suggestions", [])),
                },
            )
            result["llm_fallback_used"] = False
            return result
        except Exception:
            if not allow_rule_fallback:
                raise
            result = fallback()
            result["llm_fallback_used"] = True
            return result
