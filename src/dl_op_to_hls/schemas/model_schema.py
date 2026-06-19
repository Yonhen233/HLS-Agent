from __future__ import annotations

from ..core.design_objectives import normalize_objective_mode


def normalize_model_task(task: dict) -> dict:
    normalized = dict(task)
    normalized["objective"] = normalize_objective_mode(task.get("objective", "latency"), default="latency")
    normalized.setdefault("frontend", "onnx")
    normalized.setdefault("name", "model_demo")
    normalized.setdefault("hls4ml", {})
    return normalized
