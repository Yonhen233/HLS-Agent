from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from ..core.token_budget import TokenBudgetManager


SPECIALIST_ALLOWED_TOOLS = {
    "HLS4MLSpecialist": [
        "hls4ml.inspect_model",
        "hls4ml.check_support",
        "hls4ml.check_hls4ml_support",
        "hls4ml.generate_config",
        "hls4ml.generate_hls4ml_config",
        "hls4ml.convert",
        "hls4ml.convert_with_hls4ml",
        "hls4ml.run_csim",
        "hls4ml.run_hls4ml_csim",
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
        "fallback.generate_testbench",
        "verify.generate_testbench",
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
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ContextBuilder:
    def __init__(self, token_budget_manager: TokenBudgetManager | None = None):
        self.token_budget_manager = token_budget_manager or TokenBudgetManager()

    def build_for_specialist(self, state, todo, specialist_name: str) -> ContextEnvelope:
        max_context_tokens = int(todo.context_scope.get("max_context_tokens", 3000) if todo.context_scope else 3000)
        task = state.task
        task_summary = {
            "task_type": task.get("task_type"),
            "name": task.get("name"),
            "op_type": task.get("op_type"),
            "frontend": task.get("frontend"),
            "objective": state.objective,
            "target": task.get("target", {}),
            "todo_title": todo.title,
            "assigned_tool": getattr(todo, "assigned_tool", None),
            "assigned_specialist": getattr(todo, "assigned_specialist", None),
        }
        scoped_state = self._scoped_state(state, todo, specialist_name)
        artifact_refs = self._artifact_refs(state, specialist_name)
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
            notes=[
                "Artifact refs are paths and metadata only; raw logs, reports, code, and trace content stay outside the envelope."
            ],
        )
        self.token_budget_manager.enforce_envelope_budget(envelope)
        return envelope

    def _scoped_state(self, state, todo, specialist_name: str) -> dict[str, Any]:
        task = state.task
        target = task.get("target", {})
        if specialist_name == "HLS4MLSpecialist":
            hls4ml_cfg = task.get("hls4ml", {})
            support = state.hls4ml_support
            if support and support.get("model_path") and support.get("model_path") != task.get("model_path"):
                support = None
            if support and not support.get("model_path") and task.get("original_model_path"):
                support = None
            return {
                "task": task,
                "assigned_tool": getattr(todo, "assigned_tool", None),
                "model_path": task.get("model_path"),
                "frontend": task.get("frontend"),
                "backend": target.get("backend"),
                "part": target.get("part"),
                "clock_period": target.get("clock_period"),
                "precision": hls4ml_cfg.get("precision"),
                "reuse_factor": hls4ml_cfg.get("reuse_factor"),
                "strategy": hls4ml_cfg.get("strategy"),
                "hls4ml_support": support,
                "hls4ml_config_path": state.hls4ml_config_path,
                "hls_project_dir": state.hls_project_dir,
                "run_dir": str(self._run_dir_from_state(state)),
            }
        if specialist_name == "VivadoSpecialist":
            return {
                "hls_project_dir": state.hls_project_dir,
                "top_function": task.get("top_function") or task.get("name"),
                "part": target.get("part"),
                "clock_period": target.get("clock_period"),
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
            }
        return {"task": task}

    def _artifact_refs(self, state, specialist_name: str) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        for artifact_type, path in state.artifacts.items():
            if not path:
                continue
            if self._artifact_relevant(artifact_type, specialist_name):
                refs.append({"type": artifact_type, "path": str(path)})
        return refs

    def _artifact_relevant(self, artifact_type: str, specialist_name: str) -> bool:
        relevant = {
            "HLS4MLSpecialist": {"input_task", "normalized_task", "hls4ml_config"},
            "VivadoSpecialist": {"hls_project", "tcl", "vivado_log", "vivado_report", "report_json", "compressed_logs"},
            "VerificationSpecialist": {"hls_cpp", "hls_header", "testbench", "tcl", "report_json"},
            "OptimizationSpecialist": {"report_json", "summary", "suggestions"},
            "MemorySpecialist": {"summary", "suggestions", "compressed_context", "report_json", "unsupported_report"},
        }
        allowed = relevant.get(specialist_name)
        return allowed is None or artifact_type in allowed

    def _run_dir_from_state(self, state) -> str:
        if state.artifacts.get("run_dir"):
            return str(state.artifacts["run_dir"])
        trace_path = state.artifacts.get("trace")
        if trace_path:
            return str(trace_path).rsplit("\\", 1)[0].rsplit("/", 1)[0]
        return f"runs/{state.run_id}"
