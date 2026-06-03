from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..core.errors import AgentRuntimeError, build_error
from ..llm.prompts import SPECIALIST_REACT_SYSTEM_PROMPT
from ..llm.schemas import SPECIALIST_REACT_DECISION_SCHEMA
from .context import ContextEnvelope


SPECIALIST_REACT_ACTIONS = [
    "call_tool",
    "mark_blocked",
    "mark_failed",
    "finish_with_result",
]


@dataclass
class SpecialistReActGuard:
    def validate(self, decision: dict[str, Any], allowed_tools: list[str], preferred_tool: str | None = None) -> dict[str, Any]:
        errors: list[str] = []
        decision_name = decision.get("decision")
        action = decision.get("action") or {}
        if decision_name not in SPECIALIST_REACT_ACTIONS:
            errors.append(f"Action {decision_name} is not a valid Specialist ReAct action.")
        if decision_name == "call_tool":
            tool_name = action.get("tool_name") or action.get("tool")
            if tool_name not in allowed_tools:
                errors.append(f"Tool {tool_name} is outside specialist allowed_tools.")
        if decision_name == "finish_with_result" and preferred_tool is not None:
            errors.append(f"finish_with_result is not allowed while required tool {preferred_tool} still needs to be called.")
        return {"status": "invalid" if errors else "valid", "errors": errors}


class SpecialistReActDecider:
    def __init__(self, guard: SpecialistReActGuard | None = None):
        self.guard = guard or SpecialistReActGuard()

    def decide(
        self,
        *,
        envelope: ContextEnvelope,
        allowed_tools: list[str],
        recent_observations: list[dict[str, Any]],
        preferred_tool: str | None,
        arguments: dict[str, Any] | None = None,
        client=None,
    ) -> dict[str, Any]:
        arguments = arguments or {}
        if client is not None and client.is_enabled():
            payload = {
                "context_envelope": envelope.to_dict(),
                "allowed_tools": allowed_tools,
                "recent_observations": recent_observations[-5:],
                "preferred_tool": preferred_tool,
                "candidate_arguments": arguments,
                "allowed_actions": SPECIALIST_REACT_ACTIONS,
            }
            decision = client.complete_json(
                system_prompt=SPECIALIST_REACT_SYSTEM_PROMPT,
                user_prompt=json.dumps(payload, ensure_ascii=False, default=str),
                schema=SPECIALIST_REACT_DECISION_SCHEMA,
                temperature=0.0,
            )
        else:
            decision = self._deterministic_decision(preferred_tool, arguments, allowed_tools)

        decision = self._enforce_preferred_tool_contract(decision, preferred_tool, arguments)
        validation = self.guard.validate(decision, allowed_tools, preferred_tool=preferred_tool)
        if validation["status"] != "valid":
            raise AgentRuntimeError(
                build_error(
                    "PermissionDeniedError",
                    "Specialist ReAct decision violated the local action/tool schema.",
                    recoverable=False,
                    source=f"{envelope.specialist_name}.local_react",
                    details={"decision": decision, "validation_errors": validation["errors"]},
                )
            )
        return decision

    def _enforce_preferred_tool_contract(
        self,
        decision: dict[str, Any],
        preferred_tool: str | None,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        if preferred_tool is None:
            return decision
        missing = sorted(key for key, value in arguments.items() if value is None)
        if decision.get("decision") == "call_tool" and missing:
            return {
                "reason_summary": f"Required arguments are missing for {preferred_tool}: {', '.join(missing)}.",
                "decision": "mark_blocked",
                "action": {"missing_inputs": missing, "tool_name": preferred_tool},
            }
        if decision.get("decision") == "finish_with_result":
            return {
                "reason_summary": f"Specialist guard repaired invalid finish_with_result by calling required tool {preferred_tool}.",
                "decision": "call_tool",
                "action": {"tool_name": preferred_tool, "arguments": arguments},
            }
        if decision.get("decision") == "call_tool":
            action = decision.get("action") or {}
            tool_name = action.get("tool_name") or action.get("tool")
            if tool_name != preferred_tool:
                return {
                    "reason_summary": f"Specialist guard repaired tool selection to required tool {preferred_tool}.",
                    "decision": "call_tool",
                    "action": {"tool_name": preferred_tool, "arguments": arguments},
                }
            repaired = dict(decision)
            repaired["action"] = {"tool_name": preferred_tool, "arguments": arguments}
            return repaired
        return decision

    def _deterministic_decision(
        self,
        preferred_tool: str | None,
        arguments: dict[str, Any],
        allowed_tools: list[str],
    ) -> dict[str, Any]:
        if preferred_tool is None:
            return {
                "reason_summary": "No local tool is required; finish with current result.",
                "decision": "finish_with_result",
                "action": {},
            }
        if preferred_tool not in allowed_tools:
            return {
                "reason_summary": f"Preferred tool {preferred_tool} is outside this specialist scope.",
                "decision": "call_tool",
                "action": {"tool_name": preferred_tool, "arguments": arguments},
            }
        missing = sorted(key for key, value in arguments.items() if value is None)
        if missing:
            return {
                "reason_summary": f"Required arguments are missing for {preferred_tool}: {', '.join(missing)}.",
                "decision": "mark_blocked",
                "action": {"missing_inputs": missing, "tool_name": preferred_tool},
            }
        return {
            "reason_summary": f"Call scoped specialist tool {preferred_tool}.",
            "decision": "call_tool",
            "action": {"tool_name": preferred_tool, "arguments": arguments},
            "expected_observation": "Structured tool result or structured error.",
        }
