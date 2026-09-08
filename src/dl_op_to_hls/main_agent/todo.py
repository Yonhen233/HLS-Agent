"""main_agent layer implementation for todo.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DONE_STATUSES = {"completed", "completed_with_warning", "skipped"}

WARNING_DEPENDENCY_OK_TOOLS = {
    "graph_rewrite.rewrite",
    "fallback.generate_operator_hls",
    "llm.generate_candidate",
    "llm.generate_hls_candidate",
    "report.write_unsupported",
    "vivado.parse_report",
    "vivado.parse_csynth_report",
    "suggestion.suggest_optimization",
    "summary.write_summary",
    "memory.promote_to_long_term",
}

SKIPPED_DEPENDENCY_OK_TOOLS = {
    "vivado.parse_report",
    "vivado.parse_csynth_report",
    "suggestion.suggest_optimization",
    "summary.write_summary",
    "memory.promote_to_long_term",
}


def _now() -> str:
    """Implement the internal _now helper.

    Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

    Returns:
        The structured value promised by the function signature.
    """
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class TodoItem:
    """Coordinate TodoItem within the todo boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    id: str
    title: str
    description: str
    status: str
    priority: int
    dependencies: list[str]
    assigned_tool: str | None
    assigned_specialist: str | None
    inputs: dict[str, Any]
    outputs: dict[str, Any] | None
    error: dict[str, Any] | None
    context_scope: dict[str, Any] = field(default_factory=dict)
    react_steps: list[dict[str, Any]] = field(default_factory=list)
    specialist_result: dict[str, Any] | None = None
    created_at: str = ""
    updated_at: str = ""
    requirement_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Execute to_dict at the todo boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Returns:
            The structured value promised by the function signature.
        """
        return asdict(self)


@dataclass
class TodoList:
    """Coordinate TodoList within the todo boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    run_id: str
    items: list[TodoItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Execute to_dict at the todo boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Returns:
            The structured value promised by the function signature.
        """
        return {"run_id": self.run_id, "items": [item.to_dict() for item in self.items]}


class TodoManager:
    """Coordinate TodoManager within the todo boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    def __init__(self, run_dir: str | Path, hooks=None, artifact_manager=None):
        """Implement the internal __init__ helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            run_dir: Value supplied by the caller and validated by the surrounding schema.
            hooks: Value supplied by the caller and validated by the surrounding schema.
            artifact_manager: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        self.run_dir = Path(run_dir)
        self.hooks = hooks
        self.artifact_manager = artifact_manager
        self.todo_list: TodoList | None = None
        self._artifact_registered = False

    def _emit(self, event: str, payload: dict[str, Any]) -> None:
        """Implement the internal _emit helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            event: Value supplied by the caller and validated by the surrounding schema.
            payload: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        if self.hooks:
            self.hooks.emit(event, payload)

    def _tool_for_title(self, title: str, task: dict[str, Any]) -> str | None:
        """Implement the internal _tool_for_title helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            title: Value supplied by the caller and validated by the surrounding schema.
            task: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        mapping = {
            "Validate task schema": "task.validate_schema",
            "Inspect model structure": "hls4ml.inspect_model",
            "Check hls4ml support": "hls4ml.check_support",
            "Try graph rewrite": "graph_rewrite.rewrite",
            "Generate hls4ml config": "hls4ml.generate_config",
            "Convert with hls4ml": "hls4ml.convert",
            "Generate fallback HLS template": "fallback.generate_operator_hls",
            "Generate LLM candidate": "llm.generate_candidate",
            "Verify LLM candidate": "verify_candidate.run",
            "Prepare existing HLS project": "task.prepare_existing_project",
            "Run Vivado HLS synthesis": "vivado.run_csynth",
            "Parse synthesis report": "vivado.parse_report",
            "Generate unsupported report": "report.write_unsupported",
            "Generate optimization suggestions": "suggestion.suggest_optimization",
            "Write run summary": "summary.write_summary",
            "Promote memories": "memory.promote_to_long_term",
        }
        if title == "Inspect model structure" and task.get("task_type") != "model":
            return None
        return mapping.get(title)

    def _specialist_for_tool(self, tool_name: str | None, title: str) -> str | None:
        """Implement the internal _specialist_for_tool helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            tool_name: Value supplied by the caller and validated by the surrounding schema.
            title: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        if not tool_name:
            return None
        if tool_name.startswith("hls4ml."):
            return "HLS4MLSpecialist"
        if tool_name in {"llm.generate_candidate", "llm.generate_hls_candidate"}:
            return "CodegenSpecialist"
        if tool_name.startswith("vivado."):
            return "VivadoSpecialist"
        if tool_name.startswith("verify"):
            return "VerificationSpecialist"
        if tool_name.startswith("suggestion.") or title == "Generate optimization suggestions":
            return "OptimizationSpecialist"
        if tool_name.startswith("memory."):
            return "MemorySpecialist"
        return None

    def _context_scope_for_specialist(self, specialist_name: str | None) -> dict[str, Any]:
        """Implement the internal _context_scope_for_specialist helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            specialist_name: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        if not specialist_name:
            return {}
        return {
            "include": ["run_id", "task_summary", "relevant_artifacts", "retrieved_memory_refs"],
            "exclude": ["raw_logs", "full_trace", "all_memories", "full_hls_code", "raw_report"],
            "max_context_tokens": 3000,
        }

    def create_from_plan(self, run_id: str, plan: list[str], task: dict) -> TodoList:
        """Execute create_from_plan at the todo boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            run_id: Value supplied by the caller and validated by the surrounding schema.
            plan: Value supplied by the caller and validated by the surrounding schema.
            task: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        items: list[TodoItem] = []
        previous_id: str | None = None
        for index, title in enumerate(plan, start=1):
            todo_id = f"todo_{index:03d}"
            assigned_tool = self._tool_for_title(title, task)
            assigned_specialist = self._specialist_for_tool(assigned_tool, title)
            item = TodoItem(
                id=todo_id,
                title=title,
                description=title,
                status="pending",
                priority=index,
                dependencies=[previous_id] if previous_id else [],
                assigned_tool=assigned_tool,
                assigned_specialist=assigned_specialist,
                inputs={"task_type": task.get("task_type"), "task_name": task.get("name")},
                outputs=None,
                error=None,
                context_scope=self._context_scope_for_specialist(assigned_specialist),
                created_at=_now(),
                updated_at=_now(),
                requirement_ids=[],
            )
            items.append(item)
            previous_id = todo_id
            self._emit("TodoCreated", {"run_id": run_id, "todo_id": todo_id, "title": title})
        self.todo_list = TodoList(run_id=run_id, items=items)
        self.save(run_id, self.todo_list)
        return self.todo_list

    def _find(self, todo_id: str) -> TodoItem:
        """Implement the internal _find helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            todo_id: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        if not self.todo_list:
            raise KeyError("TodoList not initialized")
        for item in self.todo_list.items:
            if item.id == todo_id:
                return item
        raise KeyError(todo_id)

    def _dep_satisfied_for_item(self, item: TodoItem, dep: TodoItem) -> bool:
        """Implement the internal _dep_satisfied_for_item helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            item: Value supplied by the caller and validated by the surrounding schema.
            dep: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        if dep.status == "completed":
            return True
        if dep.status == "completed_with_warning":
            return True
        if dep.status == "skipped":
            return item.assigned_tool in SKIPPED_DEPENDENCY_OK_TOOLS
        return False

    def _deps_satisfied(self, item: TodoItem) -> bool:
        """Implement the internal _deps_satisfied helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            item: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        for dep_id in item.dependencies:
            dep = self._find(dep_id)
            if not self._dep_satisfied_for_item(item, dep):
                return False
        return True

    def _refresh_blocked_items(self) -> None:
        """Implement the internal _refresh_blocked_items helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Returns:
            The structured value promised by the function signature.
        """
        if not self.todo_list:
            return
        for item in self.todo_list.items:
            is_dependency_block = (item.error or {}).get("message") == "Dependencies are not completed yet."
            if item.status == "blocked" and is_dependency_block and self._deps_satisfied(item):
                item.status = "pending"
                item.updated_at = _now()

    def get_next_ready_item(self, todo_list: TodoList) -> TodoItem | None:
        """Execute get_next_ready_item at the todo boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            todo_list: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        self.todo_list = todo_list
        self._refresh_blocked_items()
        for item in todo_list.items:
            if item.status == "pending" and self._deps_satisfied(item):
                return item
            if item.status == "pending" and item.dependencies and not self._deps_satisfied(item):
                self.mark_blocked(item.id, "Dependencies are not completed yet.")
        return None

    def mark_started(self, todo_id: str) -> None:
        """Execute mark_started at the todo boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            todo_id: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        item = self._find(todo_id)
        item.status = "in_progress"
        item.updated_at = _now()
        self._emit("TodoStarted", {"run_id": self.todo_list.run_id, "todo_id": todo_id})
        self.save(self.todo_list.run_id, self.todo_list)

    def mark_completed(self, todo_id: str, outputs: dict) -> None:
        """Execute mark_completed at the todo boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            todo_id: Value supplied by the caller and validated by the surrounding schema.
            outputs: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        item = self._find(todo_id)
        item.status = "completed"
        item.outputs = outputs
        item.error = None
        item.updated_at = _now()
        self._emit("TodoCompleted", {"run_id": self.todo_list.run_id, "todo_id": todo_id})
        self.save(self.todo_list.run_id, self.todo_list)

    def mark_completed_with_warning(self, todo_id: str, outputs: dict, warning: dict) -> None:
        """Execute mark_completed_with_warning at the todo boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            todo_id: Value supplied by the caller and validated by the surrounding schema.
            outputs: Value supplied by the caller and validated by the surrounding schema.
            warning: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        item = self._find(todo_id)
        item.status = "completed_with_warning"
        item.outputs = outputs
        item.error = warning
        item.updated_at = _now()
        self._emit("TodoCompletedWithWarning", {"run_id": self.todo_list.run_id, "todo_id": todo_id, "warning": warning})
        self.save(self.todo_list.run_id, self.todo_list)

    def mark_failed(self, todo_id: str, error: dict) -> None:
        """Execute mark_failed at the todo boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            todo_id: Value supplied by the caller and validated by the surrounding schema.
            error: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        item = self._find(todo_id)
        item.status = "failed"
        item.error = error
        item.updated_at = _now()
        self._emit("TodoFailed", {"run_id": self.todo_list.run_id, "todo_id": todo_id, "error": error})
        self.save(self.todo_list.run_id, self.todo_list)

    def mark_skipped(self, todo_id: str, reason: str) -> None:
        """Execute mark_skipped at the todo boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            todo_id: Value supplied by the caller and validated by the surrounding schema.
            reason: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        item = self._find(todo_id)
        item.status = "skipped"
        item.error = {"message": reason}
        item.updated_at = _now()
        self._emit("TodoSkipped", {"run_id": self.todo_list.run_id, "todo_id": todo_id, "reason": reason})
        self.save(self.todo_list.run_id, self.todo_list)

    def mark_blocked(self, todo_id: str, reason: str) -> None:
        """Execute mark_blocked at the todo boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            todo_id: Value supplied by the caller and validated by the surrounding schema.
            reason: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        item = self._find(todo_id)
        if item.status == "blocked" and item.error == {"message": reason}:
            return
        item.status = "blocked"
        item.error = {"message": reason}
        item.updated_at = _now()
        self._emit("TodoBlocked", {"run_id": self.todo_list.run_id, "todo_id": todo_id, "reason": reason})
        self.save(self.todo_list.run_id, self.todo_list)

    def mark_cancelled(self, todo_id: str, reason: str) -> None:
        """Execute mark_cancelled at the todo boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            todo_id: Value supplied by the caller and validated by the surrounding schema.
            reason: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        item = self._find(todo_id)
        item.status = "cancelled"
        item.error = {"message": reason}
        item.updated_at = _now()
        self._emit("TodoCancelled", {"run_id": self.todo_list.run_id, "todo_id": todo_id, "reason": reason})
        self.save(self.todo_list.run_id, self.todo_list)

    def append_item(
        self,
        *,
        title: str,
        description: str,
        priority: int,
        assigned_tool: str | None,
        assigned_specialist: str | None = None,
        dependencies: list[str] | None = None,
        inputs: dict[str, Any] | None = None,
    ) -> TodoItem:
        """Execute append_item at the todo boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            title: Value supplied by the caller and validated by the surrounding schema.
            description: Value supplied by the caller and validated by the surrounding schema.
            priority: Value supplied by the caller and validated by the surrounding schema.
            assigned_tool: Value supplied by the caller and validated by the surrounding schema.
            assigned_specialist: Value supplied by the caller and validated by the surrounding schema.
            dependencies: Value supplied by the caller and validated by the surrounding schema.
            inputs: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        if not self.todo_list:
            raise KeyError("TodoList not initialized")
        todo_id = f"todo_{len(self.todo_list.items) + 1:03d}"
        resolved_specialist = assigned_specialist or self._specialist_for_tool(assigned_tool, title)
        item = TodoItem(
            id=todo_id,
            title=title,
            description=description,
            status="pending",
            priority=priority,
            dependencies=list(dependencies or []),
            assigned_tool=assigned_tool,
            assigned_specialist=resolved_specialist,
            inputs=dict(inputs or {}),
            outputs=None,
            error=None,
            context_scope=self._context_scope_for_specialist(resolved_specialist),
            created_at=_now(),
            updated_at=_now(),
            requirement_ids=[],
        )
        self.todo_list.items.append(item)
        self._emit("TodoCreated", {"run_id": self.todo_list.run_id, "todo_id": todo_id, "title": title})
        self.save(self.todo_list.run_id, self.todo_list)
        return item

    def add_dependency(self, todo_id: str, dependency_id: str) -> None:
        """Execute add_dependency at the todo boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            todo_id: Value supplied by the caller and validated by the surrounding schema.
            dependency_id: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        item = self._find(todo_id)
        if dependency_id not in item.dependencies:
            item.dependencies.append(dependency_id)
            item.updated_at = _now()
            self.save(self.todo_list.run_id, self.todo_list)

    def save(self, run_id: str, todo_list: TodoList | None = None) -> str:
        """Execute save at the todo boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            run_id: Value supplied by the caller and validated by the surrounding schema.
            todo_list: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        current = todo_list or self.todo_list
        if current is None:
            raise KeyError("TodoList not initialized")
        path = self.run_dir / "todos.json"
        path.write_text(json.dumps(current.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        if self.artifact_manager is not None:
            self.artifact_manager.register_file(path, "todos")
            self._artifact_registered = True
        return str(path)

    def has_pending_or_ready(self) -> bool:
        """Execute has_pending_or_ready at the todo boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Returns:
            The structured value promised by the function signature.
        """
        if not self.todo_list:
            return False
        return any(item.status in {"pending", "blocked"} for item in self.todo_list.items)
