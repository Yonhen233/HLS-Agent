from __future__ import annotations

import json
from typing import Any, Callable

from . import prompts
from .schemas import OPTIMIZATION_SUGGESTION_SCHEMA
from .trace import emit_llm_event


class LLMOptimizationEngine:
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
                system_prompt=prompts.OPTIMIZER_SYSTEM_PROMPT,
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
