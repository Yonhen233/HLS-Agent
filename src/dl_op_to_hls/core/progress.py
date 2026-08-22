from __future__ import annotations

from collections import Counter
from typing import Any

from .trace import stable_hash


class ProgressSupervisor:
    """Detect repeated failures, no-progress loops, drift, and runaway plans."""

    AUXILIARY_PREFIXES = (
        "workspace.",
        "memory.",
        "rag.",
        "summary.",
        "suggestion.",
        "parameter_advisor.",
        "db.",
    )

    def __init__(self, *, max_steps: int = 64, replan_after: int = 2, terminate_after: int = 3):
        self.max_steps = max(1, int(max_steps))
        self.replan_after = max(1, int(replan_after))
        self.terminate_after = max(self.replan_after + 1, int(terminate_after))
        self.step_count = 0
        self._last_state_hash: str | None = None
        self._same_state_count = 0
        self._failure_signatures: Counter[str] = Counter()
        self._consecutive_drift = 0
        self._open_requirement_history: list[list[str]] = []
        self.history: list[dict[str, Any]] = []

    def observe(
        self,
        state: Any,
        todo: Any,
        observation: dict[str, Any],
        *,
        completion_gate: Any | None = None,
        goal_contract: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.step_count += 1
        state_hash = self._state_hash(state)
        if state_hash == self._last_state_hash:
            self._same_state_count += 1
        else:
            self._same_state_count = 0
        self._last_state_hash = state_hash

        error = self._extract_error(observation)
        signature = None
        repeated_failures = 0
        if error:
            signature = stable_hash(
                {
                    "tool": getattr(todo, "assigned_tool", None),
                    "error_type": error.get("error_type"),
                    "message": error.get("message"),
                    "inputs": getattr(todo, "inputs", {}),
                }
            )
            self._failure_signatures[signature] += 1
            repeated_failures = self._failure_signatures[signature]

        completion = None
        open_requirements: list[str] = []
        if completion_gate is not None and goal_contract:
            completion = completion_gate.evaluate(state, goal_contract, [])
            open_requirements = list(completion.get("missing_required", []))
            self._open_requirement_history.append(open_requirements)

        tool_name = str(getattr(todo, "assigned_tool", None) or "")
        requirement_ids = list(getattr(todo, "requirement_ids", []) or [])
        drift = bool(tool_name) and not requirement_ids and not tool_name.startswith(self.AUXILIARY_PREFIXES)
        self._consecutive_drift = self._consecutive_drift + 1 if drift else 0
        decision = "continue"
        reason = "progress_observed"
        if self.step_count > self.max_steps:
            decision = "terminate"
            reason = "max_steps_exceeded"
        elif repeated_failures >= self.terminate_after:
            decision = "terminate"
            reason = "repeated_failure_loop"
        elif self._consecutive_drift >= self.terminate_after:
            decision = "terminate"
            reason = "direction_drift"
        elif self._same_state_count >= self.terminate_after:
            decision = "terminate"
            reason = "state_stagnation"
        elif repeated_failures >= self.replan_after or self._same_state_count >= self.replan_after:
            decision = "replan"
            reason = "repeated_failure_requires_replan" if repeated_failures else "state_stagnation_requires_replan"
        elif self._consecutive_drift >= self.replan_after:
            decision = "replan"
            reason = "direction_drift_requires_replan"
        elif drift:
            decision = "review"
            reason = "todo_not_mapped_to_goal_requirement"

        record = {
            "step": self.step_count,
            "todo_id": getattr(todo, "id", None),
            "tool_name": tool_name or None,
            "requirement_ids": requirement_ids,
            "state_hash": state_hash,
            "same_state_count": self._same_state_count,
            "failure_signature": signature,
            "repeated_failures": repeated_failures,
            "open_requirements": open_requirements,
            "drift_review": drift,
            "consecutive_drift": self._consecutive_drift,
            "decision": decision,
            "reason": reason,
        }
        self.history.append(record)
        state.progress = {
            "step_count": self.step_count,
            "last_decision": decision,
            "last_reason": reason,
            "same_state_count": self._same_state_count,
            "max_repeated_failure": max(self._failure_signatures.values(), default=0),
            "consecutive_drift": self._consecutive_drift,
            "open_requirements": open_requirements,
            "history": self.history[-20:],
        }
        return record

    @staticmethod
    def _extract_error(observation: dict[str, Any]) -> dict[str, Any] | None:
        nested = observation.get("observation") if isinstance(observation.get("observation"), dict) else {}
        error = observation.get("error") or nested.get("error")
        if isinstance(error, dict):
            return error
        error_type = observation.get("error_type") or nested.get("error_type")
        if error_type:
            return {"error_type": error_type, "message": nested.get("summary") or str(error_type)}
        return None

    @staticmethod
    def _state_hash(state: Any) -> str:
        return stable_hash(
            {
                "selected_path": getattr(state, "selected_path", None),
                "hls_project_dir": getattr(state, "hls_project_dir", None),
                "report": getattr(state, "report", None),
                "verification": getattr(state, "verification", None),
                "artifact_keys": sorted((getattr(state, "artifacts", {}) or {}).keys()),
                "todos": [
                    {
                        "id": item.id,
                        "tool": item.assigned_tool,
                        "status": item.status,
                        "error_type": (item.error or {}).get("error_type"),
                    }
                    for item in getattr(state, "todos", [])
                ],
            }
        )
