from __future__ import annotations

from typing import Any

from ..core.errors import AgentRuntimeError, build_error


def load_task(payload: dict[str, Any]) -> dict[str, Any]:
    task_type = payload.get("task_type")
    if task_type not in {"model", "operator", "hls_project"}:
        raise AgentRuntimeError(
            build_error(
                "InvalidTaskError",
                "task_type must be one of model, operator, or hls_project.",
                recoverable=False,
                source="schemas.task_schema",
                suggested_action="Check the example JSON files and provide a supported task_type.",
                details={"task_type": task_type},
            )
        )
    return payload

