from __future__ import annotations

from .registry import SkillRegistry


class SkillPromptContextBuilder:
    def build(self, task: dict, registry: SkillRegistry, top_k: int = 5) -> dict:
        candidates = registry.find_candidates(task)[:top_k]
        return {
            "available_skills": [skill.to_prompt_summary() for skill in candidates],
            "selection_notes": [
                "Skills are playbook priors, not strict deterministic plans.",
                "LLM may adapt or reorder recommended_todos under guardrails.",
                "For initial model-to-HLS tasks, choose the end-to-end hls4ml_model_flow even when the objective is resource or latency.",
                "Optimization-only skills require existing report metrics and must not replace conversion/synthesis steps.",
                "Do not plan hls4ml.run_csim for real toolchains; real csim/csynth is delegated to VivadoSpecialist through the configured HLS toolchain.",
            ],
        }
