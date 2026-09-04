from __future__ import annotations

import re
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)(?:\.(0|[1-9]\d*))?(?:-[0-9A-Za-z.-]+)?$")
VALID_STATUSES = {"candidate", "approved", "deprecated"}
VALID_RISK_LEVELS = {"low", "medium", "high", "critical"}


@dataclass
class SkillValidationReport:
    name: str
    version: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "status": "valid" if self.valid else "invalid",
            "errors": self.errors,
            "warnings": self.warnings,
        }


class SkillValidator:
    """Static linter/compiler checks for declarative Agent skills."""

    REQUIRED = {
        "name",
        "description",
        "intent",
        "trigger",
        "recommended_todos",
        "allowed_tools",
        "allowed_specialists",
        "failure_policy",
        "verification_policy",
        "memory_policy",
    }

    def validate_document(self, payload: dict[str, Any]) -> SkillValidationReport:
        name = str(payload.get("name") or "<unnamed>")
        version = str(payload.get("version") or "1.0")
        report = SkillValidationReport(name=name, version=version)
        missing = sorted(self.REQUIRED - set(payload))
        if missing:
            report.errors.append(f"Missing required fields: {', '.join(missing)}")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{2,127}", name):
            report.errors.append("name must be a stable identifier with at least three characters")
        if not SEMVER_RE.fullmatch(version):
            report.errors.append(f"version is not semantic: {version}")
        elif version.count(".") == 1:
            report.warnings.append("Use a three-part semantic version (for example 1.0.0) for published skills.")
        status = str(payload.get("status") or "approved")
        if status not in VALID_STATUSES:
            report.errors.append(f"Invalid status: {status}")
        for field_name in ("recommended_todos", "allowed_tools", "allowed_specialists"):
            if field_name in payload and not isinstance(payload[field_name], list):
                report.errors.append(f"{field_name} must be a list")
        self._validate_todos(payload.get("recommended_todos", []), report)
        self._validate_policy(payload, report)
        self._validate_dependencies(payload.get("dependencies", []), report)
        integrity = payload.get("integrity", {})
        if isinstance(integrity, dict) and integrity.get("sha256"):
            unsigned = dict(payload)
            unsigned.pop("integrity", None)
            actual = hashlib.sha256(
                json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
            ).hexdigest()
            if actual != str(integrity["sha256"]):
                report.errors.append("integrity.sha256 does not match the normalized skill document")
        return report

    def validate_runtime(self, skill, tool_names: set[str], specialist_names: set[str]) -> SkillValidationReport:
        report = SkillValidationReport(skill.name, skill.version)
        for tool in skill.allowed_tools:
            if tool not in tool_names:
                report.errors.append(f"Unknown allowed tool: {tool}")
        for specialist in skill.allowed_specialists:
            if specialist not in specialist_names:
                report.errors.append(f"Unknown allowed specialist: {specialist}")
        for todo in skill.recommended_todos:
            tool = todo.get("assigned_tool")
            specialist = todo.get("assigned_specialist")
            if tool and tool not in skill.allowed_tools:
                report.errors.append(f"Todo uses tool outside skill allowlist: {tool}")
            if specialist and specialist not in skill.allowed_specialists:
                report.errors.append(f"Todo uses specialist outside skill allowlist: {specialist}")
        return report

    def _validate_todos(self, todos: Any, report: SkillValidationReport) -> None:
        if not isinstance(todos, list) or not todos:
            report.errors.append("recommended_todos must contain at least one todo")
            return
        ids: set[str] = set()
        graph: dict[str, list[str]] = {}
        for index, todo in enumerate(todos):
            if not isinstance(todo, dict):
                report.errors.append(f"recommended_todos[{index}] must be an object")
                continue
            if not todo.get("title"):
                report.errors.append(f"recommended_todos[{index}] has no title")
            todo_id = str(todo.get("id") or f"step_{index + 1}")
            if todo_id in ids:
                report.errors.append(f"Duplicate todo id: {todo_id}")
            ids.add(todo_id)
            dependencies = todo.get("dependencies", [])
            if dependencies and not isinstance(dependencies, list):
                report.errors.append(f"Todo {todo_id} dependencies must be a list")
                dependencies = []
            graph[todo_id] = [str(item) for item in dependencies]
        for todo_id, dependencies in graph.items():
            unknown = [item for item in dependencies if item not in ids]
            if unknown:
                report.errors.append(f"Todo {todo_id} has unknown dependencies: {', '.join(unknown)}")
        if self._has_cycle(graph):
            report.errors.append("Todo dependency graph contains a cycle")

    def _validate_policy(self, payload: dict[str, Any], report: SkillValidationReport) -> None:
        budget = payload.get("budget_policy", {})
        concurrency = payload.get("concurrency_policy", {})
        permissions = payload.get("permissions", {})
        if budget and not isinstance(budget, dict):
            report.errors.append("budget_policy must be an object")
        else:
            for key in ("max_steps", "max_repair_attempts", "max_tool_calls", "max_llm_calls", "max_tokens"):
                if key in budget and int(budget[key]) <= 0:
                    report.errors.append(f"budget_policy.{key} must be positive")
        if concurrency and not isinstance(concurrency, dict):
            report.errors.append("concurrency_policy must be an object")
        elif int(concurrency.get("max_parallel_tools", 1)) > 8:
            report.errors.append("max_parallel_tools may not exceed 8")
        risk = str((permissions or {}).get("risk_level", "low"))
        if risk not in VALID_RISK_LEVELS:
            report.errors.append(f"Invalid permissions.risk_level: {risk}")

    @staticmethod
    def _validate_dependencies(dependencies: Any, report: SkillValidationReport) -> None:
        if not isinstance(dependencies, list):
            report.errors.append("dependencies must be a list")
            return
        for dependency in dependencies:
            if not isinstance(dependency, dict) or not dependency.get("name"):
                report.errors.append("Each dependency must contain name and optional version constraint")

    @staticmethod
    def _has_cycle(graph: dict[str, list[str]]) -> bool:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> bool:
            if node in visiting:
                return True
            if node in visited:
                return False
            visiting.add(node)
            if any(visit(child) for child in graph.get(node, []) if child in graph):
                return True
            visiting.remove(node)
            visited.add(node)
            return False

        return any(visit(node) for node in graph)


