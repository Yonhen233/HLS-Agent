"""core layer implementation for context_window.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

import json
from typing import Any

from .token_budget import TokenBudgetManager
from .trace import stable_hash


class ContextWindowManager:
    """Builds compact, deduplicated model context with explicit priorities."""

    def __init__(self, token_budget: TokenBudgetManager | None = None):
        """Implement the internal __init__ helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            token_budget: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        self.token_budget = token_budget or TokenBudgetManager()

    def compact_records(
        self,
        records: list[dict[str, Any]],
        *,
        max_items: int = 6,
        max_tokens: int = 1200,
    ) -> list[dict[str, Any]]:
        """Execute compact_records at the context_window boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            records: Value supplied by the caller and validated by the surrounding schema.
            max_items: Value supplied by the caller and validated by the surrounding schema.
            max_tokens: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
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
        """Execute compact_recent_observations at the context_window boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            observations: Value supplied by the caller and validated by the surrounding schema.
            max_items: Value supplied by the caller and validated by the surrounding schema.
            max_tokens: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
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
        """Implement the internal _compact_record helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            item: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
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
        """Execute estimate_payload_tokens at the context_window boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            payload: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        return self.token_budget.estimate_tokens(json.dumps(payload, ensure_ascii=False, default=str))
