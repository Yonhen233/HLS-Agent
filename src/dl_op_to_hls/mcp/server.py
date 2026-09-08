"""mcp layer implementation for server.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
from pathlib import Path
from typing import Any, Callable

import anyio
from mcp import types
from mcp.server import stdio
from mcp.server.lowlevel import Server as SDKServer


ContextFactory = Callable[[str, dict[str, Any]], dict[str, Any]]


class MCPServer:
    """Production MCP facade backed by the official Python SDK.

    Domain tools remain ToolRegistry entries. The SDK owns protocol lifecycle,
    capability negotiation, cancellation, stdio framing, and Streamable HTTP.
    """

    def __init__(
        self,
        name: str,
        registry,
        *,
        version: str = "1.0.0",
        instructions: str | None = None,
        context_factory: ContextFactory | None = None,
        page_size: int = 100,
        auth: Any | None = None,
        token_verifier: Any | None = None,
    ):
        """Implement the internal __init__ helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            name: Value supplied by the caller and validated by the surrounding schema.
            registry: Value supplied by the caller and validated by the surrounding schema.
            version: Value supplied by the caller and validated by the surrounding schema.
            instructions: Value supplied by the caller and validated by the surrounding schema.
            context_factory: Value supplied by the caller and validated by the surrounding schema.
            page_size: Value supplied by the caller and validated by the surrounding schema.
            auth: Value supplied by the caller and validated by the surrounding schema.
            token_verifier: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        self.name = name
        self.registry = registry
        self.version = version
        self.context_factory = context_factory
        self.page_size = max(1, min(int(page_size), 1000))
        self.auth = auth
        self.token_verifier = token_verifier
        self._cursor_secret = secrets.token_bytes(32)
        self.sdk_server = SDKServer(
            name,
            version=version,
            instructions=instructions or self._default_instructions(),
            on_list_tools=self._list_tools,
            on_call_tool=self._call_tool,
        )

    def serve(self) -> None:
        """Run the standard newline-delimited JSON-RPC stdio transport."""
        anyio.run(self._serve_stdio)

    def serve_http(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 8000,
        path: str = "/mcp",
        stateless: bool = False,
        max_request_body_size: int = 4 * 1024 * 1024,
        max_sessions: int = 100,
        session_idle_timeout: float = 1800,
    ) -> None:
        """Run the standard Streamable HTTP transport.

        Unauthenticated service is deliberately restricted to loopback. Remote
        deployment must use the SDK OAuth 2.1 resource-server integration.
        """
        if host not in {"127.0.0.1", "localhost", "::1"} and not (self.auth and self.token_verifier):
            raise ValueError(
                "Unauthenticated MCP Streamable HTTP may only bind to loopback. "
                "Configure the official SDK OAuth token verifier before remote deployment."
            )
        import uvicorn

        app = self.streamable_http_app(
            host=host,
            path=path,
            stateless=stateless,
            max_request_body_size=max_request_body_size,
            max_sessions=max_sessions,
            session_idle_timeout=session_idle_timeout,
        )
        uvicorn.run(app, host=host, port=int(port), log_level="info")

    def streamable_http_app(
        self,
        *,
        host: str = "127.0.0.1",
        path: str = "/mcp",
        stateless: bool = False,
        json_response: bool = False,
        max_request_body_size: int = 4 * 1024 * 1024,
        max_sessions: int = 100,
        session_idle_timeout: float = 1800,
    ):
        """Build an ASGI Streamable HTTP app for an existing deployment."""
        if host not in {"127.0.0.1", "localhost", "::1"} and not (self.auth and self.token_verifier):
            raise ValueError(
                "Unauthenticated MCP Streamable HTTP may only bind to loopback. "
                "Configure the official SDK OAuth token verifier before remote deployment."
            )
        return self.sdk_server.streamable_http_app(
            streamable_http_path=path,
            json_response=json_response,
            stateless_http=stateless,
            max_request_body_size=max_request_body_size,
            session_idle_timeout=session_idle_timeout,
            max_sessions=max_sessions,
            host=host,
            auth=self.auth,
            token_verifier=self.token_verifier,
        )

    async def _serve_stdio(self) -> None:
        # SDK v2 reserves protocol file descriptors so library output cannot
        # corrupt the JSON-RPC stream on stdout.
        """Implement the internal _serve_stdio helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Returns:
            The structured value promised by the function signature.
        """
        async with stdio.stdio_server() as (read_stream, write_stream):
            await self.sdk_server.run(
                read_stream,
                write_stream,
                self.sdk_server.create_initialization_options(),
            )

    async def _list_tools(
        self,
        _request_context,
        params: types.PaginatedRequestParams | None,
    ) -> types.ListToolsResult:
        """Implement the internal _list_tools helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            _request_context: Value supplied by the caller and validated by the surrounding schema.
            params: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        cursor = self._param(params, "cursor")
        offset = self._decode_cursor(str(cursor)) if cursor else 0
        specs = self.registry.list_tools()
        selected = specs[offset : offset + self.page_size]
        tools = [self._tool_manifest(spec) for spec in selected]
        next_offset = offset + len(selected)
        next_cursor = self._encode_cursor(next_offset) if next_offset < len(specs) else None
        return types.ListToolsResult(tools=tools, nextCursor=next_cursor)

    async def _call_tool(self, request_context, params: types.CallToolRequestParams) -> types.CallToolResult:
        """Implement the internal _call_tool helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            request_context: Value supplied by the caller and validated by the surrounding schema.
            params: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        name = str(self._param(params, "name") or "")
        arguments = self._param(params, "arguments") or {}
        if not isinstance(arguments, dict):
            return self._error_result("Tool arguments must be a JSON object.", "ToolSchemaError")
        try:
            self.registry.get(name)
        except KeyError:
            return self._error_result(f"Unknown tool: {name}", "UnknownToolError")

        await request_context.session.report_progress(0, 1, f"Starting {name}")
        context = self._execution_context(name, arguments)
        context["mcp_request"] = {
            "request_id": str(request_context.request_id),
            "protocol_version": request_context.protocol_version,
        }
        try:
            result = await anyio.to_thread.run_sync(
                lambda: self.registry.call(name, arguments, context),
                abandon_on_cancel=True,
            )
        except anyio.get_cancelled_exc_class():
            raise
        except Exception as exc:  # pragma: no cover - defensive protocol boundary
            await request_context.session.send_log_message(
                "error",
                {"tool": name, "error_type": type(exc).__name__, "message": str(exc)},
                logger=self.name,
                related_request_id=request_context.request_id,
            )
            return self._error_result(str(exc), type(exc).__name__)

        await request_context.session.report_progress(1, 1, f"Finished {name}")
        return self._result(result)

    def _execution_context(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Implement the internal _execution_context helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            name: Value supplied by the caller and validated by the surrounding schema.
            arguments: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        context = dict(self.context_factory(name, arguments) if self.context_factory else {})
        context.setdefault("run_id", f"mcp:{self.name}")
        context.setdefault("mcp_server", self.name)
        return context

    def _tool_manifest(self, spec) -> types.Tool:
        """Implement the internal _tool_manifest helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            spec: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        annotations = types.ToolAnnotations(
            readOnlyHint=spec.permission_level == "read",
            destructiveHint=spec.risk_level in {"high", "critical"},
            idempotentHint=bool(spec.idempotent),
            openWorldHint=bool(spec.network_domains),
        )
        return types.Tool(
            name=spec.name,
            description=spec.description,
            inputSchema=spec.input_schema,
            outputSchema=spec.output_schema or None,
            annotations=annotations,
            _meta={
                "io.dl-op-to-hls/server": spec.server or self.name,
                "io.dl-op-to-hls/risk-level": spec.risk_level,
            },
        )

    @staticmethod
    def _result(result: Any) -> types.CallToolResult:
        """Implement the internal _result helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            result: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        structured = result if isinstance(result, dict) else {"status": "success", "value": result}
        status = str(structured.get("status") or "success")
        is_error = status in {"error", "failed", "timeout", "interrupted", "blocked"}
        text = json.dumps(structured, ensure_ascii=False, default=str)
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=text)],
            structuredContent=structured,
            isError=is_error,
        )

    @staticmethod
    def _error_result(message: str, error_type: str) -> types.CallToolResult:
        """Implement the internal _error_result helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            message: Value supplied by the caller and validated by the surrounding schema.
            error_type: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        return MCPServer._result(
            {
                "status": "error",
                "error": {
                    "error_type": error_type,
                    "message": message,
                    "recoverable": False,
                    "source": "mcp.server",
                },
            }
        )

    @staticmethod
    def _param(params: Any, name: str) -> Any:
        """Implement the internal _param helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            params: Value supplied by the caller and validated by the surrounding schema.
            name: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        if params is None:
            return None
        if isinstance(params, dict):
            return params.get(name)
        return getattr(params, name, None)

    def _encode_cursor(self, offset: int) -> str:
        """Implement the internal _encode_cursor helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            offset: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        payload = f"tools:{offset}".encode("ascii")
        signature = hmac.new(self._cursor_secret, payload, hashlib.sha256).digest()[:12]
        encoded_payload = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
        encoded_signature = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
        return f"{encoded_payload}.{encoded_signature}"

    def _decode_cursor(self, cursor: str) -> int:
        """Implement the internal _decode_cursor helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            cursor: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        try:
            payload_text, signature_text = cursor.split(".", 1)
            payload = base64.urlsafe_b64decode((payload_text + "=" * (-len(payload_text) % 4)).encode("ascii"))
            signature = base64.urlsafe_b64decode(
                (signature_text + "=" * (-len(signature_text) % 4)).encode("ascii")
            )
            expected = hmac.new(self._cursor_secret, payload, hashlib.sha256).digest()[:12]
            if not hmac.compare_digest(signature, expected):
                raise ValueError
            prefix, raw_offset = payload.decode("ascii").split(":", 1)
            if prefix != "tools":
                raise ValueError
            return max(0, int(raw_offset))
        except (ValueError, TypeError, binascii.Error) as exc:
            raise ValueError("Invalid or expired MCP pagination cursor.") from exc

    def _default_instructions(self) -> str:
        """Implement the internal _default_instructions helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Returns:
            The structured value promised by the function signature.
        """
        return (
            f"{self.name} exposes bounded HLS tools. Call tools only with paths permitted by their JSON "
            "schemas; large logs and reports are returned as artifact references or structured summaries."
        )


