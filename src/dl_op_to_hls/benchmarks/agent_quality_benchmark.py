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

AGENT_SELECTED_PATHS = {
    "fallback_template_path",
    "hls4ml_path",
    "existing_hls_project_path",
    "llm_candidate_path",
    "unsupported_path",
}

PATH_TOOLCHAIN_RULES = {
    "fallback_template_path": {
        "required_any": [
            ["fallback.generate_operator_hls"],
            ["vivado.create_project", "vivado.create_vivado_project", "vivado.run_csynth"],
            ["vivado.parse_report", "vivado.parse_csynth_report"],
        ],
        "forbidden": ["hls4ml.convert", "hls4ml.convert_with_hls4ml", "task.prepare_existing_project", "report.write_unsupported"],
    },
    "hls4ml_path": {
        "required_any": [
            ["hls4ml.inspect_model", "hls4ml.check_support", "hls4ml.check_hls4ml_support"],
            ["hls4ml.generate_config", "hls4ml.generate_hls4ml_config", "hls4ml.convert", "hls4ml.convert_with_hls4ml"],
            ["vivado.run_csynth", "vivado.parse_report", "vivado.parse_csynth_report"],
        ],
        "forbidden": ["fallback.generate_operator_hls", "task.prepare_existing_project", "report.write_unsupported"],
    },
    "existing_hls_project_path": {
        "required_any": [
            ["vivado.create_project", "vivado.create_vivado_project"],
            ["vivado.run_csynth"],
            ["vivado.parse_report", "vivado.parse_csynth_report"],
        ],
        "forbidden": ["fallback.generate_operator_hls", "hls4ml.convert", "hls4ml.convert_with_hls4ml", "report.write_unsupported"],
    },
    "unsupported_path": {
        "required_any": [["report.write_unsupported"]],
        "forbidden": ["vivado.run_csynth", "vivado.parse_report", "vivado.parse_csynth_report"],
    },
    "llm_candidate_path": {
        "required_any": [
            ["llm.generate_candidate", "llm.generate_hls_candidate"],
            ["verify_candidate.run", "verify.run_csim"],
            ["vivado.run_csynth"],
            ["vivado.parse_report", "vivado.parse_csynth_report"],
        ],
        "forbidden": ["hls4ml.convert", "hls4ml.convert_with_hls4ml", "task.prepare_existing_project", "report.write_unsupported"],
    },
}

LLM_HARNESS_EVENTS = [
    "LLMCallStarted",
    "LLMCallFinished",
    "LLMCallFailed",
    "LLMPlanGenerated",
    "LLMPlanAccepted",
    "LLMPlanRejected",
    "LLMReActDecision",
    "LLMReActAutoDelegated",
    "LLMReActFailed",
    "LLMReflectionDecision",
    "LLMReflectionTodoRejected",
    "LLMGuardRejected",
    "LLMSpecialistMismatchRejected",
    "LLMJsonRepairStarted",
    "LLMJsonRepairFinished",
    "LLMCandidateGenerated",
]

RECOVERY_STAGE_TERMS = {
    "csim": ["csim", "verification"],
    "conversion": ["hls4ml.convert", "convert", "conversion"],
    "report_parse": ["parse_report", "parse report", "reportparse", "reportparseerror"],
    "llm_candidate": ["llm.generate", "candidate", "llmgenerationerror"],
    "toolchain": ["vivado", "vitis", "toolchain"],
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


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * percentile
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[int(rank)]
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower), 4)


def _wilson_interval(successes: int, total: int, z: float = 1.96) -> dict[str, Any]:
    if total <= 0:
        return {"n": 0, "estimate": None, "low": None, "high": None, "statistically_usable": False}
    estimate = successes / total
    denominator = 1 + (z * z / total)
    center = (estimate + z * z / (2 * total)) / denominator
    margin = z * math.sqrt((estimate * (1 - estimate) + z * z / (4 * total)) / total) / denominator
    return {
        "n": total,
        "estimate": round(estimate, 4),
        "low": round(max(0.0, center - margin), 4),
        "high": round(min(1.0, center + margin), 4),
        "statistically_usable": total >= 20,
    }


def _todo_items(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in state.get("todos", []) if isinstance(item, dict)]


def _collect_tool_names(value: Any) -> set[str]:
    names: set[str] = set()
    if isinstance(value, dict):
        tool_name = value.get("tool")
        if isinstance(tool_name, str) and "." in tool_name:
            names.add(tool_name)
        action = value.get("action")
        if isinstance(action, dict):
            action_tool = action.get("tool") or action.get("tool_name")
            if isinstance(action_tool, str) and "." in action_tool:
                names.add(action_tool)
        for item in value.values():
            names.update(_collect_tool_names(item))
    elif isinstance(value, list):
        for item in value:
            names.update(_collect_tool_names(item))
    return names


def _tools_used(state: dict[str, Any], events: list[dict[str, Any]]) -> list[str]:
    names = _collect_tool_names(state.get("tool_results", []))
    for event in events:
        tool_name = event.get("tool") if event.get("event") in {"PreToolUse", "PostToolUse", "ToolFailed"} else None
        if isinstance(tool_name, str) and "." in tool_name:
            names.add(tool_name)
    return sorted(names)


def _has_any_tool(tools: set[str], candidates: list[str]) -> bool:
    return any(candidate in tools for candidate in candidates)


def _verified_composite_capabilities(receipts: list[dict[str, Any]]) -> set[str]:
    capabilities: set[str] = set()
    for receipt in receipts:
        if not isinstance(receipt, dict) or receipt.get("tool_name") != "verify_candidate.run":
            continue
        if receipt.get("valid") is not True or receipt.get("evidence_class") != "real_csynth":
            continue
        checks = {
            str(check.get("name")): bool(check.get("passed"))
            for check in receipt.get("checks", [])
            if isinstance(check, dict)
        }
        if checks.get("golden_csim_passed"):
            capabilities.add("vivado.run_csim")
        if checks.get("candidate_report_exists") and checks.get("current_run_candidate_report"):
            capabilities.update({"vivado.run_csynth", "vivado.parse_report"})
    return capabilities


