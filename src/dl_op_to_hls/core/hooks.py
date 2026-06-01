from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable


HookHandler = Callable[[dict[str, Any]], None]


class HookManager:
    def __init__(self):
        self._handlers: dict[str, list[HookHandler]] = defaultdict(list)

    def register(self, event_name: str, handler: HookHandler) -> None:
        self._handlers[event_name].append(handler)

    def emit(self, event_name: str, payload: dict[str, Any]) -> None:
        enriched = dict(payload)
        enriched.setdefault("event", event_name)
        for handler in self._handlers.get(event_name, []):
            handler(enriched)
        for handler in self._handlers.get("*", []):
            handler(enriched)


@dataclass
class ConsoleHook:
    enabled: bool = True

    def __call__(self, payload: dict[str, Any]) -> None:
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
    callback: Callable[[dict[str, Any]], None]

    def __call__(self, payload: dict[str, Any]) -> None:
        self.callback(payload)


@dataclass
class DbHook:
    callback: Callable[[dict[str, Any]], None]

    def __call__(self, payload: dict[str, Any]) -> None:
        self.callback(payload)

