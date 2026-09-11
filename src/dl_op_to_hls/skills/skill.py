"""skills layer implementation for skill.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Skill:
    """Coordinate Skill within the skill boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
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
    version: str = "1.0"
    status: str = "approved"
    context_policy: dict[str, Any] = field(default_factory=dict)
    budget_policy: dict[str, Any] = field(default_factory=dict)
    concurrency_policy: dict[str, Any] = field(default_factory=dict)
    dependencies: list[dict[str, Any]] = field(default_factory=list)
    permissions: dict[str, Any] = field(default_factory=dict)
    tests: list[dict[str, Any]] = field(default_factory=list)
    integrity: dict[str, Any] = field(default_factory=dict)
    # Natural-language guidance complements the machine-enforced contract.
    purpose: str = ""
    procedure: list[str] = field(default_factory=list)
    decision_rules: list[str] = field(default_factory=list)
    pitfalls: list[str] = field(default_factory=list)
    verification_guidance: list[str] = field(default_factory=list)
    examples: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any], source: str = "extracted_from_legacy_workflow") -> "Skill":
        """Execute from_dict at the skill boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            payload: Value supplied by the caller and validated by the surrounding schema.
            source: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
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
            version=str(payload.get("version", "1.0")),
            status=str(payload.get("status", "approved")),
            context_policy=dict(
                payload.get(
                    "context_policy",
                    {"max_context_tokens": 3000, "max_memory_items": 5, "artifact_mode": "references_only"},
                )
            ),
            budget_policy=dict(payload.get("budget_policy", {"max_steps": 24, "max_repair_attempts": 2})),
            concurrency_policy=dict(
                payload.get(
                    "concurrency_policy",
                    {"max_parallel_tools": 2, "max_parallel_llm_calls": 1, "parallelize_read_only": True},
                )
            ),
            dependencies=[dict(item) for item in payload.get("dependencies", [])],
            permissions=dict(payload.get("permissions", {"risk_level": "low", "capabilities": []})),
            tests=[dict(item) for item in payload.get("tests", [])],
            integrity=dict(payload.get("integrity", {})),
            purpose=str(payload.get("purpose", payload.get("description", ""))),
            procedure=[str(item) for item in payload.get("procedure", [])],
            decision_rules=[str(item) for item in payload.get("decision_rules", [])],
            pitfalls=[str(item) for item in payload.get("pitfalls", [])],
            verification_guidance=[str(item) for item in payload.get("verification_guidance", [])],
            examples=[dict(item) for item in payload.get("examples", []) if isinstance(item, dict)],
        )

    def to_prompt_summary(self) -> dict[str, Any]:
        """Execute to_prompt_summary at the skill boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Returns:
            The structured value promised by the function signature.
        """
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
            "version": self.version,
            "status": self.status,
            "context_policy": self.context_policy,
            "budget_policy": self.budget_policy,
            "concurrency_policy": self.concurrency_policy,
            "dependencies": self.dependencies,
            "permissions": self.permissions,
            "integrity": self.integrity,
            "purpose": self.purpose,
            "procedure": self.procedure[:8],
            "decision_rules": self.decision_rules[:8],
            "pitfalls": self.pitfalls[:6],
            "verification_guidance": self.verification_guidance[:6],
            "examples": self.examples[:3],
        }

    def to_catalog_summary(self) -> dict[str, Any]:
        """Return the compact first-disclosure view used for candidate selection."""
        summary = self.to_prompt_summary()
        summary["procedure"] = self.procedure[:3]
        summary["decision_rules"] = self.decision_rules[:3]
        summary["pitfalls"] = self.pitfalls[:2]
        summary["verification_guidance"] = self.verification_guidance[:2]
        summary["examples"] = self.examples[:1]
        summary["disclosure_level"] = "catalog"
        return summary

    def to_execution_guidance(self, specialist_name: str) -> dict[str, Any]:
        """Project the selected playbook without exposing other specialists' tools."""
        if self.status != "approved" or specialist_name not in self.allowed_specialists:
            return {}
        return {
            "name": self.name,
            "version": self.version,
            "purpose": self.purpose,
            "procedure": list(self.procedure[:8]),
            "decision_rules": list(self.decision_rules[:8]),
            "pitfalls": list(self.pitfalls[:6]),
            "verification_guidance": list(self.verification_guidance[:6]),
            "role_scope": (
                "Apply this playbook only to your assigned Todo and allowed tools. "
                "Return cross-specialist follow-up proposals to Main Agent; do not execute them locally."
            ),
        }
