"""memory layer implementation for short_term.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

from typing import Any


def build_short_term_entry(key: str, value: dict[str, Any]) -> dict[str, Any]:
    """Execute build_short_term_entry at the short_term boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Args:
        key: Value supplied by the caller and validated by the surrounding schema.
        value: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    return {"key": key, "value": value}

