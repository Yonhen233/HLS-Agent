"""skills layer implementation for policy.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

from typing import Any

from .skill import Skill
from .schema import SkillValidator


# These tools are owned by the runtime finalization boundary. They may appear
# in an LLM plan for ordering/evidence purposes, but are not Skill capabilities.
RUNTIME_OWNED_TOOLS = {"summary.write_summary"}


class SkillPolicy:
    """Coordinate SkillPolicy within the policy boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    def validate_skill(self, skill: Skill, tool_registry, specialist_router) -> dict[str, Any]:
        """Execute validate_skill at the policy boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            skill: Value supplied by the caller and validated by the surrounding schema.
            tool_registry: Value supplied by the caller and validated by the surrounding schema.
            specialist_router: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        validator = SkillValidator()
        runtime_report = validator.validate_runtime(
            skill,
            {spec.name for spec in tool_registry.list_tools()},
            {item["name"] for item in specialist_router.list_specialists()},
        )
        errors: list[str] = list(runtime_report.errors)
        if skill.status not in {"approved", "candidate", "deprecated"}:
            errors.append(f"Invalid skill status for {skill.name}: {skill.status}")
        return {"status": "invalid" if errors else "valid", "errors": errors}

    def validate_llm_plan_against_skill(
        self,
        plan: dict[str, Any],
        selected_skill: Skill | None,
        task: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute validate_llm_plan_against_skill at the policy boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            plan: Value supplied by the caller and validated by the surrounding schema.
            selected_skill: Value supplied by the caller and validated by the surrounding schema.
            task: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        errors: list[str] = []
        todos = plan.get("todos", [])
        if not isinstance(todos, list) or not todos:
            errors.append("Todo plan must include at least one todo item.")
        if selected_skill is None:
            return {"status": "invalid" if errors else "valid", "errors": errors}
        if selected_skill.status != "approved":
            errors.append(f"Skill {selected_skill.name} is {selected_skill.status}; only approved skills may execute.")
        if selected_skill.name == "unsupported_boundary_flow" or "safety_only" in selected_skill.tags:
            errors.append("Safety-only Skills are legacy evidence contracts, not executable LLM plans.")
        max_steps = int(selected_skill.budget_policy.get("max_steps", 24))
        if len(todos) > max_steps:
            errors.append(f"Skill {selected_skill.name} plan exceeds max_steps={max_steps}.")
        if "report_metrics_available" in selected_skill.preconditions and not self._task_has_report_metrics(task or {}):
            errors.append(
                f"Skill {selected_skill.name} requires existing report metrics; "
                "use an end-to-end conversion/synthesis skill before optimization-only skills."
            )
        allowed_tools = set(selected_skill.allowed_tools)
        allowed_specialists = set(selected_skill.allowed_specialists)
        verification_required = bool(selected_skill.verification_policy.get("generated_code_requires_verification"))
        seen_verification = False
        tool_counts: dict[str, int] = {}
        for todo in todos:
            assigned_tool = todo.get("assigned_tool")
            assigned_specialist = todo.get("assigned_specialist")
            if assigned_tool and assigned_tool not in allowed_tools and assigned_tool not in RUNTIME_OWNED_TOOLS:
                errors.append(f"Tool {assigned_tool} is outside selected skill allowlist.")
            if assigned_tool:
                tool_counts[assigned_tool] = tool_counts.get(assigned_tool, 0) + 1
            if assigned_specialist and assigned_specialist not in allowed_specialists:
                errors.append(f"Specialist {assigned_specialist} is outside selected skill allowlist.")
            if assigned_specialist == "VerificationSpecialist" or str(assigned_tool).startswith("verify"):
                seen_verification = True
            if assigned_tool in {"llm.generate_hls_candidate", "llm.generate_candidate"} and not seen_verification:
                # soft-check later after full scan
                pass
        for tool_name, count in tool_counts.items():
            if count > 2:
                errors.append(f"Initial plan repeats tool {tool_name} {count} times; repairs must be added after observations.")
        if verification_required and any(
            todo.get("assigned_tool") in {"llm.generate_hls_candidate", "llm.generate_candidate"} for todo in todos
        ) and not any(
            todo.get("assigned_specialist") == "VerificationSpecialist"
            or str(todo.get("assigned_tool", "")).startswith("verify")
            for todo in todos
        ):
            errors.append("LLM candidate generation must include a verification todo.")
        return {"status": "invalid" if errors else "valid", "errors": errors}

    def _task_has_report_metrics(self, task: dict[str, Any]) -> bool:
        """Implement the internal _task_has_report_metrics helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            task: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        report = task.get("report")
        if isinstance(report, dict) and report.get("status") == "success":
            return True
        return bool(task.get("report_path") or task.get("csynth_report_path") or task.get("synthesis_report_path"))

    def validate_skill_modification(self, modification: dict[str, Any], selected_skill: Skill) -> dict[str, Any]:
        """Execute validate_skill_modification at the policy boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            modification: Value supplied by the caller and validated by the surrounding schema.
            selected_skill: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        errors: list[str] = []
        requested_tools = modification.get("add_tools", [])
        if requested_tools and not isinstance(requested_tools, list):
            errors.append("add_tools must be a list.")
        for tool in requested_tools or []:
            if tool not in selected_skill.allowed_tools:
                errors.append(f"Tool {tool} is not in skill {selected_skill.name} allowlist.")
        requested_specialists = modification.get("add_specialists", [])
        if requested_specialists and not isinstance(requested_specialists, list):
            errors.append("add_specialists must be a list.")
        for specialist in requested_specialists or []:
            if specialist not in selected_skill.allowed_specialists:
                errors.append(f"Specialist {specialist} is not in skill {selected_skill.name} allowlist.")
        return {"status": "invalid" if errors else "valid", "errors": errors}
