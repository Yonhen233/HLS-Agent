from __future__ import annotations

from ..core.design_objectives import normalize_objective_mode


def normalize_hls_project_task(task: dict) -> dict:
    normalized = dict(task)
    normalized["objective"] = normalize_objective_mode(task.get("objective", "resource"), default="resource")
    normalized.setdefault("name", "existing_hls_project")
    return normalized
