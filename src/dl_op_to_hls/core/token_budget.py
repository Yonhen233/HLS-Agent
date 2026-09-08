"""core layer implementation for token_budget.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

import copy
import json
import math
from dataclasses import is_dataclass
from typing import Any


class TokenBudgetManager:
    """Lightweight token estimator and truncator for scoped agent context."""

    def __init__(self, chars_per_token: int = 4):
        """Implement the internal __init__ helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            chars_per_token: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        self.chars_per_token = max(1, chars_per_token)

    def estimate_tokens(self, value: Any) -> int:
        """Execute estimate_tokens at the token_budget boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            value: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        text = self._to_text(value)
        return max(1, math.ceil(len(text) / self.chars_per_token))

    def truncate_text(self, text: str, max_tokens: int) -> str:
        """Execute truncate_text at the token_budget boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            text: Value supplied by the caller and validated by the surrounding schema.
            max_tokens: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        max_chars = max(0, max_tokens * self.chars_per_token)
        if len(text) <= max_chars:
            return text
        if max_chars <= 20:
            return text[:max_chars]
        return text[: max_chars - 16].rstrip() + "...[truncated]"

    def enforce_envelope_budget(self, envelope) -> dict[str, Any]:
        """Execute enforce_envelope_budget at the token_budget boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            envelope: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        before = self.estimate_tokens(envelope.to_dict())
        usage = {
            "estimated_input_tokens_before": before,
            "estimated_input_tokens": before,
            "max_context_tokens": envelope.max_context_tokens,
            "truncated": False,
            "truncation_steps": [],
        }
        if before <= envelope.max_context_tokens:
            envelope.constraints["token_budget"] = usage
            return usage

        usage["truncated"] = True
        self._truncate_rag_context(envelope, usage)
        self._truncate_retrieved_memories(envelope, usage)
        self._truncate_state_summary(envelope, usage)
        self._truncate_notes(envelope, usage)

        after = self.estimate_tokens(envelope.to_dict())
        if after > envelope.max_context_tokens:
            self._truncate_generic_strings(envelope.scoped_state, max_tokens=80)
            self._truncate_generic_strings(envelope.task_summary, max_tokens=80)
            usage["truncation_steps"].append("generic_long_string_truncation")
            after = self.estimate_tokens(envelope.to_dict())

        if after > envelope.max_context_tokens:
            self._drop_tail(envelope.retrieved_memory_refs, keep=2)
            rag_context = envelope.scoped_state.get("rag_context")
            if isinstance(rag_context, list):
                self._drop_tail(rag_context, keep=2)
            usage["truncation_steps"].append("drop_tail_memory_and_rag_refs")
            after = self.estimate_tokens(envelope.to_dict())

        if after > envelope.max_context_tokens:
            envelope.retrieved_memory_refs = envelope.retrieved_memory_refs[:1]
            rag_context = envelope.scoped_state.get("rag_context")
            if isinstance(rag_context, list):
                envelope.scoped_state["rag_context"] = rag_context[:1]
            state_summary = envelope.scoped_state.get("state_summary")
            if isinstance(state_summary, dict):
                envelope.scoped_state["state_summary"] = {
                    "run_id": state_summary.get("run_id"),
                    "objective": state_summary.get("objective"),
                    "selected_path": state_summary.get("selected_path"),
                    "report": state_summary.get("report"),
                }
            usage["truncation_steps"].append("minimize_memory_refs_and_state_summary")
            after = self.estimate_tokens(envelope.to_dict())

        usage["estimated_input_tokens"] = after
        envelope.constraints["token_budget"] = usage
        if after > envelope.max_context_tokens:
            envelope.notes.append(
                "Context still exceeds the estimated token budget after truncation; only artifact refs and compressed summaries are included."
            )
        else:
            envelope.notes.append("ContextEnvelope was truncated to fit the estimated token budget.")
        return usage

    def _truncate_rag_context(self, envelope, usage: dict[str, Any]) -> None:
        """Implement the internal _truncate_rag_context helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            envelope: Value supplied by the caller and validated by the surrounding schema.
            usage: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        rag_context = envelope.scoped_state.get("rag_context")
        if not isinstance(rag_context, list):
            return
        for item in rag_context:
            if isinstance(item, dict):
                for key in ("summary", "text"):
                    if isinstance(item.get(key), str):
                        item[key] = self.truncate_text(item[key], 80)
        usage["truncation_steps"].append("truncate_scoped_rag_context")

    def _truncate_retrieved_memories(self, envelope, usage: dict[str, Any]) -> None:
        """Implement the internal _truncate_retrieved_memories helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            envelope: Value supplied by the caller and validated by the surrounding schema.
            usage: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        for item in envelope.retrieved_memory_refs:
            if isinstance(item, dict):
                for key in ("summary", "text"):
                    if isinstance(item.get(key), str):
                        item[key] = self.truncate_text(item[key], 80)
        usage["truncation_steps"].append("truncate_retrieved_memory_refs")

    def _truncate_state_summary(self, envelope, usage: dict[str, Any]) -> None:
        """Implement the internal _truncate_state_summary helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            envelope: Value supplied by the caller and validated by the surrounding schema.
            usage: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        state_summary = envelope.scoped_state.get("state_summary")
        if not isinstance(state_summary, dict):
            return
        suggestions = state_summary.get("suggestions")
        if isinstance(suggestions, list):
            state_summary["suggestions"] = [self.truncate_text(str(item), 80) for item in suggestions[:5]]
        task = state_summary.get("task")
        if isinstance(task, dict) and "demo" in task:
            task = dict(task)
            task["demo"] = {"description": self.truncate_text(str(task.get("demo", {}).get("description", "")), 40)}
            state_summary["task"] = task
        usage["truncation_steps"].append("truncate_state_summary")

    def _truncate_notes(self, envelope, usage: dict[str, Any]) -> None:
        """Implement the internal _truncate_notes helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            envelope: Value supplied by the caller and validated by the surrounding schema.
            usage: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        envelope.notes = [self.truncate_text(str(item), 60) for item in envelope.notes[:5]]
        usage["truncation_steps"].append("truncate_notes")

    def _truncate_generic_strings(self, value: Any, max_tokens: int) -> Any:
        """Implement the internal _truncate_generic_strings helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            value: Value supplied by the caller and validated by the surrounding schema.
            max_tokens: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        if isinstance(value, dict):
            for key, item in list(value.items()):
                if isinstance(item, str):
                    value[key] = self.truncate_text(item, max_tokens)
                else:
                    self._truncate_generic_strings(item, max_tokens)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                if isinstance(item, str):
                    value[index] = self.truncate_text(item, max_tokens)
                else:
                    self._truncate_generic_strings(item, max_tokens)
        return value

    def _drop_tail(self, items: list[Any], keep: int) -> None:
        """Implement the internal _drop_tail helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            items: Value supplied by the caller and validated by the surrounding schema.
            keep: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        if len(items) > keep:
            del items[keep:]

    def _to_text(self, value: Any) -> str:
        """Implement the internal _to_text helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            value: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        if is_dataclass(value):
            value = copy.deepcopy(value).__dict__
        try:
            return json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)
        except Exception:
            return str(value)
