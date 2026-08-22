from __future__ import annotations

from typing import Any


MAIN_AGENT_ACTIONS = [
    "delegate_to_specialist",
    "direct_tool_only_when_no_specialist",
    "request_replan",
    "mark_blocked",
    "mark_failed",
]


def main_agent_action_schema() -> dict[str, Any]:
    return {
        "actions": [
            {
                "name": "delegate_to_specialist",
                "when": "Use only when the todo is assigned to a specialist.",
                "allowed_action_payload": {"specialist_name": "string"},
            },
            {
                "name": "direct_tool_only_when_no_specialist",
                "when": "Use only for atomic todos that have no specialist route.",
                "allowed_action_payload": {"tool_name": "string", "arguments": "object"},
            },
            {
                "name": "request_replan",
                "when": "Use when the current todo cannot proceed under the current plan.",
                "allowed_action_payload": {"reason": "string"},
            },
            {
                "name": "mark_blocked",
                "when": "Use when dependencies or required artifacts are missing.",
                "allowed_action_payload": {"reason": "string"},
            },
            {
                "name": "mark_failed",
                "when": "Use when the todo has an unrecoverable contract or execution error.",
                "allowed_action_payload": {"reason": "string"},
            },
        ],
        "rules": [
            "Main Agent may delegate specialist-owned todos but must not call specialist private tools directly.",
            "Specialist private tools are visible only inside the specialist ContextEnvelope.",
            "Direct tool execution is allowed only when no specialist is routed for the todo.",
        ],
    }


def build_layered_tool_view(tool_registry, specialist_router) -> dict[str, Any]:
    canonical_tools = tool_registry.list_tools(include_aliases=False)
    specialist_specs = specialist_router.list_specialists()
    specialist_private_tools = {
        tool_name
        for specialist in specialist_specs
        for tool_name in specialist.get("allowed_tools", [])
    }
    direct_tools = [
        tool.name
        for tool in canonical_tools
        if tool.name not in specialist_private_tools
    ]
    direct_tool_specs = [
        {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.input_schema,
            "output_schema": tool.output_schema,
            "permission_level": tool.permission_level,
            "idempotent": tool.idempotent,
            "cacheable": tool.cacheable,
            "parallel_safe": tool.parallel_safe,
            "risk_level": tool.risk_level,
            "required_capabilities": tool.required_capabilities or [],
        }
        for tool in canonical_tools
        if tool.name in direct_tools
    ]
    specialists = [
        {
            "name": item.get("name"),
            "description": item.get("description"),
            "capability_tools": item.get("allowed_tools", []),
        }
        for item in specialist_specs
    ]
    return {
        "main_agent_actions": main_agent_action_schema(),
        "direct_tools": direct_tools,
        "direct_tool_specs": direct_tool_specs,
        "specialists": specialists,
    }