def _path_toolchain_quality(
    selected_path: str | None,
    tools_used: list[str],
    receipts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if selected_path not in PATH_TOOLCHAIN_RULES:
        return {
            "applicable": False,
            "correct_for_selected_path": None,
            "missing_required_groups": [],
            "forbidden_tools_used": [],
            "tools_used": tools_used,
        }
    direct_tools = set(tools_used)
    evidenced_capabilities = _verified_composite_capabilities(receipts or [])
    tools = direct_tools | evidenced_capabilities
    rule = PATH_TOOLCHAIN_RULES[selected_path]
    direct_missing = [group for group in rule["required_any"] if not _has_any_tool(direct_tools, group)]
    missing = [group for group in rule["required_any"] if not _has_any_tool(tools, group)]
    forbidden = [tool for tool in rule.get("forbidden", []) if tool in tools]
    return {
        "applicable": True,
        "correct_for_selected_path": not missing and not forbidden,
        "direct_trace_correct_for_selected_path": not direct_missing and not forbidden,
        "evidence_backed_correct_for_selected_path": not missing and not forbidden,
        "direct_missing_required_groups": direct_missing,
        "missing_required_groups": missing,
        "forbidden_tools_used": forbidden,
        "tools_used": tools_used,
        "evidenced_composite_capabilities": sorted(evidenced_capabilities),
        "metric_contract": "direct ToolRegistry calls plus capabilities proven by valid current-run composite receipts",
    }


def _estimated_context_tokens(state: dict[str, Any]) -> dict[str, int]:
    input_tokens = 0
    output_tokens = 0
    for todo in _todo_items(state):
        usage = ((todo.get("specialist_result") or {}).get("context_usage") or {})
        input_tokens += int(usage.get("estimated_input_tokens") or 0)
        output_tokens += int(usage.get("estimated_output_tokens") or 0)
    for result in state.get("tool_results", []):
        usage = ((result.get("result") or {}).get("context_usage") or {}) if isinstance(result, dict) else {}
        input_tokens += int(usage.get("estimated_input_tokens") or 0)
        output_tokens += int(usage.get("estimated_output_tokens") or 0)
    return {
        "estimated_input_tokens": input_tokens,
        "estimated_output_tokens": output_tokens,
        "estimated_total_tokens": input_tokens + output_tokens,
    }


def _agent_runtime_quality(run_dir: Path, state: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    messages = _read_trace(run_dir / "agent_messages.jsonl")
    requests = [item for item in messages if item.get("message_type") == "delegation_request"]
    results = [item for item in messages if item.get("message_type") == "delegation_result"]
    request_correlations = {item.get("correlation_id") for item in requests}
    result_correlations = {item.get("correlation_id") for item in results}
    matched = len(request_correlations.intersection(result_correlations))
    session_id = state.get("session_id")
    session_events = []
    if session_id:
        session_events = _read_trace(run_dir.parent / "sessions" / str(session_id) / "events.jsonl")
    tool_pairs = [
        (event.get("tool"), event.get("args_hash"))
        for event in events
        if event.get("event") == "PreToolUse" and int(event.get("attempt") or 1) == 1
    ]
    duplicate_calls = max(0, len(tool_pairs) - len(set(tool_pairs)))
    return {
        "session_id": session_id,
        "checkpoint_count": _event_count(events, "SessionCheckpointCreated"),
        "interrupt_requested": _event_count(session_events, "SessionInterruptRequested") > 0,
        "interrupted": _event_count(session_events, "SessionInterrupted") > 0,
        "resumed": _event_count(session_events, "SessionResumed") > 0,
        "rolled_back": _event_count(session_events, "SessionRolledBack") > 0,
        "delegation_request_count": len(requests),
        "delegation_result_count": len(results),
        "delegation_completion_rate": round(matched / max(len(request_correlations), 1), 4),
        "tool_schema_rejection_count": _event_count(events, "ToolSchemaRejected"),
        "tool_cache_hit_count": _event_count(events, "ToolCacheHit"),
        "duplicate_tool_call_count": duplicate_calls,
        "duplicate_tool_call_rate": round(duplicate_calls / max(len(tool_pairs), 1), 4),
        "scheduler_batch_count": _event_count(events, "SchedulerBatchStarted"),
        "budget_exceeded_count": _event_count(events, "BudgetExceeded"),
    }


def _trace_completeness(run_dir: Path, state: dict[str, Any], events: list[dict[str, Any]], tool_call_count: int) -> dict[str, Any]:
    event_names = set(_trace_event_names(events))
    todos = _todo_items(state)
    manifest_artifacts = _artifact_paths_from_manifest(run_dir)
    has_failures = bool(state.get("errors")) or bool(event_names & {"ToolFailed", "TodoFailed", "LLMCallFailed"})
    errors_have_stage = all(bool(item.get("source") or item.get("error_type")) for item in state.get("errors", []) if isinstance(item, dict))
    components = {
        "plan": bool(state.get("plan") or "LLMPlanGenerated" in event_names),
        "todo": bool(todos or (run_dir / "todos.json").exists() or "TodoCreated" in event_names),
        "tool_call": tool_call_count > 0,
        "specialist_result": any((todo.get("specialist_result") or {}) for todo in todos) or "SpecialistResultMerged" in event_names,
        "artifact": bool(state.get("artifacts") or manifest_artifacts),
        "error_stage": (not has_failures) or errors_have_stage or bool(event_names & {"ToolFailed", "TodoFailed", "LLMCallFailed"}),
        "summary": (run_dir / "summary.md").exists(),
    }
    passed = sum(1 for value in components.values() if value)
    return {
        "rate": round(passed / max(len(components), 1), 4),
        "components": components,
        "missing": [name for name, value in components.items() if not value],
        "error_stage_not_applicable": not has_failures,
    }


def _contains_any(text: str, terms: list[str]) -> bool:
    return any(term in text for term in terms)


def _failure_stages(state: dict[str, Any], events: list[dict[str, Any]]) -> list[str]:
    evidence = "\n".join(
        [
            _normalize_text(state.get("errors", [])),
            _normalize_text([event for event in events if event.get("event") in {"ToolFailed", "TodoFailed", "LLMCallFailed"}]),
        ]
    ).strip()
    stages = [stage for stage, terms in RECOVERY_STAGE_TERMS.items() if _contains_any(evidence, terms)]
    if evidence and not stages:
        stages.append("other")
    return stages


def _repair_quality(state: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    event_names = _trace_event_names(events)
    decision_text = _normalize_text(state.get("llm_decisions", []))
    todo_text = _normalize_text(state.get("todos", []))
    repair_event_count = sum(1 for name in event_names if name in {"LLMJsonRepairStarted", "LLMJsonRepairFinished"})
    repair_attempted = bool(repair_event_count or "repair" in decision_text or "replan" in decision_text or "repair" in todo_text or "replan" in todo_text)
    stages = _failure_stages(state, events)
    status = state.get("status")
    success_after_failure = bool(stages and repair_attempted and status in {"success", "partial_success"})
    return {
        "failure_stages": stages,
        "failure_stage_count": len(stages),
        "repair_event_count": repair_event_count,
        "repair_attempted": repair_attempted,
        "repair_success": success_after_failure,
    }


def _llm_harness_quality(state: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {name: _event_count(events, name) for name in LLM_HARNESS_EVENTS}
    plan_attempts = counts["LLMPlanAccepted"] + counts["LLMPlanRejected"]
    json_repairs = counts["LLMJsonRepairStarted"]
    candidate_todos = [
        item
        for item in state.get("todos", [])
        if isinstance(item, dict) and item.get("assigned_tool") in {"llm.generate_candidate", "llm.generate_hls_candidate"}
    ]
    candidate_repair_todos = [
        item
        for item in candidate_todos
        if isinstance(item.get("inputs"), dict) and item["inputs"].get("repair_reason")
    ]
    return {
        "selected_skill": state.get("selected_skill"),
        "skill_usage_mode": state.get("skill_usage_mode"),
        "event_counts": counts,
        "llm_call_failed_count": counts["LLMCallFailed"],
        "plan_generated": counts["LLMPlanGenerated"] > 0,
        "plan_accepted": counts["LLMPlanAccepted"] > 0,
        "plan_rejected_count": counts["LLMPlanRejected"],
        "plan_acceptance_rate": round(counts["LLMPlanAccepted"] / max(plan_attempts, 1), 4),
        "react_decision_count": counts["LLMReActDecision"],
        "auto_delegation_count": counts["LLMReActAutoDelegated"],
        "reflection_decision_count": counts["LLMReflectionDecision"],
        "guard_rejection_count": counts["LLMGuardRejected"] + counts["LLMSpecialistMismatchRejected"],
        "json_repair_count": json_repairs,
        "json_repair_success_count": counts["LLMJsonRepairFinished"],
        "json_repair_success_rate": round(counts["LLMJsonRepairFinished"] / max(json_repairs, 1), 4),
        "candidate_generation_event_count": counts["LLMCandidateGenerated"],
        "candidate_generation_todo_count": len(candidate_todos),
        "candidate_repair_todo_count": len(candidate_repair_todos),
    }


def _maturity_quality(run_dir: Path, state: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    context_events = [item for item in events if item.get("event") == "ContextPackBuilt"]
    context_within_budget = [
        item
        for item in context_events
        if int(item.get("estimated_tokens") or 0) <= int(item.get("token_budget") or 0)
    ]
    tool_events = [item for item in events if item.get("event") == "PreToolUse"]
    workspace_tools = [item for item in tool_events if str(item.get("tool") or "").startswith("workspace.")]
    memory_tools = [item for item in tool_events if str(item.get("tool") or "").startswith("memory.")]
    mcp_tools = [item for item in tool_events if item.get("transport") == "mcp"]
    invocation = _read_json(run_dir / "skill_invocation.json", {})
    skill_contract_fields = {
        "allowed_tools",
        "allowed_specialists",
        "context_policy",
        "budget_policy",
        "concurrency_policy",
    }
    skill_contract_complete = bool(invocation) and skill_contract_fields.issubset(invocation)
    components = {
        "durable_session": bool(state.get("session_id")),
        "checkpointing": _event_count(events, "SessionCheckpointCreated") > 0,
        "bounded_runtime": (run_dir / "run_budget.json").exists(),
        "specialist_protocol": _event_prefix_count(events, "Specialist") > 0,
        "skill_contract": skill_contract_complete,
        "context_pack": bool(context_events),
        "context_budget_compliance": bool(context_events) and len(context_within_budget) == len(context_events),
        "memory_retrieval": bool(memory_tools),
        "permission_enforcement": any(
            item.get("event") in {"PermissionDenied", "ApprovalRequired", "ToolSchemaRejected"} for item in events
        ),
        "workspace_context": bool(workspace_tools),
        "mcp_transport": bool(mcp_tools),
    }
    core_components = [
        "durable_session",
        "checkpointing",
        "bounded_runtime",
        "specialist_protocol",
        "skill_contract",
        "context_pack",
        "context_budget_compliance",
        "memory_retrieval",
    ]
    return {
        "core_score": round(sum(bool(components[key]) for key in core_components) / len(core_components), 4),
        "components": components,
        "context_pack_count": len(context_events),
        "context_budget_compliance_rate": round(len(context_within_budget) / max(len(context_events), 1), 4),
        "workspace_tool_call_count": len(workspace_tools),
        "cross_session_memory_call_count": sum(item.get("tool") == "memory.retrieve_conversation" for item in memory_tools),
        "permission_denial_count": _event_count(events, "PermissionDenied"),
        "approval_request_count": _event_count(events, "ApprovalRequired"),
        "mcp_tool_call_count": len(mcp_tools),
        "mcp_servers": sorted({str(item.get("server")) for item in mcp_tools if item.get("server")}),
    }


def _unsupported_honesty(state: dict[str, Any], synthesis: dict[str, Any]) -> dict[str, Any]:
    selected_path = state.get("selected_path")
    report = state.get("report") or {}
    verification = state.get("verification") or report.get("verification") or {}
    unsupported_like = selected_path == "unsupported_path" or report.get("status") == "unsupported"
    no_synthesis_metrics = not any(synthesis.get(key) is not None for key in ["latency_max_cycles", "dsp", "bram", "lut", "ff"])
    no_verification_claim = not verification or verification.get("status") in {"skipped", "unsupported", "not_applicable", "missing"}
    honest_status = (not unsupported_like) or state.get("status") in {"partial_success", "unsupported"}
    honest = (not unsupported_like) or (honest_status and no_synthesis_metrics and no_verification_claim)
    return {
        "applicable": unsupported_like,
        "honest": honest,
        "status_honest": honest_status,
        "no_synthesis_metrics": no_synthesis_metrics,
        "no_verification_claim": no_verification_claim,
    }


def _task_family_terms(task: dict[str, Any], selected_path: str | None) -> list[str]:
    text = _normalize_text([task, selected_path])
    terms: set[str] = set()
    if "mnist" in text:
        terms.update({"mnist", "hls4ml", "recognition", "classification"})
    if "resnet" in text or "residual" in text:
        terms.update({"resnet", "residual", "boundary", "unsupported"})
    if "dense" in text:
        terms.update({"dense"})
    if "matmul" in text:
        terms.update({"matmul"})
    if "scale_shift" in text or "scaleshift" in text:
        terms.update({"scale_shift", "llm", "candidate", "verification"})
    if selected_path == "hls4ml_path":
        terms.add("hls4ml")
    if selected_path == "fallback_template_path":
        terms.add("fallback")
    if selected_path == "llm_candidate_path":
        terms.update({"llm", "candidate", "verification"})
    if selected_path == "unsupported_path":
        terms.add("unsupported")
    return sorted(terms)


def _rag_quality(task: dict[str, Any], selected_path: str | None, retrieved_text_lower: str, retrieved_count: int) -> dict[str, Any]:
    task_terms = _task_family_terms(task, selected_path)
    evidence_hit = None if retrieved_count == 0 else any(term in retrieved_text_lower for term in task_terms)
    task_text = _normalize_text(task)
    cross_task_pollution = False
    if "mnist" in task_text:
        cross_task_pollution = _contains_any(retrieved_text_lower, ["cifar", "resnet18", "matmul resource"])
    elif "resnet" in task_text:
        cross_task_pollution = "matmul" in retrieved_text_lower
    return {
        "evidence_hit": evidence_hit,
        "pollution_detected": bool(cross_task_pollution),
        "task_terms": task_terms,
    }


def _agent_task_success(metrics: dict[str, Any], category: str | None = None) -> bool:
    status = metrics.get("status")
    selected_path = metrics.get("selected_path")
    if selected_path == "unsupported_path" or str(category or "").endswith("_recovery"):
        return status in {"success", "partial_success", "unsupported"}
    return status == "success"


def collect_run_metrics(run_dir: str | Path) -> dict[str, Any]:
    run_dir = Path(run_dir)
    state = _read_json(run_dir / "state.json", {})
    trace_events = _read_trace(run_dir / "trace.jsonl")
    benchmark_case = _read_json(run_dir / "benchmark_case.json", {})
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
    synthesis = {
        "latency_min_cycles": latency.get("min_cycles"),
        "latency_max_cycles": latency.get("max_cycles"),
        "ii_min": (report.get("interval") or {}).get("min_ii"),
        "ii_max": (report.get("interval") or {}).get("max_ii"),
        "dsp": resources.get("dsp"),
        "bram": resources.get("bram"),
        "lut": resources.get("lut"),
        "ff": resources.get("ff"),
        "timing_met": timing.get("met"),
    }
    tools_used = _tools_used(state, trace_events)
    tool_call_count = _event_count(trace_events, "PreToolUse")
    llm_call_count = _event_count(trace_events, "LLMCallStarted")
    context_tokens = _estimated_context_tokens(state)
    recorded_budget = _read_json(run_dir / "run_budget.json", {})
    rag_score = _rag_quality(task, selected_path, retrieved_text_lower, len(state.get("retrieved_memories", [])))
    trace_score = _trace_completeness(run_dir, state, trace_events, tool_call_count)
    repair_score = _repair_quality(state, trace_events)
    unsupported_score = _unsupported_honesty(state, synthesis)
    llm_harness_score = _llm_harness_quality(state, trace_events)
    maturity_score = _maturity_quality(run_dir, state, trace_events)
    completion = state.get("completion") or _read_json(run_dir / "completion_gate.json", {})
    plan_coverage = state.get("plan_coverage") or _read_json(run_dir / "plan_coverage.json", {})
    rag_evidence = state.get("rag_evidence_report") or _read_json(run_dir / "memory" / "rag_evidence_report.json", {})
    receipts = state.get("evidence_receipts") or _read_json(run_dir / "tool_evidence.json", {}).get("receipts", [])
    toolchain_score = _path_toolchain_quality(selected_path, tools_used, receipts)
    valid_receipts = [item for item in receipts if isinstance(item, dict) and item.get("valid")]
    progress = state.get("progress") or {}
    rag_events = [item for item in trace_events if item.get("event") == "RagRetrieved"]
    rag_modes = [str(item.get("retrieval_mode") or "unknown") for item in rag_events]

    metrics = {
        "run_id": state.get("run_id") or run_dir.name,
        "run_dir": str(run_dir),
        "benchmark_case_id": benchmark_case.get("case_id"),
        "benchmark_category": benchmark_case.get("category"),
        "task_name": task.get("name"),
        "task_type": task.get("task_type"),
        "objective": state.get("objective") or task.get("objective"),
        "status": status,
        "selected_path": selected_path,
        "selected_skill": state.get("selected_skill"),
        "skill_usage_mode": state.get("skill_usage_mode"),
        "report_status": report_status,
        "runtime_s": _trace_duration_s(trace_events),
        "todo_count": len(state.get("todos", [])),
        "llm_decision_count": len(state.get("llm_decisions", [])),
        "llm_call_count": llm_call_count,
        "trace_event_count": len(trace_events),
        "tool_call_count": tool_call_count,
        "tool_failure_count": _event_count(trace_events, "ToolFailed"),
        "todo_failed_count": _event_count(trace_events, "TodoFailed"),
        "todo_skipped_count": _event_count(trace_events, "TodoSkipped"),
        "specialist_event_count": _event_prefix_count(trace_events, "Specialist"),
        "context_envelope_count": _event_count(trace_events, "ContextEnvelopeCreated"),
        "tools_used": tools_used,
        "toolchain_quality": toolchain_score,
        "llm_harness": llm_harness_score,
        "agent_maturity": maturity_score,
        "agent_runtime": _agent_runtime_quality(run_dir, state, trace_events),
        "bad_case_governance": {
            "completion_gate_passed": completion.get("passed"),
            "completion_stop_reason": completion.get("stop_reason"),
            "false_success_prevented": bool(completion.get("false_success_prevented")),
            "production_ready": bool(completion.get("production_ready")),
            "evidence_level": completion.get("evidence_level"),
            "missing_required_count": len(completion.get("missing_required", [])),
            "plan_coverage_status": plan_coverage.get("status"),
            "missing_plan_requirement_count": len(plan_coverage.get("missing_requirements", [])),
            "tool_evidence_receipt_count": len(receipts),
            "tool_evidence_valid_rate": round(len(valid_receipts) / max(len(receipts), 1), 4),
            "tool_postcondition_failure_count": _event_count(trace_events, "ToolPostconditionFailed"),
            "rag_evidence_status": rag_evidence.get("status"),
            "rag_rejected_count": len(rag_evidence.get("rejected", [])),
            "rag_claims_passed": (rag_evidence.get("claim_verification") or {}).get("passed"),
            "progress_last_decision": progress.get("last_decision"),
            "progress_max_repeated_failure": int(progress.get("max_repeated_failure") or 0),
            "progress_consecutive_drift": int(progress.get("consecutive_drift") or 0),
            "progress_replan_event_count": sum(
                1 for item in progress.get("history", []) if isinstance(item, dict) and item.get("decision") == "replan"
            ),
            "progress_terminate_event_count": sum(
                1 for item in progress.get("history", []) if isinstance(item, dict) and item.get("decision") == "terminate"
            ),
        },
        "trace_completeness": trace_score,
        "repair_quality": repair_score,
        "unsupported_honesty": unsupported_score,
        "cost": {
            "runtime_s": _trace_duration_s(trace_events),
            "tool_calls": tool_call_count,
            "llm_calls": llm_call_count,
            **context_tokens,
            "recorded_input_tokens": int(recorded_budget.get("input_tokens") or 0),
            "recorded_output_tokens": int(recorded_budget.get("output_tokens") or 0),
            "recorded_total_tokens": int(recorded_budget.get("total_tokens") or 0),
            "tool_cache_hits": int(recorded_budget.get("cache_hits") or 0),
            "budget": recorded_budget,
        },
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
            "retrieval_event_count": len(rag_events),
            "embedding_retrieval_count": sum(1 for mode in rag_modes if mode.startswith("embedding") or mode == "cross_encoder"),
            "cross_encoder_rerank_count": sum(1 for mode in rag_modes if mode == "cross_encoder"),
            "lexical_fallback_count": sum(1 for mode in rag_modes if mode == "lexical_fallback"),
            "retrieval_modes": rag_modes,
            **rag_score,
        },
        "semantic_quality": {
            "unsupported_status_correct": selected_path != "unsupported_path" or status in {"partial_success", "unsupported"},
            "unsupported_metric_suggestion_error": bool(is_unsupported_missing and _has_metric_specific_suggestion(suggestions)),
            "unsupported_suggestion_count": len(suggestions) if is_unsupported_missing else None,
        },
        "synthesis": synthesis,
    }
    metrics["agent_task_success"] = _agent_task_success(metrics, benchmark_case.get("category"))
    return metrics


def aggregate_metrics(run_metrics: list[dict[str, Any]]) -> dict[str, Any]:
    runtimes = [item["runtime_s"] for item in run_metrics if isinstance(item.get("runtime_s"), (int, float))]
    artifact_rates = [item["artifact_completeness"]["rate"] for item in run_metrics]
    trace_rates = [item.get("trace_completeness", {}).get("rate") for item in run_metrics if isinstance(item.get("trace_completeness", {}).get("rate"), (int, float))]
    status_counts: dict[str, int] = {}
    path_counts: dict[str, int] = {}
    category_totals: dict[str, int] = {}
    category_successes: dict[str, int] = {}
    for item in run_metrics:
        status_counts[str(item.get("status"))] = status_counts.get(str(item.get("status")), 0) + 1
        path_counts[str(item.get("selected_path"))] = path_counts.get(str(item.get("selected_path")), 0) + 1
        category = str(item.get("benchmark_category") or item.get("selected_path") or "uncategorized")
        category_totals[category] = category_totals.get(category, 0) + 1
        category_successes[category] = category_successes.get(category, 0) + (1 if item.get("agent_task_success") else 0)
    rag_pollution_runs = [
        item["run_id"]
        for item in run_metrics
        if item["rag_quality"]["contains_prior_experience_hint"]
        or item["rag_quality"]["contains_matmul_for_resnet_boundary"]
        or item["rag_quality"].get("pollution_detected")
    ]
    rag_evidence_runs = [
        item["run_id"] for item in run_metrics if item["rag_quality"].get("evidence_hit") is True
    ]
    rag_evidence_applicable = [
        item["run_id"] for item in run_metrics if item["rag_quality"].get("evidence_hit") is not None
    ]
    unsupported_status_errors = [
        item["run_id"] for item in run_metrics if not item["semantic_quality"]["unsupported_status_correct"]
    ]
    unsupported_metric_suggestion_errors = [
        item["run_id"] for item in run_metrics if item["semantic_quality"]["unsupported_metric_suggestion_error"]
    ]
    unsupported_applicable = [item for item in run_metrics if item.get("unsupported_honesty", {}).get("applicable")]
    unsupported_honest_runs = [item["run_id"] for item in unsupported_applicable if item.get("unsupported_honesty", {}).get("honest")]
    toolchain_applicable = [item for item in run_metrics if item.get("toolchain_quality", {}).get("applicable")]
    toolchain_correct_runs = [item["run_id"] for item in toolchain_applicable if item.get("toolchain_quality", {}).get("correct_for_selected_path")]
    direct_toolchain_correct_runs = [
        item["run_id"]
        for item in toolchain_applicable
        if item.get("toolchain_quality", {}).get("direct_trace_correct_for_selected_path")
    ]
    repair_applicable = [item for item in run_metrics if item.get("repair_quality", {}).get("failure_stage_count", 0) > 0]
    repair_success_runs = [item["run_id"] for item in repair_applicable if item.get("repair_quality", {}).get("repair_success")]
    report_success_runs = [item["run_id"] for item in run_metrics if item.get("report_status") == "success"]
    vivado_success_runs = [
        item["run_id"]
        for item in run_metrics
        if item.get("report_status") == "success" and item["synthesis"].get("latency_max_cycles") is not None
    ]
    total_runs = max(len(run_metrics), 1)
    total_tool_calls = sum(item.get("tool_call_count", 0) for item in run_metrics)
    total_llm_calls = sum(item.get("llm_call_count", 0) for item in run_metrics)
    total_tokens = sum(item.get("cost", {}).get("estimated_total_tokens", 0) for item in run_metrics)
    total_recorded_tokens = sum(item.get("cost", {}).get("recorded_total_tokens", 0) for item in run_metrics)
    successful_runs = sum(1 for item in run_metrics if item.get("agent_task_success"))
    false_success_runs = [item["run_id"] for item in run_metrics if item.get("status") == "success" and not item.get("agent_task_success")]
    delegation_requests = sum(item.get("agent_runtime", {}).get("delegation_request_count", 0) for item in run_metrics)
    delegation_results = sum(item.get("agent_runtime", {}).get("delegation_result_count", 0) for item in run_metrics)
    llm_harness_applicable = [
        item
        for item in run_metrics
        if item.get("llm_call_count", 0) > 0 or item.get("llm_harness", {}).get("plan_generated")
    ]
    total_plan_accepts = sum(item.get("llm_harness", {}).get("event_counts", {}).get("LLMPlanAccepted", 0) for item in run_metrics)
    total_plan_rejects = sum(item.get("llm_harness", {}).get("event_counts", {}).get("LLMPlanRejected", 0) for item in run_metrics)
    total_json_repairs = sum(item.get("llm_harness", {}).get("json_repair_count", 0) for item in run_metrics)
    total_json_repair_successes = sum(item.get("llm_harness", {}).get("json_repair_success_count", 0) for item in run_metrics)
    total_candidate_generation_events = sum(
        item.get("llm_harness", {}).get("candidate_generation_event_count", 0) for item in run_metrics
    )
    total_candidate_repair_todos = sum(
        item.get("llm_harness", {}).get("candidate_repair_todo_count", 0) for item in run_metrics
    )
    guard_rejection_runs = [
        item["run_id"] for item in run_metrics if item.get("llm_harness", {}).get("guard_rejection_count", 0) > 0
    ]
    llm_call_failed_runs = [
        item["run_id"] for item in run_metrics if item.get("llm_harness", {}).get("llm_call_failed_count", 0) > 0
    ]
    candidate_generation_runs = [
        item["run_id"]
        for item in run_metrics
        if item.get("llm_harness", {}).get("candidate_generation_event_count", 0) > 0
    ]
    maturity_scores = [
        float(item.get("agent_maturity", {}).get("core_score"))
        for item in run_metrics
        if isinstance(item.get("agent_maturity", {}).get("core_score"), (int, float))
    ]
    total_context_packs = sum(item.get("agent_maturity", {}).get("context_pack_count", 0) for item in run_metrics)
    total_context_compliant = sum(
        round(
            item.get("agent_maturity", {}).get("context_pack_count", 0)
            * item.get("agent_maturity", {}).get("context_budget_compliance_rate", 0.0)
        )
        for item in run_metrics
    )
    governance_runs = [item.get("bad_case_governance", {}) for item in run_metrics]
    completion_applicable = [item for item in governance_runs if item.get("completion_gate_passed") is not None]
    plan_coverage_applicable = [item for item in governance_runs if item.get("plan_coverage_status")]
    receipt_total = sum(int(item.get("tool_evidence_receipt_count") or 0) for item in governance_runs)
    valid_receipt_total = sum(
        round(
            int(item.get("tool_evidence_receipt_count") or 0)
            * float(item.get("tool_evidence_valid_rate") or 0.0)
        )
        for item in governance_runs
    )
    total_rag_retrievals = sum(int(item.get("rag_quality", {}).get("retrieval_event_count") or 0) for item in run_metrics)
    total_embedding_retrievals = sum(
        int(item.get("rag_quality", {}).get("embedding_retrieval_count") or 0) for item in run_metrics
    )
    total_cross_reranks = sum(
        int(item.get("rag_quality", {}).get("cross_encoder_rerank_count") or 0) for item in run_metrics
    )
    total_lexical_fallbacks = sum(
        int(item.get("rag_quality", {}).get("lexical_fallback_count") or 0) for item in run_metrics
    )
    return {
        "run_count": len(run_metrics),
        "status_counts": status_counts,
        "selected_path_counts": path_counts,
        "selected_path_valid_rate": round(
            sum(1 for item in run_metrics if item.get("selected_path") in AGENT_SELECTED_PATHS) / total_runs,
            4,
        ),
        "toolchain_selection_accuracy": round(len(toolchain_correct_runs) / max(len(toolchain_applicable), 1), 4),
        "direct_tool_trace_coverage": round(
            len(direct_toolchain_correct_runs) / max(len(toolchain_applicable), 1), 4
        ),
        "toolchain_metric_contract": (
            "selection accuracy accepts direct ToolRegistry calls or valid current-run composite evidence; "
            "direct_tool_trace_coverage reports only directly visible atomic calls"
        ),
        "toolchain_correct_runs": toolchain_correct_runs,
        "direct_toolchain_correct_runs": direct_toolchain_correct_runs,
        "task_success_rate_by_category": {
            category: round(category_successes.get(category, 0) / max(total, 1), 4)
            for category, total in sorted(category_totals.items())
        },
        "runtime_s": {
            "min": min(runtimes) if runtimes else None,
            "median": statistics.median(runtimes) if runtimes else None,
            "p50": _percentile(runtimes, 0.50),
            "p95": _percentile(runtimes, 0.95),
            "max": max(runtimes) if runtimes else None,
        },
        "llm_decision_count_total": sum(item.get("llm_decision_count", 0) for item in run_metrics),
        "tool_call_count_total": total_tool_calls,
        "llm_call_count_total": total_llm_calls,
        "specialist_event_count_total": sum(item.get("specialist_event_count", 0) for item in run_metrics),
        "avg_tool_calls_per_run": round(total_tool_calls / total_runs, 4),
        "avg_llm_calls_per_run": round(total_llm_calls / total_runs, 4),
        "avg_estimated_tokens_per_run": round(total_tokens / total_runs, 4),
        "avg_recorded_tokens_per_run": round(total_recorded_tokens / total_runs, 4),
        "task_success_rate": round(successful_runs / total_runs, 4),
        "false_success_rate": round(len(false_success_runs) / total_runs, 4),
        "false_success_runs": false_success_runs,
        "confidence_95": {
            "task_success_rate": _wilson_interval(successful_runs, len(run_metrics)),
            "toolchain_selection_accuracy": _wilson_interval(len(toolchain_correct_runs), len(toolchain_applicable)),
            "unsupported_honesty_rate": _wilson_interval(len(unsupported_honest_runs), len(unsupported_applicable)),
            "repair_success_rate": _wilson_interval(len(repair_success_runs), len(repair_applicable)),
            "rag_evidence_hit_rate": _wilson_interval(len(rag_evidence_runs), len(rag_evidence_applicable)),
            "rag_pollution_rate": _wilson_interval(len(rag_pollution_runs), len(run_metrics)),
        },
        "tokens_per_success": round(total_tokens / max(successful_runs, 1), 4),
        "artifact_completeness_avg": round(sum(artifact_rates) / max(len(artifact_rates), 1), 4),
        "trace_completeness_avg": round(sum(trace_rates) / max(len(trace_rates), 1), 4) if trace_rates else None,
        "agent_runtime": {
            "session_run_rate": round(sum(1 for item in run_metrics if item.get("agent_runtime", {}).get("session_id")) / total_runs, 4),
            "checkpoint_count_total": sum(item.get("agent_runtime", {}).get("checkpoint_count", 0) for item in run_metrics),
            "delegation_completion_rate": round(delegation_results / max(delegation_requests, 1), 4),
            "tool_schema_rejection_count_total": sum(item.get("agent_runtime", {}).get("tool_schema_rejection_count", 0) for item in run_metrics),
            "tool_cache_hit_count_total": sum(item.get("agent_runtime", {}).get("tool_cache_hit_count", 0) for item in run_metrics),
            "duplicate_tool_call_count_total": sum(item.get("agent_runtime", {}).get("duplicate_tool_call_count", 0) for item in run_metrics),
            "budget_exceeded_count_total": sum(item.get("agent_runtime", {}).get("budget_exceeded_count", 0) for item in run_metrics),
        },
        "report_success_runs": report_success_runs,
        "vivado_metric_runs": vivado_success_runs,
        "rag_evidence_hit_runs": rag_evidence_runs,
        "rag_evidence_hit_rate": round(len(rag_evidence_runs) / max(len(rag_evidence_applicable), 1), 4),
        "rag_pollution_runs": rag_pollution_runs,
        "rag_pollution_rate": round(len(rag_pollution_runs) / total_runs, 4),
        "semantic_rag": {
            "retrieval_count_total": total_rag_retrievals,
            "embedding_retrieval_rate": round(total_embedding_retrievals / max(total_rag_retrievals, 1), 4),
            "cross_encoder_rerank_rate": round(total_cross_reranks / max(total_rag_retrievals, 1), 4),
            "lexical_fallback_rate": round(total_lexical_fallbacks / max(total_rag_retrievals, 1), 4),
        },
        "unsupported_status_errors": unsupported_status_errors,
        "unsupported_metric_suggestion_errors": unsupported_metric_suggestion_errors,
        "unsupported_honest_runs": unsupported_honest_runs,
        "unsupported_honesty_rate": round(len(unsupported_honest_runs) / max(len(unsupported_applicable), 1), 4),
        "repair_success_runs": repair_success_runs,
        "repair_success_rate": round(len(repair_success_runs) / max(len(repair_applicable), 1), 4),
        "unsupported_semantics_pass_rate": round(
            1.0 - (len(unsupported_status_errors) + len(unsupported_metric_suggestion_errors)) / total_runs,
            4,
        ),
        "llm_harness": {
            "applicable_run_count": len(llm_harness_applicable),
            "plan_acceptance_rate": round(total_plan_accepts / max(total_plan_accepts + total_plan_rejects, 1), 4),
            "plan_reject_count_total": total_plan_rejects,
            "json_repair_count_total": total_json_repairs,
            "json_repair_success_rate": round(total_json_repair_successes / max(total_json_repairs, 1), 4),
            "guard_rejection_runs": guard_rejection_runs,
            "guard_rejection_run_rate": round(len(guard_rejection_runs) / max(len(llm_harness_applicable), 1), 4),
            "llm_call_failed_runs": llm_call_failed_runs,
            "candidate_generation_runs": candidate_generation_runs,
            "candidate_generation_event_count_total": total_candidate_generation_events,
            "candidate_repair_todo_count_total": total_candidate_repair_todos,
        },
        "agent_maturity": {
            "core_score_avg": round(sum(maturity_scores) / max(len(maturity_scores), 1), 4),
            "context_pack_count_total": total_context_packs,
            "context_budget_compliance_rate": round(total_context_compliant / max(total_context_packs, 1), 4),
            "workspace_tool_call_count_total": sum(item.get("agent_maturity", {}).get("workspace_tool_call_count", 0) for item in run_metrics),
            "cross_session_memory_call_count_total": sum(item.get("agent_maturity", {}).get("cross_session_memory_call_count", 0) for item in run_metrics),
            "permission_denial_count_total": sum(item.get("agent_maturity", {}).get("permission_denial_count", 0) for item in run_metrics),
            "approval_request_count_total": sum(item.get("agent_maturity", {}).get("approval_request_count", 0) for item in run_metrics),
            "mcp_tool_call_count_total": sum(item.get("agent_maturity", {}).get("mcp_tool_call_count", 0) for item in run_metrics),
        },
        "bad_case_governance": {
            "completion_gate_pass_rate": round(
                sum(1 for item in completion_applicable if item.get("completion_gate_passed"))
                / max(len(completion_applicable), 1),
                4,
            ),
            "false_success_prevented_count": sum(
                1 for item in governance_runs if item.get("false_success_prevented")
            ),
            "production_ready_rate": round(
                sum(1 for item in completion_applicable if item.get("production_ready"))
                / max(len(completion_applicable), 1),
                4,
            ),
            "plan_coverage_rate": round(
                sum(1 for item in plan_coverage_applicable if item.get("plan_coverage_status") == "valid")
                / max(len(plan_coverage_applicable), 1),
                4,
            ),
            "tool_evidence_receipt_count_total": receipt_total,
            "tool_evidence_valid_rate": round(valid_receipt_total / max(receipt_total, 1), 4),
            "tool_postcondition_failure_count_total": sum(
                int(item.get("tool_postcondition_failure_count") or 0) for item in governance_runs
            ),
            "rag_rejected_count_total": sum(int(item.get("rag_rejected_count") or 0) for item in governance_runs),
            "progress_replan_event_count_total": sum(
                int(item.get("progress_replan_event_count") or 0) for item in governance_runs
            ),
            "progress_terminate_event_count_total": sum(
                int(item.get("progress_terminate_event_count") or 0) for item in governance_runs
            ),
        },
    }


def load_suite_cases(path: str | Path) -> list[dict[str, Any]]:
    payload = _read_json(Path(path), {})
    cases = payload.get("cases", []) if isinstance(payload, dict) else payload
    expected_defaults = payload.get("expected_defaults", {}) if isinstance(payload, dict) else {}
    if not isinstance(cases, list):
        raise ValueError(f"Benchmark suite file has no cases list: {path}")
    normalized = []
    for index, case in enumerate(cases, start=1):
        if not isinstance(case, dict) or not case.get("id") or not case.get("task"):
            raise ValueError(f"Invalid benchmark suite case #{index}: every case needs id and task.")
        normalized_case = dict(case)
        normalized_case["expected"] = {**expected_defaults, **(case.get("expected") or {})}
        normalized.append(normalized_case)
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
    if expected.get("toolchain_for_path"):
        checks.append(
            _check(
                bool(metrics.get("toolchain_quality", {}).get("correct_for_selected_path")),
                "toolchain_for_selected_path",
                metrics.get("toolchain_quality", {}),
            )
        )
    for tool in expected.get("required_tools", []):
        tools_used = set(metrics.get("tools_used", []))
        checks.append(_check(str(tool) in tools_used, f"required_tool:{tool}", {"tool": tool, "tools_used": sorted(tools_used)}))
    for index, group in enumerate(expected.get("required_tool_groups", []), start=1):
        tools_used = set(metrics.get("tools_used", []))
        candidates = [str(item) for item in group]
        checks.append(
            _check(
                _has_any_tool(tools_used, candidates),
                f"required_tool_group:{index}",
                {"candidates": candidates, "tools_used": sorted(tools_used)},
            )
        )
    for tool in expected.get("forbidden_tools", []):
        tools_used = set(metrics.get("tools_used", []))
        checks.append(_check(str(tool) not in tools_used, f"forbidden_tool:{tool}", {"tool": tool, "tools_used": sorted(tools_used)}))
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
    if "trace_completeness_min" in expected:
        checks.append(
            _check(
                metrics.get("trace_completeness", {}).get("rate", 0.0) >= float(expected["trace_completeness_min"]),
                "trace_completeness_min",
                {"actual": metrics.get("trace_completeness", {}).get("rate"), "expected_min": expected["trace_completeness_min"]},
            )
        )
    if expected.get("rag_evidence_hit"):
        checks.append(
            _check(
                metrics.get("rag_quality", {}).get("evidence_hit") is True,
                "rag_evidence_hit",
                metrics.get("rag_quality", {}),
            )
        )
    if expected.get("rag_no_pollution"):
        checks.append(
            _check(
                not metrics.get("rag_quality", {}).get("pollution_detected")
                and not metrics.get("rag_quality", {}).get("contains_prior_experience_hint")
                and not metrics.get("rag_quality", {}).get("contains_matmul_for_resnet_boundary"),
                "rag_no_pollution",
                metrics.get("rag_quality", {}),
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
    if expected.get("unsupported_honesty"):
        checks.append(_check(bool(metrics.get("unsupported_honesty", {}).get("honest")), "unsupported_honesty", metrics.get("unsupported_honesty", {})))
    if expected.get("repair_success_required"):
        checks.append(_check(bool(metrics.get("repair_quality", {}).get("repair_success")), "repair_success_required", metrics.get("repair_quality", {})))
    if "max_llm_decisions" in expected:
        checks.append(_check(metrics.get("llm_decision_count", 0) <= int(expected["max_llm_decisions"]), "max_llm_decisions", {"actual": metrics.get("llm_decision_count", 0), "max": expected["max_llm_decisions"]}))
    if "min_llm_calls" in expected:
        checks.append(_check(metrics.get("llm_call_count", 0) >= int(expected["min_llm_calls"]), "min_llm_calls", {"actual": metrics.get("llm_call_count", 0), "min": expected["min_llm_calls"]}))
    if "max_llm_calls" in expected:
        checks.append(_check(metrics.get("llm_call_count", 0) <= int(expected["max_llm_calls"]), "max_llm_calls", {"actual": metrics.get("llm_call_count", 0), "max": expected["max_llm_calls"]}))
    if expected.get("selected_skill") is not None:
        checks.append(_check(metrics.get("selected_skill") == expected["selected_skill"], "selected_skill", {"actual": metrics.get("selected_skill"), "expected": expected["selected_skill"]}))
    if expected.get("llm_plan_accepted"):
        checks.append(_check(bool(metrics.get("llm_harness", {}).get("plan_accepted")), "llm_plan_accepted", metrics.get("llm_harness", {})))
    if "max_llm_guard_rejections" in expected:
        checks.append(_check(metrics.get("llm_harness", {}).get("guard_rejection_count", 0) <= int(expected["max_llm_guard_rejections"]), "max_llm_guard_rejections", {"actual": metrics.get("llm_harness", {}).get("guard_rejection_count", 0), "max": expected["max_llm_guard_rejections"]}))
    if "min_llm_react_decisions" in expected:
        checks.append(_check(metrics.get("llm_harness", {}).get("react_decision_count", 0) >= int(expected["min_llm_react_decisions"]), "min_llm_react_decisions", {"actual": metrics.get("llm_harness", {}).get("react_decision_count", 0), "min": expected["min_llm_react_decisions"]}))
    if "min_llm_candidate_generations" in expected:
        checks.append(_check(metrics.get("llm_harness", {}).get("candidate_generation_event_count", 0) >= int(expected["min_llm_candidate_generations"]), "min_llm_candidate_generations", {"actual": metrics.get("llm_harness", {}).get("candidate_generation_event_count", 0), "min": expected["min_llm_candidate_generations"]}))
    if "min_llm_json_repairs" in expected:
        checks.append(_check(metrics.get("llm_harness", {}).get("json_repair_count", 0) >= int(expected["min_llm_json_repairs"]), "min_llm_json_repairs", {"actual": metrics.get("llm_harness", {}).get("json_repair_count", 0), "min": expected["min_llm_json_repairs"]}))
    if expected.get("llm_json_repair_success"):
        checks.append(_check(metrics.get("llm_harness", {}).get("json_repair_success_rate", 0.0) >= 1.0, "llm_json_repair_success", metrics.get("llm_harness", {})))
    if "min_llm_candidate_repair_todos" in expected:
        checks.append(_check(metrics.get("llm_harness", {}).get("candidate_repair_todo_count", 0) >= int(expected["min_llm_candidate_repair_todos"]), "min_llm_candidate_repair_todos", {"actual": metrics.get("llm_harness", {}).get("candidate_repair_todo_count", 0), "min": expected["min_llm_candidate_repair_todos"]}))
    if "min_promoted_memories" in expected:
        checks.append(_check(metrics["memory"].get("promoted_count", 0) >= int(expected["min_promoted_memories"]), "min_promoted_memories", {"actual": metrics["memory"].get("promoted_count", 0), "min": expected["min_promoted_memories"]}))
    agent_runtime = metrics.get("agent_runtime", {})
    if expected.get("require_session"):
        checks.append(_check(bool(agent_runtime.get("session_id")), "require_session", {"session_id": agent_runtime.get("session_id")}))
    if "min_checkpoints" in expected:
        checks.append(_check(agent_runtime.get("checkpoint_count", 0) >= int(expected["min_checkpoints"]), "min_checkpoints", {"actual": agent_runtime.get("checkpoint_count", 0), "min": expected["min_checkpoints"]}))
    if "delegation_completion_min" in expected:
        checks.append(_check(agent_runtime.get("delegation_completion_rate", 0.0) >= float(expected["delegation_completion_min"]), "delegation_completion_min", {"actual": agent_runtime.get("delegation_completion_rate", 0.0), "min": expected["delegation_completion_min"]}))
    if "max_duplicate_tool_call_rate" in expected:
        checks.append(_check(agent_runtime.get("duplicate_tool_call_rate", 0.0) <= float(expected["max_duplicate_tool_call_rate"]), "max_duplicate_tool_call_rate", {"actual": agent_runtime.get("duplicate_tool_call_rate", 0.0), "max": expected["max_duplicate_tool_call_rate"]}))
    if "max_budget_exceeded" in expected:
        checks.append(_check(agent_runtime.get("budget_exceeded_count", 0) <= int(expected["max_budget_exceeded"]), "max_budget_exceeded", {"actual": agent_runtime.get("budget_exceeded_count", 0), "max": expected["max_budget_exceeded"]}))
    if "max_tool_schema_rejections" in expected:
        checks.append(_check(agent_runtime.get("tool_schema_rejection_count", 0) <= int(expected["max_tool_schema_rejections"]), "max_tool_schema_rejections", {"actual": agent_runtime.get("tool_schema_rejection_count", 0), "max": expected["max_tool_schema_rejections"]}))
    if "max_recorded_tokens" in expected:
        checks.append(_check(metrics.get("cost", {}).get("recorded_total_tokens", 0) <= int(expected["max_recorded_tokens"]), "max_recorded_tokens", {"actual": metrics.get("cost", {}).get("recorded_total_tokens", 0), "max": expected["max_recorded_tokens"]}))
    if "max_estimated_tokens" in expected:
        checks.append(_check(metrics.get("cost", {}).get("estimated_total_tokens", 0) <= int(expected["max_estimated_tokens"]), "max_estimated_tokens", {"actual": metrics.get("cost", {}).get("estimated_total_tokens", 0), "max": expected["max_estimated_tokens"]}))
    if "max_tool_calls_run" in expected:
        checks.append(_check(metrics.get("tool_call_count", 0) <= int(expected["max_tool_calls_run"]), "max_tool_calls_run", {"actual": metrics.get("tool_call_count", 0), "max": expected["max_tool_calls_run"]}))

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
        result["selected_path"] = metrics.get("selected_path")
        result["task_success"] = _agent_task_success(metrics, result.get("category"))
        result["toolchain_correct"] = metrics.get("toolchain_quality", {}).get("correct_for_selected_path")
        result["unsupported_honest"] = metrics.get("unsupported_honesty", {}).get("honest")
        result["trace_completeness_rate"] = metrics.get("trace_completeness", {}).get("rate")
        case_results.append(result)
    category_scores: dict[str, list[float]] = {}
    category_success: dict[str, list[bool]] = {}
    for result in case_results:
        category = str(result.get("category") or "uncategorized")
        category_scores.setdefault(category, []).append(float(result["score"]))
        category_success.setdefault(category, []).append(bool(result.get("task_success")))

    def _check_passed(result: dict[str, Any], name: str) -> bool | None:
        for check in result.get("checks", []):
            if check.get("name") == name:
                return bool(check.get("passed"))
        return None

    path_checks = [item for item in (_check_passed(result, "selected_path") for result in case_results) if item is not None]
    toolchain_checks = [
        item for item in (_check_passed(result, "toolchain_for_selected_path") for result in case_results) if item is not None
    ]
    unsupported_checks = [item for item in (_check_passed(result, "unsupported_honesty") for result in case_results) if item is not None]
    repair_checks = [item for item in (_check_passed(result, "repair_success_required") for result in case_results) if item is not None]
    return {
        "case_count": len(case_results),
        "pass_count": sum(1 for item in case_results if item["passed"]),
        "pass_rate": round(sum(1 for item in case_results if item["passed"]) / max(len(case_results), 1), 4),
        "average_score": round(sum(float(item["score"]) for item in case_results) / max(len(case_results), 1), 4),
        "category_scores": {
            category: round(sum(scores) / max(len(scores), 1), 4) for category, scores in sorted(category_scores.items())
        },
        "agent_metrics": {
            "path_selection_accuracy": round(sum(1 for item in path_checks if item) / max(len(path_checks), 1), 4),
            "toolchain_selection_accuracy": round(sum(1 for item in toolchain_checks if item) / max(len(toolchain_checks), 1), 4),
            "task_success_rate_by_category": {
                category: round(sum(1 for item in values if item) / max(len(values), 1), 4)
                for category, values in sorted(category_success.items())
            },
            "unsupported_honesty_rate": round(sum(1 for item in unsupported_checks if item) / max(len(unsupported_checks), 1), 4),
            "repair_success_rate": round(sum(1 for item in repair_checks if item) / max(len(repair_checks), 1), 4),
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
    expect_abstain = bool(case.get("expect_abstain") or case.get("expect_no_results"))

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
    retrieval_modes = [str((result.get("retrieval") or {}).get("mode") or "unknown") for result in top_results]
    semantic_scores = [
        float((result.get("retrieval") or {})["semantic_score"])
        for result in top_results
        if isinstance((result.get("retrieval") or {}).get("semantic_score"), (int, float))
    ]
    cross_encoder_scores = [
        float((result.get("retrieval") or {})["cross_encoder_score"])
        for result in top_results
        if isinstance((result.get("retrieval") or {}).get("cross_encoder_score"), (int, float))
    ]
    rerank_deltas = [
        int((result.get("retrieval") or {})["pre_rerank_rank"])
        - int((result.get("retrieval") or {})["final_rank"])
        for result in top_results
        if isinstance((result.get("retrieval") or {}).get("pre_rerank_rank"), int)
        and isinstance((result.get("retrieval") or {}).get("final_rank"), int)
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
        "expect_abstain": expect_abstain,
        "abstention_correct": (not top_results) if expect_abstain else None,
        "embedding_recall_usage_rate": round(
            sum(1 for mode in retrieval_modes if mode.startswith("embedding")) / max(len(retrieval_modes), 1), 4
        ),
        "cross_encoder_rerank_usage_rate": round(
            sum(1 for mode in retrieval_modes if mode == "embedding_cross_encoder") / max(len(retrieval_modes), 1), 4
        ),
        "semantic_score_avg": round(sum(semantic_scores) / len(semantic_scores), 4) if semantic_scores else None,
        "cross_encoder_score_avg": (
            round(sum(cross_encoder_scores) / len(cross_encoder_scores), 4) if cross_encoder_scores else None
        ),
        "rerank_mean_position_gain": round(sum(rerank_deltas) / len(rerank_deltas), 4) if rerank_deltas else None,
        "retrieval_modes": retrieval_modes,
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
        "abstention_accuracy": _mean("abstention_correct"),
        "embedding_recall_usage_rate": _mean("embedding_recall_usage_rate"),
        "cross_encoder_rerank_usage_rate": _mean("cross_encoder_rerank_usage_rate"),
        "semantic_score_avg": _mean("semantic_score_avg"),
        "cross_encoder_score_avg": _mean("cross_encoder_score_avg"),
        "rerank_mean_position_gain": _mean("rerank_mean_position_gain"),
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
    case_ids: list[str] | None = None,
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
    if case_ids:
        requested = set(case_ids)
        available = {str(case["id"]) for case in case_specs}
        unknown = requested - available
        if unknown:
            raise ValueError(f"Unknown benchmark case ids: {sorted(unknown)}")
        case_specs = [case for case in case_specs if str(case["id"]) in requested]
    for iteration in range(1, repeat + 1):
        for case in case_specs:
            case_env = dict(case.get("env", {}))
            case_mock_tools = bool(case.get("mock_tools", mock_tools))
            if case_mock_tools:
                case_env.setdefault("DL_OP_TO_HLS_MOCK_TOOLS", "1")
                case_env.setdefault("DL_OP_TO_HLS_MOCK_HLS4ML", "1")
                case_env.setdefault("DL_OP_TO_HLS_MOCK_VIVADO", "1")
            else:
                case_env.setdefault("DL_OP_TO_HLS_MOCK_TOOLS", "0")
                case_env.setdefault("DL_OP_TO_HLS_MOCK_HLS4ML", "0")
                case_env.setdefault("DL_OP_TO_HLS_MOCK_VIVADO", "0")
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
    return evaluate_rag_cases(
        cases,
        lambda query, k: agent.rag_memory.retrieve_corrective(query, top_k=k)["results"],
        default_top_k=top_k,
    )


def build_payload(
    run_dirs: list[Path],
    compare: tuple[str, str] | None = None,
    rag_eval_file: str | Path | None = None,
    rag_top_k: int = 5,
    suite_file: str | Path | None = None,
) -> dict[str, Any]:
    run_metrics = [collect_run_metrics(path) for path in run_dirs]
    aggregate = aggregate_metrics(run_metrics)
    from ..core.observability import SLOEvaluator

    payload: dict[str, Any] = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "benchmark_version": "agent-quality-v1",
        "metrics": run_metrics,
        "aggregate": aggregate,
        "slo": SLOEvaluator().evaluate(
            {
                "task_success_rate": aggregate["task_success_rate"],
                "false_success_rate": aggregate["false_success_rate"],
                "rag_pollution_rate": aggregate["rag_pollution_rate"],
                "p95_runtime_seconds": aggregate["runtime_s"]["p95"] or 0,
                "tokens_per_success": aggregate["tokens_per_success"],
                "queue_lease_expiry_rate": 0,
            }
        ),
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
        f"- Selected path valid rate: `{aggregate['selected_path_valid_rate']}`",
        f"- Toolchain selection accuracy: `{aggregate['toolchain_selection_accuracy']}`",
        f"- Task success rate by category: `{aggregate['task_success_rate_by_category']}`",
        f"- Runtime p50 / p95: `{aggregate['runtime_s']['p50']}` / `{aggregate['runtime_s']['p95']}` seconds",
        f"- LLM decisions total: `{aggregate['llm_decision_count_total']}`",
        f"- Tool calls total / avg per run: `{aggregate['tool_call_count_total']}` / `{aggregate['avg_tool_calls_per_run']}`",
        f"- LLM calls total / avg per run: `{aggregate['llm_call_count_total']}` / `{aggregate['avg_llm_calls_per_run']}`",
        f"- Estimated tokens avg per run: `{aggregate['avg_estimated_tokens_per_run']}`",
        f"- Artifact completeness avg: `{aggregate['artifact_completeness_avg']}`",
        f"- Trace completeness avg: `{aggregate['trace_completeness_avg']}`",
        f"- RAG evidence hit / pollution rate: `{aggregate['rag_evidence_hit_rate']}` / `{aggregate['rag_pollution_rate']}`",
        f"- Unsupported honesty rate: `{aggregate['unsupported_honesty_rate']}`",
        f"- Repair success rate: `{aggregate['repair_success_rate']}`",
        f"- 95% Wilson confidence intervals: `{aggregate.get('confidence_95', {})}`",
        f"- Unsupported semantics pass rate: `{aggregate['unsupported_semantics_pass_rate']}`",
        f"- LLM harness: `{aggregate.get('llm_harness', {})}`",
        f"- Bad Case governance: `{aggregate.get('bad_case_governance', {})}`",
        f"- Vivado metric runs (secondary hardware evidence): `{aggregate['vivado_metric_runs']}`",
        "",
        "## Per-run Metrics",
        "| Run | Status | Path | Skill | Toolchain OK | Runtime(s) | Tool calls | LLM calls | Est. tokens | Trace | RAG hit | RAG polluted | Unsupported honest | Repair |",
        "|---|---|---|---|---|---:|---:|---:|---:|---:|---|---|---|---|",
    ]
    for item in payload["metrics"]:
        rag_bad = item["rag_quality"]["contains_prior_experience_hint"] or item["rag_quality"]["contains_matmul_for_resnet_boundary"]
        rag_bad = rag_bad or item["rag_quality"].get("pollution_detected")
        unsupported_ok = item.get("unsupported_honesty", {}).get("honest")
        lines.append(
            "| {run_id} | {status} | {path} | {skill} | {toolchain} | {runtime} | {tools} | {llm_calls} | {tokens} | {trace} | {rag_hit} | {rag_bad} | {unsupported_ok} | {repair} |".format(
                run_id=item["run_id"],
                status=item.get("status"),
                path=item.get("selected_path"),
                skill=item.get("selected_skill"),
                toolchain=item.get("toolchain_quality", {}).get("correct_for_selected_path"),
                runtime=item.get("runtime_s"),
                tools=item.get("tool_call_count"),
                llm_calls=item.get("llm_call_count"),
                tokens=item.get("cost", {}).get("estimated_total_tokens"),
                trace=item.get("trace_completeness", {}).get("rate"),
                rag_hit=item["rag_quality"].get("evidence_hit"),
                rag_bad=rag_bad,
                unsupported_ok=unsupported_ok,
                repair=item.get("repair_quality", {}).get("repair_success"),
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
                f"- Agent metrics: `{suite.get('agent_metrics', {})}`",
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
    parser.add_argument("--case-id", nargs="*", default=[], help="Run only selected case ids from --suite-file.")
    parser.add_argument("--runner", choices=["deterministic", "llm"], default="llm")
    parser.add_argument("--mock-tools", action="store_true")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--quiet", action="store_true", help="Write output files without printing the full JSON payload to stdout.")
    parser.add_argument(
        "--tasks",
        nargs="*",
        default=["examples/mnist_recognition_mlp.json"],
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
            case_ids=args.case_id,
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
    if not args.quiet:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
