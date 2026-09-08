"""main_agent layer implementation for __init__.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from .workflow import run_task, run_task_llm

__all__ = ["run_task", "run_task_llm"]
