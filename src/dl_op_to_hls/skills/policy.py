from __future__ import annotations

from typing import Any

from .skill import Skill


class SkillPolicy:
    def validate_skill(self, skill: Skill, tool_registry, specialist_router) -> dict[str, Any]:
        errors: list[str] = []
        tool_names = {spec.name for spec in tool_registry.list_tools()}
        specialist_names = {item["name"] for item in specialist_router.list_specialists()}
        for tool in skill.allowed_tools:
            if tool not in tool_names:
                errors.append(f"Unknown tool in skill {skill.name}: {tool}")
        for specialist in skill.allowed_specialists:
            if specialist not in specialist_names:
                errors.append(f"Unknown specialist in skill {skill.name}: {specialist}")
        return {"status": "invalid" if errors else "valid", "errors": errors}

    def validate_llm_plan_against_skill(self, plan: dict[str, Any], selected_skill: Skill | None) -> dict[str, Any]:
        errors: list[str] = []
        todos = plan.get("todos", [])
        if not isinstance(todos, list) or not todos:
            errors.append("Todo plan must include at least one todo item.")
        if selected_skill is None:
            return {"status": "invalid" if errors else "valid", "errors": errors}
        allowed_tools = set(selected_skill.allowed_tools)
        allowed_specialists = set(selected_skill.allowed_specialists)
        verification_required = bool(selected_skill.verification_policy.get("generated_code_requires_verification"))
        seen_verification = False
        for todo in todos:
            assigned_tool = todo.get("assigned_tool")
            assigned_specialist = todo.get("assigned_specialist")
            if assigned_tool and assigned_tool not in allowed_tools:
                errors.append(f"Tool {assigned_tool} is outside selected skill allowlist.")
            if assigned_specialist and assigned_specialist not in allowed_specialists:
                errors.append(f"Specialist {assigned_specialist} is outside selected skill allowlist.")
            if assigned_specialist == "VerificationSpecialist" or str(assigned_tool).startswith("verify"):
                seen_verification = True
            if assigned_tool == "llm.generate_hls_candidate" and not seen_verification:
                # soft-check later after full scan
                pass
        if verification_required and any(
            todo.get("assigned_tool") == "llm.generate_hls_candidate" for todo in todos
        ) and not any(
            todo.get("assigned_specialist") == "VerificationSpecialist"
            or str(todo.get("assigned_tool", "")).startswith("verify")
            for todo in todos
        ):
            errors.append("LLM candidate generation must include a verification todo.")
        return {"status": "invalid" if errors else "valid", "errors": errors}

    def validate_skill_modification(self, modification: dict[str, Any], selected_skill: Skill) -> dict[str, Any]:
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
