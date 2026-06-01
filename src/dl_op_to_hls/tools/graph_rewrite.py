from __future__ import annotations

from pathlib import Path
from typing import Any


def rewrite_graph(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    del context
    task = arguments.get("task", {})
    op_type = task.get("op_type") or task.get("name") or "unknown"
    rewrites = []
    recommendation = "No rewrite rule matched."
    detected_ops: list[str] = []
    model_path = task.get("model_path")
    if model_path and Path(model_path).exists() and Path(model_path).suffix.lower() == ".onnx":
        try:
            import onnx  # type: ignore

            model = onnx.load(str(model_path))
            detected_ops = sorted({node.op_type for node in model.graph.node})
        except Exception:
            detected_ops = []
    if str(op_type).lower() == "gemm":
        rewrites = ["Gemm -> MatMul + Add"]
        recommendation = "Try MatMul + Add fallback template."
    elif "Gemm" in detected_ops:
        rewrites = ["Gemm -> MatMul + Add"]
        recommendation = "Rewrite ONNX Gemm into explicit MatMul plus Add before hls4ml conversion."
    elif any(op in detected_ops for op in {"Shape", "Reshape", "Flatten"}):
        rewrites = ["Shape/Reshape/Flatten -> static shape elimination"]
        recommendation = "Eliminate static shape operators before hls4ml conversion; keep tensor shapes in metadata."
    elif str(op_type).lower() in {"batchnorm", "batchnormalization"}:
        rewrites = ["BatchNorm inference -> fold into Dense / Conv"]
        recommendation = "Fold BatchNorm parameters before HLS conversion."
    elif str(op_type).lower() in {"flatten", "reshape"}:
        rewrites = ["Flatten / Reshape -> static shape elimination"]
        recommendation = "Remove no-op reshape and retry support check."
    return {
        "status": "rewrite_suggested" if rewrites else "success",
        "rewrites": rewrites,
        "detected_ops": detected_ops,
        "recommendation": recommendation,
        "implemented": False,
    }
