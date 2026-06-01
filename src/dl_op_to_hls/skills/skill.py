from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Skill:
    name: str
    description: str
    intent: str
    trigger: dict[str, Any]
    preconditions: list[str]
    recommended_todos: list[dict[str, Any]]
    allowed_tools: list[str]
    allowed_specialists: list[str]
    required_artifacts: list[str]
    failure_policy: dict[str, Any]
    verification_policy: dict[str, Any]
    memory_policy: dict[str, Any]
    tags: list[str] = field(default_factory=list)
    source: str = "extracted_from_legacy_workflow"

    @classmethod
    def from_dict(cls, payload: dict[str, Any], source: str = "extracted_from_legacy_workflow") -> "Skill":
        return cls(
            name=str(payload["name"]),
            description=str(payload.get("description", "")),
            intent=str(payload.get("intent", payload["name"])),
            trigger=dict(payload.get("trigger", {})),
            preconditions=[str(item) for item in payload.get("preconditions", [])],
            recommended_todos=[dict(item) for item in payload.get("recommended_todos", [])],
            allowed_tools=[str(item) for item in payload.get("allowed_tools", [])],
            allowed_specialists=[str(item) for item in payload.get("allowed_specialists", [])],
            required_artifacts=[str(item) for item in payload.get("required_artifacts", [])],
            failure_policy=dict(payload.get("failure_policy", {})),
            verification_policy=dict(payload.get("verification_policy", {})),
            memory_policy=dict(payload.get("memory_policy", {})),
            tags=[str(item) for item in payload.get("tags", [])],
            source=source,
        )

    def to_prompt_summary(self) -> dict[str, Any]:
        recommended_steps = []
        for todo in self.recommended_todos[:10]:
            tool = todo.get("assigned_tool")
            title = todo.get("title")
            if tool:
                recommended_steps.append(str(tool))
            elif title:
                recommended_steps.append(str(title))
        failure_lines = []
        for error_type, policy in self.failure_policy.items():
            if isinstance(policy, dict):
                action = policy.get("recommended_action") or policy.get("continue_with")
                failure_lines.append(f"{error_type} -> {action}")
            else:
                failure_lines.append(f"{error_type} -> {policy}")
        return {
            "name": self.name,
            "intent": self.intent,
            "when_to_use": self.description,
            "recommended_steps": recommended_steps,
            "allowed_tools": self.allowed_tools[:20],
            "key_failure_policies": failure_lines[:8],
            "allowed_specialists": self.allowed_specialists[:10],
            "tags": self.tags[:12],
        }
