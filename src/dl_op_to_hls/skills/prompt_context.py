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
            ],
        }
