from __future__ import annotations

from .registry import SkillRegistry


class SkillPromptContextBuilder:
    def build(self, task: dict, registry: SkillRegistry, top_k: int = 5) -> dict:
        candidates = registry.find_candidates(task)[:top_k]
        llm_candidate_cfg = task.get("llm_candidate") if isinstance(task.get("llm_candidate"), dict) else {}
        forced_llm_candidate = bool(llm_candidate_cfg.get("required"))
        if forced_llm_candidate:
            candidates = [skill for skill in candidates if skill.name == "llm_candidate_verification_flow"]
            if not candidates:
                candidates = [registry.get("llm_candidate_verification_flow")]
        selection_notes = [
            "Skills are playbook priors, not strict deterministic plans.",
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
        return {
            "available_skills": [skill.to_prompt_summary() for skill in candidates],
            "selection_notes": selection_notes,
        }
