"""mcp layer implementation for __init__.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from .client import StdioMCPClient
from .proxy import register_mcp_proxy_tools
from .server import MCPServer

__all__ = ["MCPServer", "StdioMCPClient", "register_mcp_proxy_tools"]
