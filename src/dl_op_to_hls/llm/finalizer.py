from __future__ import annotations

from typing import Any


class LLMFinalizer:
    def build_fact_guarded_context(self, state: dict[str, Any]) -> dict[str, Any]:
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
