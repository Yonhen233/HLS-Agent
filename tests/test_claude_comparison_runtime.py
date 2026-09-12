"""Regression coverage for the real benchmark's orchestration and accounting."""

import importlib
import json
import os
import sys
from pathlib import Path

import pytest


@pytest.fixture
def runner(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    return importlib.import_module("run_claude_cli_comparison")


def stream(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def assistant(message_id, input_tokens=10, output_tokens=2):
    return {"type": "assistant", "session_id": "same-session", "message": {
        "id": message_id, "model": "test", "usage": {"input_tokens": input_tokens,
        "output_tokens": output_tokens, "cache_read_input_tokens": 20,
        "cache_creation_input_tokens": 5}}}


def test_stream_deduplicates_api_messages_and_counts_cache(runner, tmp_path):
    path = tmp_path / "stdout.log"
    stream(path, [assistant("a"), assistant("a", output_tokens=3), assistant("b"),
                  {"type": "result", "session_id": "same-session", "usage": {"input_tokens": 20, "output_tokens": 5}}])
    calls = runner.claude_call_ledger(path)
    assert len(calls) == 2
    assert calls[0]["usage"]["prompt_tokens"] == 35
    assert calls[0]["usage"]["total_tokens"] == 38
    assert runner.parse_json_envelope(path)["session_id"] == "same-session"


def test_interrupted_stream_keeps_usage(runner, tmp_path):
    path = tmp_path / "stdout.log"
    stream(path, [assistant("a"), assistant("b")])
    with path.open("a") as handle:
        handle.write('{"unfinished":')
    turn = runner.summarize_claude_turn(tmp_path, {"stdout": str(path), "status": "timeout"})
    assert turn["usage"]["llm_calls"] == 2
    assert turn["usage"]["total_tokens"] == 74
    usage = runner.aggregate_usage([turn])
    assert usage["total_tokens"] is None
    assert usage["known_total_tokens"] == 74
    assert usage["observed_llm_calls"] == 2


def test_timeout_is_not_model_catalog_failure(runner, tmp_path):
    (tmp_path / "stderr.log").write_text('[claude-code:unrecognized_model] test', encoding="utf-8")
    assert runner.cli_error_code(tmp_path, {"status": "timeout", "timed_out": True}) == "timeout"
    assert runner.cli_error_code(tmp_path, {"status": "process_success"}) is None
    assert runner.cli_error_code(tmp_path, {"status": "process_failed"}) is None
    (tmp_path / "stderr.log").write_text('No conversation found with session ID: test', encoding="utf-8")
    assert runner.cli_error_code(tmp_path, {"status": "process_failed"}) == "session_not_found"


def test_invocations_are_not_llm_calls(runner):
    turns = [{"status": "process_success", "usage": {"total_tokens": 80, "llm_calls": 3}},
             {"status": "process_failed", "usage": {}}]
    usage = runner.aggregate_usage(turns)
    assert usage["cli_invocations"] == 2
    assert usage["llm_calls"] is None
    assert usage["observed_llm_calls"] == 3
    assert usage["total_tokens"] is None
    assert usage["known_total_tokens"] == 80
    assert usage["missing_usage_invocations"] == 1


def test_no_source_or_summary_false_success(runner, tmp_path):
    (tmp_path / "test.cpp").write_text('puts("GOLDEN_CHECK_PASSED");', encoding="utf-8")
    (tmp_path / "stdout.log").write_text('GOLDEN_CHECK_PASSED', encoding="utf-8")
    runner.write_json(tmp_path / "claude_completion.json", {"status": "success"})
    assert not runner.classify_completion(tmp_path)["terminal"]
    (tmp_path / "csim.log").write_text('GOLDEN_CHECK_PASSED\nCSim done with 0 errors.\n', encoding="utf-8")
    assert not runner.classify_completion(tmp_path)["terminal"]
    (tmp_path / "csynth.rpt").write_text("Vivado HLS Report for 'top'\nPerformance Estimates\nUtilization Estimates", encoding="utf-8")
    assert runner.classify_completion(tmp_path)["verified"]


def test_stdin_multiline_preserves_flags_and_archives_logs(runner, tmp_path):
    script = "import sys,json; print(json.dumps({'args':sys.argv[1:],'input':sys.stdin.read()}))"
    command = [sys.executable, "-c", script, "--session-id", "test", "--output-format", "json"]
    prompt = 'first line\nsecond line with "quotes" & shell symbols'
    first = runner.run_process(command, tmp_path, os.environ.copy(), tmp_path, 15, [], input_text=prompt)
    payload = json.loads(Path(first["stdout"]).read_text(encoding="utf-8"))
    assert payload["input"] == prompt
    assert payload["args"] == command[3:]
    runner.run_process(command, tmp_path, os.environ.copy(), tmp_path, 15, [], input_text="new")
    assert list((tmp_path / "process_history").glob("*/stdout.log"))


def test_spawn_failure_has_durable_record(runner, tmp_path):
    result = runner.run_process([str(tmp_path / "missing.exe")], tmp_path, os.environ.copy(), tmp_path, 1, [], input_text="test")
    assert result["failure_stage"] == "spawn"
    assert json.loads((tmp_path / "process.json").read_text())["status"] == "process_failed"


def test_same_session_continues_and_terminal_result_is_cached(runner, monkeypatch, tmp_path):
    commands = []
    monkeypatch.setattr(runner, "claude_executable", lambda: sys.executable)

    def fake(command, cwd, env, output_dir, timeout, secrets, input_text=None):
        commands.append(command)
        assert input_text
        assert input_text not in command
        assert env["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "test-model"
        stream(output_dir / "stdout.log", [assistant(str(len(commands))),
               {"type": "result", "session_id": "same-session", "usage": {"input_tokens": 10, "output_tokens": 2}}])
        (output_dir / "stderr.log").write_text("", encoding="utf-8")
        return {"stdout": str(output_dir / "stdout.log"), "status": "process_success", "elapsed_seconds": 5}

    monkeypatch.setattr(runner, "run_process", fake)
    monkeypatch.setattr(runner, "classify_completion", lambda _: {
        "terminal": len(commands) == 2, "outcome": "success" if len(commands) == 2 else "incomplete",
        "verified": len(commands) == 2, "reason": "test", "evidence_files": []})
    kwargs = dict(case_task=tmp_path / "task.json", system_root=tmp_path, timeout_seconds=100,
                  max_turns=4, model="test-model", cli_model="sonnet", base_url="http://unused",
                  api_key="test", secrets=[], env_base={})
    result = runner.run_claude_case(**kwargs)
    assert "--session-id" in commands[0]
    assert commands[1][commands[1].index("--resume") + 1] == "same-session"
    assert result["interruption_count"] == 1
    assert result["usage"]["llm_calls"] == 2
    assert result["elapsed_seconds"] == 10
    runner.run_claude_case(**kwargs)
    assert len(commands) == 2


def test_budget_not_reset_after_restart(runner, monkeypatch, tmp_path):
    runner.write_json(tmp_path / "session.json", {"runner_version": runner.RUNNER_VERSION,
        "session_id": "saved", "status": "running", "turns": [{"turn": 1, "status": "timeout", "elapsed_seconds": 100}]})
    monkeypatch.setattr(runner, "classify_completion", lambda _: {"terminal": False, "outcome": "incomplete", "verified": False, "reason": "none", "evidence_files": []})
    monkeypatch.setattr(runner, "run_process", lambda *args, **kwargs: pytest.fail("budget replenished"))
    result = runner.run_claude_case(tmp_path / "task", tmp_path, 100, 4, "model", "sonnet", "http://unused", "key", [], {})
    assert result["status"] == "timeout"
    assert result["elapsed_seconds"] == 100


def test_runner_lock_rejects_duplicate(runner, tmp_path):
    with runner.suite_lock(tmp_path):
        with pytest.raises(OSError):
            with runner.suite_lock(tmp_path):
                pass
    with runner.suite_lock(tmp_path):
        pass


def test_report_excludes_live_runs_and_sums_all_turns(runner, tmp_path):
    report = importlib.import_module("summarize_claude_cli_comparison")
    root = tmp_path / "test"
    runner.write_json(root / "case.json", {"id": "test"})
    cli = root / "claude_cli"
    runner.write_json(cli / "result.json", {"status": "completed", "outcome": "success", "verified": True})
    runner.write_json(cli / "claude_completion.json", {"status": "success"})
    (cli / "csim.log").write_text('GOLDEN_CHECK_PASSED\nCSim done with 0 errors.\n', encoding="utf-8")
    (cli / "csynth.rpt").write_text("Vivado HLS Report for 'top'\nPerformance Estimates\nUtilization Estimates", encoding="utf-8")
    runner.write_json(cli / "session.json", {"status": "completed", "interruption_count": 1, "turns": [
        {"turn": 1, "status": "process_success", "elapsed_seconds": 20},
        {"turn": 2, "status": "process_success", "elapsed_seconds": 30}]})
    stream(cli / "turn_01/stdout.log", [{"type": "result", "usage": {"input_tokens": 10, "output_tokens": 1, "cache_read_input_tokens": 30}}])
    stream(cli / "turn_02/stdout.log", [{"type": "result", "usage": {"input_tokens": 20, "output_tokens": 2}}])
    rows = report.collect(tmp_path)
    summary = report.system_summary(rows, "claude_cli")
    assert summary["tokens_per_run"]["mean"] == 63
    assert summary["runtime_seconds"]["mean"] == 50
    assert summary["llm_calls_per_run"]["mean"] is None
    assert report.diagnosis(rows[0]["result"]) == "success_after_recovery"
    rows.append({"system": "claude_cli", "result": {"status": "running", "verified": True}})
    assert report.system_summary(rows, "claude_cli")["cases"] == 1


def test_hls_provider_fields_and_timeout_precedence(runner, tmp_path):
    run = tmp_path / "runs/agent-test"
    runner.write_json(run / "state.json", {"status": "partial_success", "completion": {"passed": True}})
    event = {"event": "LLMUsageRecorded", "call_id": "1", "input_tokens": 30, "output_tokens": 5, "total_tokens": 35}
    stream(run / "trace.jsonl", [event, event])
    stream(run / "specialists/test/trace.jsonl", [event])
    result = runner.summarize_hls(tmp_path, {"status": "timeout"})
    assert result["status"] == "timeout"
    assert not result["verified"]
    assert result["usage"]["llm_calls"] == 1
    assert result["usage"]["prompt_tokens"] == 30
