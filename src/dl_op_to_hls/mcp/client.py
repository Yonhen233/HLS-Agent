from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any


class MCPProtocolError(RuntimeError):
    pass


class StdioMCPClient:
    """Supervised MCP stdio client with negotiation, timeout, and one reconnect."""

    def __init__(
        self,
        command: list[str],
        *,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        timeout_seconds: float = 30.0,
        name: str = "mcp-server",
        secret_env_names: list[str] | None = None,
    ):
        self.command = list(command)
        self.cwd = str(cwd) if cwd else None
        self.env = dict(env or {})
        self.timeout_seconds = max(0.1, float(timeout_seconds))
        self.name = name
        self.secret_env_names = set(secret_env_names or [])
        self._process: subprocess.Popen[str] | None = None
        self._reader: threading.Thread | None = None
        self._pending: dict[int, queue.Queue[dict[str, Any]]] = {}
        self._pending_lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._next_id = 1
        self.server_info: dict[str, Any] = {}

    @property
    def alive(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self) -> dict[str, Any]:
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
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
        )
        self._reader = threading.Thread(target=self._read_loop, name=f"{self.name}-reader", daemon=True)
        self._reader.start()
        initialized = self.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "dl-op-to-hls-agent", "version": "1.0.0"},
            },
            retry=False,
        )
        self.server_info = dict(initialized)
        self.notify("notifications/initialized", {})
        return self.server_info

    def list_tools(self) -> list[dict[str, Any]]:
        self.start()
        result = self.request("tools/list", {})
        return list(result.get("tools", []))

    def list_resources(self) -> list[dict[str, Any]]:
        self.start()
        return list(self.request("resources/list", {}).get("resources", []))

    def list_prompts(self) -> list[dict[str, Any]]:
        self.start()
        return list(self.request("prompts/list", {}).get("prompts", []))

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.start()
        result = self.request("tools/call", {"name": name, "arguments": arguments})
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
    ) -> dict[str, Any]:
        if not self.alive and method != "initialize":
            self.start()
        request_id = self._allocate_id()
        response_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        with self._pending_lock:
            self._pending[request_id] = response_queue
        try:
            self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
            response = response_queue.get(timeout=timeout_seconds or self.timeout_seconds)
        except (BrokenPipeError, OSError, queue.Empty) as exc:
            with self._pending_lock:
                self._pending.pop(request_id, None)
            if retry:
                self.close()
                self.start()
                return self.request(method, params, timeout_seconds=timeout_seconds, retry=False)
            raise TimeoutError(f"MCP request {method} failed for {self.name}: {exc}") from exc
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
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def close(self) -> None:
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
        process = self._process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            request_id = message.get("id")
            with self._pending_lock:
                target = self._pending.get(request_id)
            if target is not None:
                target.put(message)

    def _send(self, payload: dict[str, Any]) -> None:
        if self._process is None or self._process.stdin is None or self._process.poll() is not None:
            raise BrokenPipeError(f"MCP server {self.name} is not running")
        with self._write_lock:
            self._process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self._process.stdin.flush()

    def _allocate_id(self) -> int:
        with self._pending_lock:
            value = self._next_id
            self._next_id += 1
            return value

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()
