"""core layer implementation for hooks.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable


HookHandler = Callable[[dict[str, Any]], None]


class HookManager:
    """Coordinate HookManager within the hooks boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    def __init__(self):
        """Implement the internal __init__ helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Returns:
            The structured value promised by the function signature.
        """
        self._handlers: dict[str, list[HookHandler]] = defaultdict(list)

    def register(self, event_name: str, handler: HookHandler) -> None:
        """Execute register at the hooks boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            event_name: Value supplied by the caller and validated by the surrounding schema.
            handler: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        self._handlers[event_name].append(handler)

    def emit(self, event_name: str, payload: dict[str, Any]) -> None:
        """Execute emit at the hooks boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            event_name: Value supplied by the caller and validated by the surrounding schema.
            payload: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        enriched = dict(payload)
        enriched.setdefault("event", event_name)
        for handler in self._handlers.get(event_name, []):
            handler(enriched)
        for handler in self._handlers.get("*", []):
            handler(enriched)


@dataclass
class ConsoleHook:
    """Coordinate ConsoleHook within the hooks boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    enabled: bool = True

    def __call__(self, payload: dict[str, Any]) -> None:
        """Implement the internal __call__ helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            payload: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        if not self.enabled:
            return
        event = payload.get("event", "Event")
        tool = payload.get("tool")
        status = payload.get("status")
        if tool and status:
            print(f"[{event}] {tool} -> {status}")
        elif tool:
            print(f"[{event}] {tool}")
        else:
            print(f"[{event}] {payload.get('message', '')}".rstrip())


@dataclass
class ArtifactHook:
    """Coordinate ArtifactHook within the hooks boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    callback: Callable[[dict[str, Any]], None]

    def __call__(self, payload: dict[str, Any]) -> None:
        """Implement the internal __call__ helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            payload: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        self.callback(payload)


@dataclass
class DbHook:
    """Coordinate DbHook within the hooks boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    callback: Callable[[dict[str, Any]], None]

    def __call__(self, payload: dict[str, Any]) -> None:
        """Implement the internal __call__ helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            payload: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        self.callback(payload)

