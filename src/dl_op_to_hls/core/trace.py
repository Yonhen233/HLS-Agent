"""core layer implementation for trace.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections import deque
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def utc_now() -> str:
    """Execute utc_now at the trace boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Returns:
        The structured value promised by the function signature.
    """
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def stable_hash(payload: Any) -> str:
    """Execute stable_hash at the trace boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Args:
        payload: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    serialized = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


@dataclass
class TraceWriter:
    """Coordinate TraceWriter within the trace boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    path: Path
    run_id: str
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def append(self, event: str, payload: dict[str, Any]) -> None:
        """Execute append at the trace boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            event: Value supplied by the caller and validated by the surrounding schema.
            payload: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Envelope fields belong to the writer and must not be overridden by
        # partially populated hook payloads.
        record = dict(payload)
        record.update({"ts": utc_now(), "event": event, "run_id": self.run_id})
        with self._lock, self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


class TraceHook:
    """Coordinate TraceHook within the trace boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    def __init__(self, writer: TraceWriter):
        """Implement the internal __init__ helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            writer: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        self.writer = writer

    def __call__(self, payload: dict[str, Any]) -> None:
        """Implement the internal __call__ helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            payload: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        event = str(payload.get("event", "UnknownEvent"))
        record = {key: value for key, value in payload.items() if key != "event"}
        self.writer.append(event, record)


DECISION_SOURCE_EVENTS = {
    "LLMReActDecision",
    "LLMReflectionDecision",
    "LLMReActAutoDelegated",
    "LLMReActAutoDirect",
    "SpecialistSelected",
    "TodoSkipped",
    "TodoFailed",
    "TodoBlocked",
    "TodoCancelled",
    "ReplanRequested",
    "PathSelected",
    "ParameterSelected",
    "ValidationGatePassed",
    "ValidationGateFailed",
}


def _compact_json(value: Any, *, max_chars: int = 1200) -> Any:
    """Keep projections useful without copying raw tool payloads into memory."""
    if isinstance(value, dict):
        safe = {}
        for key, child in value.items():
            lowered = str(key).lower()
            if any(token in lowered for token in ("raw", "stdout", "stderr", "trace", "source_code", "hls_code")):
                continue
            safe[str(key)] = _compact_json(child, max_chars=max_chars)
        return safe
    if isinstance(value, list):
        return [_compact_json(item, max_chars=max_chars) for item in value[:20]]
    if isinstance(value, str) and len(value) > max_chars:
        return value[:max_chars] + "..."
    return value


def _decision_from_record(record: dict[str, Any]) -> dict[str, Any]:
    """Implement the internal _decision_from_record helper.

    Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

    Args:
        record: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    event = str(record.get("event", ""))
    payload = {key: value for key, value in record.items() if key not in {"ts", "event", "run_id"}}
    decision = payload.get("decision") or payload.get("action") or event
    if isinstance(decision, dict):
        decision = decision.get("type") or decision.get("decision") or decision.get("tool") or event
    trigger = payload.get("trigger") or payload.get("reason") or payload.get("reason_summary")
    status = payload.get("status")
    if not status and event == "TodoSkipped":
        status = "skipped"
    if not status and event == "TodoFailed":
        status = "failed"
    if not status and event == "TodoBlocked":
        status = "blocked"
    evidence_refs = payload.get("evidence_refs") or payload.get("artifact_refs") or []
    if not isinstance(evidence_refs, list):
        evidence_refs = [evidence_refs]
    return {
        "ts": record.get("ts"),
        "run_id": record.get("run_id"),
        "source_event": event,
        "todo_id": payload.get("todo_id"),
        "decision": str(decision),
        "trigger": _compact_json(trigger),
        "before": _compact_json(payload.get("before", {})),
        "after": _compact_json(payload.get("after", {})),
        "evidence_refs": _compact_json(evidence_refs),
        "outcome": _compact_json(payload.get("outcome") or payload.get("summary") or payload.get("message")),
        "status": status,
    }


