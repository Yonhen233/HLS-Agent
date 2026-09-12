"""main_agent layer implementation for planner.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations


def build_plan(task: dict) -> list[str]:
    """Execute build_plan at the planner boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Args:
        task: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    task_type = task.get("task_type")
    if task_type == "model":
        return [
            "Validate task schema",
            "Generate unsupported report",
            "Write run summary",
            "Promote memories",
        ]
    if task_type == "operator":
        return [
            "Validate task schema",
            "Generate LLM candidate",
            "Verify LLM candidate",
            "Run Vivado HLS synthesis",
            "Parse synthesis report",
            "Generate optimization suggestions",
            "Write run summary",
            "Promote memories",
        ]
    return [
        "Validate task schema",
        "Prepare existing HLS project",
        "Run Vivado HLS synthesis",
        "Parse synthesis report",
        "Generate optimization suggestions",
        "Write run summary",
        "Promote memories",
    ]
