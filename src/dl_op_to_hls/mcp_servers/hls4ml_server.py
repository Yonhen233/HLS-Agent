"""mcp_servers layer implementation for hls4ml_server.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

from ..core.tool_registry import ToolRegistry, ToolSpec
from ..schemas.tool_schema import simple_schema


def register_hls4ml_tools(registry: ToolRegistry, adapter) -> None:
    """Execute register_hls4ml_tools at the hls4ml_server boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Args:
        registry: Value supplied by the caller and validated by the surrounding schema.
        adapter: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    registry.register(
        ToolSpec(
            name="hls4ml.inspect_model",
            description="Inspect a model and return lightweight layer metadata.",
            input_schema=simple_schema({"model_path": {"type": "string"}, "frontend": {"type": "string"}}, ["model_path", "frontend"]),
            output_schema=simple_schema({"status": {"type": "string"}}),
            permission_level="read",
            server="hls4ml",
            tags=["mcp", "model"],
            handler=lambda arguments, context: adapter.inspect_model(arguments["model_path"], arguments["frontend"]),
        )
    )
    registry.register(
        ToolSpec(
            name="hls4ml.check_support",
            description="Check whether the task is supported by hls4ml.",
            input_schema=simple_schema({"task": {"type": "object"}}, ["task"]),
            output_schema=simple_schema({"status": {"type": "string"}}),
            permission_level="read",
            server="hls4ml",
            tags=["mcp", "support"],
            handler=lambda arguments, context: adapter.check_support(arguments["task"]),
        )
    )
    registry.register(
        ToolSpec(
            name="hls4ml.generate_config",
            description="Generate an hls4ml configuration file.",
            input_schema=simple_schema({"model_path": {"type": "string"}, "output_dir": {"type": "string"}}, ["model_path", "output_dir"]),
            output_schema=simple_schema({"config_path": {"type": "string"}}),
            permission_level="write",
            server="hls4ml",
            tags=["mcp", "config"],
            handler=lambda arguments, context: adapter.generate_config(arguments),
        )
    )
    registry.register(
        ToolSpec(
            name="hls4ml.convert",
            description="Convert a supported model with hls4ml.",
            input_schema=simple_schema({"model_path": {"type": "string"}, "output_dir": {"type": "string"}}, ["model_path", "output_dir"]),
            output_schema=simple_schema({"hls_project_dir": {"type": "string"}}),
            permission_level="write",
            server="hls4ml",
            tags=["mcp", "convert"],
            handler=lambda arguments, context: adapter.convert(arguments),
        )
    )
    registry.register(
        ToolSpec(
            name="hls4ml.run_csim",
            description="Run hls4ml-generated csim flow.",
            input_schema=simple_schema({"hls_project_dir": {"type": "string"}}, ["hls_project_dir"]),
            output_schema=simple_schema({"log_path": {"type": "string"}}),
            permission_level="write",
            server="hls4ml",
            tags=["mcp", "csim"],
            handler=lambda arguments, context: adapter.run_csim(arguments["hls_project_dir"]),
        )
    )


def build_hls4ml_registry(adapter) -> ToolRegistry:
    """Execute build_hls4ml_registry at the hls4ml_server boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Args:
        adapter: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    registry = ToolRegistry()
    register_hls4ml_tools(registry, adapter)
    return registry
