from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class SpecialistResult:
    specialist_name: str
    todo_id: str
    status: str
    summary: str
    observations: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] | None = None
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    suggested_todos: list[dict[str, Any]] = field(default_factory=list)
    memory_candidates: list[dict[str, Any]] = field(default_factory=list)
    context_usage: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
