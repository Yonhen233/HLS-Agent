"""main_agent layer implementation for reflector.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

from ..core.errors import unresolved_errors
from ..core.termination import is_blocked, terminal_outcome


def reflect_on_errors(state) -> None:
    """Execute reflect_on_errors at the reflector boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Args:
        state: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    if state.status == "interrupted":
        return
    if unresolved_errors(state.errors) and state.status not in {"partial_success", "failed"}:
        state.status = "partial_success" if state.report or state.selected_path or terminal_outcome(state) else "failed"


def _is_superseded_cancellation(item) -> bool:
    """Implement the internal _is_superseded_cancellation helper.

    Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

    Args:
        item: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    message = ((item.error or {}).get("message") or "").lower()
    return (
        "repair" in message
        or "repaired" in message
        or "replace the previous" in message
        or "superseded" in message
    )


def update_status_from_todos(state) -> None:
    """Execute update_status_from_todos at the reflector boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Args:
        state: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    if state.status == "interrupted":
        return
    statuses = {item.status for item in state.todos}
    if not statuses:
        return
    unsupported_report_completed = any(
        item.assigned_tool == "report.write_unsupported" and item.status in {"completed", "completed_with_warning"}
        for item in state.todos
    )
    if is_blocked(state) and unsupported_report_completed:
        meaningful_unfinished = [
            item
            for item in state.todos
            if item.status in {"blocked", "pending", "in_progress"}
            and item.assigned_tool != "report.write_unsupported"
        ]
        if not meaningful_unfinished:
            state.status = "partial_success"
            return
    if "failed" in statuses and state.report is None:
        state.status = "failed"
        return
    active_errors = unresolved_errors(state.errors)
    if getattr(state, "pipeline_status", {}).get("deployment_ready_candidate") and not active_errors:
        unfinished = [item for item in state.todos if item.status in {"blocked", "pending", "in_progress"}]
        meaningful_cancelled = [
            item for item in state.todos if item.status == "cancelled" and not _is_superseded_cancellation(item)
        ]
        if not unfinished and not meaningful_cancelled:
            state.status = "success"
            return
    if statuses.intersection({"blocked", "pending", "in_progress"}):
        if state.status != "failed":
            state.status = "partial_success"
        return
    meaningful_cancelled = [
        item for item in state.todos if item.status == "cancelled" and not _is_superseded_cancellation(item)
    ]
    if meaningful_cancelled:
        if state.status != "failed":
            state.status = "partial_success"
        return
    meaningful_skips = [
        item
        for item in state.todos
        if item.status == "skipped" and (item.title != "Promote memories" or (item.error or {}).get("message") != "Memory promotion is handled during runtime finalization.")
    ]
    if (
        not meaningful_skips
        and not active_errors
        and state.report
        and state.report.get("status") == "success"
        and state.report.get("timing", {}).get("met") is not False
        and state.selected_path in {"fallback_template_path", "hls4ml_path", "existing_hls_project_path", "llm_candidate_path"}
        and statuses.issubset({"completed", "completed_with_warning", "skipped", "cancelled"})
    ):
        state.status = "success"
        return
    if meaningful_skips or "completed_with_warning" in statuses or active_errors:
        state.status = "partial_success" if state.status != "failed" else state.status
        return
    if terminal_outcome(state):
        state.status = "partial_success"
        return
    if statuses.issubset({"completed", "skipped"}):
        if state.task.get("task_type") in {"model", "operator", "hls_project"} and not state.selected_path:
            state.status = "partial_success"
            return
        if (
            state.selected_path in {"fallback_template_path", "hls4ml_path", "existing_hls_project_path", "llm_candidate_path"}
            and state.report
            and state.report.get("status") in {"missing", "skipped", "report_missing"}
        ):
            state.status = "partial_success"
            return
        state.status = "success"
