"""skills layer implementation for selector.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

from .registry import SkillRegistry
from .skill import Skill


class SkillSelector:
    """Coordinate SkillSelector within the selector boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    def __init__(self, registry: SkillRegistry):
        """Implement the internal __init__ helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            registry: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        self.registry = registry

    def select(self, task: dict) -> Skill | None:
        """Execute select at the selector boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            task: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        candidates = self.registry.find_candidates(task)
        return candidates[0] if candidates else None
