"""mcp layer implementation for client.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable

# This synchronous bridge uses the handshake-based protocol. The official SDK
# server also accepts the newer handshake-free 2026-07-28 request envelopes.
LATEST_STABLE_PROTOCOL_VERSION = "2025-11-25"


class MCPProtocolError(RuntimeError):
    """Coordinate MCPProtocolError within the client boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    pass


class StdioMCPClient:
    """Supervised synchronous MCP stdio client for the Agent ToolRegistry.

    The project runtime is synchronous, so this client provides a small bridge
    to MCP stdio while preserving cancellation, notifications, diagnostics, and
    at-most-once behavior for non-idempotent tool calls.
    """

    def __init__(
        self,
        command: list[str],
        *,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        timeout_seconds: float = 30.0,
        name: str = "mcp-server",
        secret_env_names: list[str] | None = None,
        stderr_path: str | Path | None = None,
        notification_handler: Callable[[dict[str, Any]], None] | None = None,
    ):
        """Implement the internal __init__ helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            command: Value supplied by the caller and validated by the surrounding schema.
            cwd: Value supplied by the caller and validated by the surrounding schema.
            env: Value supplied by the caller and validated by the surrounding schema.
            timeout_seconds: Value supplied by the caller and validated by the surrounding schema.
            name: Value supplied by the caller and validated by the surrounding schema.
            secret_env_names: Value supplied by the caller and validated by the surrounding schema.
            stderr_path: Value supplied by the caller and validated by the surrounding schema.
            notification_handler: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        self.command = list(command)
        self.cwd = str(cwd) if cwd else None
        self.env = dict(env or {})
        self.timeout_seconds = max(0.1, float(timeout_seconds))
        self.name = name
        self.secret_env_names = set(secret_env_names or [])
        self.stderr_path = Path(stderr_path) if stderr_path else None
        self.notification_handler = notification_handler
        self._process: subprocess.Popen[str] | None = None
        self._reader: threading.Thread | None = None
        self._stderr_reader: threading.Thread | None = None
        self._pending: dict[int, queue.Queue[dict[str, Any]]] = {}
        self._pending_lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._next_id = 1
        self._stderr_tail: deque[str] = deque(maxlen=200)
        self.notifications: deque[dict[str, Any]] = deque(maxlen=500)
        self.server_info: dict[str, Any] = {}

    @property
    def alive(self) -> bool:
        """Execute alive at the client boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Returns:
            The structured value promised by the function signature.
        """
        return self._process is not None and self._process.poll() is None

    @property
    def stderr_tail(self) -> list[str]:
        """Execute stderr_tail at the client boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Returns:
            The structured value promised by the function signature.
        """
        return list(self._stderr_tail)

    def start(self) -> dict[str, Any]:
        """Execute start at the client boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Returns:
            The structured value promised by the function signature.
        """
        if self.alive:
            return self.server_info
        process_env = os.environ.copy()
        for secret_name in {
            "DL_OP_TO_HLS_LLM_API_KEY",
            "OPENAI_API_KEY",
            "DEEPSEEK_API_KEY",
            "ANTHROPIC_API_KEY",
        } - self.secret_env_names:
            process_env.pop(secret_name, None)
        process_env.update(self.env)
        process_env["PYTHONUNBUFFERED"] = "1"
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self._process = subprocess.Popen(
            self.command,
            cwd=self.cwd,
            env=process_env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
        )
        self._reader = threading.Thread(target=self._read_loop, name=f"{self.name}-reader", daemon=True)
        self._stderr_reader = threading.Thread(
            target=self._stderr_loop,
            name=f"{self.name}-stderr",
            daemon=True,
        )
        self._reader.start()
        self._stderr_reader.start()
        initialized = self.request(
            "initialize",
            {
                "protocolVersion": LATEST_STABLE_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "dl-op-to-hls-agent", "version": "1.0.0"},
            },
            retry=False,
        )
        negotiated = str(initialized.get("protocolVersion") or "")
        if not negotiated:
            self.close()
            raise MCPProtocolError("MCP server did not return a negotiated protocolVersion")
        self.server_info = dict(initialized)
        self.notify("notifications/initialized", {})
        return self.server_info

    def list_tools(self) -> list[dict[str, Any]]:
        """Execute list_tools at the client boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Returns:
            The structured value promised by the function signature.
        """
        self.start()
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params = {"cursor": cursor} if cursor else {}
            result = self.request("tools/list", params)
            items.extend(result.get("tools", []))
            cursor = result.get("nextCursor")
            if not cursor:
                return items

    def list_resources(self) -> list[dict[str, Any]]:
        """Execute list_resources at the client boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Returns:
            The structured value promised by the function signature.
        """
        self.start()
        return list(self.request("resources/list", {}).get("resources", []))

    def list_prompts(self) -> list[dict[str, Any]]:
        """Execute list_prompts at the client boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Returns:
            The structured value promised by the function signature.
        """
        self.start()
        return list(self.request("prompts/list", {}).get("prompts", []))

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        timeout_seconds: float | None = None,
        cancellation_token: Any = None,
    ) -> dict[str, Any]:
        """Execute call_tool at the client boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            name: Value supplied by the caller and validated by the surrounding schema.
            arguments: Value supplied by the caller and validated by the surrounding schema.
            timeout_seconds: Value supplied by the caller and validated by the surrounding schema.
            cancellation_token: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        self.start()
        # tools/call is never transport-retried: the server may have completed a
        # side effect before the connection failed. ToolRegistry owns safe retry.
        result = self.request(
            "tools/call",
            {
                "name": name,
                "arguments": arguments,
                "_meta": {"progressToken": f"{self.name}:{time.time_ns()}"},
            },
            timeout_seconds=timeout_seconds,
            retry=False,
            cancellation_token=cancellation_token,
        )
        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            return structured
        content = result.get("content") or []
        if content and isinstance(content[0], dict):
            try:
                decoded = json.loads(str(content[0].get("text") or "{}"))
                if isinstance(decoded, dict):
                    return decoded
            except json.JSONDecodeError:
                pass
        return {"status": "error" if result.get("isError") else "success", "content": content}

    def request(
        self,
        method: str,
        params: dict[str, Any],
        *,
        timeout_seconds: float | None = None,
        retry: bool = True,
        cancellation_token: Any = None,
    ) -> dict[str, Any]:
        """Execute request at the client boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            method: Value supplied by the caller and validated by the surrounding schema.
            params: Value supplied by the caller and validated by the surrounding schema.
            timeout_seconds: Value supplied by the caller and validated by the surrounding schema.
            retry: Value supplied by the caller and validated by the surrounding schema.
            cancellation_token: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        if not self.alive and method != "initialize":
            self.start()
        request_id = self._allocate_id()
        response_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        with self._pending_lock:
            self._pending[request_id] = response_queue
        timeout = self.timeout_seconds if timeout_seconds is None else max(0.1, float(timeout_seconds))
        deadline = time.monotonic() + timeout
        try:
            self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
            while True:
                if cancellation_token is not None and cancellation_token.cancelled:
                    self.cancel(request_id, str(cancellation_token.reason))
                    raise InterruptedError(str(cancellation_token.reason))
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self.cancel(request_id, f"Client timeout after {timeout:.3f}s")
                    raise TimeoutError(f"MCP request {method} timed out for {self.name}")
                try:
                    response = response_queue.get(timeout=min(0.1, remaining))
                    break
                except queue.Empty:
                    continue
        except (BrokenPipeError, OSError) as exc:
            if retry:
                self.close()
                self.start()
                return self.request(method, params, timeout_seconds=timeout, retry=False)
            raise MCPProtocolError(f"MCP request {method} failed for {self.name}: {exc}") from exc
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)
        if "error" in response:
            error = response["error"]
            raise MCPProtocolError(f"{error.get('code')}: {error.get('message')}")
        result = response.get("result", {})
        if not isinstance(result, dict):
            raise MCPProtocolError(f"MCP method {method} returned a non-object result")
        return result

    def notify(self, method: str, params: dict[str, Any]) -> None:
        """Execute notify at the client boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            method: Value supplied by the caller and validated by the surrounding schema.
            params: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def cancel(self, request_id: int, reason: str | None = None) -> None:
        """Execute cancel at the client boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            request_id: Value supplied by the caller and validated by the surrounding schema.
            reason: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        if self.alive:
            self.notify("notifications/cancelled", {"requestId": request_id, "reason": reason})

    def close(self) -> None:
        """Execute close at the client boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Returns:
            The structured value promised by the function signature.
        """
        process = self._process
        self._process = None
        if process is None:
            return
        if process.stdin:
            try:
                process.stdin.close()
            except OSError:
                pass
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        with self._pending_lock:
            for response_queue in self._pending.values():
                try:
                    response_queue.put_nowait({"error": {"code": -32000, "message": "MCP server closed"}})
                except queue.Full:
                    pass
            self._pending.clear()

    def _read_loop(self) -> None:
        """Implement the internal _read_loop helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Returns:
            The structured value promised by the function signature.
        """
        process = self._process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                self._record_stderr(f"Invalid MCP stdout frame: {line.rstrip()}")
                continue
            if "method" in message and "id" not in message:
                self.notifications.append(message)
                if self.notification_handler is not None:
                    self.notification_handler(message)
                continue
            request_id = message.get("id")
            with self._pending_lock:
                target = self._pending.get(request_id)
            if target is not None:
                target.put(message)

    def _stderr_loop(self) -> None:
        """Implement the internal _stderr_loop helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Returns:
            The structured value promised by the function signature.
        """
        process = self._process
        if process is None or process.stderr is None:
            return
        for line in process.stderr:
            self._record_stderr(line.rstrip("\r\n"))

    def _record_stderr(self, line: str) -> None:
        """Implement the internal _record_stderr helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            line: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        if not line:
            return
        self._stderr_tail.append(line)
        if self.stderr_path is not None:
            self.stderr_path.parent.mkdir(parents=True, exist_ok=True)
            with self.stderr_path.open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")

    def _send(self, payload: dict[str, Any]) -> None:
        """Implement the internal _send helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            payload: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        if self._process is None or self._process.stdin is None or self._process.poll() is not None:
            raise BrokenPipeError(f"MCP server {self.name} is not running")
        with self._write_lock:
            self._process.stdin.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
            self._process.stdin.flush()

    def _allocate_id(self) -> int:
        """Implement the internal _allocate_id helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Returns:
            The structured value promised by the function signature.
        """
        with self._pending_lock:
            value = self._next_id
            self._next_id += 1
            return value

    def __enter__(self):
        """Implement the internal __enter__ helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Returns:
            The structured value promised by the function signature.
        """
        self.start()
        return self

    def __exit__(self, exc_type, exc, traceback):
        """Implement the internal __exit__ helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            exc_type: Value supplied by the caller and validated by the surrounding schema.
            exc: Value supplied by the caller and validated by the surrounding schema.
            traceback: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        self.close()
