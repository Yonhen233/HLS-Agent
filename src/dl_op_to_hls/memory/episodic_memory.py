from __future__ import annotations


def build_episodic_candidate(state: dict) -> dict:
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
