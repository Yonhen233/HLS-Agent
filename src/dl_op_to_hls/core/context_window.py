from __future__ import annotations

import json
from typing import Any

from .token_budget import TokenBudgetManager
from .trace import stable_hash


class ContextWindowManager:
    """Builds compact, deduplicated model context with explicit priorities."""

    def __init__(self, token_budget: TokenBudgetManager | None = None):
        self.token_budget = token_budget or TokenBudgetManager()

    def compact_records(
        self,
        records: list[dict[str, Any]],
        *,
        max_items: int = 6,
        max_tokens: int = 1200,
    ) -> list[dict[str, Any]]:
        selected: list[dict[str, Any]] = []
        seen: set[str] = set()
        used_tokens = 0
        ordered = sorted(
            records,
            key=lambda item: (
                float(item.get("score", 0.0)),
                float(item.get("confidence", (item.get("provenance") or {}).get("trust_score", 0.0))),
            ),
            reverse=True,
        )
        for item in ordered:
            compact = self._compact_record(item)
            fingerprint = stable_hash(compact)
            if fingerprint in seen:
                continue
            item_tokens = self.token_budget.estimate_tokens(compact)
            if selected and used_tokens + item_tokens > max_tokens:
                continue
            selected.append(compact)
            seen.add(fingerprint)
            used_tokens += item_tokens
            if len(selected) >= max_items:
                break
        return selected

    def compact_recent_observations(
        self,
        observations: list[dict[str, Any]],
        *,
        max_items: int = 5,
        max_tokens: int = 700,
    ) -> list[dict[str, Any]]:
        compacted: list[dict[str, Any]] = []
        used = 0
        for item in reversed(observations):
            result = item.get("result") if isinstance(item.get("result"), dict) else item
            compact = {
                "tool": item.get("tool") or item.get("specialist"),
                "status": result.get("status") if isinstance(result, dict) else None,
                "summary": self.token_budget.truncate_text(
                    str((result or {}).get("summary") or (result or {}).get("error") or ""),
                    80,
                ),
            }
            cost = self.token_budget.estimate_tokens(compact)
            if compacted and used + cost > max_tokens:
                continue
            compacted.append(compact)
            used += cost
            if len(compacted) >= max_items:
                break
        compacted.reverse()
        return compacted

    def _compact_record(self, item: dict[str, Any]) -> dict[str, Any]:
        text = item.get("summary") or item.get("text") or item.get("fact") or ""
        return {
            "source": item.get("source_id") or item.get("source_run_id") or item.get("id"),
            "summary": self.token_budget.truncate_text(str(text), 120),
            "score": item.get("score"),
            "memory_type": item.get("memory_type") or (item.get("metadata") or {}).get("memory_type"),
            "provenance": item.get("provenance") or {
                "source_type": (item.get("metadata") or {}).get("source_type"),
                "confidence": item.get("confidence"),
            },
        }

    def estimate_payload_tokens(self, payload: dict[str, Any]) -> int:
        return self.token_budget.estimate_tokens(json.dumps(payload, ensure_ascii=False, default=str))
