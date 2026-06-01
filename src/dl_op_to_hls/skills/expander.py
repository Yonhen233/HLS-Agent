from __future__ import annotations

from typing import Any

from .skill import Skill


class SkillExpander:
    def expand_recommended_todos(self, skill: Skill, task: dict[str, Any]) -> list[dict[str, Any]]:
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
