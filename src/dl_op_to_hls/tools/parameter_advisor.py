from __future__ import annotations

import json
import re
from typing import Any

from ..core.design_objectives import normalize_objective_mode


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in re.findall(r"[A-Za-z0-9_]+", text or "") if len(token) >= 3}


def _verified(value: dict[str, Any]) -> bool:
    verification = value.get("verification") or {}
    if not isinstance(verification, dict):
        return False
    mode = verification.get("mode")
    if verification.get("passed") is True and mode in {"golden_testbench", "hls4ml_reference_compare", "reference_compare"}:
        return True
    comparison = verification.get("comparison") if isinstance(verification.get("comparison"), dict) else {}
    return verification.get("passed") is True and comparison.get("passed") is True


def _load_value(item: dict[str, Any]) -> dict[str, Any]:
    raw = item.get("value_json") or "{}"
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _timing_is_usable(value: dict[str, Any]) -> bool:
    report = value.get("report") if isinstance(value.get("report"), dict) else value
    timing = report.get("timing") if isinstance(report, dict) else {}
    return not (isinstance(timing, dict) and timing.get("met") is False)


def _looks_like_sample_fixture(value: dict[str, Any]) -> bool:
    """Guard ParameterAdvisor against mock/sample Vivado reports promoted during demo runs."""
    report = value.get("report") if isinstance(value.get("report"), dict) else value
    if not isinstance(report, dict):
        return False
    resources = report.get("resources") if isinstance(report.get("resources"), dict) else {}
    latency = report.get("latency") if isinstance(report.get("latency"), dict) else {}
    timing = report.get("timing") if isinstance(report.get("timing"), dict) else {}
    sample_resources = resources == {"bram": 0, "dsp": 32, "ff": 2100, "lut": 3500}
    sample_latency = latency.get("min_cycles") == 45 and latency.get("max_cycles") == 45
    sample_timing = float(timing.get("estimated_ns", -1)) == 4.3
    verification = value.get("verification") if isinstance(value.get("verification"), dict) else {}
    model_task = (value.get("task") or {}).get("task_type") == "model"
    return bool(model_task and sample_resources and sample_latency and sample_timing and verification.get("mode") == "golden_testbench")


def _task_signature(task: dict[str, Any]) -> set[str]:
    shape_text = " ".join(str(item) for item in (task.get("input_shape") or task.get("output_shape") or []))
    return _tokens(
        " ".join(
            str(task.get(key, ""))
            for key in ["name", "op_type", "task_type", "frontend", "objective", "layout"]
        )
        + " "
        + shape_text
    )


def _task_family(task: dict[str, Any]) -> str | None:
    text = " ".join(str(task.get(key, "")) for key in ["name", "op_type", "frontend"]).lower()
    if "resnet" in text or "residual" in text:
        return "residual"
    if "qonnx" in text or "qkeras" in text:
        return "quantized_cnn"
    if "cnn" in text or "conv" in text:
        return "cnn"
    if "mlp" in text or "dense" in text:
        return "mlp"
    if "matmul" in text:
        return "matmul"
    if "relu" in text:
        return "relu"
    if "add" in text:
        return "add"
    return None


def _objective(task: dict[str, Any]) -> str:
    optimization = task.get("optimization") if isinstance(task.get("optimization"), dict) else {}
    return normalize_objective_mode(task.get("objective") or optimization.get("objective") or "balanced", default="balanced")


def _params_from_task(task: dict[str, Any]) -> dict[str, Any]:
    hls4ml = task.get("hls4ml") or {}
    target = task.get("target") or {}
    optimization = task.get("optimization") or {}
    return {
        "precision": hls4ml.get("precision") or task.get("dtype"),
        "reuse_factor": hls4ml.get("reuse_factor") or optimization.get("reuse_factor"),
        "strategy": hls4ml.get("strategy"),
        "clock_period": target.get("clock_period"),
        "pipeline_ii": optimization.get("pipeline_ii"),
    }


def _updates_from_params(params: dict[str, Any]) -> dict[str, Any]:
    updates = {"hls4ml": {}, "target": {}, "optimization": {}}
    if params.get("precision") is not None:
        updates["hls4ml"]["precision"] = params["precision"]
    if params.get("reuse_factor") is not None:
        updates["hls4ml"]["reuse_factor"] = params["reuse_factor"]
        updates["optimization"]["reuse_factor"] = params["reuse_factor"]
    if params.get("strategy") is not None:
        updates["hls4ml"]["strategy"] = params["strategy"]
    if params.get("clock_period") is not None:
        updates["target"]["clock_period"] = params["clock_period"]
    if params.get("pipeline_ii") is not None:
        updates["optimization"]["pipeline_ii"] = params["pipeline_ii"]
    return {key: value for key, value in updates.items() if value}


def _resource_cost(report: dict[str, Any], objective: str) -> float:
    resources = report.get("resources") if isinstance(report.get("resources"), dict) else {}
    latency = report.get("latency") if isinstance(report.get("latency"), dict) else {}
    interval = report.get("interval") if isinstance(report.get("interval"), dict) else {}
    lut = float(resources.get("lut") if resources.get("lut") is not None else 1_000_000)
    ff = float(resources.get("ff") if resources.get("ff") is not None else 1_000_000)
    dsp = float(resources.get("dsp") if resources.get("dsp") is not None else 10_000)
    bram = float(resources.get("bram") if resources.get("bram") is not None else 10_000)
    latency_cycles = float(latency.get("max_cycles") if latency.get("max_cycles") is not None else 1_000_000)
    ii_cycles = float(interval.get("max_ii") if interval.get("max_ii") is not None else latency_cycles)
    # Weighted cost keeps units comparable enough for ranking verified profiles.
    cost = lut + 0.1 * ff + 100.0 * dsp + 50.0 * bram
    if objective == "latency":
        return latency_cycles + 0.10 * ii_cycles + 0.02 * cost
    if objective == "throughput":
        return ii_cycles + 0.20 * latency_cycles + 0.02 * cost
    if objective == "performance":
        return 0.45 * latency_cycles + 0.45 * ii_cycles + 0.03 * cost
    if objective == "balanced":
        return cost + 0.35 * latency_cycles + 0.35 * ii_cycles
    if objective == "standard":
        return 0.8 * cost + 0.2 * latency_cycles
    return cost


