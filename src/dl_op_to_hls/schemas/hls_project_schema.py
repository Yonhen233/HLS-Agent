from __future__ import annotations


def normalize_hls_project_task(task: dict) -> dict:
    normalized = dict(task)
    normalized.setdefault("objective", task.get("objective", "resource"))
    normalized.setdefault("name", "existing_hls_project")
    return normalized

