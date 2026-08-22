from __future__ import annotations

import json
import time
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable

from .budgets import BudgetExceededError
from .errors import build_error
from .json_schema import SchemaValidationError, validate_json_schema
from .trace import stable_hash


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict
    output_schema: dict
    permission_level: str
    handler: Callable[..., dict]
    server: str | None = None
    tags: list[str] | None = None
    idempotent: bool = False
    cacheable: bool = False
    parallel_safe: bool = False
    max_retries: int = 0
    required_capabilities: list[str] | None = None
    risk_level: str = "low"
    timeout_seconds: float | None = None
    network_domains: list[str] | None = None
    credential_audience: str | None = None
    credential_scope: str | None = None
    alias_of: str | None = None


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolSpec] = {}

    def register(self, tool: ToolSpec) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def register_alias(self, alias_name: str, target_name: str) -> None:
        target = self.get(target_name)
        self.register(
            ToolSpec(
                name=alias_name,
                description=f"Compatibility alias of {target_name}",
                input_schema=target.input_schema,
                output_schema=target.output_schema,
                permission_level=target.permission_level,
                handler=target.handler,
                server=target.server,
                tags=[*(target.tags or []), "alias"],
                idempotent=target.idempotent,
                cacheable=target.cacheable,
                parallel_safe=target.parallel_safe,
                max_retries=target.max_retries,
                required_capabilities=list(target.required_capabilities or []),
                risk_level=target.risk_level,
                timeout_seconds=target.timeout_seconds,
                network_domains=list(target.network_domains or []),
                credential_audience=target.credential_audience,
                credential_scope=target.credential_scope,
                alias_of=target_name,
            )
        )

    def get(self, name: str) -> ToolSpec:
        return self._tools[name]

    def list_tools(self, *, include_aliases: bool = True) -> list[ToolSpec]:
        tools = list(self._tools.values())
        return tools if include_aliases else [tool for tool in tools if tool.alias_of is None]

    def call(self, name: str, arguments: dict, context: dict) -> dict:
        requested_tool = self.get(name)
        canonical_name = requested_tool.alias_of or name
        tool = self.get(canonical_name)
        hooks = context.get("hooks")
        permission_gate = context.get("permission_gate")
        run_budget = context.get("run_budget")
        cancellation_token = context.get("cancellation_token")
        run_id = context.get("run_id")
        started = time.time()
        args_hash = stable_hash(arguments)
        if cancellation_token is not None and cancellation_token.cancelled:
            error = build_error(
                "UserInterruptError",
                cancellation_token.reason,
                recoverable=True,
                source=name,
                suggested_action="Resume the durable session to continue from the latest checkpoint.",
            ).to_dict()
            if hooks:
                hooks.emit("ToolCancelled", {"run_id": run_id, "tool": name, "reason": cancellation_token.reason})
            return {"status": "interrupted", "error": error}
        try:
            validate_json_schema(arguments, tool.input_schema, path="$.arguments")
        except SchemaValidationError as exc:
            error = build_error(
                "ToolSchemaError",
                str(exc),
                recoverable=True,
                source=name,
                suggested_action="Repair the tool arguments to match ToolSpec.input_schema.",
            ).to_dict()
            if hooks:
                hooks.emit("ToolSchemaRejected", {"run_id": run_id, "tool": name, "stage": "input", "message": str(exc), "args_hash": args_hash})
            return {"status": "error", "error": error}
        if permission_gate is not None:
            permission = permission_gate.check_tool(
                canonical_name,
                arguments,
                tool_spec=tool,
                principal=context.get("principal"),
            )
            if permission["decision"] == "ask":
                session_id = context.get("session_id")
                session_manager = context.get("session_manager")
                approval_status = None
                if session_id and session_manager is not None:
                    approval_status = session_manager.approval_status(session_id, canonical_name, args_hash)
                approval_consumed = False
                if approval_status == "approved" and session_manager is not None:
                    approval_consumed = session_manager.consume_approval(session_id, canonical_name, args_hash)
                if approval_status == "approved" and approval_consumed:
                    permission = {"decision": "allow", "reason": "Approved for this session and argument hash."}
                elif approval_status == "rejected":
                    permission = {"decision": "deny", "reason": "The user rejected this tool call."}
                else:
                    approval = None
                    if session_id and session_manager is not None:
                        approval = session_manager.create_approval_request(
                            session_id,
                            tool_name=canonical_name,
                            args_hash=args_hash,
                            reason=permission["reason"],
                            ttl_seconds=int(permission_gate.config.get("approvals", {}).get("ttl_seconds", 900)),
                            max_uses=int(permission_gate.config.get("approvals", {}).get("max_uses", 1)),
                        )
                    if hooks:
                        hooks.emit(
                            "ApprovalRequired",
                            {"run_id": run_id, "session_id": session_id, "tool": name, "args_hash": args_hash, "approval_id": (approval or {}).get("approval_id")},
                        )
                    return {
                        "status": "blocked",
                        "approval_id": (approval or {}).get("approval_id"),
                        "error": build_error(
                            "ApprovalRequiredError",
                            permission["reason"],
                            recoverable=True,
                            source=name,
                            suggested_action="Approve or reject the pending session action, then resume the session.",
                        ).to_dict(),
                    }
            if permission["decision"] != "allow":
                if hooks:
                    hooks.emit(
                        "PermissionDenied",
                        {"run_id": run_id, "tool": name, "reason": permission["reason"], "args_hash": args_hash},
                    )
                return {"status": "error", "error": permission_gate.denied_error(name, permission["reason"])}
        cache = context.setdefault("tool_result_cache", {})
        cache_key = f"{canonical_name}:{args_hash}"
        if tool.cacheable and cache_key in cache:
            if run_budget is not None:
                run_budget.record_cache_hit()
            if hooks:
                hooks.emit("ToolCacheHit", {"run_id": run_id, "tool": name, "args_hash": args_hash})
            cached = deepcopy(cache[cache_key])
            cached_receipt = cached.get("evidence_receipt") if isinstance(cached, dict) else None
            if isinstance(cached_receipt, dict):
                context.setdefault("evidence_receipts", []).append(cached_receipt)
            return cached
        try:
            if run_budget is not None:
                run_budget.reserve_tool_call()
        except BudgetExceededError as exc:
            error = build_error(
                "BudgetExceededError",
                str(exc),
                recoverable=True,
                source=name,
                suggested_action="Reduce repeated tool calls or increase the explicit run budget.",
            ).to_dict()
            if hooks:
                hooks.emit("BudgetExceeded", {"run_id": run_id, "tool": name, "budget_type": "tool_calls"})
            return {"status": "error", "error": error}

        credential_lease = None
        if tool.credential_scope:
            broker = context.get("credential_broker")
            tokens = context.get("credential_tokens") or {}
            token = tokens.get(name) or tokens.get(canonical_name) or tokens.get(tool.credential_audience)
            try:
                if broker is None or not token or not tool.credential_audience:
                    raise PermissionError("A scoped short-lived credential is required for this tool.")
                credential_lease = broker.consume(
                    token,
                    run_id=str(run_id),
                    audience=tool.credential_audience,
                    scope=tool.credential_scope,
                )
            except PermissionError as exc:
                if hooks:
                    hooks.emit("CredentialDenied", {"run_id": run_id, "tool": name, "reason": str(exc)})
                return {
                    "status": "error",
                    "error": build_error(
                        "PermissionDeniedError",
                        str(exc),
                        recoverable=True,
                        source=name,
                        suggested_action="Issue a run-bound credential with the required audience and scope.",
                    ).to_dict(),
                }

        attempts = max(1, int(tool.max_retries) + 1 if tool.idempotent else 1)
        for attempt in range(1, attempts + 1):
            if hooks:
                hooks.emit(
                    "PreToolUse",
                    {
                        "run_id": run_id,
                        "tool": name,
                        "server": tool.server,
                        "transport": "mcp" if "remote" in (tool.tags or []) else "in_process",
                        "args_hash": args_hash,
                        "attempt": attempt,
                    },
                )
            try:
                if credential_lease is not None:
                    context.setdefault("leased_credentials", {})[name] = credential_lease
                try:
                    result = tool.handler(arguments=arguments, context=context)
                finally:
                    context.get("leased_credentials", {}).pop(name, None)
                elapsed = time.time() - started
                if tool.timeout_seconds is not None and elapsed > float(tool.timeout_seconds):
                    raise TimeoutError(
                        f"Tool {name} exceeded timeout_seconds={tool.timeout_seconds}; "
                        "the handler must observe the cancellation deadline for hard cancellation."
                    )
                json.dumps(result, default=str)
                validate_json_schema(result, tool.output_schema, path="$.result")
                evidence_registry = context.get("tool_postcondition_registry")
                if evidence_registry is not None:
                    receipt = evidence_registry.verify(canonical_name, arguments, result, context)
                    context.setdefault("evidence_receipts", []).append(receipt)
                    if not receipt.get("valid", False) and str(result.get("status") or "success") in {
                        "success",
                        "supported",
                        "candidate_generated",
                        "verified",
                    }:
                        error = build_error(
                            "ToolPostconditionError",
                            f"Tool {name} returned a success-like status without valid semantic evidence.",
                            recoverable=True,
                            source=name,
                            suggested_action="Repair the tool result, rerun the producing stage, or select a verified fallback.",
                            details={"evidence_receipt": receipt},
                        ).to_dict()
                        if hooks:
                            hooks.emit(
                                "ToolPostconditionFailed",
                                {
                                    "run_id": run_id,
                                    "tool": name,
                                    "args_hash": args_hash,
                                    "receipt_id": receipt.get("receipt_id"),
                                    "checks": receipt.get("checks", []),
                                },
                            )
                        return {"status": "error", "error": error, "evidence_receipt": receipt}
                    result = {**result, "evidence_receipt": receipt}
                    if hooks:
                        hooks.emit(
                            "ToolEvidenceRecorded",
                            {
                                "run_id": run_id,
                                "tool": name,
                                "receipt_id": receipt.get("receipt_id"),
                                "valid": receipt.get("valid"),
                                "mock_evidence": receipt.get("mock_evidence"),
                            },
                        )
                duration_ms = int((time.time() - started) * 1000)
                if tool.cacheable:
                    cache[cache_key] = deepcopy(result)
                if hooks:
                    hooks.emit(
                        "PostToolUse",
                        {
                            "run_id": run_id,
                            "tool": name,
                            "server": tool.server,
                            "transport": "mcp" if "remote" in (tool.tags or []) else "in_process",
                            "status": result.get("status", "success"),
                            "args_hash": args_hash,
                            "output_hash": stable_hash(result),
                            "duration_ms": duration_ms,
                            "attempt": attempt,
                        },
                    )
                return result
            except SchemaValidationError as exc:
                duration_ms = int((time.time() - started) * 1000)
                error = build_error(
                    "ToolSchemaError",
                    str(exc),
                    recoverable=True,
                    source=name,
                    suggested_action="Repair the tool handler output to match ToolSpec.output_schema.",
                ).to_dict()
                if hooks:
                    hooks.emit("ToolSchemaRejected", {"run_id": run_id, "tool": name, "stage": "output", "message": str(exc), "duration_ms": duration_ms})
                return {"status": "error", "error": error}
            except Exception as exc:  # pragma: no cover - defensive branch
                duration_ms = int((time.time() - started) * 1000)
                if attempt < attempts:
                    if hooks:
                        hooks.emit("ToolRetry", {"run_id": run_id, "tool": name, "attempt": attempt, "error_type": type(exc).__name__})
                    continue
                if hooks:
                    hooks.emit(
                        "ToolFailed",
                        {
                            "run_id": run_id,
                            "tool": name,
                            "server": tool.server,
                            "transport": "mcp" if "remote" in (tool.tags or []) else "in_process",
                            "error_type": type(exc).__name__,
                            "args_hash": args_hash,
                            "message": str(exc),
                            "recoverable": True,
                            "duration_ms": duration_ms,
                            "attempt": attempt,
                        },
                    )
                raise
        raise RuntimeError(f"Tool {name} exhausted execution attempts")
