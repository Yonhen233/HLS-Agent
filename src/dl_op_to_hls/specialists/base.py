"""specialists layer implementation for base.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from ..core.errors import build_error
from ..core.token_budget import TokenBudgetManager
from .context import ContextEnvelope
from .react import SpecialistReActDecider
from .result import SpecialistResult


def _snake_name(name: str) -> str:
    """Implement the internal _snake_name helper.

    Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

    Args:
        name: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    normalized = name.replace("HLS4ML", "Hls4ml")
    return re.sub(r"(?<!^)(?=[A-Z])", "_", normalized).lower()


class BaseSpecialist(ABC):
    """Coordinate BaseSpecialist within the base boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    name: str = "BaseSpecialist"
    description: str = ""
    allowed_tools: list[str] = []

    def __init__(self, runtime_context: dict[str, Any] | None = None):
        """Implement the internal __init__ helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            runtime_context: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        self.runtime_context = runtime_context or {}
        self.local_react_decider = SpecialistReActDecider()
        self.token_budget_manager = TokenBudgetManager()

    def set_runtime_context(self, runtime_context: dict[str, Any]) -> None:
        """Execute set_runtime_context at the base boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            runtime_context: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        self.runtime_context = runtime_context

    @abstractmethod
    def can_handle(self, todo) -> bool:
        """Execute can_handle at the base boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            todo: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        ...

    @abstractmethod
    def handle(self, envelope: ContextEnvelope, tool_registry, permission_gate) -> SpecialistResult:
        """Execute handle at the base boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            envelope: Value supplied by the caller and validated by the surrounding schema.
            tool_registry: Value supplied by the caller and validated by the surrounding schema.
            permission_gate: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        ...

    def _tool_context(self, envelope: ContextEnvelope, permission_gate) -> dict[str, Any]:
        """Implement the internal _tool_context helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            envelope: Value supplied by the caller and validated by the surrounding schema.
            permission_gate: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        context = dict(self.runtime_context)
        context.setdefault("run_id", envelope.run_id)
        context.setdefault("permission_gate", permission_gate)
        context["principal"] = {
            "type": "specialist",
            "id": self.name,
            "capabilities": self._capabilities(),
        }
        return context

    def _capabilities(self) -> list[str]:
        """Implement the internal _capabilities helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Returns:
            The structured value promised by the function signature.
        """
        capabilities: set[str] = set()
        for tool in self.allowed_tools:
            if tool.startswith("workspace."):
                capabilities.add("workspace.read")
            elif tool.startswith(("memory.retrieve", "rag.", "trace.")):
                capabilities.add("memory.read")
            elif tool.startswith("memory."):
                capabilities.add("memory.write")
            elif tool.startswith(("hls4ml.", "vivado.")):
                capabilities.update({"hls.inspect", "hls.execute"})
        return sorted(capabilities)

    def _call_tool(self, tool_name: str, arguments: dict[str, Any], envelope: ContextEnvelope, tool_registry, permission_gate) -> dict[str, Any]:
        """Implement the internal _call_tool helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            tool_name: Value supplied by the caller and validated by the surrounding schema.
            arguments: Value supplied by the caller and validated by the surrounding schema.
            envelope: Value supplied by the caller and validated by the surrounding schema.
            tool_registry: Value supplied by the caller and validated by the surrounding schema.
            permission_gate: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        if tool_name not in envelope.allowed_tools or tool_name not in self.allowed_tools:
            error = build_error(
                "PermissionDeniedError",
                "Specialist attempted to call a tool outside its allowed tool list.",
                recoverable=False,
                source=f"{self.name}.{tool_name}",
                details={"tool": tool_name, "allowed_tools": envelope.allowed_tools},
            )
            return {"status": "error", "error": error.to_dict()}
        return tool_registry.call(tool_name, arguments, self._tool_context(envelope, permission_gate))

    def _local_react_step(
        self,
        envelope: ContextEnvelope,
        observations: list[dict[str, Any]],
        preferred_tool: str | None,
        arguments: dict[str, Any] | None = None,
        force_deterministic: bool = False,
    ) -> dict[str, Any]:
        """Implement the internal _local_react_step helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            envelope: Value supplied by the caller and validated by the surrounding schema.
            observations: Value supplied by the caller and validated by the surrounding schema.
            preferred_tool: Value supplied by the caller and validated by the surrounding schema.
            arguments: Value supplied by the caller and validated by the surrounding schema.
            force_deterministic: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        legacy_enabled = str(
            self.runtime_context.get(
                "specialist_llm_decider_enabled",
                os.environ.get("DL_OP_TO_HLS_SPECIALIST_LLM_DECIDER_ENABLED", "0"),
            )
        ).lower() in {"1", "true", "yes", "on"}
        mode = str(
            self.runtime_context.get(
                "specialist_llm_mode",
                os.environ.get("DL_OP_TO_HLS_SPECIALIST_LLM_MODE", "always" if legacy_enabled else "off"),
            )
        ).lower()
        has_failure_observation = any(
            str((item.get("result") or item).get("status", "")).lower() in {"failed", "error", "blocked"}
            for item in observations
            if isinstance(item, dict) and isinstance(item.get("result") or item, dict)
        )
        needs_reasoning = preferred_tool is None or has_failure_observation or (not arguments and len(envelope.allowed_tools) > 1)
        llm_decider_enabled = legacy_enabled and (mode == "always" or (mode == "adaptive" and needs_reasoning))
        if force_deterministic:
            llm_decider_enabled = False
        decision = self.local_react_decider.decide(
            envelope=envelope,
            allowed_tools=[tool for tool in envelope.allowed_tools if tool in self.allowed_tools],
            recent_observations=observations,
            preferred_tool=preferred_tool,
            arguments=arguments or {},
            client=self.runtime_context.get("llm_client") if llm_decider_enabled else None,
        )
        observations.append({"type": "local_react", "decision": decision})
        return decision

    def _blocked_result_from_decision(
        self,
        envelope: ContextEnvelope,
        observations: list[dict[str, Any]],
        decision: dict[str, Any],
    ) -> SpecialistResult:
        """Implement the internal _blocked_result_from_decision helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            envelope: Value supplied by the caller and validated by the surrounding schema.
            observations: Value supplied by the caller and validated by the surrounding schema.
            decision: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        return SpecialistResult(
            specialist_name=self.name,
            todo_id=envelope.todo_id,
            status="blocked",
            summary=decision.get("reason_summary") or "Specialist local ReAct marked the todo blocked.",
            observations=observations,
            warnings=[{"message": decision.get("reason_summary", "Blocked by local ReAct."), "action": decision.get("action", {})}],
        )

    def _failed_result_from_decision(
        self,
        envelope: ContextEnvelope,
        observations: list[dict[str, Any]],
        decision: dict[str, Any],
    ) -> SpecialistResult:
        """Implement the internal _failed_result_from_decision helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            envelope: Value supplied by the caller and validated by the surrounding schema.
            observations: Value supplied by the caller and validated by the surrounding schema.
            decision: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        error = build_error(
            (decision.get("action") or {}).get("error_type") or "LLMGenerationError",
            decision.get("reason_summary") or (decision.get("action") or {}).get("message") or "Specialist local ReAct failed.",
            recoverable=False,
            source=f"{self.name}.local_react",
            details={"decision": decision},
        )
        return SpecialistResult(
            specialist_name=self.name,
            todo_id=envelope.todo_id,
            status="failed",
            summary=error.message,
            observations=observations,
            errors=[error.to_dict()],
        )

    def _artifact_usage(self, envelope: ContextEnvelope) -> dict[str, Any]:
        """Implement the internal _artifact_usage helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            envelope: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        raw_artifacts: list[str] = []
        raw_bytes = 0
        for ref in envelope.artifact_refs:
            path = ref.get("path")
            if not path:
                continue
            candidate = Path(path)
            if candidate.exists() and candidate.is_file():
                raw_artifacts.append(str(candidate))
                raw_bytes += candidate.stat().st_size
        return {"raw_artifacts_read": raw_artifacts, "raw_bytes_read": raw_bytes}

    def _finalize_result(self, envelope: ContextEnvelope, result: SpecialistResult) -> SpecialistResult:
        """Implement the internal _finalize_result helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            envelope: Value supplied by the caller and validated by the surrounding schema.
            result: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        usage = self._artifact_usage(envelope)
        summary_bytes = len(json.dumps(result.to_dict(), ensure_ascii=False, default=str).encode("utf-8"))
        raw_bytes = usage["raw_bytes_read"]
        envelope_budget = envelope.constraints.get("token_budget", {})
        result.context_usage = {
            **usage,
            "summary_bytes_returned": summary_bytes,
            "compression_ratio": round(summary_bytes / raw_bytes, 6) if raw_bytes else 1.0,
            "estimated_input_tokens": envelope_budget.get("estimated_input_tokens")
            or self.token_budget_manager.estimate_tokens(envelope.to_dict()),
            "estimated_output_tokens": self.token_budget_manager.estimate_tokens(result.to_dict()),
            "max_context_tokens": envelope.max_context_tokens,
            "context_truncated": bool(envelope_budget.get("truncated")),
        }
        self._write_local_outputs(envelope, result)
        return result

    def _write_local_outputs(self, envelope: ContextEnvelope, result: SpecialistResult) -> None:
        """Implement the internal _write_local_outputs helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            envelope: Value supplied by the caller and validated by the surrounding schema.
            result: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        artifact_manager = self.runtime_context.get("artifact_manager")
        relative_dir = f"specialists/{_snake_name(self.name)}"
        summary_payload = result.to_dict()
        if artifact_manager:
            summary_path = artifact_manager.write_json(f"{relative_dir}/summary.json", summary_payload, "specialist_summary")
            result.artifacts.append({"type": "specialist_summary", "path": str(summary_path), "specialist": self.name})
            trace_path = artifact_manager.write_text(
                f"{relative_dir}/trace.jsonl",
                json.dumps(
                    {
                        "event": "SpecialistLocalSummary",
                        "run_id": envelope.run_id,
                        "todo_id": envelope.todo_id,
                        "specialist": self.name,
                        "status": result.status,
                    },
                    ensure_ascii=False,
                    default=str,
                )
                + "\n",
                "specialist_trace",
            )
            result.artifacts.append({"type": "specialist_trace", "path": str(trace_path), "specialist": self.name})
