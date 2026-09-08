"""llm layer implementation for trace.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

from typing import Any


def emit_llm_event(context: dict[str, Any], event: str, payload: dict[str, Any]) -> None:
    """Execute emit_llm_event at the trace boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Args:
        context: Value supplied by the caller and validated by the surrounding schema.
        event: Value supplied by the caller and validated by the surrounding schema.
        payload: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    hooks = context.get("hooks")
    if hooks is not None:
        hooks.emit(event, payload)
