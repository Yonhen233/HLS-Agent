"""main_agent layer implementation for state.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .todo import TodoItem


@dataclass
class AgentState:
    """Coordinate AgentState within the state boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    run_id: str
    task: dict
    session_id: str | None = None
    status: str = "initialized"
    objective: str | None = None
    plan: list[str] = field(default_factory=list)
    todos: list[TodoItem] = field(default_factory=list)
    current_todo_id: str | None = None
    selected_path: str | None = None
    terminal_outcome: str | None = None
    terminal_reason: dict[str, Any] = field(default_factory=dict)
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
    verification: dict | None = None
    pipeline_status: dict[str, Any] = field(default_factory=dict)
    parameter_advice: dict | None = None
    short_term_memory: dict[str, Any] = field(default_factory=dict)
    retrieved_memories: list[dict[str, Any]] = field(default_factory=list)
    memory_candidates: list[dict[str, Any]] = field(default_factory=list)
    promoted_memories: list[dict[str, Any]] = field(default_factory=list)
    rag_context: list[dict] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    llm_decisions: list[dict[str, Any]] = field(default_factory=list)
    goal_contract: dict[str, Any] = field(default_factory=dict)
    plan_coverage: dict[str, Any] = field(default_factory=dict)
    completion: dict[str, Any] = field(default_factory=dict)
    progress: dict[str, Any] = field(default_factory=dict)
    rag_evidence_report: dict[str, Any] = field(default_factory=dict)
    evidence_receipts: list[dict[str, Any]] = field(default_factory=list)
    release_manifest: dict[str, Any] = field(default_factory=dict)
    telemetry: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Execute to_dict at the state boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Returns:
            The structured value promised by the function signature.
        """
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AgentState":
        """Execute from_dict at the state boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            payload: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
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
        if updated.get("selected_path") == "unsupported_path":
            updated["selected_path"] = None
            updated["terminal_outcome"] = updated.get("terminal_outcome") or "blocked"
            updated["terminal_reason"] = updated.get("terminal_reason") or {
                "kind": "legacy_boundary", "reason": "Migrated legacy unsupported_path checkpoint."
            }
        updated["todos"] = todos
        return cls(**updated)

    def save(self, path: str | Path) -> Path:
        """Execute save at the state boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            path: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        target = Path(path)
        target.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        return target
