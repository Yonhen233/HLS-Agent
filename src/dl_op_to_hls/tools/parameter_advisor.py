from __future__ import annotations

import json
import re
from typing import Any


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


def _task_signature(task: dict[str, Any]) -> set[str]:
    return _tokens(
        " ".join(
            str(task.get(key, ""))
            for key in ["name", "op_type", "task_type", "frontend", "objective"]
        )
    )


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


def recommend_parameters(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    state = arguments.get("state") or {}
    task = state.get("task") or arguments.get("task") or {}
    current_run_id = state.get("run_id")
    repository = context.get("repository")
    current_params = _params_from_task(task)
    if repository is None:
        return {
            "status": "no_repository",
            "mode": "unavailable",
            "recommendations": [],
            "reason": "ParameterAdvisor requires the metadata repository in tool context.",
        }

    task_tokens = _task_signature(task)
    candidates: list[dict[str, Any]] = []
    for item in repository.list_memory_items(["optimization", "implementation"]):
        if current_run_id and item.get("source_run_id") == current_run_id:
            continue
        value = _load_value(item)
        if not _verified(value):
            continue
        if not _timing_is_usable(value):
            continue
        candidate_task = value.get("task") or {}
        candidate_tokens = _task_signature(candidate_task)
        overlap = len(task_tokens.intersection(candidate_tokens))
        if task_tokens and candidate_tokens and overlap == 0:
            continue
        report = value.get("report") if isinstance(value.get("report"), dict) else value
        params = _params_from_task(candidate_task)
        candidates.append(
            {
                "memory_id": item.get("id"),
                "source_run_id": item.get("source_run_id"),
                "score": overlap + float(item.get("importance") or 1) * 0.1,
                "params": params,
                "report": report,
                "verification": value.get("verification"),
            }
        )
    candidates.sort(key=lambda item: item["score"], reverse=True)
    if candidates:
        best = candidates[0]
        recommendations = []
        for key, value in best["params"].items():
            if value is not None:
                recommendations.append(
                    {
                        "parameter": key,
                        "recommended_value": value,
                        "reason": f"Matched verified run {best.get('source_run_id')} with functional verification passed.",
                    }
                )
        return {
            "status": "success",
            "mode": "verified_history",
            "confidence": 0.9,
            "source_count": len(candidates),
            "recommendations": recommendations,
            "matched_history": candidates[:5],
        }

    bootstrap = []
    if current_params.get("reuse_factor") is not None:
        bootstrap.append(
            {
                "parameter": "reuse_factor",
                "recommended_value": current_params["reuse_factor"],
                "reason": "No verified history exists yet; keep current task setting until a verified run is promoted.",
            }
        )
    if current_params.get("precision") is not None:
        bootstrap.append(
            {
                "parameter": "precision",
                "recommended_value": current_params["precision"],
                "reason": "No verified history exists yet; use current precision as bootstrap only.",
            }
        )
    if current_params.get("clock_period") is not None:
        bootstrap.append(
            {
                "parameter": "clock_period",
                "recommended_value": current_params["clock_period"],
                "reason": "No verified history exists yet; use current clock target as bootstrap only.",
            }
        )
    return {
        "status": "no_verified_history",
        "mode": "bootstrap",
        "confidence": 0.25,
        "source_count": 0,
        "recommendations": bootstrap,
        "reason": "No functionally verified parameter history matched the current task.",
    }
