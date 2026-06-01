from __future__ import annotations


def normalize_operator_task(task: dict) -> dict:
    normalized = dict(task)
    normalized.setdefault("name", f"{task.get('op_type', 'operator').lower()}_demo")
    optimization = dict(task.get("optimization", {}))
    normalized["objective"] = optimization.get("objective", task.get("objective", "latency"))
    normalized["optimization"] = optimization
    return normalized

