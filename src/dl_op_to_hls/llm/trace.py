from __future__ import annotations

from typing import Any


def emit_llm_event(context: dict[str, Any], event: str, payload: dict[str, Any]) -> None:
    hooks = context.get("hooks")
    if hooks is not None:
        hooks.emit(event, payload)
