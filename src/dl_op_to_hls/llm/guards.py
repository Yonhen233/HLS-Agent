"""llm layer implementation for guards.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class LLMGuard:
    """Coordinate LLMGuard within the guards boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    def validate_todo_plan(self, plan: dict, tool_registry, specialist_router, skill_registry) -> dict:
        """Execute validate_todo_plan at the guards boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            plan: Value supplied by the caller and validated by the surrounding schema.
            tool_registry: Value supplied by the caller and validated by the surrounding schema.
            specialist_router: Value supplied by the caller and validated by the surrounding schema.
            skill_registry: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        errors: list[str] = []
        todos = plan.get("todos")
        if not isinstance(todos, list) or not todos:
            errors.append("Todo plan must contain a non-empty todos list.")
            return {"status": "invalid", "errors": errors}

        selected_skill = plan.get("selected_skill")
        if plan.get("skill_usage") not in {"strict", "adapted"}:
            errors.append("skill_usage must be exactly 'strict' or 'adapted'.")
        if selected_skill:
            try:
                skill = skill_registry.get(selected_skill)
                if skill.name == "unsupported_boundary_flow" or "safety_only" in skill.tags:
                    errors.append("Safety-only Skills cannot be selected by the planner; terminal outcomes belong to runtime gates.")
            except KeyError:
                errors.append(f"Unknown selected_skill: {selected_skill}")

        tools = {spec.name for spec in tool_registry.list_tools()}
        specialist_specs = {item["name"]: item for item in specialist_router.list_specialists()}
        specialists = set(specialist_specs)
        private_tool_owners: dict[str, list[str]] = {}
        for specialist_name, spec in specialist_specs.items():
            for allowed_tool in spec.get("allowed_tools", []):
                private_tool_owners.setdefault(allowed_tool, []).append(specialist_name)
        for index, todo in enumerate(todos, start=1):
            tool_name = todo.get("assigned_tool")
            specialist_name = todo.get("assigned_specialist")
            if tool_name and tool_name not in tools:
                errors.append(f"Todo #{index} uses unknown tool: {tool_name}")
            if specialist_name and specialist_name not in specialists:
                errors.append(f"Todo #{index} uses unknown specialist: {specialist_name}")
            if tool_name in private_tool_owners and not specialist_name:
                errors.append(
                    f"Todo #{index} uses specialist-private tool {tool_name} without assigning one of {private_tool_owners[tool_name]}."
                )
            if specialist_name and tool_name and specialist_name in specialist_specs:
                allowed_tools = set(specialist_specs[specialist_name].get("allowed_tools", []))
                if tool_name not in allowed_tools:
                    errors.append(
                        f"Todo #{index} assigns tool {tool_name} to specialist {specialist_name}, but it is outside allowed_tools."
                    )
            if tool_name in {"llm.generate_hls_candidate", "llm.generate_candidate"}:
                if not any(
                    (
                        item.get("assigned_specialist") == "VerificationSpecialist"
                        or str(item.get("assigned_tool", "")).startswith("verify")
                        or item.get("assigned_tool") == "verify_candidate.run"
                    )
                    for item in todos
                ):
                    errors.append("LLM candidate generation must include verification specialist/tool.")

        return {"status": "invalid" if errors else "valid", "errors": errors}

    def validate_react_decision(
        self,
        decision: dict,
        allowed_tools: list[str] | None = None,
        allowed_actions: list[str] | None = None,
    ) -> dict:
        """Execute validate_react_decision at the guards boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            decision: Value supplied by the caller and validated by the surrounding schema.
            allowed_tools: Value supplied by the caller and validated by the surrounding schema.
            allowed_actions: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        allowed_tools = allowed_tools or []
        allowed_actions = allowed_actions or [
            "delegate_to_specialist",
            "direct_tool_only_when_no_specialist",
            "request_replan",
            "mark_blocked",
            "mark_failed",
        ]
        errors: list[str] = []
        action = decision.get("action", {})
        decision_name = decision.get("decision")
        if decision_name not in allowed_actions:
            errors.append(f"Action {decision_name} is not in allowed_actions.")
        if decision_name == "delegate_to_specialist":
            specialist_name = action.get("specialist_name") or action.get("specialist")
            if not specialist_name:
                errors.append("delegate_to_specialist requires action.specialist_name.")
        if decision_name == "direct_tool_only_when_no_specialist":
            tool_name = action.get("tool_name") or action.get("tool")
            if tool_name not in allowed_tools:
                errors.append(f"Tool {tool_name} is not in allowed_tools.")
        return {"status": "invalid" if errors else "valid", "errors": errors}

    def validate_reflection(self, reflection: dict, current_skill: str | None) -> dict:
        """Execute validate_reflection at the guards boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            reflection: Value supplied by the caller and validated by the surrounding schema.
            current_skill: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        errors: list[str] = []
        if "new_todos" not in reflection:
            errors.append("Reflection payload must include new_todos.")
        if reflection.get("todo_status") not in {
            "pending",
            "in_progress",
            "completed",
            "completed_with_warning",
            "failed",
            "blocked",
            "skipped",
            "cancelled",
        }:
            errors.append("Invalid todo_status in reflection.")
        if current_skill is None and reflection.get("decision") == "switch_skill":
            errors.append("Cannot switch skill when no current skill is selected.")
        return {"status": "invalid" if errors else "valid", "errors": errors}

    def validate_candidate_files(self, candidate: dict, run_dir: str) -> dict:
        """Execute validate_candidate_files at the guards boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            candidate: Value supplied by the caller and validated by the surrounding schema.
            run_dir: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        errors: list[str] = []
        run_path = Path(run_dir).resolve()
        if candidate.get("status") == "verified":
            errors.append("Candidate cannot be marked verified before verification pipeline.")
        files = candidate.get("files")
        if not isinstance(files, list) or not files:
            errors.append("Candidate must include a non-empty files list.")
            return {"status": "invalid" if errors else "valid", "errors": errors}
        for index, file_item in enumerate(files, start=1):
            if not isinstance(file_item, dict):
                errors.append(f"Candidate file #{index} must be an object.")
                continue
            rel = file_item.get("relative_path", "")
            content = file_item.get("content")
            if not rel:
                errors.append(f"Candidate file #{index} is missing relative_path.")
                continue
            if not isinstance(content, str) or not content.strip():
                errors.append(f"Candidate file {rel} is missing non-empty content.")
            if Path(rel).is_absolute():
                errors.append(f"Candidate file path must be relative: {rel}")
                continue
            resolved = (run_path / rel).resolve()
            allowed_root = (run_path / "candidate").resolve()
            if resolved != allowed_root and allowed_root not in resolved.parents:
                errors.append(f"Candidate file path is outside run candidate dir: {rel}")
        return {"status": "invalid" if errors else "valid", "errors": errors}
