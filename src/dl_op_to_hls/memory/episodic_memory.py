"""memory layer implementation for episodic_memory.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations


def build_episodic_candidate(state: dict) -> dict:
    """Execute build_episodic_candidate at the episodic_memory boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Args:
        state: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    return {
        "kind": "episodic",
        "key": f"episode.{state['run_id']}",
        "summary": f"Run {state['run_id']} used {state.get('selected_path')} with status {state.get('status')}.",
        "value": {
            "run_id": state["run_id"],
            "task_type": state["task"].get("task_type"),
            "name": state["task"].get("name"),
            "selected_path": state.get("selected_path"),
            "objective": state.get("objective"),
            "status": state.get("status"),
            "report": state.get("report"),
            "verification": state.get("verification"),
            "pipeline_status": state.get("pipeline_status"),
            "errors": state.get("errors", []),
            "suggestions": state.get("suggestions", []),
        },
    }
