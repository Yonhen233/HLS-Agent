from __future__ import annotations

from .registry import SkillRegistry
from .skill import Skill


class SkillSelector:
    def __init__(self, registry: SkillRegistry):
        self.registry = registry

    def select(self, task: dict) -> Skill | None:
        candidates = self.registry.find_candidates(task)
        return candidates[0] if candidates else None
