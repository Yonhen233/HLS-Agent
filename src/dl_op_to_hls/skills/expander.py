"""skills layer implementation for expander.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

from typing import Any

from .skill import Skill


class SkillExpander:
    """Coordinate SkillExpander within the expander boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    def expand_recommended_todos(self, skill: Skill, task: dict[str, Any]) -> list[dict[str, Any]]:
        """Execute expand_recommended_todos at the expander boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            skill: Value supplied by the caller and validated by the surrounding schema.
            task: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        todos: list[dict[str, Any]] = []
        for index, todo in enumerate(skill.recommended_todos, start=1):
            payload = dict(todo)
            payload.setdefault("id", f"todo_{index:03d}")
            payload.setdefault("priority", index)
            payload.setdefault("description", payload.get("title", ""))
            payload.setdefault("dependencies", [f"todo_{index - 1:03d}"] if index > 1 else [])
            payload.setdefault(
                "inputs",
                {
                    "task_type": task.get("task_type"),
                    "task_name": task.get("name"),
                },
            )
            todos.append(payload)
        return todos
