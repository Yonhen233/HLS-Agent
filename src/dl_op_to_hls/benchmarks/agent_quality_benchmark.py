from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import statistics
import time
from pathlib import Path
from typing import Any


REQUIRED_RUN_ARTIFACTS = [
    "state.json",
    "todos.json",
    "trace.jsonl",
    "artifacts.json",
    "summary.md",
    "suggestions.md",
    "memory/short_term.json",
    "memory/compressed_context.json",
    "memory/memory_candidates.json",
    "memory/promoted_memories.json",
    "memory/retrieved_memories.json",
]

DEFAULT_SUITE_FILE = Path("benchmarks/agent_capability_suite.json")

METRIC_SUGGESTION_TERMS = {
    "array partition",
    "bram",
    "dsp",
    "ii",
    "latency",
    "lut",
    "reuse_factor",
    "unroll",
}


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _read_trace(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _parse_ts(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _trace_duration_s(events: list[dict[str, Any]]) -> float | None:
    timestamps = [_parse_ts(str(event.get("ts") or "")) for event in events]
    timestamps = [item for item in timestamps if item is not None]
    if not timestamps:
        return None
    return round((max(timestamps) - min(timestamps)).total_seconds(), 3)


def _event_count(events: list[dict[str, Any]], name: str) -> int:
    return sum(1 for event in events if event.get("event") == name)


def _event_prefix_count(events: list[dict[str, Any]], prefix: str) -> int:
    return sum(1 for event in events if str(event.get("event") or "").startswith(prefix))


def _flatten_text(value: Any) -> str:
    if isinstance(value, dict):
        return "\n".join(_flatten_text(item) for item in value.values())
    if isinstance(value, list):
        return "\n".join(_flatten_text(item) for item in value)
    return str(value or "")


def _normalize_text(value: Any) -> str:
    return _flatten_text(value).lower()


def _normalize_result_text(result: dict[str, Any]) -> str:
    return str(result.get("text") or "").lower()


def _artifact_completeness(run_dir: Path) -> dict[str, Any]:
    existing = [item for item in REQUIRED_RUN_ARTIFACTS if (run_dir / item).exists()]
    missing = [item for item in REQUIRED_RUN_ARTIFACTS if item not in existing]
    return {
        "required": len(REQUIRED_RUN_ARTIFACTS),
        "present": len(existing),
        "missing": missing,
        "rate": round(len(existing) / max(len(REQUIRED_RUN_ARTIFACTS), 1), 4),
    }


def _has_metric_specific_suggestion(suggestions: list[Any]) -> bool:
    text = _flatten_text(suggestions).lower()
    if "not applicable" in text or "不适用" in text:
        return False
    return any(term in text for term in METRIC_SUGGESTION_TERMS)


def collect_run_metrics(run_dir: str | Path) -> dict[str, Any]:
    run_dir = Path(run_dir)
    state = _read_json(run_dir / "state.json", {})
    trace_events = _read_trace(run_dir / "trace.jsonl")
    task = state.get("task") or {}
    report = state.get("report") or {}
    report_status = report.get("status")
    selected_path = state.get("selected_path")
    status = state.get("status")
    retrieved_text = _flatten_text(state.get("retrieved_memories", [])) + "\n" + _flatten_text(state.get("rag_context", []))
    retrieved_text_lower = retrieved_text.lower()
    suggestions = state.get("suggestions", [])
    is_unsupported_missing = selected_path == "unsupported_path" and report_status in {"missing", "skipped", "report_missing", None}
    is_boundary = "boundary" in str(task.get("name") or state.get("run_id") or run_dir.name).lower()
    is_resnet = "resnet" in str(task.get("name") or state.get("run_id") or run_dir.name).lower()
    latency = report.get("latency") or {}
    resources = report.get("resources") or {}
    timing = report.get("timing") or {}

    metrics = {
        "run_id": state.get("run_id") or run_dir.name,
        "run_dir": str(run_dir),
        "task_name": task.get("name"),
        "task_type": task.get("task_type"),
        "objective": state.get("objective") or task.get("objective"),
        "status": status,
        "selected_path": selected_path,
        "report_status": report_status,
        "runtime_s": _trace_duration_s(trace_events),
        "todo_count": len(state.get("todos", [])),
        "llm_decision_count": len(state.get("llm_decisions", [])),
        "trace_event_count": len(trace_events),
        "tool_call_count": _event_count(trace_events, "PreToolUse"),
        "tool_failure_count": _event_count(trace_events, "ToolFailed"),
        "todo_failed_count": _event_count(trace_events, "TodoFailed"),
        "todo_skipped_count": _event_count(trace_events, "TodoSkipped"),
        "specialist_event_count": _event_prefix_count(trace_events, "Specialist"),
        "context_envelope_count": _event_count(trace_events, "ContextEnvelopeCreated"),
        "artifact_completeness": _artifact_completeness(run_dir),
        "memory": {
            "retrieved_count": len(state.get("retrieved_memories", [])),
            "candidate_count": len(state.get("memory_candidates", [])),
            "promoted_count": len(state.get("promoted_memories", [])),
        },
        "rag_quality": {
            "contains_prior_experience_hint": "prior experience hint" in retrieved_text_lower,
            "contains_matmul_for_resnet_boundary": bool(is_resnet and is_boundary and "matmul" in retrieved_text_lower),
            "retrieved_text_bytes": len(retrieved_text.encode("utf-8", errors="ignore")),
        },
        "semantic_quality": {
            "unsupported_status_correct": selected_path != "unsupported_path" or status == "partial_success",
            "unsupported_metric_suggestion_error": bool(is_unsupported_missing and _has_metric_specific_suggestion(suggestions)),
            "unsupported_suggestion_count": len(suggestions) if is_unsupported_missing else None,
        },
        "synthesis": {
            "latency_min_cycles": latency.get("min_cycles"),
            "latency_max_cycles": latency.get("max_cycles"),
            "ii_min": (report.get("interval") or {}).get("min_ii"),
            "ii_max": (report.get("interval") or {}).get("max_ii"),
            "dsp": resources.get("dsp"),
            "bram": resources.get("bram"),
            "lut": resources.get("lut"),
            "ff": resources.get("ff"),
            "timing_met": timing.get("met"),
        },
    }
    return metrics


def aggregate_metrics(run_metrics: list[dict[str, Any]]) -> dict[str, Any]:
    runtimes = [item["runtime_s"] for item in run_metrics if isinstance(item.get("runtime_s"), (int, float))]
    artifact_rates = [item["artifact_completeness"]["rate"] for item in run_metrics]
    status_counts: dict[str, int] = {}
    path_counts: dict[str, int] = {}
    for item in run_metrics:
        status_counts[str(item.get("status"))] = status_counts.get(str(item.get("status")), 0) + 1
        path_counts[str(item.get("selected_path"))] = path_counts.get(str(item.get("selected_path")), 0) + 1
    rag_pollution_runs = [
        item["run_id"]
        for item in run_metrics
        if item["rag_quality"]["contains_prior_experience_hint"]
        or item["rag_quality"]["contains_matmul_for_resnet_boundary"]
    ]
    unsupported_status_errors = [
        item["run_id"] for item in run_metrics if not item["semantic_quality"]["unsupported_status_correct"]
    ]
    unsupported_metric_suggestion_errors = [
        item["run_id"] for item in run_metrics if item["semantic_quality"]["unsupported_metric_suggestion_error"]
    ]
    report_success_runs = [item["run_id"] for item in run_metrics if item.get("report_status") == "success"]
    vivado_success_runs = [
        item["run_id"]
        for item in run_metrics
        if item.get("report_status") == "success" and item["synthesis"].get("latency_max_cycles") is not None
    ]
    return {
        "run_count": len(run_metrics),
        "status_counts": status_counts,
        "selected_path_counts": path_counts,
        "runtime_s": {
            "min": min(runtimes) if runtimes else None,
            "median": statistics.median(runtimes) if runtimes else None,
            "max": max(runtimes) if runtimes else None,
        },
        "llm_decision_count_total": sum(item.get("llm_decision_count", 0) for item in run_metrics),
        "tool_call_count_total": sum(item.get("tool_call_count", 0) for item in run_metrics),
        "specialist_event_count_total": sum(item.get("specialist_event_count", 0) for item in run_metrics),
        "artifact_completeness_avg": round(sum(artifact_rates) / max(len(artifact_rates), 1), 4),
        "report_success_runs": report_success_runs,
        "vivado_metric_runs": vivado_success_runs,
        "rag_pollution_runs": rag_pollution_runs,
        "rag_pollution_rate": round(len(rag_pollution_runs) / max(len(run_metrics), 1), 4),
        "unsupported_status_errors": unsupported_status_errors,
        "unsupported_metric_suggestion_errors": unsupported_metric_suggestion_errors,
        "unsupported_semantics_pass_rate": round(
            1.0 - (len(unsupported_status_errors) + len(unsupported_metric_suggestion_errors)) / max(len(run_metrics), 1),
            4,
        ),
    }


def load_suite_cases(path: str | Path) -> list[dict[str, Any]]:
    payload = _read_json(Path(path), {})
    cases = payload.get("cases", []) if isinstance(payload, dict) else payload
    if not isinstance(cases, list):
        raise ValueError(f"Benchmark suite file has no cases list: {path}")
    normalized = []
    for index, case in enumerate(cases, start=1):
        if not isinstance(case, dict) or not case.get("id") or not case.get("task"):
            raise ValueError(f"Invalid benchmark suite case #{index}: every case needs id and task.")
        normalized.append(case)
    return normalized


def _trace_event_names(events: list[dict[str, Any]]) -> list[str]:
    return [str(event.get("event") or "") for event in events]


def _artifact_paths_from_manifest(run_dir: Path) -> list[str]:
    manifest = _read_json(run_dir / "artifacts.json", {})
    return [str(item.get("path") or "") for item in manifest.get("artifacts", []) if isinstance(item, dict)]


def _error_types(state: dict[str, Any]) -> set[str]:
    return {str(item.get("error_type") or "") for item in state.get("errors", []) if isinstance(item, dict)}


def _todo_status_counts(state: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for todo in state.get("todos", []):
        status = str(todo.get("status") or "")
        counts[status] = counts.get(status, 0) + 1
    return counts


def _specialists_used(state: dict[str, Any], events: list[dict[str, Any]]) -> set[str]:
    used = {str(event.get("specialist") or "") for event in events if event.get("event") == "SpecialistSelected"}
    for todo in state.get("todos", []):
        result = todo.get("specialist_result") or {}
        if result.get("specialist_name"):
            used.add(str(result["specialist_name"]))
    return {item for item in used if item}


def _check(condition: bool, name: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"name": name, "passed": bool(condition), "details": details or {}}


def evaluate_suite_case(case: dict[str, Any], run_dir: str | Path, metrics: dict[str, Any] | None = None) -> dict[str, Any]:
    run_dir = Path(run_dir)
    state = _read_json(run_dir / "state.json", {})
    events = _read_trace(run_dir / "trace.jsonl")
    metrics = metrics or collect_run_metrics(run_dir)
    expected = case.get("expected", {}) or {}
    event_names = _trace_event_names(events)
    artifact_paths = _artifact_paths_from_manifest(run_dir)
    status_counts = _todo_status_counts(state)
    errors = _error_types(state)
    checks: list[dict[str, Any]] = []

    allowed_statuses = set(expected.get("allowed_statuses") or [])
    if allowed_statuses:
        checks.append(_check(metrics.get("status") in allowed_statuses, "status_allowed", {"actual": metrics.get("status"), "allowed": sorted(allowed_statuses)}))
    if expected.get("selected_path") is not None:
        checks.append(_check(metrics.get("selected_path") == expected["selected_path"], "selected_path", {"actual": metrics.get("selected_path"), "expected": expected["selected_path"]}))
    if expected.get("report_status") is not None:
        checks.append(_check(metrics.get("report_status") == expected["report_status"], "report_status", {"actual": metrics.get("report_status"), "expected": expected["report_status"]}))
    if "artifact_completeness_min" in expected:
        checks.append(
            _check(
                metrics["artifact_completeness"]["rate"] >= float(expected["artifact_completeness_min"]),
                "artifact_completeness_min",
                {"actual": metrics["artifact_completeness"]["rate"], "expected_min": expected["artifact_completeness_min"]},
            )
        )
    for artifact in expected.get("required_artifacts", []):
        exists = (run_dir / artifact).exists() or any(str(artifact) in path for path in artifact_paths)
        checks.append(_check(exists, f"artifact:{artifact}", {"artifact": artifact}))
    for event_name in expected.get("required_trace_events", []):
        checks.append(_check(event_name in event_names, f"trace_event:{event_name}", {"event": event_name}))
    for event_name in expected.get("forbidden_trace_events", []):
        checks.append(_check(event_name not in event_names, f"forbidden_trace_event:{event_name}", {"event": event_name}))
    for specialist in expected.get("required_specialists", []):
        checks.append(_check(specialist in _specialists_used(state, events), f"specialist:{specialist}", {"specialist": specialist}))
    for error_type in expected.get("forbidden_error_types", []):
        checks.append(_check(error_type not in errors, f"forbidden_error:{error_type}", {"error_type": error_type, "errors": sorted(errors)}))
    if "max_todo_failed" in expected:
        checks.append(_check(status_counts.get("failed", 0) <= int(expected["max_todo_failed"]), "max_todo_failed", {"actual": status_counts.get("failed", 0), "max": expected["max_todo_failed"]}))
    if "max_tool_failures" in expected:
        checks.append(_check(metrics.get("tool_failure_count", 0) <= int(expected["max_tool_failures"]), "max_tool_failures", {"actual": metrics.get("tool_failure_count", 0), "max": expected["max_tool_failures"]}))
    if expected.get("vivado_metrics_required"):
        synthesis = metrics.get("synthesis", {})
        checks.append(
            _check(
                synthesis.get("latency_max_cycles") is not None and synthesis.get("dsp") is not None,
                "vivado_metrics_required",
                {"synthesis": synthesis},
            )
        )
    if expected.get("unsupported_no_synthesis_metrics"):
        synthesis = metrics.get("synthesis", {})
        checks.append(
            _check(
                not any(synthesis.get(key) is not None for key in ["latency_max_cycles", "dsp", "lut", "ff"]),
                "unsupported_no_synthesis_metrics",
                {"synthesis": synthesis},
            )
        )
        checks.append(
            _check(
                not metrics["semantic_quality"]["unsupported_metric_suggestion_error"],
                "unsupported_no_metric_specific_suggestions",
                {"suggestion_count": metrics["semantic_quality"].get("unsupported_suggestion_count")},
            )
        )
    if "max_llm_decisions" in expected:
        checks.append(_check(metrics.get("llm_decision_count", 0) <= int(expected["max_llm_decisions"]), "max_llm_decisions", {"actual": metrics.get("llm_decision_count", 0), "max": expected["max_llm_decisions"]}))
    if "min_promoted_memories" in expected:
        checks.append(_check(metrics["memory"].get("promoted_count", 0) >= int(expected["min_promoted_memories"]), "min_promoted_memories", {"actual": metrics["memory"].get("promoted_count", 0), "min": expected["min_promoted_memories"]}))

    passed_count = sum(1 for item in checks if item["passed"])
    score = round(passed_count / max(len(checks), 1), 4)
    return {
        "case_id": case["id"],
        "title": case.get("title") or case["id"],
        "category": case.get("category"),
        "tags": case.get("tags", []),
        "run_id": metrics.get("run_id"),
        "score": score,
        "passed": score == 1.0,
        "checks_passed": passed_count,
        "checks_total": len(checks),
        "failed_checks": [item for item in checks if not item["passed"]],
        "checks": checks,
    }


def evaluate_suite_results(run_dirs: list[Path], suite_cases: list[dict[str, Any]]) -> dict[str, Any]:
    case_by_id = {case["id"]: case for case in suite_cases}
    case_results = []
    for run_dir in run_dirs:
        metadata = _read_json(run_dir / "benchmark_case.json", {})
        case_id = metadata.get("case_id")
        if not case_id or case_id not in case_by_id:
            continue
        metrics = collect_run_metrics(run_dir)
        result = evaluate_suite_case(case_by_id[case_id], run_dir, metrics)
        result["iteration"] = metadata.get("iteration")
        result["wall_time_s"] = metadata.get("wall_time_s")
        case_results.append(result)
    category_scores: dict[str, list[float]] = {}
    for result in case_results:
        category = str(result.get("category") or "uncategorized")
        category_scores.setdefault(category, []).append(float(result["score"]))
    return {
        "case_count": len(case_results),
        "pass_count": sum(1 for item in case_results if item["passed"]),
        "pass_rate": round(sum(1 for item in case_results if item["passed"]) / max(len(case_results), 1), 4),
        "average_score": round(sum(float(item["score"]) for item in case_results) / max(len(case_results), 1), 4),
        "category_scores": {
            category: round(sum(scores) / max(len(scores), 1), 4) for category, scores in sorted(category_scores.items())
        },
        "failed_cases": [item["case_id"] for item in case_results if not item["passed"]],
        "cases": case_results,
    }


def compare_runs(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_runtime = before.get("runtime_s")
    after_runtime = after.get("runtime_s")
    runtime_delta_s = None
    runtime_delta_pct = None
    if isinstance(before_runtime, (int, float)) and isinstance(after_runtime, (int, float)) and before_runtime:
        runtime_delta_s = round(after_runtime - before_runtime, 3)
        runtime_delta_pct = round((after_runtime - before_runtime) / before_runtime * 100.0, 2)
    return {
        "before_run_id": before["run_id"],
        "after_run_id": after["run_id"],
        "runtime_delta_s": runtime_delta_s,
        "runtime_delta_pct": runtime_delta_pct,
        "status_change": {"before": before.get("status"), "after": after.get("status")},
        "path_change": {"before": before.get("selected_path"), "after": after.get("selected_path")},
        "rag_pollution_removed": (
            before["rag_quality"]["contains_prior_experience_hint"]
            or before["rag_quality"]["contains_matmul_for_resnet_boundary"]
        )
        and not (
            after["rag_quality"]["contains_prior_experience_hint"]
            or after["rag_quality"]["contains_matmul_for_resnet_boundary"]
        ),
        "unsupported_status_fixed": (
            not before["semantic_quality"]["unsupported_status_correct"]
            and after["semantic_quality"]["unsupported_status_correct"]
        ),
        "unsupported_metric_suggestions_fixed": (
            before["semantic_quality"]["unsupported_metric_suggestion_error"]
            and not after["semantic_quality"]["unsupported_metric_suggestion_error"]
        ),
        "llm_decision_delta": after.get("llm_decision_count", 0) - before.get("llm_decision_count", 0),
        "tool_call_delta": after.get("tool_call_count", 0) - before.get("tool_call_count", 0),
    }


def _result_source_keys(result: dict[str, Any]) -> set[str]:
    metadata = result.get("metadata") or {}
    keys = {
        str(result.get("source_id") or ""),
        str(metadata.get("run_id") or ""),
        str(metadata.get("source_id") or ""),
        str(metadata.get("key") or ""),
    }
    return {item for item in keys if item}


def _matches_source_id(result: dict[str, Any], relevant_source_ids: set[str]) -> bool:
    if not relevant_source_ids:
        return False
    keys = _result_source_keys(result)
    return any(key in relevant_source_ids or any(label in key for label in relevant_source_ids) for key in keys)


def _term_present(text: str, term: str) -> bool:
    return term.lower() in text


def _matches_required_terms(result: dict[str, Any], required_terms: list[str]) -> bool:
    if not required_terms:
        return False
    text = _normalize_text(result)
    return all(_term_present(text, term) for term in required_terms)


def _dcg(relevance: list[int]) -> float:
    return sum(rel / math.log2(index + 2) for index, rel in enumerate(relevance))


def evaluate_rag_case(case: dict[str, Any], results: list[dict[str, Any]], default_top_k: int = 5) -> dict[str, Any]:
    top_k = int(case.get("top_k") or default_top_k)
    top_results = results[:top_k]
    relevant_source_ids = {str(item) for item in case.get("relevant_source_ids", [])}
    relevant_terms = [str(item).lower() for item in case.get("relevant_terms", [])]
    required_terms = [str(item).lower() for item in case.get("required_terms", relevant_terms)]
    irrelevant_terms = [str(item).lower() for item in case.get("irrelevant_terms", [])]

    if relevant_source_ids:
        relevance = [1 if _matches_source_id(result, relevant_source_ids) else 0 for result in top_results]
        relevant_hits = sum(relevance)
        precision_at_k = relevant_hits / max(len(top_results), 1)
        recall_at_k = relevant_hits / max(len(relevant_source_ids), 1)
        hit_at_k = 1.0 if relevant_hits else 0.0
        mrr = 0.0
        for index, rel in enumerate(relevance, start=1):
            if rel:
                mrr = 1.0 / index
                break
        ideal_relevance = [1] * min(len(relevant_source_ids), top_k)
        ndcg_at_k = _dcg(relevance) / max(_dcg(ideal_relevance), 1e-9)
    else:
        relevance = [1 if _matches_required_terms(result, required_terms) else 0 for result in top_results]
        relevant_hits = sum(relevance)
        precision_at_k = relevant_hits / max(len(top_results), 1)
        recall_at_k = None
        hit_at_k = 1.0 if relevant_hits else 0.0
        mrr = 0.0
        for index, rel in enumerate(relevance, start=1):
            if rel:
                mrr = 1.0 / index
                break
        ndcg_at_k = None

    joined_text = "\n".join(_normalize_text(result) for result in top_results)
    covered_terms = [term for term in relevant_terms if _term_present(joined_text, term)]
    polluted_results = [
        result
        for result in top_results
        if any(_term_present(_normalize_result_text(result), term) for term in irrelevant_terms)
    ]
    return {
        "query": case["query"],
        "top_k": top_k,
        "result_count": len(top_results),
        "precision_at_k": round(precision_at_k, 4),
        "recall_at_k": round(recall_at_k, 4) if recall_at_k is not None else None,
        "hit_at_k": hit_at_k,
        "mrr": round(mrr, 4),
        "ndcg_at_k": round(ndcg_at_k, 4) if ndcg_at_k is not None else None,
        "relevant_term_coverage_at_k": round(len(covered_terms) / max(len(relevant_terms), 1), 4) if relevant_terms else None,
        "pollution_at_k": round(len(polluted_results) / max(len(top_results), 1), 4),
        "covered_terms": covered_terms,
        "polluted_source_ids": [str(result.get("source_id") or "") for result in polluted_results],
        "top_source_ids": [str(result.get("source_id") or "") for result in top_results],
    }


def evaluate_rag_cases(cases: list[dict[str, Any]], retrieve_fn, default_top_k: int = 5) -> dict[str, Any]:
    case_metrics = []
    for case in cases:
        top_k = int(case.get("top_k") or default_top_k)
        results = retrieve_fn(case["query"], top_k)
        case_metrics.append(evaluate_rag_case(case, results, default_top_k=top_k))

    def _mean(key: str) -> float | None:
        values = [item[key] for item in case_metrics if isinstance(item.get(key), (int, float))]
        if not values:
            return None
        return round(sum(values) / len(values), 4)

    return {
        "case_count": len(case_metrics),
        "macro_precision_at_k": _mean("precision_at_k"),
        "macro_recall_at_k": _mean("recall_at_k"),
        "macro_hit_at_k": _mean("hit_at_k"),
        "macro_mrr": _mean("mrr"),
        "macro_ndcg_at_k": _mean("ndcg_at_k"),
        "macro_relevant_term_coverage_at_k": _mean("relevant_term_coverage_at_k"),
        "macro_pollution_at_k": _mean("pollution_at_k"),
        "cases": case_metrics,
    }


def resolve_run_dirs(runs_root: Path, run_ids_or_paths: list[str]) -> list[Path]:
    run_dirs = []
    for item in run_ids_or_paths:
        candidate = Path(item)
        if candidate.exists():
            run_dirs.append(candidate)
        else:
            run_dirs.append(runs_root / item)
    return run_dirs


def latest_run_dirs(runs_root: Path, count: int) -> list[Path]:
    if not runs_root.exists():
        return []
    return sorted([path for path in runs_root.iterdir() if path.is_dir()], key=lambda item: item.stat().st_mtime, reverse=True)[:count]


def _apply_case_environment(env: dict[str, Any]) -> dict[str, str | None]:
    old_env: dict[str, str | None] = {key: os.environ.get(key) for key in env}
    for key, value in env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[str(key)] = str(value)
    return old_env


def _restore_environment(old_env: dict[str, str | None]) -> None:
    for key, value in old_env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def run_benchmark_suite(
    tasks: list[str],
    *,
    runner: str,
    mock_tools: bool,
    repeat: int,
    suite_file: str | Path | None = None,
) -> list[Path]:
    from ..main_agent.agent import MainAgent
    from ..main_agent.workflow import run_task, run_task_llm

    run_dirs: list[Path] = []
    if suite_file:
        case_specs = load_suite_cases(suite_file)
    else:
        case_specs = [
            {"id": Path(task).stem, "task": task, "runner": runner, "mock_tools": mock_tools}
            for task in tasks
        ]
    for iteration in range(1, repeat + 1):
        for case in case_specs:
            case_env = dict(case.get("env", {}))
            if bool(case.get("mock_tools", mock_tools)):
                case_env.setdefault("DL_OP_TO_HLS_MOCK_HLS4ML", "1")
                case_env.setdefault("DL_OP_TO_HLS_MOCK_VIVADO", "1")
            old_env = _apply_case_environment(case_env)
            try:
                agent = MainAgent(console=False)
                start = time.perf_counter()
                case_runner = str(case.get("runner") or runner)
                if case_runner == "llm":
                    state = run_task_llm(str(case["task"]), agent=agent)
                else:
                    state = run_task(str(case["task"]), agent=agent)
                wall_time_s = round(time.perf_counter() - start, 3)
                run_dir = agent.config.runs_root / state.run_id
                _write_json(
                    run_dir / "benchmark_case.json",
                    {
                        "case_id": case["id"],
                        "title": case.get("title"),
                        "category": case.get("category"),
                        "tags": case.get("tags", []),
                        "iteration": iteration,
                        "runner": case_runner,
                        "mock_tools": bool(case.get("mock_tools", mock_tools)),
                        "wall_time_s": wall_time_s,
                    },
                )
                run_dirs.append(run_dir)
            finally:
                _restore_environment(old_env)
    return run_dirs


def evaluate_rag_file(path: str | Path, top_k: int = 5) -> dict[str, Any]:
    from ..main_agent.agent import MainAgent

    cases = _read_json(Path(path), [])
    if isinstance(cases, dict):
        cases = cases.get("cases", [])
    agent = MainAgent(console=False)
    return evaluate_rag_cases(cases, lambda query, k: agent.rag_memory.retrieve(query, top_k=k), default_top_k=top_k)


def build_payload(
    run_dirs: list[Path],
    compare: tuple[str, str] | None = None,
    rag_eval_file: str | Path | None = None,
    rag_top_k: int = 5,
    suite_file: str | Path | None = None,
) -> dict[str, Any]:
    run_metrics = [collect_run_metrics(path) for path in run_dirs]
    payload: dict[str, Any] = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "benchmark_version": "agent-quality-v1",
        "metrics": run_metrics,
        "aggregate": aggregate_metrics(run_metrics),
    }
    if compare:
        before = collect_run_metrics(compare[0])
        after = collect_run_metrics(compare[1])
        payload["comparison"] = compare_runs(before, after)
    if rag_eval_file:
        payload["rag_eval"] = evaluate_rag_file(rag_eval_file, top_k=rag_top_k)
    if suite_file:
        payload["suite_eval"] = evaluate_suite_results(run_dirs, load_suite_cases(suite_file))
    return payload


def write_outputs(payload: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path = output.with_suffix(".md")
    aggregate = payload["aggregate"]
    lines = [
        "# Agent Quality Benchmark",
        "",
        "## Aggregate",
        f"- Runs analyzed: {aggregate['run_count']}",
        f"- Status counts: `{aggregate['status_counts']}`",
        f"- Selected path counts: `{aggregate['selected_path_counts']}`",
        f"- Runtime median: `{aggregate['runtime_s']['median']}` seconds",
        f"- LLM decisions total: `{aggregate['llm_decision_count_total']}`",
        f"- Tool calls total: `{aggregate['tool_call_count_total']}`",
        f"- Artifact completeness avg: `{aggregate['artifact_completeness_avg']}`",
        f"- RAG pollution rate: `{aggregate['rag_pollution_rate']}`",
        f"- Unsupported semantics pass rate: `{aggregate['unsupported_semantics_pass_rate']}`",
        f"- Vivado metric runs: `{aggregate['vivado_metric_runs']}`",
        "",
        "## Per-run Metrics",
        "| Run | Status | Path | Runtime(s) | LLM decisions | Tool calls | RAG polluted | Unsupported OK | Report | Latency | DSP | LUT |",
        "|---|---|---|---:|---:|---:|---|---|---|---:|---:|---:|",
    ]
    for item in payload["metrics"]:
        rag_bad = item["rag_quality"]["contains_prior_experience_hint"] or item["rag_quality"]["contains_matmul_for_resnet_boundary"]
        unsupported_ok = item["semantic_quality"]["unsupported_status_correct"] and not item["semantic_quality"]["unsupported_metric_suggestion_error"]
        lines.append(
            "| {run_id} | {status} | {path} | {runtime} | {llm} | {tools} | {rag_bad} | {unsupported_ok} | {report} | {latency} | {dsp} | {lut} |".format(
                run_id=item["run_id"],
                status=item.get("status"),
                path=item.get("selected_path"),
                runtime=item.get("runtime_s"),
                llm=item.get("llm_decision_count"),
                tools=item.get("tool_call_count"),
                rag_bad=rag_bad,
                unsupported_ok=unsupported_ok,
                report=item.get("report_status"),
                latency=item["synthesis"].get("latency_max_cycles"),
                dsp=item["synthesis"].get("dsp"),
                lut=item["synthesis"].get("lut"),
            )
        )
    if "comparison" in payload:
        lines.extend(["", "## Comparison", "```json", json.dumps(payload["comparison"], indent=2, ensure_ascii=False), "```"])
    if "rag_eval" in payload:
        rag = payload["rag_eval"]
        lines.extend(
            [
                "",
                "## RAG Evaluation",
                f"- Cases: `{rag['case_count']}`",
                f"- Macro Precision@K: `{rag['macro_precision_at_k']}`",
                f"- Macro Recall@K: `{rag['macro_recall_at_k']}`",
                f"- Macro Hit@K: `{rag['macro_hit_at_k']}`",
                f"- Macro MRR: `{rag['macro_mrr']}`",
                f"- Macro nDCG@K: `{rag['macro_ndcg_at_k']}`",
                f"- Macro relevant-term coverage@K: `{rag['macro_relevant_term_coverage_at_k']}`",
                f"- Macro pollution@K: `{rag['macro_pollution_at_k']}`",
                "",
                "| Query | P@K | R@K | Hit@K | MRR | nDCG@K | Term coverage | Pollution |",
                "|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for case in rag["cases"]:
            lines.append(
                f"| {case['query']} | {case['precision_at_k']} | {case['recall_at_k']} | {case['hit_at_k']} | {case['mrr']} | {case['ndcg_at_k']} | {case['relevant_term_coverage_at_k']} | {case['pollution_at_k']} |"
            )
    if "suite_eval" in payload:
        suite = payload["suite_eval"]
        lines.extend(
            [
                "",
                "## Agent Capability Suite",
                f"- Cases evaluated: `{suite['case_count']}`",
                f"- Pass rate: `{suite['pass_rate']}`",
                f"- Average score: `{suite['average_score']}`",
                f"- Category scores: `{suite['category_scores']}`",
                f"- Failed cases: `{suite['failed_cases']}`",
                "",
                "| Case | Category | Score | Passed | Failed checks |",
                "|---|---|---:|---|---|",
            ]
        )
        for case in suite["cases"]:
            failed = ", ".join(item["name"] for item in case["failed_checks"]) or "None"
            lines.append(f"| {case['case_id']} | {case.get('category')} | {case['score']} | {case['passed']} | {failed} |")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-quality-benchmark")
    parser.add_argument("--runs-root", default="runs")
    parser.add_argument("--runs", nargs="*", default=[])
    parser.add_argument("--latest", type=int, default=0, help="Analyze N latest run directories when --runs is omitted.")
    parser.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"))
    parser.add_argument("--rag-eval-file", help="JSON file with RAG relevance labels.")
    parser.add_argument("--rag-top-k", type=int, default=5)
    parser.add_argument("--output", default="runs/benchmarks/agent_quality_benchmark.json")
    parser.add_argument("--run-suite", action="store_true", help="Run tasks before collecting metrics.")
    parser.add_argument("--suite-file", default=None, help="Agent capability suite JSON with case expectations.")
    parser.add_argument("--runner", choices=["deterministic", "llm"], default="deterministic")
    parser.add_argument("--mock-tools", action="store_true")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument(
        "--tasks",
        nargs="*",
        default=["examples/dense_operator.json", "examples/matmul_resource.json", "examples/resnet18_boundary.json"],
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runs_root = Path(args.runs_root)
    if args.run_suite:
        run_dirs = run_benchmark_suite(
            args.tasks,
            runner=args.runner,
            mock_tools=args.mock_tools,
            repeat=max(args.repeat, 1),
            suite_file=args.suite_file,
        )
    elif args.runs:
        run_dirs = resolve_run_dirs(runs_root, args.runs)
    else:
        run_dirs = latest_run_dirs(runs_root, args.latest or 10)
    compare = None
    if args.compare:
        before, after = resolve_run_dirs(runs_root, list(args.compare))
        compare = (str(before), str(after))
    payload = build_payload(
        run_dirs,
        compare=compare,
        rag_eval_file=args.rag_eval_file,
        rag_top_k=args.rag_top_k,
        suite_file=args.suite_file,
    )
    write_outputs(payload, Path(args.output))
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
