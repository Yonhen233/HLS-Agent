from __future__ import annotations


def finalize_state(state, artifact_manager) -> None:
    state.artifacts["manifest"] = str(artifact_manager.run_dir / "artifacts.json")
    state.artifacts["todos"] = str(artifact_manager.run_dir / "todos.json")
