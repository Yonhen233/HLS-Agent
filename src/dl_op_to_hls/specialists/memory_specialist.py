from __future__ import annotations

from .base import BaseSpecialist
from .context import ContextEnvelope
from .result import SpecialistResult


class MemorySpecialist(BaseSpecialist):
    name = "MemorySpecialist"
    description = "Compresses run context and promotes approved memories into SQLite and RAG-backed retrieval."
    allowed_tools = [
        "memory.write_short_term",
        "memory.compress_run_context",
        "memory.extract_memory_candidates",
        "memory.promote_to_long_term",
        "memory.retrieve_similar_experiences",
        "memory.retrieve_failure_cases",
        "memory.retrieve_optimization_rules",
        "memory.save_skill",
        "rag.index_artifact",
    ]

    def can_handle(self, todo) -> bool:
        return bool(todo.assigned_tool and todo.assigned_tool.startswith("memory."))

    def handle(self, envelope: ContextEnvelope, tool_registry, permission_gate) -> SpecialistResult:
        assigned_tool = str(envelope.task_summary.get("assigned_tool") or "")
        if assigned_tool != "memory.promote_to_long_term":
            return self._handle_atomic(envelope, assigned_tool, tool_registry, permission_gate)

        observations = []
        compress_args = {"run_id": envelope.run_id}
        compress_decision = self._local_react_step(
            envelope,
            observations,
            "memory.compress_run_context",
            compress_args,
            force_deterministic=True,
        )
        if compress_decision["decision"] == "mark_blocked":
            return self._finalize_result(envelope, self._blocked_result_from_decision(envelope, observations, compress_decision))
        if compress_decision["decision"] == "mark_failed":
            return self._finalize_result(envelope, self._failed_result_from_decision(envelope, observations, compress_decision))
        compress_action = compress_decision.get("action") or {}
        compressed = self._call_tool(
            compress_action.get("tool_name") or compress_action.get("tool") or "memory.compress_run_context",
            compress_action.get("arguments") or compress_args,
            envelope,
            tool_registry,
            permission_gate,
        )
        observations.append({"tool": "memory.compress_run_context", "result": compressed})
        extract_args = {"run_id": envelope.run_id}
        extract_decision = self._local_react_step(
            envelope,
            observations,
            "memory.extract_memory_candidates",
            extract_args,
            force_deterministic=True,
        )
        if extract_decision["decision"] == "mark_blocked":
            return self._finalize_result(envelope, self._blocked_result_from_decision(envelope, observations, extract_decision))
        if extract_decision["decision"] == "mark_failed":
            return self._finalize_result(envelope, self._failed_result_from_decision(envelope, observations, extract_decision))
        extract_action = extract_decision.get("action") or {}
        extracted = self._call_tool(
            extract_action.get("tool_name") or extract_action.get("tool") or "memory.extract_memory_candidates",
            extract_action.get("arguments") or extract_args,
            envelope,
            tool_registry,
            permission_gate,
        )
        observations.append({"tool": "memory.extract_memory_candidates", "result": self._compress_result(extracted)})
        candidates = extracted.get("candidates", [])
        promote_args = {"run_id": envelope.run_id, "candidates": candidates}
        promote_decision = self._local_react_step(
            envelope,
            observations,
            "memory.promote_to_long_term",
            promote_args,
            force_deterministic=True,
        )
        if promote_decision["decision"] == "mark_blocked":
            return self._finalize_result(envelope, self._blocked_result_from_decision(envelope, observations, promote_decision))
        if promote_decision["decision"] == "mark_failed":
            return self._finalize_result(envelope, self._failed_result_from_decision(envelope, observations, promote_decision))
        promote_action = promote_decision.get("action") or {}
        promoted = self._call_tool(
            promote_action.get("tool_name") or promote_action.get("tool") or "memory.promote_to_long_term",
            promote_action.get("arguments") or promote_args,
            envelope,
            tool_registry,
            permission_gate,
        )
        observations.append({"tool": "memory.promote_to_long_term", "result": self._compress_result(promoted)})
        artifacts = []
        for item_type, result in [
            ("compressed_context", compressed),
            ("memory_candidates", extracted),
            ("promoted_memories", promoted),
        ]:
            if result.get("path"):
                artifacts.append({"type": item_type, "path": result["path"]})
        status = "success" if promoted.get("status") == "success" else "failed"
        count = len(promoted.get("promoted_memories", []))
        specialist_result = SpecialistResult(
            specialist_name=self.name,
            todo_id=envelope.todo_id,
            status=status,
            summary=f"Promoted {count} long-term memories and refreshed compressed run context.",
            observations=observations,
            metrics={
                "memory_candidates": candidates,
                "promoted_memories": promoted.get("promoted_memories", []),
            },
            artifacts=artifacts,
            errors=[promoted["error"]] if promoted.get("error") else [],
        )
        return self._finalize_result(envelope, specialist_result)

    def _handle_atomic(self, envelope, assigned_tool, tool_registry, permission_gate) -> SpecialistResult:
        observations = []
        if assigned_tool not in self.allowed_tools or not assigned_tool.startswith(("memory.", "rag.")):
            return self._finalize_result(
                envelope,
                self._failed_result_from_decision(
                    envelope,
                    observations,
                    {
                        "reason_summary": "MemorySpecialist received an unsupported atomic assignment.",
                        "action": {"error_type": "PermissionDeniedError", "tool_name": assigned_tool},
                    },
                ),
            )
        arguments = dict(envelope.scoped_state.get("todo_inputs") or {})
        if assigned_tool.startswith("memory.retrieve_"):
            arguments.setdefault(
                "query",
                " ".join(
                    str(value)
                    for value in (
                        envelope.task_summary.get("op_type"),
                        envelope.task_summary.get("name"),
                        envelope.task_summary.get("objective"),
                    )
                    if value
                ),
            )
            arguments.setdefault("top_k", 5)
        elif assigned_tool in {"memory.compress_run_context", "memory.extract_memory_candidates"}:
            arguments.setdefault("run_id", envelope.run_id)
        decision = self._local_react_step(
            envelope,
            observations,
            assigned_tool,
            arguments,
            force_deterministic=True,
        )
        if decision["decision"] == "mark_blocked":
            return self._finalize_result(envelope, self._blocked_result_from_decision(envelope, observations, decision))
        if decision["decision"] == "mark_failed":
            return self._finalize_result(envelope, self._failed_result_from_decision(envelope, observations, decision))
        action = decision.get("action") or {}
        result = self._call_tool(
            action.get("tool_name") or action.get("tool") or assigned_tool,
            action.get("arguments") or arguments,
            envelope,
            tool_registry,
            permission_gate,
        )
        observations.append({"tool": assigned_tool, "result": self._compress_result(result)})
        error = result.get("error")
        count = len(result.get("results", [])) if isinstance(result.get("results"), list) else None
        summary = f"Executed scoped memory tool {assigned_tool}."
        if count is not None:
            summary = f"Retrieved {count} scoped memory result(s) with {assigned_tool}."
        specialist_result = SpecialistResult(
            specialist_name=self.name,
            todo_id=envelope.todo_id,
            status="success" if result.get("status") == "success" else "failed",
            summary=summary,
            observations=observations,
            metrics={"results": result.get("results", [])} if count is not None else None,
            errors=[error] if error else [],
        )
        return self._finalize_result(envelope, specialist_result)

    def _compress_result(self, result: dict) -> dict:
        return {key: value for key, value in result.items() if key not in {"short_term", "compressed_context"}}
