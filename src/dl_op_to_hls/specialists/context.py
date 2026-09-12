"""specialists layer implementation for context.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..core.context_modes import ContextModeConfig
from ..core.token_budget import TokenBudgetManager


SPECIALIST_ALLOWED_TOOLS = {
    "CodegenSpecialist": [
        "llm.generate_candidate",
        "llm.generate_hls_candidate",
    ],
    "VivadoSpecialist": [
        "vivado.create_project",
        "vivado.create_vivado_project",
        "vivado.run_csim",
        "vivado.run_csynth",
        "vivado.parse_report",
        "vivado.parse_csynth_report",
        "vivado.parse_log",
        "vivado.parse_vivado_log",
    ],
    "VerificationSpecialist": [
        "verify.run_csim",
        "verify_candidate.run",
        "vivado.run_csynth",
        "vivado.parse_report",
    ],
    "OptimizationSpecialist": [
        "rag.retrieve_experience",
        "memory.retrieve_optimization_rules",
        "suggestion.suggest_optimization",
    ],
    "MemorySpecialist": [
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
    ],
}


@dataclass
class ContextEnvelope:
    """Coordinate ContextEnvelope within the context boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    run_id: str
    todo_id: str
    specialist_name: str
    task_summary: dict[str, Any]
    scoped_state: dict[str, Any]
    artifact_refs: list[dict[str, Any]]
    retrieved_memory_refs: list[dict[str, Any]]
    constraints: dict[str, Any]
    allowed_tools: list[str]
    max_context_tokens: int
    input_context_mode: str = "scoped"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Execute to_dict at the context boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Returns:
            The structured value promised by the function signature.
        """
        return asdict(self)


class ContextBuilder:
    """Coordinate ContextBuilder within the context boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    def __init__(
        self,
        token_budget_manager: TokenBudgetManager | None = None,
        mode_config: ContextModeConfig | None = None,
        skill_registry=None,
    ):
        """Implement the internal __init__ helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            token_budget_manager: Value supplied by the caller and validated by the surrounding schema.
            mode_config: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        self.token_budget_manager = token_budget_manager or TokenBudgetManager()
        self.mode_config = mode_config or ContextModeConfig.from_env()
        self.skill_registry = skill_registry

    def build_for_specialist(self, state, todo, specialist_name: str) -> ContextEnvelope:
        """Execute build_for_specialist at the context boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            state: Value supplied by the caller and validated by the surrounding schema.
            todo: Value supplied by the caller and validated by the surrounding schema.
            specialist_name: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        max_context_tokens = int(todo.context_scope.get("max_context_tokens", 3000) if todo.context_scope else 3000)
        task = state.task
        task_summary = {
            "task_type": task.get("task_type"),
            "name": task.get("name"),
            "op_type": task.get("op_type"),
            "frontend": task.get("frontend"),
            "objective": state.objective,
            "target": task.get("target", {}),
            "input_shape": task.get("input_shape"),
            "output_shape": task.get("output_shape"),
            "dtype": task.get("dtype") or (task.get("hls4ml") or {}).get("precision"),
            "top_function": task.get("top_function") or task.get("name"),
            "function_signature": (task.get("candidate_contract") or {}).get("signature"),
            "required_files": list((task.get("candidate_contract") or {}).get("required_files") or []),
            "verification_policy": {
                "mock_forbidden": True,
                "historical_report_forbidden": True,
                "success_requires_current_run_evidence": True,
            },
            "todo_title": todo.title,
            "assigned_tool": getattr(todo, "assigned_tool", None),
            "assigned_specialist": getattr(todo, "assigned_specialist", None),
            "todo_inputs": dict(getattr(todo, "inputs", None) or {}),
        }
        scoped_state = (
            self._full_state(state, todo, specialist_name)
            if self.mode_config.input_context_mode == "full"
            else self._scoped_state(state, todo, specialist_name)
        )
        if self.skill_registry is not None and getattr(state, "selected_skill", None):
            skill = self.skill_registry.get(state.selected_skill)
            guidance = skill.to_execution_guidance(specialist_name)
            if guidance:
                scoped_state["skill_guidance"] = guidance
        artifact_refs = (
            self._all_artifact_refs(state)
            if self.mode_config.input_context_mode == "full"
            else self._artifact_refs(state, specialist_name)
        )
        memory_refs = [
            {
                "source": item.get("source_run_id") or item.get("source") or item.get("id"),
                "summary": item.get("summary") or item.get("text", "")[:240],
                "memory_type": item.get("memory_type"),
            }
            for item in state.retrieved_memories[:5]
        ]
        envelope = ContextEnvelope(
            run_id=state.run_id,
            todo_id=todo.id,
            specialist_name=specialist_name,
            task_summary=task_summary,
            scoped_state=scoped_state,
            artifact_refs=artifact_refs,
            retrieved_memory_refs=memory_refs,
            constraints={
                "exclude": ["raw_logs", "full_trace", "all_memories", "full_hls_code", "raw_report"],
                "no_raw_artifact_content": True,
            },
            allowed_tools=SPECIALIST_ALLOWED_TOOLS.get(specialist_name, []),
            max_context_tokens=max_context_tokens,
            input_context_mode=self.mode_config.input_context_mode,
            notes=[
                "Artifact refs are paths and metadata only; raw logs, reports, code, and trace content stay outside the envelope."
            ],
        )
        if self.mode_config.input_context_mode == "scoped":
            self.token_budget_manager.enforce_envelope_budget(envelope)
        else:
            envelope.constraints["token_budget"] = {
                "estimated_input_tokens_before": self.token_budget_manager.estimate_tokens(envelope.to_dict()),
                "estimated_input_tokens": self.token_budget_manager.estimate_tokens(envelope.to_dict()),
                "max_context_tokens": max_context_tokens,
                "truncated": False,
                "truncation_steps": [],
                "overflow_policy": "record_without_truncation",
            }
        return envelope

    def _full_state(self, state, todo, specialist_name: str) -> dict[str, Any]:
        """Implement the internal _full_state helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            state: Value supplied by the caller and validated by the surrounding schema.
            todo: Value supplied by the caller and validated by the surrounding schema.
            specialist_name: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        payload = state.to_dict() if hasattr(state, "to_dict") else asdict(state)
        return {
            **self._scoped_state(state, todo, specialist_name),
            "agent_state": payload,
            "current_todo": todo.to_dict() if hasattr(todo, "to_dict") else asdict(todo),
        }

    def _all_artifact_refs(self, state) -> list[dict[str, Any]]:
        """Implement the internal _all_artifact_refs helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            state: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        return [
            self._artifact_ref(artifact_type, path)
            for artifact_type, path in state.artifacts.items()
            if path
        ]

    def _scoped_state(self, state, todo, specialist_name: str) -> dict[str, Any]:
        """Implement the internal _scoped_state helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            state: Value supplied by the caller and validated by the surrounding schema.
            todo: Value supplied by the caller and validated by the surrounding schema.
            specialist_name: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        task = state.task
        target = task.get("target", {})
        hls4ml_cfg = task.get("hls4ml", {})
        if specialist_name == "CodegenSpecialist":
            return {
                "task": task,
                "assigned_tool": getattr(todo, "assigned_tool", None),
                "run_dir": str(self._run_dir_from_state(state)),
                "candidate_dir": str(self._run_dir_from_state(state) + "/candidate"),
                "previous_candidate_dir": state.hls_project_dir,
                "rag_context": [
                    {
                        "source": item.get("source_run_id") or item.get("source") or item.get("id"),
                        "summary": item.get("summary") or item.get("text", "")[:240],
                        "text": item.get("text", "")[:400],
                        "memory_type": item.get("memory_type"),
                    }
                    for item in state.retrieved_memories[:5]
                ],
                "todo_inputs": dict(getattr(todo, "inputs", None) or {}),
            }
        if specialist_name == "VivadoSpecialist":
            return {
                "hls_project_dir": state.hls_project_dir,
                "top_function": task.get("top_function") or task.get("name"),
                "part": target.get("part"),
                "clock_period": target.get("clock_period"),
                "array_partition_maximum_size": hls4ml_cfg.get("array_partition_maximum_size"),
                "work_dir": state.vivado_work_dir,
                "current_report": state.report,
            }
        if specialist_name == "VerificationSpecialist":
            return {
                "candidate_dir": state.hls_project_dir,
                "candidate_file_refs": self._artifact_refs(state, specialist_name),
                "tolerance": task.get("tolerance", 0.0),
                "max_repair_attempts": task.get("max_repair_attempts", 2),
                "force_fail": bool(task.get("force_fail")),
                "top_function": task.get("top_function") or task.get("name"),
                "part": target.get("part"),
                "clock_period": target.get("clock_period"),
                "candidate_contract": dict(task.get("candidate_contract") or {}),
                "todo_inputs": dict(getattr(todo, "inputs", None) or {}),
            }
        if specialist_name == "OptimizationSpecialist":
            return {
                "report": state.report,
                "objective": state.objective,
                "selected_path": state.selected_path,
                "rag_context": state.rag_context[:5],
                "state_summary": {
                    "run_id": state.run_id,
                    "task": task,
                    "objective": state.objective,
                    "selected_path": state.selected_path,
                    "report": state.report,
                    "suggestions": state.suggestions,
                },
            }
        if specialist_name == "MemorySpecialist":
            return {
                "summary_ref": state.artifacts.get("summary"),
                "suggestions_ref": state.artifacts.get("suggestions"),
                "compressed_context_ref": state.artifacts.get("compressed_context"),
                "report": state.report,
                "errors": state.errors[-5:],
                "memory_candidates": state.memory_candidates,
                "promoted_memories": state.promoted_memories,
                "todo_inputs": dict(getattr(todo, "inputs", None) or {}),
            }
        return {"task": task}

    def _artifact_refs(self, state, specialist_name: str) -> list[dict[str, Any]]:
        """Implement the internal _artifact_refs helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            state: Value supplied by the caller and validated by the surrounding schema.
            specialist_name: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        refs: list[dict[str, Any]] = []
        for artifact_type, path in state.artifacts.items():
            if not path:
                continue
            if self._artifact_relevant(artifact_type, specialist_name):
                refs.append(self._artifact_ref(artifact_type, path))
        return refs

    @staticmethod
    def _artifact_ref(artifact_type: str, value: Any) -> dict[str, Any]:
        """Implement the internal _artifact_ref helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            artifact_type: Value supplied by the caller and validated by the surrounding schema.
            value: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        path = Path(str(value)).resolve()
        digest = None
        if path.is_file():
            sha = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    sha.update(chunk)
            digest = sha.hexdigest()
        return {
            "type": artifact_type,
            "path": str(path),
            "exists": path.exists(),
            "sha256": digest,
        }

    def _artifact_relevant(self, artifact_type: str, specialist_name: str) -> bool:
        """Implement the internal _artifact_relevant helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            artifact_type: Value supplied by the caller and validated by the surrounding schema.
            specialist_name: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        relevant = {
            "CodegenSpecialist": {"input_task", "normalized_task", "summary", "suggestions", "report_json", "vivado_log", "vivado_report", "repair_evidence", "compressed_logs", "hls_cpp", "hls_header", "testbench"},
            "VivadoSpecialist": {"hls_project", "tcl", "vivado_log", "vivado_report", "report_json", "compressed_logs"},
            "VerificationSpecialist": {"hls_cpp", "hls_header", "testbench", "tcl", "vivado_log", "repair_evidence", "report_json"},
            "OptimizationSpecialist": {"report_json", "summary", "suggestions"},
            "MemorySpecialist": {"summary", "suggestions", "compressed_context", "report_json", "unsupported_report"},
        }
        allowed = relevant.get(specialist_name)
        return allowed is None or artifact_type in allowed

    def _run_dir_from_state(self, state) -> str:
        """Implement the internal _run_dir_from_state helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            state: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        if state.artifacts.get("run_dir"):
            return str(state.artifacts["run_dir"])
        trace_path = state.artifacts.get("trace")
        if trace_path:
            return str(trace_path).rsplit("\\", 1)[0].rsplit("/", 1)[0]
        return f"runs/{state.run_id}"
