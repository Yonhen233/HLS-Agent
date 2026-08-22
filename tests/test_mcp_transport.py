from __future__ import annotations

import os
import sys
from pathlib import Path

from dl_op_to_hls.adapters.hls4ml_adapter import HLS4MLAdapter
from dl_op_to_hls.mcp.client import StdioMCPClient
from dl_op_to_hls.mcp.server import MCPServer
from dl_op_to_hls.mcp_servers.hls4ml_server import build_hls4ml_registry


def test_mcp_server_negotiates_lists_and_calls_tools():
    server = MCPServer("hls4ml", build_hls4ml_registry(HLS4MLAdapter(mock_mode=True)))
    initialized = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}})
    listed = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    called = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "hls4ml.check_support", "arguments": {"task": {"task_type": "model", "frontend": "onnx"}}},
        }
    )
    assert initialized["result"]["serverInfo"]["name"] == "hls4ml"
    assert any(item["name"] == "hls4ml.convert" for item in listed["result"]["tools"])
    assert called["result"]["structuredContent"]["status"] == "supported"


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
    )
    try:
        assert any(item["name"] == "hls4ml.check_support" for item in client.list_tools())
        result = client.call_tool("hls4ml.check_support", {"task": {"task_type": "model", "frontend": "onnx"}})
        assert result["status"] == "supported"
    finally:
        client.close()
