from __future__ import annotations


def build_semantic_candidates(state: dict) -> list[dict]:
    candidates: list[dict] = []
    if state.get("selected_path") == "fallback_template_path" and state.get("status") in {"success", "partial_success"}:
        candidates.append(
            {
                "kind": "optimization",
                "key": f"optimization.{state['run_id']}.fallback",
                "summary": "Fallback template path produced a usable HLS project for the operator task.",
                "value": {"selected_path": state.get("selected_path"), "task": state["task"].get("name")},
            }
        )
    for error in state.get("errors", []):
        if error.get("error_type") == "VivadoNotFoundError":
            candidates.append(
                {
                    "kind": "failure",
                    "key": f"failure.{state['run_id']}.vivado_missing",
                    "summary": "VivadoNotFoundError is recoverable and should lead to skipped synthesis with partial success.",
                    "value": error,
                    "fact": "VivadoNotFoundError is recoverable and synthesis can be skipped while keeping generated HLS artifacts.",
                    "tags": ["vivado", "recoverable", "failure"],
                }
            )
    unsupported = (state.get("hls4ml_support") or {}).get("unsupported_layers", [])
    if unsupported:
        first = unsupported[0]
        candidates.append(
            {
                "kind": "semantic",
                "key": f"semantic.{state['run_id']}.unsupported",
                "summary": f"hls4ml unsupported reason recorded for {first.get('type')}.",
                "value": first,
                "fact": f"hls4ml may reject {first.get('type')} tasks because {first.get('reason')}",
                "tags": ["hls4ml", "unsupported"],
            }
        )
    return candidates
