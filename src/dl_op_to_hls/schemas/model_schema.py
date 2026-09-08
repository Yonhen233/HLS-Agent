"""schemas layer implementation for model_schema.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

from ..core.design_objectives import normalize_objective_mode


def normalize_model_task(task: dict) -> dict:
    """Execute normalize_model_task at the model_schema boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Args:
        task: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    normalized = dict(task)
    normalized["objective"] = normalize_objective_mode(task.get("objective", "latency"), default="latency")
    normalized.setdefault("frontend", "onnx")
    normalized.setdefault("name", "model_demo")
    normalized.setdefault("hls4ml", {})
    return normalized
