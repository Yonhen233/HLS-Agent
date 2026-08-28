from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import BaseSpecialist
from .context import ContextEnvelope
from .result import SpecialistResult


class VerificationSpecialist(BaseSpecialist):
    name = "VerificationSpecialist"
    description = "Verifies generated HLS candidates through explicit mock or real Vivado-backed verification modes."
    allowed_tools = [
        "fallback.generate_testbench",
        "verify.generate_testbench",
        "verify.run_csim",
        "verify_candidate.run",
        "vivado.run_csynth",
        "vivado.parse_report",
    ]

    def can_handle(self, todo) -> bool:
        return bool(todo.assigned_tool and todo.assigned_tool.startswith("verify"))

    def handle(self, envelope: ContextEnvelope, tool_registry, permission_gate) -> SpecialistResult:
        scoped = envelope.scoped_state
        run_dir = Path(self.runtime_context.get("run_dir", "."))
        observations: list[dict[str, Any]] = []
        args = {
            "candidate_dir": scoped.get("candidate_dir"),
            "report_dir": str(run_dir / "reports"),
            "force_fail": bool(scoped.get("force_fail")),
            "top_function": scoped.get("top_function"),
            "part": scoped.get("part"),
            "clock_period": scoped.get("clock_period"),
            "candidate_contract": scoped.get("candidate_contract") or {},
            "tolerance": scoped.get("tolerance", 0.0),
        }
        args.update({key: value for key, value in (scoped.get("todo_inputs") or {}).items() if value is not None})
        decision = self._local_react_step(envelope, observations, "verify_candidate.run", args)
        if decision["decision"] == "mark_blocked":
            return self._finalize_result(envelope, self._blocked_result_from_decision(envelope, observations, decision))
        if decision["decision"] == "mark_failed":
            return self._finalize_result(envelope, self._failed_result_from_decision(envelope, observations, decision))
        action = decision.get("action") or {}
        result = self._call_tool(
            action.get("tool_name") or action.get("tool") or "verify_candidate.run",
            action.get("arguments") or args,
            envelope,
            tool_registry,
            permission_gate,
        )
        status = "success" if result.get("status") == "verified" else "failed"
        errors = [result["error"]] if result.get("error") else []
        metrics = result.get("csim") if result.get("csim") else None
        memory_candidates = []
        if status == "success":
            memory_candidates.append(
                {
                    "kind": "implementation",
                    "key": f"implementation.{envelope.run_id}.{envelope.todo_id}",
                    "summary": "Candidate passed verification.",
                    "value": {"candidate_dir": scoped.get("candidate_dir"), "verification": result},
                }
            )
        specialist_result = SpecialistResult(
            specialist_name=self.name,
            todo_id=envelope.todo_id,
            status=status,
            summary="Candidate passed configured verification." if status == "success" else "Candidate verification failed.",
            observations=[*observations, {"tool": "verify_candidate.run", "result": result}],
            metrics=metrics,
            errors=errors,
            memory_candidates=memory_candidates,
        )
        return self._finalize_result(envelope, specialist_result)
