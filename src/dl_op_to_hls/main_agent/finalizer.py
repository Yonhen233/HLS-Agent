"""main_agent layer implementation for finalizer.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations


def finalize_state(state, artifact_manager) -> None:
    """Execute finalize_state at the finalizer boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Args:
        state: Value supplied by the caller and validated by the surrounding schema.
        artifact_manager: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    state.artifacts["manifest"] = str(artifact_manager.run_dir / "artifacts.json")
    state.artifacts["todos"] = str(artifact_manager.run_dir / "todos.json")
