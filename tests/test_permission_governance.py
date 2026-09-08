"""Test contracts and regression checks for test_permission_governance.py.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from dl_op_to_hls.core.permissions import PermissionGate
from dl_op_to_hls.core.tool_registry import ToolSpec


def _config():
    """Verify the _config contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    return {
        "filesystem": {"allowed_read_dirs": ["."], "allowed_write_dirs": ["./runs"], "denied_dirs": []},
        "commands": {"allow": ["pytest"], "ask": ["python"], "deny": ["curl"]},
        "network": {
            "allowed_schemes": ["https"],
            "allowed_domains": ["api.deepseek.com"],
            "denied_domains": ["localhost", "169.254.169.254"],
        },
        "limits": {"max_tool_argument_bytes": 10000},
        "approvals": {"risk_levels": ["critical"]},
    }


def _tool(schema, **kwargs):
    """Verify the _tool contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        schema: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    return ToolSpec("test.tool", "test", schema, {"type": "object"}, "read", lambda **_: {}, **kwargs)


def test_nested_schema_annotations_and_network_allowlist(tmp_path):
    """Verify the test_nested_schema_annotations_and_network_allowlist contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    gate = PermissionGate(_config(), tmp_path)
    schema = {
        "type": "object",
        "properties": {
            "nested": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "x-permission": "read_path"},
                    "url": {"type": "string", "x-permission": "url"},
                },
            }
        },
    }
    spec = _tool(schema)
    denied_path = gate.check_tool("test.tool", {"nested": {"path": str(tmp_path.parent / "secret")}}, tool_spec=spec)
    denied_url = gate.check_tool("test.tool", {"nested": {"url": "http://169.254.169.254/latest"}}, tool_spec=spec)
    allowed_url = gate.check_tool("test.tool", {"nested": {"url": "https://api.deepseek.com/v1"}}, tool_spec=spec)
    assert denied_path["decision"] == "deny"
    assert denied_url["decision"] == "deny"
    assert allowed_url["decision"] == "allow"


def test_principal_capabilities_and_risk_approval(tmp_path):
    """Verify the test_principal_capabilities_and_risk_approval contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    gate = PermissionGate(_config(), tmp_path)
    spec = _tool({"type": "object"}, required_capabilities=["workspace.read"])
    assert gate.check_tool("test.tool", {}, tool_spec=spec, principal={"capabilities": ["memory.read"]})["decision"] == "deny"
    critical = _tool({"type": "object"}, risk_level="critical")
    assert gate.check_tool("test.tool", {}, tool_spec=critical)["decision"] == "ask"
