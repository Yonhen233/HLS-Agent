"""core layer implementation for budgets.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass
from typing import Any


class BudgetExceededError(RuntimeError):
    """Coordinate BudgetExceededError within the budgets boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    pass


@dataclass
class RunBudgetSnapshot:
    """Coordinate RunBudgetSnapshot within the budgets boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    max_llm_calls: int
    max_tool_calls: int
    max_total_tokens: int
    llm_calls: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_hits: int = 0

    @property
    def total_tokens(self) -> int:
        """Execute total_tokens at the budgets boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Returns:
            The structured value promised by the function signature.
        """
        return self.input_tokens + self.output_tokens


class RunBudget:
    """Thread-safe run budget shared by the main agent, sub agents and tools."""

    def __init__(self, max_llm_calls: int = 30, max_tool_calls: int = 80, max_total_tokens: int = 120_000):
        """Implement the internal __init__ helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            max_llm_calls: Value supplied by the caller and validated by the surrounding schema.
            max_tool_calls: Value supplied by the caller and validated by the surrounding schema.
            max_total_tokens: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        self.snapshot = RunBudgetSnapshot(
            max_llm_calls=max(1, max_llm_calls),
            max_tool_calls=max(1, max_tool_calls),
            max_total_tokens=max(1, max_total_tokens),
        )
        self._lock = threading.Lock()

    def reserve_llm_call(self, estimated_input_tokens: int = 0) -> None:
        """Execute reserve_llm_call at the budgets boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            estimated_input_tokens: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        with self._lock:
            if self.snapshot.llm_calls >= self.snapshot.max_llm_calls:
                raise BudgetExceededError("LLM call budget exceeded")
            if self.snapshot.total_tokens + max(0, estimated_input_tokens) > self.snapshot.max_total_tokens:
                raise BudgetExceededError("Token budget exceeded before LLM call")
            self.snapshot.llm_calls += 1

    def record_llm_usage(self, input_tokens: int, output_tokens: int) -> None:
        """Execute record_llm_usage at the budgets boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            input_tokens: Value supplied by the caller and validated by the surrounding schema.
            output_tokens: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        with self._lock:
            self.snapshot.input_tokens += max(0, int(input_tokens))
            self.snapshot.output_tokens += max(0, int(output_tokens))
            if self.snapshot.total_tokens > self.snapshot.max_total_tokens:
                raise BudgetExceededError("Token budget exceeded after LLM call")

    def reserve_tool_call(self) -> None:
        """Execute reserve_tool_call at the budgets boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Returns:
            The structured value promised by the function signature.
        """
        with self._lock:
            if self.snapshot.tool_calls >= self.snapshot.max_tool_calls:
                raise BudgetExceededError("Tool call budget exceeded")
            self.snapshot.tool_calls += 1

    def record_cache_hit(self) -> None:
        """Execute record_cache_hit at the budgets boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Returns:
            The structured value promised by the function signature.
        """
        with self._lock:
            self.snapshot.cache_hits += 1

    def tighten(
        self,
        *,
        max_llm_calls: int | None = None,
        max_tool_calls: int | None = None,
        max_total_tokens: int | None = None,
    ) -> None:
        """Apply a skill-specific ceiling without invalidating consumed budget."""
        with self._lock:
            if max_llm_calls is not None:
                self.snapshot.max_llm_calls = max(
                    self.snapshot.llm_calls,
                    min(self.snapshot.max_llm_calls, max(1, int(max_llm_calls))),
                )
            if max_tool_calls is not None:
                self.snapshot.max_tool_calls = max(
                    self.snapshot.tool_calls,
                    min(self.snapshot.max_tool_calls, max(1, int(max_tool_calls))),
                )
            if max_total_tokens is not None:
                self.snapshot.max_total_tokens = max(
                    self.snapshot.total_tokens,
                    min(self.snapshot.max_total_tokens, max(1, int(max_total_tokens))),
                )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RunBudget":
        """Execute from_dict at the budgets boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            payload: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        budget = cls(
            max_llm_calls=int(payload.get("max_llm_calls") or 30),
            max_tool_calls=int(payload.get("max_tool_calls") or 80),
            max_total_tokens=int(payload.get("max_total_tokens") or 120_000),
        )
        with budget._lock:
            budget.snapshot.llm_calls = max(0, int(payload.get("llm_calls") or 0))
            budget.snapshot.tool_calls = max(0, int(payload.get("tool_calls") or 0))
            budget.snapshot.input_tokens = max(0, int(payload.get("input_tokens") or 0))
            budget.snapshot.output_tokens = max(0, int(payload.get("output_tokens") or 0))
            budget.snapshot.cache_hits = max(0, int(payload.get("cache_hits") or 0))
        return budget

    def to_dict(self) -> dict[str, Any]:
        """Execute to_dict at the budgets boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Returns:
            The structured value promised by the function signature.
        """
        with self._lock:
            payload = asdict(self.snapshot)
            payload["total_tokens"] = self.snapshot.total_tokens
            return payload
