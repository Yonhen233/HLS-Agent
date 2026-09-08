from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.errors import build_error
from .base import BaseSpecialist
from .context import ContextEnvelope
from .result import SpecialistResult


class CodegenSpecialist(BaseSpecialist):
    """Generate HLS candidates without exposing the generator to the Main Agent.

    Candidate generation is intentionally separated from verification. This
    specialist may create an untrusted candidate, but it cannot mark it
    verified or write long-term memory.
    """

    name = "CodegenSpecialist"
    description = "Generates sandboxed LLM HLS candidates for an explicit operator contract."
    allowed_tools = [
        "llm.generate_candidate",
        "llm.generate_hls_candidate",
    ]

    def can_handle(self, todo) -> bool:
        tool = str(getattr(todo, "assigned_tool", None) or "")
        title = str(getattr(todo, "title", "") or "").lower()
        return tool in set(self.allowed_tools) or "llm candidate" in title or "candidate generation" in title

    def handle(self, envelope: ContextEnvelope, tool_registry, permission_gate) -> SpecialistResult:
        assigned_tool = str(envelope.task_summary.get("assigned_tool") or "llm.generate_candidate")
        if assigned_tool not in self.allowed_tools:
            error = build_error(
                "PermissionDeniedError",
                f"CodegenSpecialist received unsupported tool {assigned_tool}.",
                recoverable=False,
                source=f"{self.name}.handle",
                details={"allowed_tools": self.allowed_tools},
            ).to_dict()
            return self._finalize_result(
                envelope,
                SpecialistResult(
                    specialist_name=self.name,
                    todo_id=envelope.todo_id,
                    status="failed",
                    summary=error["message"],
                    errors=[error],
                ),
            )

        scoped = envelope.scoped_state
        task = dict(scoped.get("task") or {})
        todo_inputs = dict(scoped.get("todo_inputs") or {})
        generation_context = {
            "repair_attempt": todo_inputs.get("repair_attempt", 0),
            "repair_reason": todo_inputs.get("repair_reason"),
            "last_error": todo_inputs.get("last_error"),
            "previous_candidate_dir": scoped.get("previous_candidate_dir"),
            "last_report": todo_inputs.get("last_report"),
            "timing": todo_inputs.get("timing"),
            "instruction": todo_inputs.get(
                "instruction",
                "Generate a complete candidate while preserving the declared operator contract.",
            ),
        }
        task["candidate_generation_context"] = generation_context
        args = {
            "op_spec": task,
            "rag_context": list(scoped.get("rag_context") or envelope.retrieved_memory_refs),
            "output_dir": str(scoped.get("candidate_dir") or Path(scoped.get("run_dir", ".")) / "candidate"),
        }
        observations: list[dict[str, Any]] = []
        decision = self._local_react_step(envelope, observations, assigned_tool, args)
        if decision["decision"] == "mark_blocked":
            return self._finalize_result(envelope, self._blocked_result_from_decision(envelope, observations, decision))
        if decision["decision"] == "mark_failed":
            return self._finalize_result(envelope, self._failed_result_from_decision(envelope, observations, decision))
        if decision["decision"] == "finish_with_result":
            result = SpecialistResult(
                specialist_name=self.name,
                todo_id=envelope.todo_id,
                status="failed",
                summary=decision.get("reason_summary") or "Code generation did not produce a candidate.",
                observations=observations,
                errors=[
                    build_error(
                        "LLMGenerationError",
                        "CodegenSpecialist finished without generating a candidate.",
                        recoverable=True,
                        source=f"{self.name}.handle",
                    ).to_dict()
                ],
            )
            return self._finalize_result(envelope, result)

        action = decision.get("action") or {}
        tool_name = action.get("tool_name") or action.get("tool") or assigned_tool
        tool_args = action.get("arguments") or args
        result = self._call_tool(tool_name, tool_args, envelope, tool_registry, permission_gate)
        compressed = self._compress_result(result)
        observations.append({"tool": tool_name, "result": compressed})
        if result.get("status") == "candidate_generated":
            artifacts = []
            for path in result.get("files", []):
                suffix = Path(path).suffix.lower()
                artifact_type = "hls_header" if suffix in {".h", ".hpp"} else "hls_cpp" if suffix in {".c", ".cc", ".cpp"} else "candidate_artifact"
                artifacts.append({"type": artifact_type, "path": path})
            artifacts.append({"type": "candidate_dir", "path": tool_args["output_dir"]})
            specialist_result = SpecialistResult(
                specialist_name=self.name,
                todo_id=envelope.todo_id,
                status="success",
                summary="Generated a sandbox-checked LLM HLS candidate; verification is still required.",
                observations=observations,
                artifacts=artifacts,
                warnings=[{"message": "Candidate remains unverified until golden CSim and CSynth pass."}],
                suggested_todos=[
                    {
                        "title": "Verify LLM candidate",
                        "assigned_tool": "verify_candidate.run",
                        "assigned_specialist": "VerificationSpecialist",
                    }
                ],
                memory_candidates=[
                    {
                        "kind": "implementation",
                        "key": f"llm_candidate.{envelope.run_id}.{envelope.todo_id}",
                        "summary": "Generated an LLM HLS candidate pending independent verification.",
                        "value": {"status": "candidate", "files": result.get("files", [])},
                    }
                ],
            )
        else:
            error = result.get("error") or build_error(
                "LLMGenerationError",
                "LLM candidate generation failed.",
                recoverable=True,
                source="llm.generate_candidate",
            ).to_dict()
            specialist_result = SpecialistResult(
                specialist_name=self.name,
                todo_id=envelope.todo_id,
                status="failed",
                summary=error.get("message", "LLM candidate generation failed."),
                observations=observations,
                errors=[error],
            )
        return self._finalize_result(envelope, specialist_result)

    @staticmethod
    def _compress_result(result: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in result.items()
            if key not in {"stdout", "stderr", "raw_log", "content"}
        }
