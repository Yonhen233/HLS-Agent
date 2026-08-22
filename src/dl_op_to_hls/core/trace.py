from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def stable_hash(payload: Any) -> str:
    serialized = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


@dataclass
class TraceWriter:
    path: Path
    run_id: str
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def append(self, event: str, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = {"ts": utc_now(), "event": event, "run_id": self.run_id}
        record.update(payload)
        with self._lock, self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


class TraceHook:
    def __init__(self, writer: TraceWriter):
        self.writer = writer

    def __call__(self, payload: dict[str, Any]) -> None:
        event = str(payload.get("event", "UnknownEvent"))
        record = {key: value for key, value in payload.items() if key != "event"}
        self.writer.append(event, record)
