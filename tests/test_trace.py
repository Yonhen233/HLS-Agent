"""Test contracts and regression checks for test_trace.py.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

import json

from dl_op_to_hls.core.hooks import HookManager
from dl_op_to_hls.core.trace import DecisionTraceHook, TraceHook, TraceReader, TraceWriter


def test_trace_jsonl_written(tmp_path):
    """Verify the test_trace_jsonl_written contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    writer = TraceWriter(tmp_path / "trace.jsonl", "run_1")
    writer.append("RunStarted", {"status": "ok"})
    lines = (tmp_path / "trace.jsonl").read_text(encoding="utf-8").strip().splitlines()
    record = json.loads(lines[0])
    assert record["event"] == "RunStarted"
    assert record["run_id"] == "run_1"


def test_trace_envelope_fields_cannot_be_overridden_by_payload(tmp_path):
    """Verify the test_trace_envelope_fields_cannot_be_overridden_by_payload contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    writer = TraceWriter(tmp_path / "trace.jsonl", "trusted_run")
    writer.append(
        "DecisionRecorded",
        {"ts": None, "event": "WrongEvent", "run_id": "wrong_run", "decision": "continue"},
    )

    record = json.loads((tmp_path / "trace.jsonl").read_text(encoding="utf-8"))
    assert record["ts"]
    assert record["event"] == "DecisionRecorded"
    assert record["run_id"] == "trusted_run"


def test_decision_ledger_is_stored_in_single_trace_file(tmp_path):
    """Verify the test_decision_ledger_is_stored_in_single_trace_file contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    trace_path = tmp_path / "trace.jsonl"
    writer = TraceWriter(trace_path, "run_1")
    hooks = HookManager()
    hooks.register("*", TraceHook(writer))
    hooks.register("*", DecisionTraceHook(writer))

    hooks.emit(
        "PathSelected",
        {
            "run_id": "run_1",
            "todo_id": "todo_002",
            "decision": "select_llm_candidate",
            "reason": "hls4ml does not support the operator",
            "before": {"selected_path": None},
            "after": {"selected_path": "llm_candidate_path"},
            "evidence_refs": ["runs/run_1/support.json"],
        },
    )

    records = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    assert [record["event"] for record in records] == ["PathSelected", "DecisionRecorded"]
    assert not (tmp_path / "decision_ledger.json").exists()
    ledger = TraceReader(trace_path).query("decision_ledger")
    assert ledger["source_of_truth"] == "trace.jsonl"
    assert ledger["records"][0]["decision"] == "select_llm_candidate"
    assert ledger["records"][0]["after"]["selected_path"] == "llm_candidate_path"


def test_trace_reader_returns_bounded_sanitized_latest_memory_context(tmp_path):
    """Verify the test_trace_reader_returns_bounded_sanitized_latest_memory_context contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    trace_path = tmp_path / "trace.jsonl"
    writer = TraceWriter(trace_path, "run_1")
    for index in range(6):
        writer.append(
            "DecisionRecorded",
            {
                "todo_id": f"todo_{index}",
                "decision": f"decision_{index}",
                "raw_log": "must-not-leak",
                "evidence_refs": [f"artifact_{index}.json"],
            },
        )

    result = TraceReader(trace_path).query("memory_context", max_items=2)
    assert [item["decision"] for item in result["decision_ledger"]] == ["decision_4", "decision_5"]
    assert "must-not-leak" not in json.dumps(result)