def _recommendation_rows(params: dict[str, Any], reason: str, source: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, value in params.items():
        if value is not None:
            rows.append(
                {
                    "parameter": key,
                    "recommended_value": value,
                    "source": source,
                    "reason": reason,
                }
            )
    return rows


def _heuristic_params(task: dict[str, Any]) -> dict[str, Any]:
    family = _task_family(task)
    if family == "mlp":
        return {"precision": "fixed<12,6>", "reuse_factor": 1024, "strategy": "Resource", "clock_period": 10}
    if family == "quantized_cnn":
        return {"precision": "fixed<8,3>", "reuse_factor": 32, "strategy": "Resource", "clock_period": 10}
    if family == "cnn":
        return {"precision": "fixed<10,4>", "reuse_factor": 64, "strategy": "Resource", "clock_period": 10}
    if family == "matmul":
        return {"precision": task.get("dtype") or "ap_fixed<12,4>", "reuse_factor": 8, "clock_period": 10, "pipeline_ii": 2}
    if family in {"add", "relu"}:
        return {"precision": task.get("dtype") or "ap_fixed<16,6>", "reuse_factor": 1, "clock_period": 5, "pipeline_ii": 1}
    return {}


def _rag_hints_for_task(task: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
    rag_memory = context.get("rag_memory")
    if rag_memory is None:
        return []
    query = f"{task.get('name')} {_task_family(task) or ''} precision reuse_factor clock verified parameter"
    try:
        return rag_memory.retrieve(query, top_k=3, domain="parameter")
    except TypeError:
        return rag_memory.retrieve(query, top_k=3)


def recommend_parameters(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    state = arguments.get("state") or {}
    task = state.get("task") or arguments.get("task") or {}
    current_run_id = state.get("run_id")
    repository = context.get("repository")
    current_params = _params_from_task(task)
    rag_hints = _rag_hints_for_task(task, context)
    if repository is None:
        return {
            "status": "no_repository",
            "mode": "unavailable",
            "recommendations": [],
            "reason": "ParameterAdvisor requires the metadata repository in tool context.",
        }

    task_tokens = _task_signature(task)
    objective = _objective(task)
    candidates: list[dict[str, Any]] = []
    for item in repository.list_memory_items(["parameter_experience", "verified_implementation", "optimization", "implementation"]):
        if current_run_id and item.get("source_run_id") == current_run_id:
            continue
        value = _load_value(item)
        if not _verified(value):
            continue
        if not _timing_is_usable(value):
            continue
        if _looks_like_sample_fixture(value):
            continue
        candidate_task = value.get("task") or {}
        candidate_tokens = _task_signature(candidate_task)
        overlap = len(task_tokens.intersection(candidate_tokens))
        task_family = _task_family(task)
        candidate_family = _task_family(candidate_task)
        same_family = task_family and task_family == candidate_family
        if task_family and candidate_family and task_family != candidate_family:
            continue
        if task_tokens and candidate_tokens and overlap == 0:
            continue
        report = value.get("report") if isinstance(value.get("report"), dict) else value
        params = _params_from_task(candidate_task)
        if not any(value is not None for value in params.values()):
            continue
        candidates.append(
            {
                "memory_id": item.get("id"),
                "source_run_id": item.get("source_run_id"),
                "score": overlap + (2.0 if same_family else 0.0) + float(item.get("importance") or 1) * 0.1,
                "resource_cost": _resource_cost(report, objective),
                "params": params,
                "report": report,
                "verification": value.get("verification"),
                "task_family": candidate_family,
            }
        )
    candidates.sort(key=lambda item: (-item["score"], item["resource_cost"]))
    if candidates:
        best = candidates[0]
        reason = f"Matched verified run {best.get('source_run_id')} with functional verification passed."
        recommendations = _recommendation_rows(best["params"], reason, "verified_history")
        return {
            "status": "success",
            "mode": "verified_history",
            "confidence": 0.9,
            "source_count": len(candidates),
            "recommendations": recommendations,
            "recommended_updates": _updates_from_params(best["params"]),
            "matched_history": candidates[:5],
            "rag_hints": rag_hints,
        }

    heuristic = _heuristic_params(task)
    if heuristic:
        reason = "No verified history matched; use a conservative task-family heuristic as bootstrap, not as verified evidence."
        return {
            "status": "heuristic_available",
            "mode": "heuristic_bootstrap",
            "confidence": 0.45,
            "source_count": 0,
            "recommendations": _recommendation_rows({**current_params, **heuristic}, reason, "heuristic"),
            "recommended_updates": _updates_from_params({**current_params, **heuristic}),
            "rag_hints": rag_hints,
            "reason": reason,
        }

    bootstrap = _recommendation_rows(
        current_params,
        "No verified history exists yet; keep current task setting until a verified run is promoted.",
        "current_task",
    )
    return {
        "status": "no_verified_history",
        "mode": "bootstrap",
        "confidence": 0.25,
        "source_count": 0,
        "recommendations": bootstrap,
        "recommended_updates": _updates_from_params(current_params),
        "rag_hints": rag_hints,
        "reason": "No functionally verified parameter history matched the current task.",
    }