def evaluate_conditions(conditions: list[Any], task: dict[str, Any]) -> bool:
    """Evaluate the safe condition DSL; no Python/eval expressions are accepted."""
    for condition in conditions:
        if isinstance(condition, str):
            if condition.startswith("has:"):
                if _resolve(task, condition[4:]) is None:
                    return False
                continue
            if not _evaluate_named_condition(condition, task):
                return False
            continue
        if not isinstance(condition, dict):
            return False
        actual = _resolve(task, str(condition.get("field") or ""))
        operator = str(condition.get("op") or "eq")
        expected = condition.get("value")
        if operator == "eq" and actual != expected:
            return False
        if operator == "ne" and actual == expected:
            return False
        if operator == "in" and actual not in (expected or []):
            return False
        if operator == "contains" and expected not in (actual or []):
            return False
        if operator == "exists" and bool(actual is not None) != bool(expected):
            return False
        if operator not in {"eq", "ne", "in", "contains", "exists"}:
            return False
    return True


def _evaluate_named_condition(name: str, task: dict[str, Any]) -> bool:
    objective = str(task.get("objective") or _resolve(task, "optimization.objective") or "").lower()
    llm_candidate_required = bool(_resolve(task, "llm_candidate.required"))
    expected_path = str(_resolve(task, "demo.expected_path") or "").lower()
    predicates = {
        "objective_latency": objective == "latency",
        "objective_resource": objective == "resource",
        "llm_enabled": llm_candidate_required,
        "hls4ml_unsupported": llm_candidate_required,
        "fallback_template_missing": llm_candidate_required,
        "hls4ml_unsupported_or_not_recommended": expected_path in {"unsupported", "unsupported_report"}
        or isinstance(task.get("capability_boundary"), dict),
    }
    return predicates.get(name, False)


def _resolve(payload: dict[str, Any], path: str) -> Any:
    value: Any = payload
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value
