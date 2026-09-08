"""llm layer implementation for finalizer.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

from typing import Any


class LLMFinalizer:
    """Coordinate LLMFinalizer within the finalizer boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    def build_fact_guarded_context(self, state: dict[str, Any]) -> dict[str, Any]:
        """Execute build_fact_guarded_context at the finalizer boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            state: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        report = state.get("report") or {}
        return {
            "run_id": state.get("run_id"),
            "task": state.get("task", {}),
            "selected_path": state.get("selected_path"),
            "status": state.get("status"),
            "report_metrics": {
                "latency": report.get("latency"),
                "interval": report.get("interval"),
                "resources": report.get("resources"),
                "timing": report.get("timing"),
            },
            "errors": state.get("errors", []),
            "artifacts": state.get("artifacts", {}),
        }
