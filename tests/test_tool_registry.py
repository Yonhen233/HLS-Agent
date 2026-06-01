from dl_op_to_hls.core.tool_registry import ToolRegistry, ToolSpec


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

