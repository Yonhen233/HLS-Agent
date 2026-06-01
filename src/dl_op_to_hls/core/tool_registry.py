from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable

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


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolSpec] = {}

    def register(self, tool: ToolSpec) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolSpec:
        return self._tools[name]

    def list_tools(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def call(self, name: str, arguments: dict, context: dict) -> dict:
        tool = self.get(name)
        hooks = context.get("hooks")
        permission_gate = context.get("permission_gate")
        run_id = context.get("run_id")
        started = time.time()
        args_hash = stable_hash(arguments)
        if permission_gate is not None:
            permission = permission_gate.check_tool(name, arguments)
            if permission["decision"] != "allow":
                if hooks:
                    hooks.emit(
                        "PermissionDenied",
                        {"run_id": run_id, "tool": name, "reason": permission["reason"], "args_hash": args_hash},
                    )
                return {"status": "error", "error": permission_gate.denied_error(name, permission["reason"])}
        if hooks:
            hooks.emit("PreToolUse", {"run_id": run_id, "tool": name, "args_hash": args_hash})
        try:
            result = tool.handler(arguments=arguments, context=context)
            json.dumps(result, default=str)
            duration_ms = int((time.time() - started) * 1000)
            if hooks:
                hooks.emit(
                    "PostToolUse",
                    {
                        "run_id": run_id,
                        "tool": name,
                        "status": result.get("status", "success"),
                        "args_hash": args_hash,
                        "output_hash": stable_hash(result),
                        "duration_ms": duration_ms,
                    },
                )
            return result
        except Exception as exc:  # pragma: no cover - defensive branch
            duration_ms = int((time.time() - started) * 1000)
            if hooks:
                hooks.emit(
                    "ToolFailed",
                    {
                        "run_id": run_id,
                        "tool": name,
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                        "recoverable": True,
                        "duration_ms": duration_ms,
                    },
                )
            raise
