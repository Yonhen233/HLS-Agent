from __future__ import annotations


def reflect_on_errors(state) -> None:
    if state.errors and state.status not in {"partial_success", "failed"}:
        state.status = "partial_success" if state.report or state.selected_path else "failed"


def update_status_from_todos(state) -> None:
    statuses = {item.status for item in state.todos}
    if not statuses:
        return
    if "failed" in statuses and state.report is None:
        state.status = "failed"
        return
    if statuses.intersection({"blocked", "cancelled", "pending", "in_progress"}):
        if state.status != "failed":
            state.status = "partial_success"
        return
    meaningful_skips = [
        item
        for item in state.todos
        if item.status == "skipped" and (item.title != "Promote memories" or (item.error or {}).get("message") != "Memory promotion is handled during runtime finalization.")
    ]
    if meaningful_skips or "completed_with_warning" in statuses or state.errors:
        state.status = "partial_success" if state.status != "failed" else state.status
        return
    if statuses.issubset({"completed", "skipped"}):
        state.status = "success"
