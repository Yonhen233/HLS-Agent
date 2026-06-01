from __future__ import annotations

from typing import Any


TASK_INTERPRETATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["task", "assumptions"],
    "properties": {
        "task": {"type": "object"},
        "assumptions": {"type": "array"},
        "reason_summary": {"type": "string"},
    },
}

TODO_PLAN_SCHEMA: dict[str, Any] = {
    "title": "TodoPlan",
    "type": "object",
    "required": ["selected_skill", "skill_usage", "todos", "reason_summary"],
    "properties": {
        "selected_skill": {"type": "string"},
        "skill_usage": {"type": "string"},
        "reason_summary": {"type": "string"},
        "todos": {"type": "array"},
    },
}

REACT_DECISION_SCHEMA: dict[str, Any] = {
    "title": "MainAgentReActDecision",
    "type": "object",
    "required": ["reason_summary", "decision"],
    "properties": {
        "reason_summary": {"type": "string"},
        "decision": {
            "type": "string",
            "enum": [
                "delegate_to_specialist",
                "direct_tool_only_when_no_specialist",
                "request_replan",
                "mark_blocked",
                "mark_failed",
            ],
        },
        "action": {"type": "object"},
        "expected_observation": {"type": "string"},
        "fallback_if_failed": {"type": "string"},
    },
    "examples": [
        {
            "reason_summary": "This todo is assigned to VivadoSpecialist, so Main Agent must delegate instead of calling vivado tools.",
            "decision": "delegate_to_specialist",
            "action": {"specialist_name": "VivadoSpecialist"},
            "expected_observation": "SpecialistResult with metrics or structured error.",
        },
        {
            "reason_summary": "This atomic todo has no specialist route and can use the direct validation tool.",
            "decision": "direct_tool_only_when_no_specialist",
            "action": {"tool_name": "task.validate_schema", "arguments": {}},
            "expected_observation": "Validated task schema.",
        },
    ],
}

SPECIALIST_REACT_DECISION_SCHEMA: dict[str, Any] = {
    "title": "SpecialistLocalReActDecision",
    "type": "object",
    "required": ["reason_summary", "decision"],
    "properties": {
        "reason_summary": {"type": "string"},
        "decision": {"type": "string", "enum": ["call_tool", "mark_blocked", "mark_failed", "finish_with_result"]},
        "action": {"type": "object"},
        "expected_observation": {"type": "string"},
    },
}

REFLECTION_DECISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["reason_summary", "decision", "todo_status", "run_status", "new_todos", "memory_candidates"],
    "properties": {
        "reason_summary": {"type": "string"},
        "decision": {"type": "string"},
        "todo_status": {"type": "string"},
        "run_status": {"type": "string"},
        "new_todos": {"type": "array"},
        "memory_candidates": {"type": "array"},
    },
}

OPTIMIZATION_SUGGESTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["summary", "suggestions", "memory_used"],
    "properties": {
        "summary": {"type": "string"},
        "suggestions": {"type": "array"},
        "memory_used": {"type": "array"},
    },
}

CANDIDATE_GENERATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["candidate_name", "files", "assumptions", "requires_verification"],
    "properties": {
        "candidate_name": {"type": "string"},
        "files": {"type": "array"},
        "assumptions": {"type": "array"},
        "requires_verification": {"type": "boolean"},
    },
}


def validate_required(payload: dict[str, Any], schema: dict[str, Any]) -> None:
    required = schema.get("required", [])
    for key in required:
        if key not in payload:
            raise ValueError(f"Missing required key: {key}")
