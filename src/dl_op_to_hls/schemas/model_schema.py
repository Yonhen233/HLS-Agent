from __future__ import annotations


def normalize_model_task(task: dict) -> dict:
    normalized = dict(task)
    normalized.setdefault("objective", task.get("objective", "latency"))
    normalized.setdefault("frontend", "onnx")
    normalized.setdefault("name", "model_demo")
    normalized.setdefault("hls4ml", {})
    return normalized

