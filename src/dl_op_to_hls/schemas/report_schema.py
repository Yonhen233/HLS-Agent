"""schemas layer implementation for report_schema.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations


def empty_report(status: str = "missing") -> dict:
    """Execute empty_report at the report_schema boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Args:
        status: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    return {
        "status": status,
        "latency": {"min_cycles": None, "max_cycles": None},
        "interval": {"min_ii": None, "max_ii": None},
        "resources": {"bram": None, "dsp": None, "ff": None, "lut": None},
        "timing": {"target_ns": None, "estimated_ns": None, "met": None},
    }

