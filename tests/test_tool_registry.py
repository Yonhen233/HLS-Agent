from dl_op_to_hls.core.tool_registry import ToolRegistry, ToolSpec
from dl_op_to_hls.core.trace import stable_hash
from dl_op_to_hls.core.permissions import PermissionGate
from dl_op_to_hls.core.sessions import SessionManager


def test_tool_registry_registers_tools():
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="demo.tool",
            description="demo",
            input_schema={},
            output_schema={},
            permission_level="read",
            handler=lambda arguments, context: {"status": "success"},
        )
    )
    assert registry.get("demo.tool").name == "demo.tool"
    assert len(registry.list_tools()) == 1


def test_alias_is_hidden_from_model_catalog_and_inherits_governance():
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="demo.read",
            description="canonical",
            input_schema={},
            output_schema={},
            permission_level="read",
            handler=lambda arguments, context: {"status": "success"},
            idempotent=True,
            cacheable=True,
            parallel_safe=True,
            required_capabilities=["workspace.read"],
            risk_level="medium",
        )
    )
    registry.register_alias("demo.legacy_read", "demo.read")

    alias = registry.get("demo.legacy_read")
    assert alias.alias_of == "demo.read"
    assert alias.required_capabilities == ["workspace.read"]
    assert alias.cacheable is True and alias.parallel_safe is True
    assert [tool.name for tool in registry.list_tools(include_aliases=False)] == ["demo.read"]


def test_duplicate_tool_registration_is_rejected():
    registry = ToolRegistry()
    spec = ToolSpec("demo.same", "demo", {}, {}, "read", lambda arguments, context: {})
    registry.register(spec)
    import pytest
    with pytest.raises(ValueError, match="already registered"):
        registry.register(spec)


def test_alias_and_canonical_name_share_cache_identity():
    registry = ToolRegistry()
    calls = {"count": 0}

    def handler(arguments, context):
        calls["count"] += 1
        return {"status": "success"}

    registry.register(ToolSpec("demo.canonical", "demo", {}, {}, "read", handler, idempotent=True, cacheable=True))
    registry.register_alias("demo.alias", "demo.canonical")
    context = {"run_id": "r1", "hooks": None, "permission_gate": None}
    registry.call("demo.alias", {}, context)
    registry.call("demo.canonical", {}, context)
    assert calls["count"] == 1


def test_tool_registry_calls_tool():
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="demo.tool",
            description="demo",
            input_schema={},
            output_schema={},
            permission_level="read",
            handler=lambda arguments, context: {"status": "success", "echo": arguments["value"]},
        )
    )
    result = registry.call("demo.tool", {"value": 7}, {"run_id": "r1", "hooks": None, "permission_gate": None})
    assert result["echo"] == 7


def test_tool_registry_enforces_input_and_output_contracts():
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="demo.typed",
            description="typed",
            input_schema={"type": "object", "properties": {"value": {"type": "integer"}}, "required": ["value"]},
            output_schema={"type": "object", "properties": {"status": {"type": "string"}}, "required": ["status"]},
            permission_level="read",
            handler=lambda arguments, context: {"status": "success"},
        )
    )

    rejected = registry.call("demo.typed", {"value": "bad"}, {"run_id": "r1", "hooks": None, "permission_gate": None})
    accepted = registry.call("demo.typed", {"value": 7}, {"run_id": "r1", "hooks": None, "permission_gate": None})

    assert rejected["error"]["error_type"] == "ToolSchemaError"
    assert accepted["status"] == "success"


def test_tool_registry_caches_only_explicitly_cacheable_tools():
    registry = ToolRegistry()
    calls = {"count": 0}

    def handler(arguments, context):
        calls["count"] += 1
        return {"status": "success", "value": arguments["value"]}

    registry.register(
        ToolSpec(
            name="demo.cacheable",
            description="cacheable",
            input_schema={},
            output_schema={},
            permission_level="read",
            handler=handler,
            idempotent=True,
            cacheable=True,
        )
    )
    context = {"run_id": "r1", "hooks": None, "permission_gate": None}
    registry.call("demo.cacheable", {"value": 7}, context)
    registry.call("demo.cacheable", {"value": 7}, context)

    assert calls["count"] == 1


def test_tool_registry_pauses_for_session_approval(tmp_path):
    registry = ToolRegistry()
    calls = {"count": 0}

    def handler(arguments, context):
        calls["count"] += 1
        return {"status": "success"}

    registry.register(
        ToolSpec(
            name="demo.command",
            description="command",
            input_schema={},
            output_schema={},
            permission_level="write",
            handler=handler,
        )
    )
    manager = SessionManager(tmp_path / "sessions")
    manager.create("run", "session_demo")
    gate = PermissionGate(
        {
            "filesystem": {"allowed_read_dirs": ["."], "allowed_write_dirs": ["."], "denied_dirs": []},
            "commands": {"allow": [], "ask": ["python"], "deny": []},
        },
        tmp_path,
    )
    context = {
        "run_id": "r1",
        "hooks": None,
        "permission_gate": gate,
        "session_id": "session_demo",
        "session_manager": manager,
    }

    blocked = registry.call("demo.command", {"command": ["python", "script.py"]}, context)
    assert manager.get("session_demo")["status"] == "waiting_for_approval"
    manager.decide_approval("session_demo", blocked["approval_id"], "approved")
    allowed = registry.call("demo.command", {"command": ["python", "script.py"]}, context)
    replay = registry.call("demo.command", {"command": ["python", "script.py"]}, context)

    assert blocked["status"] == "blocked"
    assert allowed["status"] == "success"
    assert replay["status"] == "blocked"
    assert calls["count"] == 1
    assert manager.approval_status("session_demo", "demo.command", stable_hash({"command": ["python", "script.py"]})) == "consumed"
