from __future__ import annotations

import json
from pathlib import Path

import pytest

from dl_op_to_hls.benchmarks.context_ablation import (
    DeepSeekV4Tokenizer,
    EvaluationConfigurationError,
    _current_run_verification,
    _retention,
    classify_external_failure,
    make_benchmark_run_id,
    paired_comparison,
    validate_execution_path,
)
from dl_op_to_hls.benchmarks.context_ablation_aggregate import aggregate_sources, extended_aggregate
from dl_op_to_hls.core.context_modes import ContextModeConfig
from dl_op_to_hls.main_agent.executor import AgentExecutor
from dl_op_to_hls.main_agent.state import AgentState
from dl_op_to_hls.main_agent.todo import TodoItem
from dl_op_to_hls.specialists.context import ContextBuilder
from dl_op_to_hls.specialists.result import SpecialistResult


def _todo() -> TodoItem:
    return TodoItem(
        id="todo_001",
        title="Run synthesis",
        description="real synthesis",
        status="pending",
        priority=1,
        dependencies=[],
        assigned_tool="vivado.run_csynth",
        assigned_specialist="VivadoSpecialist",
        inputs={},
        outputs=None,
        error=None,
        context_scope={"max_context_tokens": 80},
    )


def _state() -> AgentState:
    return AgentState(
        run_id="run_001",
        task={
            "task_type": "operator",
            "name": "dense",
            "op_type": "Dense",
            "input_shape": [16],
            "output_shape": [32],
            "dtype": "ap_fixed<16,6>",
            "target": {"part": "xc7z020clg400-1", "clock_period": 5},
        },
        tool_results=[{"tool": "previous", "result": {"raw": "x" * 800}}],
        retrieved_memories=[{"summary": "memory " * 100}],
    )


def test_context_modes_default_to_production_compressed(monkeypatch) -> None:
    monkeypatch.delenv("DL_OP_TO_HLS_INPUT_CONTEXT_MODE", raising=False)
    monkeypatch.delenv("DL_OP_TO_HLS_RESULT_CONTEXT_MODE", raising=False)
    assert ContextModeConfig.from_env().to_dict() == {
        "input_context_mode": "scoped",
        "result_context_mode": "compressed",
    }


def test_full_context_contains_agent_state_and_is_not_truncated() -> None:
    builder = ContextBuilder(mode_config=ContextModeConfig("full", "raw"))
    envelope = builder.build_for_specialist(_state(), _todo(), "VivadoSpecialist")
    assert envelope.scoped_state["agent_state"]["tool_results"]
    assert envelope.scoped_state["part"] == "xc7z020clg400-1"
    assert envelope.constraints["token_budget"]["truncated"] is False
    assert envelope.constraints["token_budget"]["overflow_policy"] == "record_without_truncation"


def test_scoped_context_excludes_unrelated_full_state() -> None:
    builder = ContextBuilder(mode_config=ContextModeConfig("scoped", "compressed"))
    envelope = builder.build_for_specialist(_state(), _todo(), "VivadoSpecialist")
    assert "agent_state" not in envelope.scoped_state
    assert "tool_results" not in envelope.scoped_state
    assert envelope.scoped_state["part"] == "xc7z020clg400-1"


class _Registry:
    def call(self, *_args, **_kwargs):
        return {"status": "success"}


def test_raw_result_delivers_text_artifact(monkeypatch, tmp_path: Path) -> None:
    artifact = tmp_path / "csynth.rpt"
    artifact.write_text("LATENCY raw report", encoding="utf-8")
    monkeypatch.setenv("DL_OP_TO_HLS_RESULT_CONTEXT_MODE", "raw")
    executor = AgentExecutor(_Registry(), {})
    state = _state()
    todo = _todo()
    result = SpecialistResult("VivadoSpecialist", todo.id, "success", "ok", artifacts=[{"type": "vivado_report", "path": str(artifact)}])
    executor.merge_specialist_result(state, todo, result)
    assert todo.specialist_result["raw_text_artifacts"][0]["text"] == "LATENCY raw report"


