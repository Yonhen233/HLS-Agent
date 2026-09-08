"""schemas layer implementation for tool_schema.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations


def simple_schema(properties: dict, required: list[str] | None = None) -> dict:
    """Execute simple_schema at the tool_schema boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Args:
        properties: Value supplied by the caller and validated by the surrounding schema.
        required: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    return {"type": "object", "properties": properties, "required": required or []}

