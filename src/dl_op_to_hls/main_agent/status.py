"""main_agent layer implementation for status.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

from typing import Any

from ..core.termination import terminal_outcome
from ..core.trace import TraceReader


VERIFIED_MODES = {"golden_testbench", "reference_compare"}


def is_functionally_verified(verification: dict[str, Any] | None) -> bool:
    """Execute is_functionally_verified at the status boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Args:
        verification: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    if not isinstance(verification, dict):
        return False
    mode = verification.get("mode")
    if verification.get("passed") is True and mode in VERIFIED_MODES:
        return True
    comparison = verification.get("comparison") if isinstance(verification.get("comparison"), dict) else {}
    return verification.get("passed") is True and comparison.get("passed") is True


def compute_pipeline_status(state: Any) -> dict[str, Any]:
    """Execute compute_pipeline_status at the status boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Args:
        state: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    task = getattr(state, "task", {}) or {}
    report = getattr(state, "report", None) or {}
    verification = getattr(state, "verification", None) or {}
    selected_path = getattr(state, "selected_path", None)
    terminal = terminal_outcome(state)
    hls_project_dir = getattr(state, "hls_project_dir", None)
    errors = getattr(state, "errors", []) or []
    timing = report.get("timing") if isinstance(report, dict) else {}
    synthesis_success = isinstance(report, dict) and report.get("status") == "success"
    conversion_success = bool(
        hls_project_dir
        or selected_path
        in {
            "llm_candidate_path",
        }
    )
    functional_verified = is_functionally_verified(verification)
    timing_met = None if not isinstance(timing, dict) else timing.get("met")
    deployment_ready_candidate = bool(
        conversion_success
        and synthesis_success
        and functional_verified
        and timing_met is not False
        and not errors
        and terminal is None
    )
    if terminal:
        level = "blocked" if terminal == "blocked" else terminal
    elif deployment_ready_candidate:
        level = "deployment_ready_candidate"
    elif functional_verified:
        level = "functional_verified"
    elif synthesis_success:
        level = "synthesis_success"
    elif conversion_success:
        level = "conversion_success"
    else:
        level = "initialized"
    return {
        "level": level,
        "conversion_success": conversion_success,
        "synthesis_success": synthesis_success,
        "functional_verified": functional_verified,
        "deployment_ready_candidate": deployment_ready_candidate,
        "timing_met": timing_met,
        "verification_mode": verification.get("mode") if isinstance(verification, dict) else None,
        "verification_status": verification.get("status") if isinstance(verification, dict) else None,
        "selected_path": selected_path,
        "terminal_outcome": terminal,
        "terminal_reason": getattr(state, "terminal_reason", {}) or {},
        "task_type": task.get("task_type"),
    }


def build_failure_diagnosis(state: Any, trace_path: str | None = None) -> dict[str, Any]:
    """Derive an explainable failure projection from state and the canonical Trace.

    This is intentionally a projection, not a second mutable error ledger.  The
    state supplies todo status and the Trace supplies tool/decision evidence.
    """
    todos = list(getattr(state, "todos", []) or [])
    failed = [item for item in todos if item.status in {"failed", "completed_with_warning"}]
    blocked = [item for item in todos if item.status in {"blocked", "cancelled"}]
    incomplete = [item for item in todos if item.status in {"pending", "in_progress"}]
    trace_failures: list[dict[str, Any]] = []
    trace_decisions: list[dict[str, Any]] = []
    if trace_path:
        reader = TraceReader(trace_path)
        trace_failures = reader.query("failures", max_items=100).get("records", [])
        trace_decisions = reader.query("decisions", max_items=100).get("records", [])

    primary = failed[0] if failed else blocked[0] if blocked else None
    matched_failure = None
    if primary is not None:
        for record in reversed(trace_failures):
            if record.get("todo_id") == primary.id:
                matched_failure = record
                break
    if matched_failure is None and trace_failures:
        matched_failure = trace_failures[-1]

    tool = str(getattr(primary, "assigned_tool", None) or (matched_failure or {}).get("tool_name") or "")
    error = getattr(primary, "error", None) if primary is not None else None
    if not isinstance(error, dict):
        error = {}
    reason = (
        error.get("message")
        or error.get("summary")
        or (matched_failure or {}).get("message")
        or (matched_failure or {}).get("reason")
        or (getattr(primary, "blocked_reason", None) if primary is not None else None)
    )
    if not reason:
        reason = (getattr(state, "terminal_reason", {}) or {}).get("reason") or "No concrete failure record was emitted."

    if tool in {"llm.generate_candidate", "llm.generate_hls_candidate"}:
        next_action = "reuse_candidate_repair_chain"
    elif tool in {"verify_candidate.run", "verify.run_csim", "vivado.run_csim"}:
        next_action = "repair_candidate_then_reverify"
    elif tool in {"vivado.run_csynth", "vivado.parse_report", "vivado.parse_csynth_report"}:
        next_action = "repair_or_replan_synthesis_stage"
    elif incomplete:
        next_action = "replan_stalled_dependency_graph"
    elif blocked:
        next_action = "record_blocked_boundary_or_request_user_input"
    else:
        next_action = "inspect_trace_and_retry_within_budget"

    return {
        "status": "failure" if failed else "blocked" if blocked else "incomplete" if incomplete else "healthy",
        "primary_stage": getattr(primary, "title", None) if primary is not None else None,
        "todo_id": getattr(primary, "id", None) if primary is not None else (matched_failure or {}).get("todo_id"),
        "tool": tool or None,
        "todo_status": getattr(primary, "status", None) if primary is not None else None,
        "reason": str(reason),
        "recoverable": bool(error.get("recoverable", True)) and bool(failed or blocked or incomplete),
        "next_action": next_action,
        "completed_stages": [item.title for item in todos if item.status in {"completed", "completed_with_warning"}],
        "failed_stages": [item.title for item in failed],
        "blocked_stages": [item.title for item in blocked],
        "incomplete_stages": [item.title for item in incomplete],
        "trace": {
            "source_path": str(trace_path) if trace_path else None,
            "failure_count": len(trace_failures),
            "decision_count": len(trace_decisions),
            "matched_failure": matched_failure,
            "source_of_truth": "trace.jsonl",
        },
    }
