from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


def _hex_id(value: str, length: int) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


@dataclass(frozen=True)
class SLOPolicy:
    min_task_success_rate: float = 0.90
    max_false_success_rate: float = 0.01
    max_rag_pollution_rate: float = 0.05
    max_p95_runtime_seconds: float = 900.0
    max_tokens_per_success: float = 120000.0
    max_queue_lease_expiry_rate: float = 0.02


class SLOEvaluator:
    def __init__(self, policy: SLOPolicy | None = None):
        self.policy = policy or SLOPolicy()

    def evaluate(self, metrics: dict[str, Any]) -> dict[str, Any]:
        checks = {
            "task_success_rate": (float(metrics.get("task_success_rate", 0)), ">=", self.policy.min_task_success_rate),
            "false_success_rate": (float(metrics.get("false_success_rate", 0)), "<=", self.policy.max_false_success_rate),
            "rag_pollution_rate": (float(metrics.get("rag_pollution_rate", 0)), "<=", self.policy.max_rag_pollution_rate),
            "p95_runtime_seconds": (float(metrics.get("p95_runtime_seconds", 0)), "<=", self.policy.max_p95_runtime_seconds),
            "tokens_per_success": (float(metrics.get("tokens_per_success", 0)), "<=", self.policy.max_tokens_per_success),
            "queue_lease_expiry_rate": (float(metrics.get("queue_lease_expiry_rate", 0)), "<=", self.policy.max_queue_lease_expiry_rate),
        }
        details = []
        for name, (actual, operator, target) in checks.items():
            passed = actual >= target if operator == ">=" else actual <= target
            details.append({"metric": name, "actual": actual, "operator": operator, "target": target, "passed": passed})
        breaches = [item for item in details if not item["passed"]]
        return {
            "status": "pass" if not breaches else "breach",
            "checks": details,
            "breaches": breaches,
            "policy": asdict(self.policy),
        }

    def write_report(self, path: str | Path, metrics: dict[str, Any]) -> dict[str, Any]:
        report = self.evaluate(metrics)
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        return report


