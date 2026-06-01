from __future__ import annotations

from typing import Any


def rewrite_graph(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    del context
    task = arguments.get("task", {})
    op_type = task.get("op_type") or task.get("name") or "unknown"
    rewrites = []
    recommendation = "No rewrite rule matched."
    if str(op_type).lower() == "gemm":
        rewrites = ["Gemm -> MatMul + Add"]
        recommendation = "Try MatMul + Add fallback template."
    elif str(op_type).lower() in {"batchnorm", "batchnormalization"}:
        rewrites = ["BatchNorm inference -> fold into Dense / Conv"]
        recommendation = "Fold BatchNorm parameters before HLS conversion."
    elif str(op_type).lower() in {"flatten", "reshape"}:
        rewrites = ["Flatten / Reshape -> static shape elimination"]
        recommendation = "Remove no-op reshape and retry support check."
    return {"status": "success", "rewrites": rewrites, "recommendation": recommendation}

