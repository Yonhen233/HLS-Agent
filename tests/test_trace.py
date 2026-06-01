import json

from dl_op_to_hls.core.trace import TraceWriter


def test_trace_jsonl_written(tmp_path):
    writer = TraceWriter(tmp_path / "trace.jsonl", "run_1")
    writer.append("RunStarted", {"status": "ok"})
    lines = (tmp_path / "trace.jsonl").read_text(encoding="utf-8").strip().splitlines()
    record = json.loads(lines[0])
    assert record["event"] == "RunStarted"
    assert record["run_id"] == "run_1"

