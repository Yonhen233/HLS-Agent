from __future__ import annotations

import os
import sys
from pathlib import Path

import anyio
import pytest
from starlette.testclient import TestClient

from dl_op_to_hls.adapters.hls4ml_adapter import HLS4MLAdapter
from dl_op_to_hls.mcp.client import LATEST_STABLE_PROTOCOL_VERSION, StdioMCPClient
from dl_op_to_hls.mcp.server import MCPServer
from dl_op_to_hls.mcp_servers.hls4ml_server import build_hls4ml_registry


def test_official_sdk_manifest_exposes_input_and_output_schemas():
    server = MCPServer("hls4ml", build_hls4ml_registry(HLS4MLAdapter(mock_mode=True)), page_size=2)

    first = anyio.run(server._list_tools, None, None)
    assert len(first.tools) == 2
    assert first.next_cursor
    assert first.tools[0].input_schema["type"] == "object"
    assert first.tools[0].output_schema["type"] == "object"
    assert first.tools[0].annotations.read_only_hint is True

    second = anyio.run(server._list_tools, None, {"cursor": first.next_cursor})
    assert second.tools


def test_mcp_cursor_is_opaque_and_tamper_evident():
    server = MCPServer("hls4ml", build_hls4ml_registry(HLS4MLAdapter(mock_mode=True)), page_size=1)
    first = anyio.run(server._list_tools, None, None)
    with pytest.raises(ValueError, match="Invalid or expired"):
        server._decode_cursor(first.next_cursor + "tampered")


def test_streamable_http_requires_loopback_without_oauth():
    server = MCPServer("hls4ml", build_hls4ml_registry(HLS4MLAdapter(mock_mode=True)))
    with pytest.raises(ValueError, match="OAuth"):
        server.serve_http(host="0.0.0.0")


def test_streamable_http_performs_standard_initialize_handshake():
    server = MCPServer("hls4ml", build_hls4ml_registry(HLS4MLAdapter(mock_mode=True)))
    app = server.streamable_http_app(stateless=True, json_response=True)
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": LATEST_STABLE_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "transport-test", "version": "1.0"},
        },
    }
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        response = client.post(
            "/mcp",
            json=payload,
            headers={"Accept": "application/json, text/event-stream"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["result"]["protocolVersion"] == LATEST_STABLE_PROTOCOL_VERSION
    assert body["result"]["capabilities"]["tools"] == {"listChanged": False}


def test_real_stdio_mcp_client_round_trip(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    python_path = str(project_root / "src")
    prior = os.environ.get("PYTHONPATH")
    env = {"PYTHONPATH": python_path + (os.pathsep + prior if prior else ""), "DL_OP_TO_HLS_MOCK_TOOLS": "1"}
    client = StdioMCPClient(
        [sys.executable, "-m", "dl_op_to_hls.cli", "serve-hls4ml"],
        cwd=tmp_path,
        env=env,
        timeout_seconds=10,
        name="hls4ml-test",
        stderr_path=tmp_path / "server.stderr.log",
    )
    try:
        tools = client.list_tools()
        manifest = next(item for item in tools if item["name"] == "hls4ml.check_support")
        assert client.server_info["protocolVersion"] == LATEST_STABLE_PROTOCOL_VERSION
        assert manifest["outputSchema"]["type"] == "object"
        result = client.call_tool("hls4ml.check_support", {"task": {"task_type": "model", "frontend": "onnx"}})
        assert result["status"] == "supported"
        methods = {item["method"] for item in client.notifications}
        assert "notifications/progress" in methods
    finally:
        client.close()
