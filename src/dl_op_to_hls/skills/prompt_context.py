"""skills layer implementation for prompt_context.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

from .registry import SkillRegistry


class SkillPromptContextBuilder:
    """Coordinate SkillPromptContextBuilder within the prompt_context boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    def build(self, task: dict, registry: SkillRegistry, top_k: int = 5) -> dict:
        """Execute build at the prompt_context boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            task: Value supplied by the caller and validated by the surrounding schema.
            registry: Value supplied by the caller and validated by the surrounding schema.
            top_k: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        candidates = registry.find_candidates(task)[:top_k]
        llm_candidate_cfg = task.get("llm_candidate") if isinstance(task.get("llm_candidate"), dict) else {}
        forced_llm_candidate = bool(llm_candidate_cfg.get("required"))
        capability_boundary = isinstance(task.get("capability_boundary"), dict)
        if capability_boundary:
            candidates = []
        if forced_llm_candidate and not capability_boundary:
            candidates = [skill for skill in candidates if skill.name == "llm_candidate_verification_flow"]
            if not candidates:
                candidates = [registry.get("llm_candidate_verification_flow")]
        selection_notes = [
            "Skills are playbook priors, not strict deterministic plans.",
            "Use each selected skill's purpose, procedure, decision_rules, pitfalls, and verification_guidance as execution guidance; never bypass its structured contract.",
            "LLM may adapt or reorder recommended_todos under guardrails.",
            "For initial model-to-HLS tasks, choose the end-to-end hls4ml_model_flow even when the objective is resource or latency.",
            "Optimization-only skills require existing report metrics and must not replace conversion/synthesis steps.",
            "Do not plan hls4ml.run_csim for real toolchains; real csim/csynth is delegated to VivadoSpecialist through the configured HLS toolchain.",
        ]
        if forced_llm_candidate:
            selection_notes.insert(
                0,
                "This task sets llm_candidate.required=true; choose llm_candidate_verification_flow and do not route back to fallback_template or hls4ml flow.",
            )
        if capability_boundary:
            selection_notes.insert(
                0,
                "The runtime capability gate owns this terminal outcome; do not select a Skill or call LLM candidate or Vivado tools. A boundary is not an implementation path.",
            )
        return {
            "available_skills": [skill.to_catalog_summary() for skill in candidates],
            "selection_notes": selection_notes,
        }