class DecisionTraceHook:
    """Materializes decision events into the same Trace JSONL stream.

    The regular event remains the source record. This hook writes a compact,
    derived DecisionRecorded event directly to the same writer, so there is no
    second mutable ledger store and no recursive HookManager emission.
    """

    def __init__(self, writer: TraceWriter):
        """Implement the internal __init__ helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            writer: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        self.writer = writer

    def __call__(self, payload: dict[str, Any]) -> None:
        """Implement the internal __call__ helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            payload: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        event = str(payload.get("event", ""))
        if event == "DecisionRecorded" or event not in DECISION_SOURCE_EVENTS:
            return
        decision = _decision_from_record({"event": event, **payload})
        self.writer.append("DecisionRecorded", decision)


class TraceReader:
    """Read bounded, structured projections from a run's single trace file."""

    def __init__(self, path: str | Path):
        """Implement the internal __init__ helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            path: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        self.path = Path(path)

    def records(self, *, max_records: int = 500) -> list[dict[str, Any]]:
        """Execute records at the trace boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            max_records: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        if not self.path.exists():
            return []
        records: deque[dict[str, Any]] = deque(maxlen=max(1, int(max_records)))
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    records.append(value)
        return list(records)

    @staticmethod
    def _project(records: list[dict[str, Any]], view: str) -> list[dict[str, Any]]:
        """Implement the internal _project helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            records: Value supplied by the caller and validated by the surrounding schema.
            view: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        if view in {"decisions", "decision_ledger"}:
            projected = [_compact_json(record) for record in records if record.get("event") == "DecisionRecorded"]
            if not projected:
                projected = [_decision_from_record(record) for record in records if record.get("event") in DECISION_SOURCE_EVENTS]
            return projected
        if view in {"todos", "todo_history"}:
            return [_compact_json(record) for record in records if str(record.get("event", "")).startswith("Todo")]
        if view in {"failures", "errors"}:
            return [
                _compact_json(record)
                for record in records
                if record.get("event") in {"ToolFailed", "SpecialistFailed", "TodoFailed", "LLMReActFailed", "LLMReflectFailed"}
                or record.get("error_type")
            ]
        if view == "evidence":
            return [
                _compact_json(record)
                for record in records
                if record.get("evidence_refs") or record.get("artifact_refs") or record.get("report_path")
            ]
        raise ValueError(f"Unsupported trace projection: {view}")

    def query(self, view: str = "decisions", *, max_items: int = 50) -> dict[str, Any]:
        """Execute query at the trace boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            view: Value supplied by the caller and validated by the surrounding schema.
            max_items: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        records = self.records(max_records=max(500, max_items * 10))
        if view == "memory_context":
            limit = max(1, int(max_items))
            return {
                "status": "success",
                "view": view,
                "source_path": str(self.path),
                "decision_ledger": self._project(records, "decisions")[-limit:],
                "todo_history": self._project(records, "todo_history")[-limit:],
                "failures": self._project(records, "failures")[-limit:],
                "evidence": self._project(records, "evidence")[-limit:],
                "source_of_truth": "trace.jsonl",
            }
        projected = self._project(records, view)
        return {
            "status": "success",
            "view": view,
            "source_path": str(self.path),
            "records": projected[-max(1, int(max_items)):],
            "count": min(len(projected), max(1, int(max_items))),
            "source_of_truth": "trace.jsonl",
        }


def project_decision_ledger(records: Iterable[dict[str, Any]], *, max_items: int = 50) -> list[dict[str, Any]]:
    """Pure helper for callers that already loaded Trace records."""
    projected = []
    for record in records:
        if record.get("event") == "DecisionRecorded":
            projected.append(_compact_json(record))
        elif record.get("event") in DECISION_SOURCE_EVENTS:
            projected.append(_decision_from_record(record))
    return projected[-max(1, int(max_items)):]