class TelemetryHook:
    """Hook-to-span bridge with a dependency-free OTLP-compatible JSONL fallback."""

    START_EVENTS = {
        "RunStarted": "run",
        "PreToolUse": "tool",
        "LLMCallStarted": "llm",
        "SpecialistStarted": "specialist",
    }
    END_EVENTS = {
        "RunFinished": ("run", "ok"),
        "RunFailed": ("run", "error"),
        "PostToolUse": ("tool", "ok"),
        "ToolFailed": ("tool", "error"),
        "LLMCallFinished": ("llm", "ok"),
        "LLMCallFailed": ("llm", "error"),
        "SpecialistFinished": ("specialist", "ok"),
        "SpecialistFailed": ("specialist", "error"),
    }

    def __init__(self, path: str | Path, run_id: str):
        self.path = Path(path)
        self.run_id = run_id
        self.trace_id = _hex_id(run_id, 32)
        self._active: dict[str, list[dict[str, Any]]] = {}
        self._lock = threading.RLock()
        self._otel_provider = None
        self._otel_tracer = None
        self._otel_parent_context = None
        self._init_opentelemetry()

    def __call__(self, payload: dict[str, Any]) -> None:
        event = str(payload.get("event", ""))
        with self._lock:
            if event in self.START_EVENTS:
                kind = self.START_EVENTS[event]
                key = self._key(kind, payload)
                self._active.setdefault(key, []).append(
                    {
                        "start_ns": time.time_ns(),
                        "span_id": _hex_id(f"{self.run_id}:{key}:{time.time_ns()}", 16),
                        "attributes": self._attributes(payload),
                        "otel_span": self._start_otel_span(key, payload),
                    }
                )
                return
            terminal = self.END_EVENTS.get(event)
            if terminal:
                kind, status = terminal
                key = self._key(kind, payload)
                stack = self._active.get(key) or []
                started = stack.pop(0) if stack else {"start_ns": time.time_ns(), "span_id": _hex_id(f"{self.run_id}:{key}:{event}", 16), "attributes": {}}
                self._write_span(kind, key, started, payload, status)
                if kind == "run" and self._otel_provider is not None:
                    self._otel_provider.force_flush(timeout_millis=5000)

    def close(self, status: str = "error") -> None:
        with self._lock:
            for key, spans in list(self._active.items()):
                kind = key.split(":", 1)[0]
                for started in spans:
                    self._write_span(kind, key, started, {"event": "SpanAbandoned"}, status)
            self._active.clear()

    def _write_span(self, kind: str, key: str, started: dict[str, Any], payload: dict[str, Any], status: str) -> None:
        end_ns = time.time_ns()
        attributes = {**started["attributes"], **self._attributes(payload)}
        otel_span = started.get("otel_span")
        if otel_span is not None:
            from opentelemetry.trace import Status, StatusCode  # type: ignore

            for attribute, value in attributes.items():
                if isinstance(value, (str, bool, int, float)):
                    otel_span.set_attribute(attribute, value)
            otel_span.set_status(Status(StatusCode.OK if status == "ok" else StatusCode.ERROR))
            otel_span.end(end_time=end_ns)
        record = {
            "resource": {"service.name": "dl-op-to-hls-agent"},
            "trace_id": self.trace_id,
            "span_id": started["span_id"],
            "name": key,
            "kind": "INTERNAL" if kind in {"run", "specialist"} else "CLIENT",
            "start_time_unix_nano": started["start_ns"],
            "end_time_unix_nano": end_ns,
            "duration_ms": round((end_ns - started["start_ns"]) / 1_000_000, 3),
            "status": status,
            "attributes": attributes,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def _key(self, kind: str, payload: dict[str, Any]) -> str:
        if kind == "tool":
            return f"tool:{payload.get('tool', 'unknown')}:{payload.get('args_hash', '')}"
        if kind == "llm":
            return f"llm:{payload.get('phase') or payload.get('purpose') or payload.get('model') or 'call'}"
        if kind == "specialist":
            return f"specialist:{payload.get('specialist', 'unknown')}:{payload.get('todo_id', '')}"
        return f"run:{self.run_id}"

    @staticmethod
    def _attributes(payload: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "run_id", "session_id", "tool", "server", "status", "error_type", "duration_ms",
            "model", "phase", "purpose", "specialist", "todo_id", "args_hash", "output_hash",
            "prompt_tokens", "completion_tokens", "total_tokens", "cached",
        }
        return {f"agent.{key}": value for key, value in payload.items() if key in allowed and value is not None}

    def _init_opentelemetry(self) -> None:
        try:
            from opentelemetry.sdk.resources import Resource  # type: ignore
            from opentelemetry.sdk.trace import TracerProvider  # type: ignore

            provider = TracerProvider(resource=Resource.create({"service.name": "dl-op-to-hls-agent"}))
            endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
            if endpoint:
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter  # type: ignore
                from opentelemetry.sdk.trace.export import BatchSpanProcessor  # type: ignore

                provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
            self._otel_provider = provider
            self._otel_tracer = provider.get_tracer("dl_op_to_hls.agent", "1.0")
            from opentelemetry import trace  # type: ignore
            from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags, TraceState  # type: ignore

            parent = SpanContext(
                trace_id=int(self.trace_id, 16),
                span_id=int(_hex_id(f"{self.run_id}:root", 16), 16),
                is_remote=False,
                trace_flags=TraceFlags(TraceFlags.SAMPLED),
                trace_state=TraceState(),
            )
            self._otel_parent_context = trace.set_span_in_context(NonRecordingSpan(parent))
        except Exception:
            self._otel_provider = None
            self._otel_tracer = None

    def _start_otel_span(self, name: str, payload: dict[str, Any]):
        if self._otel_tracer is None:
            return None
        attributes = {
            key: value for key, value in self._attributes(payload).items()
            if isinstance(value, (str, bool, int, float))
        }
        return self._otel_tracer.start_span(name, context=self._otel_parent_context, attributes=attributes)
