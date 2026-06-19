from __future__ import annotations

from ..core.design_objectives import normalize_objective_mode


def normalize_operator_task(task: dict) -> dict:
    normalized = dict(task)
    normalized.setdefault("name", f"{task.get('op_type', 'operator').lower()}_demo")
    optimization = dict(task.get("optimization", {}))
    normalized["objective"] = normalize_objective_mode(
        optimization.get("objective", task.get("objective", "latency")),
        default="latency",
    )
    if "objective" in optimization:
        optimization["objective"] = normalized["objective"]
    normalized["optimization"] = optimization
    return normalized
