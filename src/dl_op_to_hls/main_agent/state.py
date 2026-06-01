from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .todo import TodoItem


@dataclass
class AgentState:
    run_id: str
    task: dict
    status: str = "initialized"
    objective: str | None = None
    plan: list[str] = field(default_factory=list)
    todos: list[TodoItem] = field(default_factory=list)
    current_todo_id: str | None = None
    selected_path: str | None = None
    selected_skill: str | None = None
    skill_usage_mode: str | None = None
    hls4ml_support: dict | None = None
    hls4ml_config_path: str | None = None
    hls_project_dir: str | None = None
    vivado_work_dir: str | None = None
    artifacts: dict[str, Any] = field(default_factory=dict)
    tool_results: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    report: dict | None = None
    short_term_memory: dict[str, Any] = field(default_factory=dict)
    retrieved_memories: list[dict[str, Any]] = field(default_factory=list)
    memory_candidates: list[dict[str, Any]] = field(default_factory=list)
    promoted_memories: list[dict[str, Any]] = field(default_factory=list)
    rag_context: list[dict] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    llm_decisions: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AgentState":
        todos = []
        for item in payload.get("todos", []):
            normalized = {
                "assigned_specialist": None,
                "context_scope": {},
                "specialist_result": None,
                **item,
            }
            todos.append(TodoItem(**normalized))
        updated = dict(payload)
        updated["todos"] = todos
        return cls(**updated)

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        return target
