from __future__ import annotations

from ..core.tool_registry import ToolRegistry, ToolSpec
from ..schemas.tool_schema import simple_schema


def register_vivado_tools(registry: ToolRegistry, adapter) -> None:
    registry.register(
        ToolSpec(
            name="vivado.create_project",
            description="Create a Vivado HLS TCL project wrapper around generated C++ files.",
            input_schema=simple_schema({"hls_project_dir": {"type": "string"}, "work_dir": {"type": "string"}}, ["hls_project_dir", "work_dir"]),
            output_schema=simple_schema({"tcl_path": {"type": "string"}}),
            permission_level="write",
            server="vivado_hls",
            tags=["mcp", "vivado"],
            handler=lambda arguments, context: adapter.create_project(arguments),
        )
    )
    registry.register(
        ToolSpec(
            name="vivado.run_csim",
            description="Run Vivado HLS C simulation.",
            input_schema=simple_schema({"work_dir": {"type": "string"}, "tcl_path": {"type": "string"}}, ["work_dir", "tcl_path"]),
            output_schema=simple_schema({"log_path": {"type": "string"}}),
            permission_level="write",
            server="vivado_hls",
            tags=["mcp", "csim"],
            handler=lambda arguments, context: adapter.run_csim(arguments),
        )
    )
    registry.register(
        ToolSpec(
            name="vivado.run_csynth",
            description="Run Vivado HLS C synthesis.",
            input_schema=simple_schema({"work_dir": {"type": "string"}, "tcl_path": {"type": "string"}}, ["work_dir", "tcl_path"]),
            output_schema=simple_schema({"report_path": {"type": "string"}}),
            permission_level="write",
            server="vivado_hls",
            tags=["mcp", "csynth"],
            handler=lambda arguments, context: adapter.run_csynth(arguments),
        )
    )
    registry.register(
        ToolSpec(
            name="vivado.parse_report",
            description="Parse a Vivado HLS csynth report.",
            input_schema=simple_schema({"report_path": {"type": "string"}}, ["report_path"]),
            output_schema=simple_schema({"status": {"type": "string"}}),
            permission_level="read",
            server="vivado_hls",
            tags=["mcp", "report"],
            handler=lambda arguments, context: adapter.parse_report(arguments),
        )
    )
    registry.register(
        ToolSpec(
            name="vivado.parse_log",
            description="Parse a Vivado HLS log file.",
            input_schema=simple_schema({"log_path": {"type": "string"}}, ["log_path"]),
            output_schema=simple_schema({"summary": {"type": "string"}}),
            permission_level="read",
            server="vivado_hls",
            tags=["mcp", "log"],
            handler=lambda arguments, context: adapter.parse_log(arguments),
        )
    )