def test_compressed_result_excludes_raw_text_artifact(monkeypatch, tmp_path: Path) -> None:
    artifact = tmp_path / "csynth.rpt"
    artifact.write_text("LATENCY raw report", encoding="utf-8")
    monkeypatch.setenv("DL_OP_TO_HLS_RESULT_CONTEXT_MODE", "compressed")
    executor = AgentExecutor(_Registry(), {})
    state = _state()
    todo = _todo()
    result = SpecialistResult("VivadoSpecialist", todo.id, "success", "ok", artifacts=[{"type": "vivado_report", "path": str(artifact)}])
    executor.merge_specialist_result(state, todo, result)
    assert "raw_text_artifacts" not in todo.specialist_result
    assert todo.specialist_result["result_context_mode"] == "compressed"


def test_tokenizer_missing_is_hard_failure(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        DeepSeekV4Tokenizer(tmp_path / "missing")


def test_deepseek_tokenizer_uses_real_encoder(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "tokenizer.json").write_text("{}", encoding="utf-8")
    (tmp_path / "tokenizer_config.json").write_text(json.dumps({"model_max_length": 1048576}), encoding="utf-8")

    class DummyTokenizer:
        model_max_length = 1048576

        def encode(self, text, add_special_tokens=False):
            assert add_special_tokens is False
            return text.split()

        def __len__(self):
            return 100

    monkeypatch.setattr("transformers.AutoTokenizer.from_pretrained", lambda *_args, **_kwargs: DummyTokenizer())
    tokenizer = DeepSeekV4Tokenizer(tmp_path)
    assert tokenizer.count("one two three") == 3


def test_paired_comparison_uses_case_pairs() -> None:
    def record(case, mode, success, tokens):
        return {
            "case_id": case,
            "mode": mode,
            "task_completed": success,
            "golden_csim_passed": success,
            "real_csynth_completed": success,
            "tool_parameter_correct": True,
            "evidence_complete": success,
            "false_success": False,
            "api_usage": {"prompt_tokens": tokens, "total_tokens": tokens + 5},
            "offline_tokens": {"specialist_input_tokens": tokens, "delivered_result_tokens": tokens // 2},
            "wall_runtime_s": 1.0,
            "tool_calls": 2,
        }

    records = [record("one", "A", True, 100), record("one", "C", True, 50), record("two", "A", True, 120), record("two", "C", False, 60)]
    result = paired_comparison(records, "A", "C")
    assert result["n_pairs"] == 2
    assert result["binary"]["task_completed"]["discordant_left_only"] == 1
    assert result["continuous"]["api_prompt_tokens"]["paired_median_difference"]["median"] == -55.0


def _aggregate_record(case: str, mode: str, completed: bool, tokens: int, run_dir: Path) -> dict:
    return {
        "case_id": case,
        "mode": mode,
        "status": "success" if completed else "partial_success",
        "selected_path": "llm_candidate_path",
        "task_completed": completed,
        "golden_csim_passed": completed,
        "real_csynth_completed": completed,
        "tool_selection_correct": True,
        "tool_parameter_correct": True,
        "critical_constraint_retention": {"rate": 1.0},
        "evidence_complete": completed,
        "false_success": False,
        "correct_rejection": False,
        "repair_final_success": completed,
        "wall_runtime_s": float(tokens),
        "tool_calls": 2,
        "tool_failures": 0,
        "tool_retries": 0,
        "invalid_duplicate_calls": 0,
        "llm_format_errors": 0,
        "replans": 0,
        "early_termination": 0,
        "api_usage": {
            "prompt_tokens": tokens,
            "completion_tokens": 5,
            "total_tokens": tokens + 5,
            "cache_hit_tokens": 0,
            "cache_miss_tokens": tokens,
        },
        "offline_tokens": {"specialist_input_tokens": tokens, "delivered_result_tokens": tokens // 2},
        "timing": {"llm_ms": 1000, "tool_ms": 2000, "vivado_ms": 1000},
        "context_overflow": False,
        "run_id": f"{case}_{mode}",
        "run_dir": str(run_dir),
    }


def test_extended_aggregate_reports_p50_p95_and_totals(tmp_path: Path) -> None:
    records = [
        _aggregate_record("one", "A", True, 100, tmp_path / "one_a"),
        _aggregate_record("two", "A", False, 200, tmp_path / "two_a"),
    ]
    aggregate = extended_aggregate(records)["A"]
    assert aggregate["task_completion_rate"] == 0.5
    assert aggregate["api_prompt_tokens"]["p50"] == 150
    assert aggregate["api_prompt_tokens"]["p95"] == pytest.approx(195)
    assert aggregate["totals"]["api_total_tokens"] == 310
    assert aggregate["binary_counts_and_ci95"]["task_completion"]["successes"] == 1
    assert aggregate["binary_counts_and_ci95"]["task_completion"]["wilson_ci95"][0] < 0.5


def test_aggregate_sources_preserves_repeated_trials(tmp_path: Path) -> None:
    sources = []
    for trial in range(3):
        source = tmp_path / f"trial_{trial}"
        source.mkdir()
        records = []
        for mode, tokens in (("A", 100), ("B", 70), ("C", 40)):
            run_dir = source / f"run_{mode}"
            run_dir.mkdir()
            (run_dir / "trace.jsonl").write_text("", encoding="utf-8")
            records.append(_aggregate_record("one", mode, True, tokens + trial, run_dir))
        (source / "context_ablation_results.json").write_text(json.dumps({"runs": records}), encoding="utf-8")
        (source / "environment.json").write_text(json.dumps({"git_commit": "abc", "model": "deepseek-v4-pro"}), encoding="utf-8")
        (source / "tokenizer_metadata.json").write_text(json.dumps({"aggregate_sha256": "tok"}), encoding="utf-8")
        sources.append(source)
    result = aggregate_sources(sources)
    assert result["run_count"] == 9
    assert result["paired_comparisons"][2]["n_pairs"] == 3
    assert result["combined_aggregate"]["C"]["n"] == 3


def _write_trace(run_dir: Path, events: list[dict]) -> list[dict]:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "trace.jsonl").write_text("\n".join(json.dumps(item) for item in events) + "\n", encoding="utf-8")
    return events


def test_csim_pass_survives_later_csynth_failure(tmp_path: Path) -> None:
    run_dir = tmp_path / "current"
    events = _write_trace(
        run_dir,
        [
            {"event": "PreToolUse", "tool": "verify_candidate.run"},
            {"event": "ToolFailed", "tool": "verify_candidate.run", "error_type": "VivadoSynthesisError"},
        ],
    )
    (run_dir / "candidate").mkdir()
    (run_dir / "candidate" / "csim.log").write_text("GOLDEN_CHECK_PASSED\n", encoding="utf-8")
    result = _current_run_verification(run_dir, events)
    assert result["csim_exit_code"] == 0
    assert result["golden_csim_passed"] is True
    assert result["real_csynth_completed"] is False


def test_csim_failure_without_csynth(tmp_path: Path) -> None:
    run_dir = tmp_path / "current"
    events = _write_trace(run_dir, [{"event": "PreToolUse", "tool": "vivado.run_csim"}])
    (run_dir / "csim.log").write_text("GOLDEN_CHECK_FAILED\n", encoding="utf-8")
    result = _current_run_verification(run_dir, events)
    assert result["csim_exit_code"] == 1
    assert result["golden_csim_passed"] is False
    assert result["csynth_started"] is False


def test_current_run_csim_and_csynth_both_pass(tmp_path: Path) -> None:
    run_dir = tmp_path / "current"
    events = _write_trace(
        run_dir,
        [
            {"event": "PreToolUse", "tool": "vivado.run_csim"},
            {"event": "PreToolUse", "tool": "vivado.run_csynth"},
        ],
    )
    (run_dir / "csim.log").write_text("GOLDEN_CHECK_PASSED\n", encoding="utf-8")
    report = run_dir / "solution1" / "syn" / "report" / "top_csynth.rpt"
    report.parent.mkdir(parents=True)
    fixture = Path("tests/fixtures/sample_csynth.rpt")
    report.write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")
    result = _current_run_verification(run_dir, events)
    assert result["golden_csim_passed"] is True
    assert result["real_csynth_completed"] is True
    assert len(result["csynth_report_evidence"][0]["sha256"]) == 64


def test_golden_marker_from_old_run_is_rejected(tmp_path: Path) -> None:
    old = tmp_path / "old"
    old.mkdir()
    (old / "csim.log").write_text("GOLDEN_CHECK_PASSED\n", encoding="utf-8")
    current = tmp_path / "current"
    events = _write_trace(current, [{"event": "PreToolUse", "tool": "vivado.run_csim"}])
    assert _current_run_verification(current, events)["golden_csim_passed"] is False


def test_csynth_success_event_without_report_is_not_completed(tmp_path: Path) -> None:
    run_dir = tmp_path / "current"
    events = _write_trace(run_dir, [{"event": "PreToolUse", "tool": "vivado.run_csynth"}])
    result = _current_run_verification(run_dir, events)
    assert result["csynth_started"] is True
    assert result["csynth_report_present"] is False
    assert result["real_csynth_completed"] is False


def test_csynth_timeout_is_not_completed(tmp_path: Path) -> None:
    run_dir = tmp_path / "current"
    events = _write_trace(
        run_dir,
        [
            {"event": "PreToolUse", "tool": "vivado.run_csynth"},
            {"event": "ToolFailed", "tool": "vivado.run_csynth", "error_type": "ToolTimeoutError"},
        ],
    )
    result = _current_run_verification(run_dir, events)
    assert result["csynth_exit_code"] == 1
    assert result["real_csynth_completed"] is False


def test_long_vivado_path_rejected_before_launch(tmp_path: Path) -> None:
    with pytest.raises(EvaluationConfigurationError):
        validate_execution_path(tmp_path / ("nested_" * 35))


@pytest.mark.parametrize(
    ("message", "failure_type"),
    [
        ("OpenAI API HTTP error: 401 authentication failed", "authentication_failure"),
        ("OpenAI API HTTP error: 402 insufficient balance", "insufficient_balance"),
        ("HTTP 429 rate limit", "rate_limit"),
        ("HTTP 503 server overloaded", "service_unavailable"),
        ("LLM API read timeout", "api_timeout"),
        ("urlopen error connection refused", "network_failure"),
    ],
)
def test_external_api_failures_are_classified(message: str, failure_type: str) -> None:
    result = classify_external_failure(message)
    assert result["external_failure"] is True
    assert result["external_failure_type"] == failure_type


def test_benchmark_run_ids_are_unique_and_descriptive() -> None:
    left = make_benchmark_run_id("dense", "A", 0, "abc123")
    right = make_benchmark_run_id("dense", "B", 0, "def456")
    assert left == "dense_A_t0_abc123"
    assert left != right


def test_retention_scores_transport_not_final_verification(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    telemetry = run_dir / "context_telemetry"
    telemetry.mkdir(parents=True)
    task = {
        "task_type": "operator",
        "name": "add",
        "op_type": "Add",
        "input_shape": [16],
        "output_shape": [16],
        "dtype": "ap_fixed<16,6>",
        "target": {"part": "xc7z020clg400-1", "clock_period": 5},
        "objective": "resource",
    }
    policy = {"mock_forbidden": True, "historical_report_forbidden": True, "success_requires_current_run_evidence": True}
    envelope = {"task_summary": {**task, "top_function": "add", "verification_policy": policy}}
    (telemetry / "todo_input_envelope.json").write_text(json.dumps(envelope), encoding="utf-8")
    (telemetry / "todo_delivered_result.json").write_text(json.dumps({"status": "success"}), encoding="utf-8")
    (run_dir / "state.json").write_text(json.dumps({"task": task, "objective": "resource", "verification_policy": policy}), encoding="utf-8")
    result = _retention(run_dir)
    assert result["specialist_input_constraint_retention"]["rate"] == 1.0
    assert result["main_agent_result_constraint_retention"]["rate"] == 1.0
    assert all(item["field"] != "verification" for item in result["contract"])