def build_mcp_context_factory(config, *, server_name: str) -> ContextFactory:
    """Create a defense-in-depth ToolRegistry context for standalone servers."""
    import copy

    from ..core.permissions import PermissionGate
    from ..core.hooks import HookManager
    from ..core.trace import TraceHook, TraceWriter

    permission_config = copy.deepcopy(config.load_permissions())
    filesystem = permission_config.setdefault("filesystem", {})
    for key in ("allowed_read_dirs", "allowed_write_dirs"):
        allowed = list(filesystem.get(key) or [])
        runs_root = str(Path(config.runs_root).resolve())
        if runs_root not in allowed:
            allowed.append(runs_root)
        filesystem[key] = allowed
    permission_gate = PermissionGate(permission_config, config.workspace_root)
    hooks = HookManager()
    hooks.register(
        "*",
        TraceHook(
            TraceWriter(
                Path(config.runs_root) / "mcp" / f"{server_name}.trace.jsonl",
                run_id=f"mcp:{server_name}",
            )
        ),
    )

    def factory(_tool_name: str, _arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute factory at the server boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            _tool_name: Value supplied by the caller and validated by the surrounding schema.
            _arguments: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        return {
            "run_id": f"mcp:{server_name}",
            "permission_gate": permission_gate,
            "hooks": hooks,
            "principal": {"name": f"mcp:{server_name}", "capabilities": ["hls.inspect", "hls.execute"]},
        }

    return factory
