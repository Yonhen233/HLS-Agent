from __future__ import annotations

from typing import Any

from .base import BaseSpecialist
from .context import ContextEnvelope
from .result import SpecialistResult


class OptimizationSpecialist(BaseSpecialist):
    name = "OptimizationSpecialist"
    description = "Generates latency/resource/timing suggestions from metrics and scoped memory summaries."
    allowed_tools = [
        "rag.retrieve_experience",
        "memory.retrieve_optimization_rules",
        "suggestion.suggest_optimization",
    ]

    def can_handle(self, todo) -> bool:
        return bool(todo.assigned_tool and todo.assigned_tool.startswith("suggestion."))

    def handle(self, envelope: ContextEnvelope, tool_registry, permission_gate) -> SpecialistResult:
        scoped = envelope.scoped_state
        observations: list[dict[str, Any]] = []
        query = f"{envelope.task_summary.get('name')} {envelope.task_summary.get('op_type') or ''} {scoped.get('objective')} optimization"
        memory_args = {"query": query, "top_k": 5}
        memory_decision = self._local_react_step(
            envelope,
            observations,
            "memory.retrieve_optimization_rules",
            memory_args,
            force_deterministic=True,
        )
        if memory_decision["decision"] == "mark_blocked":
            return self._finalize_result(envelope, self._blocked_result_from_decision(envelope, observations, memory_decision))
        if memory_decision["decision"] == "mark_failed":
            return self._finalize_result(envelope, self._failed_result_from_decision(envelope, observations, memory_decision))
        memory_action = memory_decision.get("action") or {}
        memory_result = self._call_tool(
            memory_action.get("tool_name") or memory_action.get("tool") or "memory.retrieve_optimization_rules",
            memory_action.get("arguments") or memory_args,
            envelope,
            tool_registry,
            permission_gate,
        )
        rag_context = scoped.get("rag_context") or []
        for item in memory_result.get("results", [])[:3]:
            rag_context.append({"summary": item.get("text", "")[:200], "source": item.get("source_run_id"), "text": item.get("text", "")})
        suggest_args = {
            "state": scoped.get("state_summary", {}),
            "report": scoped.get("report") or {},
            "rag_context": rag_context,
            "objective": scoped.get("objective"),
        }
        suggest_decision = self._local_react_step(
            envelope,
            observations,
            "suggestion.suggest_optimization",
            suggest_args,
            force_deterministic=True,
        )
        if suggest_decision["decision"] == "mark_blocked":
            return self._finalize_result(envelope, self._blocked_result_from_decision(envelope, observations, suggest_decision))
        if suggest_decision["decision"] == "mark_failed":
            return self._finalize_result(envelope, self._failed_result_from_decision(envelope, observations, suggest_decision))
        suggest_action = suggest_decision.get("action") or {}
        suggest_result = self._call_tool(
            suggest_action.get("tool_name") or suggest_action.get("tool") or "suggestion.suggest_optimization",
            suggest_action.get("arguments") or suggest_args,
            envelope,
            tool_registry,
            permission_gate,
        )
        artifacts = []
        if suggest_result.get("path"):
            artifacts.append({"type": "suggestions", "path": suggest_result["path"]})
        memory_candidates = [
            {
                "kind": "optimization",
                "key": f"optimization.{envelope.run_id}.{envelope.todo_id}",
                "summary": "Optimization suggestions were generated from current metrics and scoped memory.",
                "value": {"suggestions": suggest_result.get("suggestions", []), "objective": scoped.get("objective")},
            }
        ]
        result_status = suggest_result.get("status")
        specialist_status = "success" if result_status == "success" else "skipped" if result_status == "skipped" else "failed"
        specialist_result = SpecialistResult(
            specialist_name=self.name,
            todo_id=envelope.todo_id,
            status=specialist_status,
            summary=(
                suggest_result.get("reason")
                if result_status == "skipped"
                else "Generated optimization suggestions based on current metrics and retrieved memories."
            ),
            observations=[
                *observations,
                {"tool": "memory.retrieve_optimization_rules", "result": self._compress_result(memory_result)},
                {"tool": "suggestion.suggest_optimization", "result": self._compress_result(suggest_result)},
            ],
            metrics={"suggestions": suggest_result.get("suggestions", [])},
            artifacts=artifacts,
            errors=[suggest_result["error"]] if suggest_result.get("error") else [],
            memory_candidates=memory_candidates,
        )
        return self._finalize_result(envelope, specialist_result)

    def _compress_result(self, result: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in result.items() if key not in {"markdown", "stdout", "stderr", "raw_log"}}
