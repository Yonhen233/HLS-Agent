from __future__ import annotations

import json
import sys
from typing import Any, TextIO


class MCPServer:
    """Minimal MCP JSON-RPC server over newline-delimited stdio."""

    def __init__(self, name: str, registry, *, protocol_version: str = "2024-11-05"):
        self.name = name
        self.registry = registry
        self.protocol_version = protocol_version

    def serve(self, input_stream: TextIO | None = None, output_stream: TextIO | None = None) -> None:
        input_stream = input_stream or sys.stdin
        output_stream = output_stream or sys.stdout
        for line in input_stream:
            if not line.strip():
                continue
            request: Any = None
            try:
                request = json.loads(line)
                response = self.handle(request)
            except Exception as exc:
                response = self._error((request or {}).get("id"), -32603, str(exc))
            if response is not None:
                output_stream.write(json.dumps(response, ensure_ascii=False, default=str) + "\n")
                output_stream.flush()

    def handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        if request.get("jsonrpc") != "2.0":
            return self._error(request.get("id"), -32600, "Invalid JSON-RPC version")
        method = request.get("method")
        request_id = request.get("id")
        params = request.get("params") or {}
        if request_id is None:
            return None
        if method == "initialize":
            requested = str(params.get("protocolVersion") or self.protocol_version)
            return self._result(
                request_id,
                {
                    "protocolVersion": requested,
                    "capabilities": {
                        "tools": {"listChanged": False},
                        "resources": {"subscribe": False, "listChanged": False},
                        "prompts": {"listChanged": False},
                    },
                    "serverInfo": {"name": self.name, "version": "1.0.0"},
                },
            )
        if method == "ping":
            return self._result(request_id, {})
        if method == "tools/list":
            tools = [
                {
                    "name": spec.name,
                    "description": spec.description,
                    "inputSchema": spec.input_schema,
                    "annotations": {
                        "readOnlyHint": spec.permission_level == "read",
                        "idempotentHint": bool(spec.idempotent),
                    },
                }
                for spec in self.registry.list_tools()
            ]
            return self._result(request_id, {"tools": tools})
        if method == "resources/list":
            return self._result(request_id, {"resources": []})
        if method == "prompts/list":
            return self._result(request_id, {"prompts": []})
        if method == "tools/call":
            name = str(params.get("name") or "")
            arguments = params.get("arguments") or {}
            try:
                spec = self.registry.get(name)
            except KeyError:
                return self._error(request_id, -32602, f"Unknown tool: {name}")
            try:
                result = spec.handler(arguments=arguments, context={"mcp_server": self.name})
                is_error = result.get("status") in {"error", "failed"} if isinstance(result, dict) else False
                return self._result(
                    request_id,
                    {
                        "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, default=str)}],
                        "structuredContent": result,
                        "isError": is_error,
                    },
                )
            except Exception as exc:
                return self._result(
                    request_id,
                    {
                        "content": [{"type": "text", "text": str(exc)}],
                        "structuredContent": {"status": "error", "error": {"type": type(exc).__name__, "message": str(exc)}},
                        "isError": True,
                    },
                )
        return self._error(request_id, -32601, f"Method not found: {method}")

    @staticmethod
    def _result(request_id: Any, result: Any) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    @staticmethod
    def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
