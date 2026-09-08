from __future__ import annotations

import json

from ..core.errors import build_error
from ..llm import prompts
from ..llm.schemas import MEMORY_EXPERIENCE_SELECTION_SCHEMA
from .base import BaseSpecialist
from .context import ContextEnvelope
from .result import SpecialistResult


class MemorySpecialist(BaseSpecialist):
    name = "MemorySpecialist"
    description = "Compresses run context and promotes approved memories into SQLite and RAG-backed retrieval."
    allowed_tools = [
        "trace.query",
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
        trace_decision = self._local_react_step(
            envelope,
            observations,
            "trace.query",
            {"run_id": envelope.run_id, "view": "memory_context", "max_items": 12},
            force_deterministic=True,
        )
        if trace_decision["decision"] in {"mark_blocked", "mark_failed"}:
            return self._finalize_result(envelope, self._failed_result_from_decision(envelope, observations, trace_decision))
        trace_action = trace_decision.get("action") or {}
        trace_package = self._call_tool(
            trace_action.get("tool_name") or trace_action.get("tool") or "trace.query",
            trace_action.get("arguments") or {"run_id": envelope.run_id, "view": "memory_context", "max_items": 12},
            envelope,
            tool_registry,
            permission_gate,
        )
        observations.append({"tool": "trace.query", "result": self._compress_result(trace_package)})
        if trace_package.get("status") != "success":
            error = trace_package.get("error") or build_error(
                "TraceReadError",
                "MemorySpecialist could not read the bounded decision ledger projection.",
                recoverable=True,
                source="MemorySpecialist.trace.query",
            ).to_dict()
            return self._finalize_result(
                envelope,
                SpecialistResult(
                    specialist_name=self.name,
                    todo_id=envelope.todo_id,
                    status="failed",
                    summary="Memory promotion stopped because decision evidence was unavailable.",
                    observations=observations,
                    errors=[error],
                ),
            )
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
        candidates, llm_summary_error = self._summarize_candidates_with_llm(
            envelope,
            candidates,
            trace_package,
            observations,
        )
        if llm_summary_error is not None:
            return self._finalize_result(
                envelope,
                SpecialistResult(
                    specialist_name=self.name,
                    todo_id=envelope.todo_id,
                    status="failed",
                    summary="Memory promotion stopped because the LLM experience summary failed validation.",
                    observations=observations,
                    errors=[llm_summary_error],
                ),
            )
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
                # Promotion already persisted the full evidence-backed records
                # to SQLite/RAG. Return only a bounded projection to Main Agent.
                "memory_candidates": [self._compact_candidate(item) for item in candidates],
                "promoted_memories": promoted.get("promoted_memories", []),
            },
            artifacts=artifacts,
            errors=[promoted["error"]] if promoted.get("error") else [],
        )
        return self._finalize_result(envelope, specialist_result)

    def _summarize_candidates_with_llm(self, envelope, candidates, trace_package, observations):
        """Let the configured LLM select and word experience, never evidence."""
        client = self.runtime_context.get("llm_client")
        configured = self.runtime_context.get("memory_llm_summarization_enabled")
        if configured is None:
            provider = str(getattr(getattr(client, "config", None), "provider", "") or "").lower()
            configured = provider != "fake"
        if client is None or not client.is_enabled() or not configured:
            observations.append({"type": "memory_summary", "mode": "deterministic_candidates", "selected_count": len(candidates)})
            return candidates, None

        candidate_views = []
        for index, candidate in enumerate(candidates[:16]):
            candidate_views.append(
                {
                    "source_index": index,
                    "kind": str(candidate.get("kind") or "")[:80],
                    "key": str(candidate.get("key") or "")[:160],
                    "summary": str(candidate.get("summary") or "")[:600],
                    "fact": str(candidate.get("fact") or "")[:600],
                    "domain": str(candidate.get("domain") or "")[:80],
                }
            )
        evidence = {
            "decision_ledger": trace_package.get("decision_ledger", [])[-12:],
            "todo_history": trace_package.get("todo_history", [])[-8:],
            "failures": trace_package.get("failures", [])[-8:],
            "evidence": trace_package.get("evidence", [])[-8:],
        }
        prompt_payload = {
            "run_id": envelope.run_id,
            "task_summary": {
                key: envelope.task_summary.get(key)
                for key in ("task_type", "op_type", "name", "objective", "input_shape", "output_shape", "dtype")
                if envelope.task_summary.get(key) is not None
            },
            "candidates": candidate_views,
            "evidence": evidence,
            "rules": [
                "Select only candidates by source_index.",
                "Do not invent metrics or outcomes.",
                "Return at most 8 durable design experiences.",
                "Discard routine execution noise.",
            ],
        }
        try:
            response = client.complete_json(
                prompts.resolve_prompt(self.runtime_context, "memory_extractor"),
                json.dumps(prompt_payload, ensure_ascii=False, default=str),
                MEMORY_EXPERIENCE_SELECTION_SCHEMA,
                temperature=0.0,
            )
            selected = response.get("selected_candidates", [])
            refined = []
            for item in selected:
                if not isinstance(item, dict) or not isinstance(item.get("source_index"), int):
                    continue
                index = item["source_index"]
                if index < 0 or index >= len(candidates):
                    continue
                source = dict(candidates[index])
                if item.get("summary"):
                    source["summary"] = str(item["summary"])[:1200]
                if item.get("fact"):
                    source["fact"] = str(item["fact"])[:1200]
                if item.get("title"):
                    source["title"] = str(item["title"])[:240]
                source["llm_selected"] = True
                ledger = evidence["decision_ledger"]
                decision_indexes = [
                    value
                    for value in item.get("decision_indexes", [])
                    if isinstance(value, int) and 0 <= value < len(ledger)
                ]
                source["decision_evidence"] = {
                    "source": trace_package.get("source_path"),
                    "source_of_truth": trace_package.get("source_of_truth"),
                    "records": [ledger[value] for value in decision_indexes[:8]],
                }
                refined.append(source)
            observations.append(
                {
                    "type": "memory_summary",
                    "mode": "llm",
                    "summary": str(response.get("summary") or "")[:1200],
                    "candidate_count_before": len(candidates),
                    "selected_count": len(refined),
                }
            )
            return refined, None
        except Exception as exc:
            error = getattr(exc, "error", None)
            if error is not None and hasattr(error, "to_dict"):
                error = error.to_dict()
            else:
                error = build_error(
                    "LLMGenerationError",
                    str(exc),
                    recoverable=True,
                    source="MemorySpecialist.memory_extractor",
                    suggested_action="Fix the LLM response schema or retry memory extraction.",
                ).to_dict()
            return [], error

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
        if result.get("view") == "memory_context":
            return {
                "status": result.get("status"),
                "view": result.get("view"),
                "source_of_truth": result.get("source_of_truth"),
                "source_path": result.get("source_path"),
                "decision_ledger": list(result.get("decision_ledger", [])[-12:]),
                "todo_history": list(result.get("todo_history", [])[-8:]),
                "failures": list(result.get("failures", [])[-8:]),
                "evidence": list(result.get("evidence", [])[-8:]),
            }
        return {key: value for key, value in result.items() if key not in {"short_term", "compressed_context"}}

    @staticmethod
    def _compact_candidate(candidate: dict) -> dict:
        """Return a bounded Main-Agent projection after full promotion is persisted."""
        compact = {
            key: candidate.get(key)
            for key in ("kind", "key", "summary", "fact", "title", "domain", "llm_selected")
            if candidate.get(key) is not None
        }
        evidence = candidate.get("decision_evidence")
        if isinstance(evidence, dict):
            compact["decision_evidence"] = {
                "source": evidence.get("source"),
                "source_of_truth": evidence.get("source_of_truth"),
                "record_count": len(evidence.get("records") or []),
            }
        return compact
