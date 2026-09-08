from __future__ import annotations

from pathlib import Path

from .errors import build_error, error_result
from .trace import TraceReader


def query_trace(arguments: dict, context: dict) -> dict:
    """Expose bounded Trace projections to specialists through the tool gateway."""
    try:
        run_id = str(arguments["run_id"])
        requested_run_id = str(context.get("run_id") or run_id)
        if run_id != requested_run_id:
            return error_result(
                build_error(
                    "PermissionDeniedError",
                    "A specialist may only query the trace of the current run.",
                    recoverable=False,
                    source="trace.query",
                    suggested_action="Use the current run_id from ContextEnvelope.",
                )
            )
        run_dir = Path(context.get("run_dir") or "")
        trace_path = run_dir / "trace.jsonl"
        result = TraceReader(trace_path).query(
            str(arguments.get("view", "decisions")),
            max_items=min(max(int(arguments.get("max_items", 20)), 1), 100),
        )
        return result
    except Exception as exc:  # pragma: no cover - gateway boundary
        return error_result(
            build_error(
                "TraceReadError",
                str(exc),
                recoverable=True,
                source="trace.query",
                suggested_action="Check that the current run trace exists and is valid JSONL.",
            )
        )
