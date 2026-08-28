from __future__ import annotations

from ..core.errors import unresolved_errors


def reflect_on_errors(state) -> None:
    if state.status == "interrupted":
        return
    if unresolved_errors(state.errors) and state.status not in {"partial_success", "failed"}:
        state.status = "partial_success" if state.report or state.selected_path else "failed"


def _is_superseded_cancellation(item) -> bool:
    message = ((item.error or {}).get("message") or "").lower()
    return "repair" in message or "repaired" in message or "replace the previous" in message


def update_status_from_todos(state) -> None:
    if state.status == "interrupted":
        return
    statuses = {item.status for item in state.todos}
    if not statuses:
        return
    unsupported_report_completed = any(
        item.assigned_tool == "report.write_unsupported" and item.status in {"completed", "completed_with_warning"}
        for item in state.todos
    )
    if state.selected_path == "unsupported_path" and unsupported_report_completed:
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
    if state.selected_path == "unsupported_path":
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
