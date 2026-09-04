from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import random
import re
import shutil
import sqlite3
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .agent_quality_benchmark import collect_run_metrics
from ..tools.report_parser import parse_csynth_report_file


MODES = {
    "A": {"input_context_mode": "full", "result_context_mode": "raw"},
    "B": {"input_context_mode": "scoped", "result_context_mode": "raw"},
    "C": {"input_context_mode": "scoped", "result_context_mode": "compressed"},
}
TEXT_SUFFIXES = {".txt", ".log", ".rpt", ".json", ".jsonl", ".md", ".cpp", ".cc", ".c", ".h", ".hpp", ".tcl", ".yml", ".yaml"}
MAX_ESTIMATED_VIVADO_PATH = 200
VIVADO_INTERNAL_SUFFIX = Path("vivado_project") / "solution1" / ".autopilot" / "db" / "very_long_generated_dataflow_process_name.autopilot.flow.log"
EXTERNAL_HTTP_CODES = {401, 402, 429, 500, 502, 503, 504}


class EvaluationConfigurationError(RuntimeError):
    """The benchmark configuration is invalid before an Agent run starts."""


def make_benchmark_run_id(case_id: str, mode: str, trial: int, suffix: str | None = None) -> str:
    safe_case = re.sub(r"[^A-Za-z0-9_]+", "_", case_id).strip("_").lower() or "case"
    unique = suffix or uuid.uuid4().hex[:6]
    return f"{safe_case}_{mode}_t{trial}_{unique}"


def estimate_vivado_internal_path(run_dir: Path) -> dict[str, Any]:
    estimated = run_dir.resolve() / VIVADO_INTERNAL_SUFFIX
    return {
        "run_dir": str(run_dir.resolve()),
        "estimated_longest_path": str(estimated),
        "estimated_length": len(str(estimated)),
        "limit": MAX_ESTIMATED_VIVADO_PATH,
        "valid": len(str(estimated)) <= MAX_ESTIMATED_VIVADO_PATH,
    }


def validate_execution_path(run_dir: Path) -> dict[str, Any]:
    result = estimate_vivado_internal_path(run_dir)
    if not result["valid"]:
        raise EvaluationConfigurationError(
            f"Estimated Vivado internal path is {result['estimated_length']} characters; "
            f"the benchmark limit is {result['limit']}: {result['estimated_longest_path']}"
        )
    return result


def classify_external_failure(text: str) -> dict[str, Any]:
    normalized = text or ""
    http_match = re.search(r"(?:HTTP(?: error)?[: ]+|status(?: code)?[: ]+)(401|402|429|500|502|503|504)\b", normalized, re.I)
    if not http_match:
        http_match = re.search(r"\b(401|402|429|500|502|503|504)\b.*(?:auth|invalid|balance|rate|overload|gateway|service|server)", normalized, re.I)
    if http_match and int(http_match.group(1)) in EXTERNAL_HTTP_CODES:
        code = int(http_match.group(1))
        labels = {401: "authentication_failure", 402: "insufficient_balance", 429: "rate_limit", 500: "http_500", 502: "bad_gateway", 503: "service_unavailable", 504: "gateway_timeout"}
        return {"external_failure": True, "external_failure_type": labels[code], "external_failure_message": f"HTTP {code}"}
    lowered = normalized.lower()
    if any(marker in lowered for marker in ("timed out", "timeout", "read timeout")) and any(marker in lowered for marker in ("api", "openai", "llm", "http")):
        return {"external_failure": True, "external_failure_type": "api_timeout", "external_failure_message": "LLM API timeout"}
    if any(marker in lowered for marker in ("connection refused", "connection reset", "name or service not known", "temporary failure in name resolution", "urlopen error")):
        return {"external_failure": True, "external_failure_type": "network_failure", "external_failure_message": "LLM API network failure"}
    return {"external_failure": False, "external_failure_type": None, "external_failure_message": None}


def _json_load(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _json_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class DeepSeekV4Tokenizer:
    """Strict local tokenizer loader. It never falls back to a heuristic."""

    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        if not self.path.is_dir():
            raise FileNotFoundError(f"DeepSeek V4 tokenizer directory does not exist: {self.path}")
        try:
            from transformers import AutoTokenizer

            self.tokenizer = AutoTokenizer.from_pretrained(
                str(self.path),
                local_files_only=True,
                trust_remote_code=False,
            )
        except Exception as exc:
            raise RuntimeError(f"DeepSeek V4 tokenizer failed to load: {exc}") from exc
        config = _json_load(self.path / "tokenizer_config.json", {})
        if int(config.get("model_max_length") or 0) != 1_048_576 or not (self.path / "tokenizer.json").exists():
            raise RuntimeError("Tokenizer does not satisfy the frozen DeepSeek V4 tokenizer contract.")

    def count(self, value: Any) -> int:
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        return len(self.tokenizer.encode(text, add_special_tokens=False))

    def metadata(self) -> dict[str, Any]:
        files = []
        for path in sorted(item for item in self.path.rglob("*") if item.is_file() and ".cache" not in item.parts):
            files.append({"path": str(path.relative_to(self.path)), "bytes": path.stat().st_size, "sha256": _sha256(path)})
        return {
            "source": "deepseek-ai/DeepSeek-V4-Pro",
            "local_path": str(self.path),
            "tokenizer_class": self.tokenizer.__class__.__name__,
            "vocab_size": len(self.tokenizer),
            "model_max_length": self.tokenizer.model_max_length,
            "files": files,
            "aggregate_sha256": hashlib.sha256("".join(item["sha256"] for item in files).encode()).hexdigest(),
        }


def _git(workspace: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=workspace, capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _benchmark_code_dirty(workspace: Path) -> bool:
    if _git(workspace, "diff", "--name-only") or _git(workspace, "diff", "--cached", "--name-only"):
        return True
    relevant_untracked_prefixes = (
        "src/dl_op_to_hls/",
        "benchmarks/context_ablation",
        "tests/test_context_ablation",
        "docs/context_ablation",
    )
    for line in _git(workspace, "status", "--porcelain", "--untracked-files=normal").splitlines():
        path = line[3:].replace("\\", "/") if len(line) > 3 else ""
        if line.startswith("??") and path.startswith(relevant_untracked_prefixes):
            return True
    return False


def build_manifest(workspace: Path, suite_path: Path, output_dir: Path, smoke: bool) -> dict[str, Any]:
    suite = _json_load(suite_path, {})
    cases = list(suite.get("cases") or [])
    if smoke:
        smoke_case = next((case for case in cases if case.get("case_id") == "add_llm"), None)
        cases = [smoke_case or cases[0]]
    frozen_tasks = output_dir / "frozen_tasks"
    frozen_tasks.mkdir(parents=True, exist_ok=True)
    entries = []
    for index, case in enumerate(cases):
        source = (workspace / case["task"]).resolve()
        if not source.is_file():
            raise FileNotFoundError(f"Replay task is missing: {source}")
        task = _json_load(source, {})
        candidate = dict(task.get("llm_candidate") or {})
        candidate["reuse_verified_implementations"] = False
        task["llm_candidate"] = candidate
        frozen = frozen_tasks / f"{index + 1:02d}_{case['case_id']}.json"
        _json_write(frozen, task)
        entries.append(
            {
                **case,
                "source_task": str(source),
                "source_sha256": _sha256(source),
                "frozen_task": str(frozen),
                "frozen_sha256": _sha256(frozen),
                "acceptance": {
                    "current_run_evidence_required": True,
                    "mock_forbidden": True,
                    "historical_implementation_reuse": False,
                },
            }
        )
    return {
        "schema_version": "1.0",
        "suite": suite.get("suite_name"),
        "smoke": smoke,
        "git_commit": _git(workspace, "rev-parse", "HEAD"),
        "modes": MODES,
        "rotation": "ABC/BCA/CAB",
        "cases": entries,
    }


def _sqlite_snapshot(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if not source.exists():
        sqlite3.connect(target).close()
        return
    with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
        src.backup(dst)


def _mode_order(index: int) -> list[str]:
    orders = [["A", "B", "C"], ["B", "C", "A"], ["C", "A", "B"]]
    return orders[index % len(orders)]


def _find_run_dir(runs_root: Path) -> Path | None:
    candidates = [item for item in runs_root.iterdir() if item.is_dir() and item.name not in {"sessions", "jobs"}]
    candidates = [item for item in candidates if (item / "state.json").exists()]
    return max(candidates, key=lambda item: item.stat().st_mtime) if candidates else None


def _trace(run_dir: Path) -> list[dict[str, Any]]:
    events = []
    path = run_dir / "trace.jsonl"
    if not path.exists():
        return events
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def _token_payload_metrics(run_dir: Path, tokenizer: DeepSeekV4Tokenizer) -> dict[str, Any]:
    telemetry_dir = run_dir / "context_telemetry"
    input_files = sorted(telemetry_dir.glob("*_input_envelope.json")) if telemetry_dir.exists() else []
    raw_files = sorted(telemetry_dir.glob("*_raw_specialist_result.json")) if telemetry_dir.exists() else []
    delivered_files = sorted(telemetry_dir.glob("*_delivered_result.json")) if telemetry_dir.exists() else []
    inputs = [_json_load(path, {}) for path in input_files]
    raw = [_json_load(path, {}) for path in raw_files]
    delivered = [_json_load(path, {}) for path in delivered_files]
    input_tokens = [tokenizer.count(item) for item in inputs]
    raw_tokens = [tokenizer.count(item) for item in raw]
    delivered_tokens = [tokenizer.count(item) for item in delivered]
    full_state = _json_load(run_dir / "state.json", {})
    text_artifact_tokens = 0
    text_artifact_count = 0
    for path in run_dir.rglob("*"):
        if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES and "context_telemetry" not in path.parts:
            text_artifact_tokens += tokenizer.count(path.read_text(encoding="utf-8", errors="replace"))
            text_artifact_count += 1
    removed = [max(0, raw_tokens[i] - delivered_tokens[i]) for i in range(min(len(raw_tokens), len(delivered_tokens)))]
    context_build_ms = sum(float((item.get("constraints") or {}).get("context_build_ms") or 0) for item in inputs)
    result_merge_ms = sum(float((item.get("context_usage") or {}).get("result_merge_ms") or 0) for item in raw)
    return {
        "specialist_input_tokens": sum(input_tokens),
        "specialist_input_tokens_per_call": input_tokens,
        "raw_specialist_result_tokens": sum(raw_tokens),
        "delivered_result_tokens": sum(delivered_tokens),
        "delivered_result_tokens_per_call": delivered_tokens,
        "removed_result_tokens": sum(removed),
        "full_final_state_tokens": tokenizer.count(full_state),
        "raw_text_artifact_tokens": text_artifact_tokens,
        "raw_text_artifact_count": text_artifact_count,
        "context_envelope_count": len(inputs),
        "context_build_ms": round(context_build_ms, 3),
        "result_compression_and_merge_ms": round(result_merge_ms, 3),
    }


def _api_usage(events: list[dict[str, Any]]) -> dict[str, Any]:
    usage = [item for item in events if item.get("event") == "LLMUsageRecorded"]
    return {
        "llm_calls": len(usage),
        "prompt_tokens": sum(int(item.get("input_tokens") or 0) for item in usage),
        "completion_tokens": sum(int(item.get("output_tokens") or 0) for item in usage),
        "total_tokens": sum(int(item.get("total_tokens") or 0) for item in usage),
        "cache_hit_tokens": sum(int(item.get("cache_hit_tokens") or 0) for item in usage),
        "cache_miss_tokens": sum(int(item.get("cache_miss_tokens") or 0) for item in usage),
        "latency_ms": round(sum(float(item.get("latency_ms") or 0) for item in usage), 3),
    }


def _current_run_verification(run_dir: Path, events: list[dict[str, Any]]) -> dict[str, Any]:
    """Collect independent CSim and CSynth evidence owned by exactly one run."""
    pre_tools = [str(item.get("tool") or "") for item in events if item.get("event") == "PreToolUse"]
    failed_tools = [str(item.get("tool") or "") for item in events if item.get("event") == "ToolFailed"]
    csim_tools = {"vivado.run_csim", "verify.run_csim", "verify_candidate.run"}
    csynth_tools = {"vivado.run_csynth", "verify_candidate.run"}

    log_paths = sorted(
        path for path in run_dir.rglob("*.log")
        if path.is_file() and any(marker in path.name.lower() for marker in ("csim", "csynth", "vivado_hls"))
    )
    golden_logs: list[dict[str, Any]] = []
    failed_marker_found = False
    for path in log_paths:
        content = path.read_text(encoding="utf-8", errors="replace")
        if "GOLDEN_CHECK_PASSED" in content:
            golden_logs.append({"path": str(path), "sha256": _sha256(path)})
        failed_marker_found = failed_marker_found or "GOLDEN_CHECK_FAILED" in content

    csim_started = any(tool in csim_tools for tool in pre_tools) or bool(log_paths)
    golden_marker_found = bool(golden_logs)
    # verify_candidate.run can fail during CSynth after CSim already passed. Only
    # an explicit standalone CSim failure may invalidate the CSim exit status.
    standalone_csim_failed = any(tool in {"vivado.run_csim", "verify.run_csim"} for tool in failed_tools)
    csim_exit_code = 0 if golden_marker_found else (1 if csim_started and (failed_marker_found or standalone_csim_failed) else None)
    golden_csim_passed = bool(csim_started and csim_exit_code == 0 and golden_marker_found)

    report_candidates = sorted(path for path in run_dir.rglob("*_csynth.rpt") if path.is_file())
    report_evidence: list[dict[str, Any]] = []
    for path in report_candidates:
        parsed = parse_csynth_report_file(str(path))
        if parsed.get("status") != "success":
            continue
        digest = _sha256(path)
        if digest:
            report_evidence.append({"path": str(path), "sha256": digest, "parsed": parsed})
    csynth_started = any(tool in csynth_tools for tool in pre_tools) or bool(report_candidates)
    csynth_failed_event = any(tool in csynth_tools for tool in failed_tools)
    csynth_report_present = bool(report_evidence)
    csynth_exit_code = 0 if csynth_report_present and not csynth_failed_event else (1 if csynth_started and csynth_failed_event else None)
    real_csynth_completed = bool(csynth_started and csynth_exit_code == 0 and csynth_report_present)
    return {
        "csim_started": csim_started,
        "csim_exit_code": csim_exit_code,
        "golden_marker_found": golden_marker_found,
        "golden_csim_passed": golden_csim_passed,
        "golden_log_evidence": golden_logs,
        "csynth_started": csynth_started,
        "csynth_exit_code": csynth_exit_code,
        "csynth_report_present": csynth_report_present,
        "real_csynth_completed": real_csynth_completed,
        "csynth_report_evidence": report_evidence,
    }


def _contains_semantic_value(payload: Any, key: str, expected: Any) -> tuple[bool, Any]:
    if isinstance(payload, dict):
        if key in payload:
            actual = payload[key]
            if actual == expected:
                return True, actual
        for value in payload.values():
            found, actual = _contains_semantic_value(value, key, expected)
            if found:
                return True, actual
    elif isinstance(payload, list):
        for value in payload:
            found, actual = _contains_semantic_value(value, key, expected)
            if found:
                return True, actual
    return False, None


def _constraint_contract(task: dict[str, Any], state: dict[str, Any]) -> list[dict[str, Any]]:
    target = task.get("target") or {}
    candidate = task.get("candidate_contract") or {}
    objective = state.get("objective") or task.get("objective") or (task.get("optimization") or {}).get("objective")
    candidates = [
        ("task_type", task.get("task_type")),
        ("op_type", task.get("op_type")),
        ("model_path", task.get("model_path")),
        ("hls_project_dir", task.get("hls_project_dir")),
        ("input_shape", task.get("input_shape")),
        ("output_shape", task.get("output_shape")),
        ("dtype", task.get("dtype") or (task.get("hls4ml") or {}).get("precision")),
        ("top_function", task.get("top_function") or task.get("name")),
        ("function_signature", candidate.get("signature")),
        ("part", target.get("part")),
        ("clock_period", target.get("clock_period")),
        ("objective", objective),
        ("required_files", list(candidate.get("required_files") or [])),
        ("mock_forbidden", True),
        ("historical_report_forbidden", True),
        ("success_requires_current_run_evidence", True),
    ]
    return [{"field": key, "value": value} for key, value in candidates if value not in (None, [], "")]


def _score_constraint_payload(contract: list[dict[str, Any]], payload: Any, loss_step: str) -> dict[str, Any]:
    details = []
    for item in contract:
        kept, transferred = _contains_semantic_value(payload, item["field"], item["value"])
        details.append(
            {
                "field": item["field"],
                "original_value": item["value"],
                "transferred_value": transferred,
                "retained": kept,
                "first_loss_step": None if kept else loss_step,
            }
        )
    return {
        "retained": sum(bool(item["retained"]) for item in details),
        "required": len(details),
        "rate": sum(bool(item["retained"]) for item in details) / max(1, len(details)),
        "missing": [item for item in details if not item["retained"]],
        "details": details,
    }


def _retention(run_dir: Path) -> dict[str, Any]:
    state = _json_load(run_dir / "state.json", {})
    task = state.get("task") or {}
    contract = _constraint_contract(task, state)
    telemetry = run_dir / "context_telemetry"
    envelopes = [_json_load(path, {}) for path in sorted(telemetry.glob("*_input_envelope.json"))] if telemetry.exists() else []
    delivered = [_json_load(path, {}) for path in sorted(telemetry.glob("*_delivered_result.json"))] if telemetry.exists() else []
    specialist = _score_constraint_payload(contract, envelopes, "ContextEnvelopeCreated")
    normalized_constraints = {item["field"]: item["value"] for item in contract}
    main_result = _score_constraint_payload(
        contract,
        {"state": state, "normalized_task_constraints": normalized_constraints, "delivered_results": delivered},
        "SpecialistResultMerged",
    )
    semantic = {
        "correct": specialist["retained"] + main_result["retained"],
        "checked": specialist["required"] + main_result["required"],
    }
    semantic["rate"] = semantic["correct"] / max(1, semantic["checked"])
    return {
        "contract": contract,
        "specialist_input_constraint_retention": specialist,
        "main_agent_result_constraint_retention": main_result,
        "constraint_semantic_correctness": semantic,
        "rate": specialist["rate"],
    }


def analyze_run(run_dir: Path, mode: str, case: dict[str, Any], tokenizer: DeepSeekV4Tokenizer, wall_s: float) -> dict[str, Any]:
    base = collect_run_metrics(run_dir)
    events = _trace(run_dir)
    api = _api_usage(events)
    tokens = _token_payload_metrics(run_dir, tokenizer)
    verification = _current_run_verification(run_dir, events)
    csim_passed = verification["golden_csim_passed"]
    csynth_passed = verification["real_csynth_completed"]
    false_success = base.get("status") == "success" and not (base.get("agent_task_success") and (csynth_passed or base.get("selected_path") == "unsupported_path"))
    retention = _retention(run_dir)
    coverage = set(case.get("coverage") or [])
    task_category = str(case.get("category") or ("unsupported" if "unsupported" in coverage or "boundary" in coverage else "supported"))
    unsupported_case = task_category == "unsupported"
    recovery_challenge = task_category == "recovery_challenge"
    selected_path = base.get("selected_path")
    path_selection_matches_case = (
        selected_path == "unsupported_path"
        if task_category in {"unsupported", "recovery_challenge"}
        else selected_path != "unsupported_path"
    )
    post_tool_events = [item for item in events if item.get("event") == "PostToolUse"]
    tool_duration_ms = sum(float(item.get("duration_ms") or 0) for item in post_tool_events)
    vivado_duration_ms = sum(
        float(item.get("duration_ms") or 0)
        for item in post_tool_events
        if str(item.get("tool") or "").startswith("vivado.")
    )
    pre_tool_events = [item for item in events if item.get("event") == "PreToolUse"]
    retries = sum(1 for item in pre_tool_events if int(item.get("attempt") or 1) > 1)
    tool_sequence = [str(item.get("tool") or "") for item in pre_tool_events]
    duplicate_calls = sum(1 for left, right in zip(tool_sequence, tool_sequence[1:]) if left and left == right)
    evidence_rate = base.get("bad_case_governance", {}).get("tool_evidence_valid_rate", 0)
    evidence_count = base.get("bad_case_governance", {}).get("tool_evidence_receipt_count", 0)
    evidence_complete = bool(
        base.get("selected_path") == "unsupported_path"
        or (evidence_count > 0 and evidence_rate == 1.0 and (csim_passed or csynth_passed))
    )
    return {
        "case_id": case["case_id"],
        "mode": mode,
        "mode_config": MODES[mode],
        "run_id": base.get("run_id"),
        "run_dir": str(run_dir),
        "status": base.get("status"),
        "selected_path": selected_path,
        "task_category": task_category,
        "path_selection_matches_case": path_selection_matches_case,
        "task_completed": bool(base.get("agent_task_success") and not false_success),
        "golden_csim_passed": csim_passed,
        "real_csynth_completed": csynth_passed,
        "verification_evidence": verification,
        "tool_selection_correct": bool(
            path_selection_matches_case
            and base.get("toolchain_quality", {}).get("correct_for_selected_path")
        ),
        "direct_tool_trace_complete": bool(
            path_selection_matches_case
            and base.get("toolchain_quality", {}).get("direct_trace_correct_for_selected_path")
        ),
        "tool_parameter_correct": base.get("bad_case_governance", {}).get("tool_postcondition_failure_count", 0) == 0,
        "completion_gate_passed": bool(base.get("bad_case_governance", {}).get("completion_gate_passed")),
        "critical_constraint_retention": retention,
        "evidence_complete": evidence_complete,
        "false_success": false_success,
        "correct_rejection": bool(base.get("selected_path") == "unsupported_path" and base.get("status") in {"partial_success", "unsupported", "success"}),
        "recovery_challenge_handled": bool(
            recovery_challenge
            and base.get("selected_path") == "unsupported_path"
            and base.get("status") in {"partial_success", "unsupported"}
            and base.get("repair_quality", {}).get("failure_stage_count", 0) > 0
        ),
        "invalid_vivado_call_for_unsupported": bool(unsupported_case and verification["csynth_started"]),
        "repair_final_success": bool(base.get("repair_quality", {}).get("repair_success")),
        "wall_runtime_s": wall_s,
        "tool_calls": base.get("tool_call_count", 0),
        "tool_failures": base.get("tool_failure_count", 0),
        "tool_retries": retries,
        "invalid_duplicate_calls": duplicate_calls,
        "llm_format_errors": base.get("llm_harness", {}).get("json_repair_count", 0),
        "replans": base.get("bad_case_governance", {}).get("progress_replan_event_count", 0),
        "early_termination": base.get("bad_case_governance", {}).get("progress_terminate_event_count", 0),
        "repair_attempts": base.get("repair_quality", {}).get("repair_attempts", 0),
        "api_usage": api,
        "offline_tokens": tokens,
        "timing": {
            "llm_ms": api["latency_ms"],
            "tool_ms": round(tool_duration_ms, 3),
            "vivado_ms": round(vivado_duration_ms, 3),
        },
        "context_overflow": any(
            count > tokenizer.tokenizer.model_max_length
            for count in tokens["specialist_input_tokens_per_call"]
        ),
        "base_metrics": base,
        "run_valid_for_comparison": True,
        "external_failure": False,
        "external_failure_type": None,
        "external_failure_message": None,
    }


def _bootstrap_median(values: list[float], samples: int = 4000, seed: int = 20260901) -> dict[str, Any]:
    if not values:
        return {"median": None, "ci95": [None, None], "n": 0}
    rng = random.Random(seed)
    medians = []
    for _ in range(samples):
        medians.append(statistics.median(rng.choice(values) for _ in values))
    medians.sort()
    return {
        "median": statistics.median(values),
        "ci95": [medians[int(0.025 * (samples - 1))], medians[int(0.975 * (samples - 1))]],
        "n": len(values),
    }


def _bootstrap_mean(values: list[float], samples: int = 4000, seed: int = 20260901) -> dict[str, Any]:
    if not values:
        return {"mean": None, "ci95": [None, None], "n": 0}
    rng = random.Random(seed)
    means = [statistics.mean(rng.choice(values) for _ in values) for _ in range(samples)]
    means.sort()
    return {
        "mean": statistics.mean(values),
        "ci95": [means[int(0.025 * (samples - 1))], means[int(0.975 * (samples - 1))]],
        "n": len(values),
    }


def _mcnemar_exact(left_only: int, right_only: int) -> dict[str, Any]:
    discordant = left_only + right_only
    if discordant == 0:
        return {"discordant": 0, "two_sided_p": 1.0}
    tail = min(left_only, right_only)
    probability = sum(math.comb(discordant, k) for k in range(tail + 1)) / (2**discordant)
    return {"discordant": discordant, "two_sided_p": min(1.0, 2 * probability)}


def paired_comparison(records: list[dict[str, Any]], left: str, right: str) -> dict[str, Any]:
    valid = [item for item in records if item.get("run_valid_for_comparison", True)]
    by_case = {(item["case_id"], int(item.get("trial_index") or 0), item["mode"]): item for item in valid}
    case_trials = sorted({(item["case_id"], int(item.get("trial_index") or 0)) for item in valid})
    pairs = [
        (by_case[(case, trial, left)], by_case[(case, trial, right)])
        for case, trial in case_trials
        if (case, trial, left) in by_case and (case, trial, right) in by_case
    ]
    binary_fields = ["task_completed", "golden_csim_passed", "real_csynth_completed", "tool_parameter_correct", "evidence_complete", "false_success"]
    continuous = {
        "api_prompt_tokens": lambda item: item["api_usage"]["prompt_tokens"],
        "api_total_tokens": lambda item: item["api_usage"]["total_tokens"],
        "offline_specialist_input_tokens": lambda item: item["offline_tokens"]["specialist_input_tokens"],
        "offline_delivered_result_tokens": lambda item: item["offline_tokens"]["delivered_result_tokens"],
        "wall_runtime_s": lambda item: item["wall_runtime_s"],
        "tool_calls": lambda item: item["tool_calls"],
    }
    binary = {}
    for field in binary_fields:
        values = [(int(bool(a.get(field))), int(bool(b.get(field)))) for a, b in pairs]
        diffs = [b - a for a, b in values]
        left_only = sum(1 for a, b in values if a == 1 and b == 0)
        right_only = sum(1 for a, b in values if a == 0 and b == 1)
        binary[field] = {
            "left_count": sum(a for a, _ in values),
            "right_count": sum(b for _, b in values),
            "absolute_rate_difference": sum(diffs) / max(1, len(diffs)),
            "discordant_left_only": left_only,
            "discordant_right_only": right_only,
            "mcnemar_exact": _mcnemar_exact(left_only, right_only),
            "paired_rate_difference_bootstrap": _bootstrap_mean([float(item) for item in diffs]),
        }
    numeric = {}
    for name, getter in continuous.items():
        diffs = [float(getter(b)) - float(getter(a)) for a, b in pairs]
        left_values = [float(getter(a)) for a, _ in pairs]
        right_values = [float(getter(b)) for _, b in pairs]
        numeric[name] = {
            "left_median": statistics.median(left_values) if left_values else None,
            "right_median": statistics.median(right_values) if right_values else None,
            "paired_median_difference": _bootstrap_median(diffs),
        }
    return {"comparison": f"{left}_vs_{right}", "n_pairs": len(pairs), "binary": binary, "continuous": numeric}


def _aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    groups = {}
    for mode in MODES:
        items = [item for item in records if item["mode"] == mode and item.get("run_valid_for_comparison", True)]
        supported = [item for item in items if item.get("task_category", "supported") == "supported"]
        unsupported = [item for item in items if item.get("task_category") == "unsupported"]
        recovery = [item for item in items if item.get("task_category") == "recovery_challenge"]
        groups[mode] = {
            "n": len(items),
            "task_completion_rate": sum(item["task_completed"] for item in items) / max(1, len(items)),
            "golden_csim_rate": sum(item["golden_csim_passed"] for item in items) / max(1, len(items)),
            "real_csynth_rate": sum(item["real_csynth_completed"] for item in items) / max(1, len(items)),
            "false_success_rate": sum(item["false_success"] for item in items) / max(1, len(items)),
            "constraint_retention_rate": statistics.mean(item["critical_constraint_retention"]["rate"] for item in items) if items else 0,
            "main_result_constraint_retention_rate": statistics.mean(
                item["critical_constraint_retention"].get("main_agent_result_constraint_retention", {}).get(
                    "rate", item["critical_constraint_retention"].get("rate", 0)
                ) for item in items
            ) if items else 0,
            "constraint_semantic_correctness_rate": statistics.mean(
                item["critical_constraint_retention"].get("constraint_semantic_correctness", {}).get(
                    "rate", item["critical_constraint_retention"].get("rate", 0)
                ) for item in items
            ) if items else 0,
            "median_api_prompt_tokens": statistics.median(item["api_usage"]["prompt_tokens"] for item in items) if items else None,
            "median_api_total_tokens": statistics.median(item["api_usage"]["total_tokens"] for item in items) if items else None,
            "median_offline_input_tokens": statistics.median(item["offline_tokens"]["specialist_input_tokens"] for item in items) if items else None,
            "median_runtime_s": statistics.median(item["wall_runtime_s"] for item in items) if items else None,
            "supported": {
                "n": len(supported),
                "end_to_end_success_rate": sum(bool(item.get("task_completed")) for item in supported) / max(1, len(supported)),
                "golden_csim_rate": sum(bool(item.get("golden_csim_passed")) for item in supported) / max(1, len(supported)),
                "real_csynth_rate": sum(bool(item.get("real_csynth_completed")) for item in supported) / max(1, len(supported)),
                "evidence_complete_rate": sum(bool(item.get("evidence_complete")) for item in supported) / max(1, len(supported)),
                "completion_gate_pass_rate": sum(bool(item.get("completion_gate_passed")) for item in supported) / max(1, len(supported)),
                "tool_selection_accuracy": sum(bool(item.get("tool_selection_correct")) for item in supported) / max(1, len(supported)),
                "direct_tool_trace_coverage": sum(bool(item.get("direct_tool_trace_complete")) for item in supported) / max(1, len(supported)),
            },
            "unsupported": {
                "n": len(unsupported),
                "correct_rejection_rate": sum(bool(item.get("correct_rejection")) for item in unsupported) / max(1, len(unsupported)),
                "false_success_rate": sum(bool(item.get("false_success")) for item in unsupported) / max(1, len(unsupported)),
                "invalid_vivado_call_rate": sum(bool(item.get("invalid_vivado_call_for_unsupported")) for item in unsupported) / max(1, len(unsupported)),
            },
            "recovery_challenge": {
                "n": len(recovery),
                "handled_rate": sum(bool(item.get("recovery_challenge_handled")) for item in recovery) / max(1, len(recovery)),
                "false_success_rate": sum(bool(item.get("false_success")) for item in recovery) / max(1, len(recovery)),
            },
        }
    return groups


def _write_reports(output_dir: Path, manifest: dict[str, Any], results: dict[str, Any]) -> None:
    aggregate = results["aggregate"]
    lines = [
        "# Context Ablation Repair And Rerun Report",
        "",
        f"Git commit: `{manifest['git_commit']}`",
        f"Valid runs: `{results['valid_run_count']}`; total attempts: `{results['total_attempt_count']}`; external failures: `{results['external_failure_count']}`.",
        "",
        "## Supported HLS Tasks",
        "",
        "| Mode | N | End-to-end | Golden CSim | Real CSynth | Completion gate | Evidence complete | Tool selection | Direct tool trace |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for mode in MODES:
        item = aggregate[mode]["supported"]
        lines.append(
            f"| {mode} | {item['n']} | {item['end_to_end_success_rate']:.3f} | {item['golden_csim_rate']:.3f} | {item['real_csynth_rate']:.3f} | {item['completion_gate_pass_rate']:.3f} | {item['evidence_complete_rate']:.3f} | {item['tool_selection_accuracy']:.3f} | {item['direct_tool_trace_coverage']:.3f} |"
        )
    lines.extend([
        "",
        "## Unsupported Tasks",
        "",
        "| Mode | N | Correct rejection | False success | Invalid Vivado call |",
        "|---|---:|---:|---:|---:|",
    ])
    for mode in MODES:
        item = aggregate[mode]["unsupported"]
        lines.append(f"| {mode} | {item['n']} | {item['correct_rejection_rate']:.3f} | {item['false_success_rate']:.3f} | {item['invalid_vivado_call_rate']:.3f} |")
    lines.extend([
        "",
        "## Recovery Challenges",
        "",
        "| Mode | N | Recovery handled | False success |",
        "|---|---:|---:|---:|",
    ])
    for mode in MODES:
        item = aggregate[mode]["recovery_challenge"]
        lines.append(f"| {mode} | {item['n']} | {item['handled_rate']:.3f} | {item['false_success_rate']:.3f} |")
    lines.extend([
        "",
        "## Context And Token Metrics",
        "",
        "| Mode | API prompt p50 | API total p50 | Specialist input p50 | Runtime p50 (s) | Input retention | Main-result retention | Semantic correctness |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for mode in MODES:
        item = aggregate[mode]
        lines.append(
            f"| {mode} | {item['median_api_prompt_tokens']} | {item['median_api_total_tokens']} | {item['median_offline_input_tokens']} | {item['median_runtime_s']} | {item['constraint_retention_rate']:.3f} | {item['main_result_constraint_retention_rate']:.3f} | {item['constraint_semantic_correctness_rate']:.3f} |"
        )
    lines.extend(["", "## Paired Comparisons", ""])
    for comparison in results["paired_comparisons"]:
        token = comparison["continuous"]["api_total_tokens"]
        lines.append(
            f"- `{comparison['comparison']}`: {comparison['n_pairs']} task/trial pairs; API-token paired median difference `{token['paired_median_difference']['median']}`, 95% CI `{token['paired_median_difference']['ci95']}`."
        )
    lines.extend(["", "## Validity", ""])
    lines.extend(
        [
            f"- All valid runs use unique logical Run IDs: `{results['unique_logical_run_ids']}`.",
            f"- All Vivado path preflights stayed within {MAX_ESTIMATED_VIVADO_PATH} characters: `{results['all_paths_valid']}`.",
            "- External API failures are excluded from Token, quality, and confidence-interval statistics; any affected A/B/C pair is rerun in full.",
            "- Golden CSim and real CSynth are independently derived from current-run logs and hashed reports.",
        ]
    )
    (output_dir / "context_ablation_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    a = aggregate["A"]
    c = aggregate["C"]
    a_supported = a["supported"]
    c_supported = c["supported"]
    ac = next(item for item in results["paired_comparisons"] if item["comparison"] == "A_vs_C")
    token_ci = ac["continuous"]["api_total_tokens"]["paired_median_difference"]["ci95"]
    allowed = (
        a_supported["golden_csim_rate"] > 0
        and a_supported["real_csynth_rate"] > 0
        and c_supported["end_to_end_success_rate"] >= a_supported["end_to_end_success_rate"] - 0.05
        and c_supported["golden_csim_rate"] >= a_supported["golden_csim_rate"]
        and c_supported["real_csynth_rate"] >= a_supported["real_csynth_rate"]
        and c["false_success_rate"] == 0
        and c["constraint_retention_rate"] == 1.0
        and c_supported["evidence_complete_rate"] >= a_supported["evidence_complete_rate"]
        and (c["median_api_prompt_tokens"] or 0) < (a["median_api_prompt_tokens"] or 0)
        and token_ci[1] is not None and token_ci[1] < 0
    )
    conclusion = ["# Resume Conclusion", ""]
    if allowed:
        conclusion.append("允许表述：在冻结、配对、真实 LLM + Vivado HLS 任务上，scoped/compressed 显著降低了 API Token，且未观察到功能验证、综合完成率或证据完整率下降。")
    else:
        conclusion.append("当前只能表述为“降低 Token，但尚未证明质量无损”；至少一项预注册质量或统计门槛未满足。")
    conclusion.append("")
    conclusion.append("不能声称：该结果适用于任意模型、任意 FPGA 工具链或证明压缩是唯一因果因素。")
    (output_dir / "context_ablation_resume_conclusion.md").write_text("\n".join(conclusion) + "\n", encoding="utf-8")


def _chat_completions_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if urllib.parse.urlparse(normalized).path in {"", "/"}:
        normalized += "/v1"
    return normalized + "/chat/completions"


def api_preflight(base_url: str, api_key: str, model: str) -> dict[str, Any]:
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": "Reply with exactly OK."}],
            "max_tokens": 8,
            "temperature": 0,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        _chat_completions_url(base_url),
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    started = time.perf_counter()
    payload = None
    last_failure: dict[str, Any] | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                payload = json.loads(response.read().decode("utf-8"))
                break
        except urllib.error.HTTPError as exc:
            message = exc.read().decode("utf-8", errors="replace")[:500]
            last_failure = classify_external_failure(f"HTTP {exc.code} {message}")
            if exc.code == 402 or exc.code not in {429, 500, 502, 503, 504} or attempt == 2:
                break
            time.sleep(2**attempt)
        except Exception as exc:
            last_failure = classify_external_failure(f"LLM API {type(exc).__name__}: {exc}")
            if attempt == 2:
                break
            time.sleep(2**attempt)
    if payload is None:
        return {"status": "failed", "latency_s": round(time.perf_counter() - started, 3), **(last_failure or classify_external_failure("LLM API unknown failure"))}
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    return {
        "status": "success",
        "model": payload.get("model") or model,
        "latency_s": round(time.perf_counter() - started, 3),
        "usage": usage,
        "external_failure": False,
        "external_failure_type": None,
        "external_failure_message": None,
    }


def _runner_failure_record(
    *, case: dict[str, Any], mode: str, trial: int, attempt: int, run_id: str,
    run_dir: Path, wall_s: float, exit_code: int | None, output: str,
) -> dict[str, Any]:
    failure = classify_external_failure(output)
    return {
        "case_id": case["case_id"],
        "mode": mode,
        "trial_index": trial,
        "pair_attempt": attempt,
        "run_id": run_id,
        "run_dir": str(run_dir),
        "status": "external_failure" if failure["external_failure"] else "runner_failed",
        "process_exit_code": exit_code,
        "wall_runtime_s": wall_s,
        "run_valid_for_comparison": False,
        **failure,
    }


def validate_resume_checkpoint(
    *,
    workspace: Path,
    output_dir: Path,
    execution_root: Path,
    trials: int,
    smoke: bool,
    model: str,
    base_url: str,
    tokenizer_sha256: str,
    max_pair_attempts: int,
    run_timeout_seconds: int,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], set[tuple[int, str]]]:
    manifest = _json_load(output_dir / "context_ablation_manifest.json")
    environment = _json_load(output_dir / "environment.json")
    partial = _json_load(output_dir / "context_ablation_results.partial.json", {"runs": []})
    if not isinstance(manifest, dict) or not isinstance(environment, dict):
        raise EvaluationConfigurationError("Resume requires the original manifest and environment files.")
    expected = {
        "git_commit": (_git(workspace, "rev-parse", "HEAD"), manifest.get("git_commit")),
        "execution_root": (str(execution_root), manifest.get("execution_root")),
        "trials": (trials, manifest.get("trials")),
        "smoke": (smoke, manifest.get("smoke")),
        "modes": (MODES, manifest.get("modes")),
        "model": (model, environment.get("model")),
        "base_url": (base_url.rstrip("/"), str(environment.get("base_url") or "").rstrip("/")),
        "tokenizer_sha256": (tokenizer_sha256, environment.get("tokenizer_sha256")),
        "max_pair_attempts": (max_pair_attempts, manifest.get("max_pair_attempts")),
        "run_timeout_seconds": (run_timeout_seconds, manifest.get("run_timeout_seconds")),
    }
    mismatches = {key: {"requested": left, "frozen": right} for key, (left, right) in expected.items() if left != right}
    snapshot = output_dir / "memory_snapshot.db"
    frozen_snapshot_hash = environment.get("memory_snapshot_sha256")
    if not snapshot.is_file() or not frozen_snapshot_hash or _sha256(snapshot) != frozen_snapshot_hash:
        mismatches["memory_snapshot"] = {"requested": "present with matching SHA256", "frozen": frozen_snapshot_hash}
    if mismatches:
        raise EvaluationConfigurationError(f"Resume checkpoint does not match the frozen benchmark: {json.dumps(mismatches, ensure_ascii=False)}")

    records = list((partial or {}).get("runs") or [])
    invalid_runs = list(_json_load(output_dir / "invalid_runs.json", []) or [])
    raw_run_index = list(_json_load(output_dir / "raw_run_index.json", []) or [])
    valid_cases = {str(item["case_id"]) for item in manifest.get("cases", [])}
    groups: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for record in records:
        key = (int(record.get("trial_index", -1)), str(record.get("case_id") or ""))
        groups.setdefault(key, []).append(record)
    completed: set[tuple[int, str]] = set()
    for key, items in groups.items():
        trial, case_id = key
        modes = [str(item.get("mode")) for item in items]
        if trial < 0 or trial >= trials or case_id not in valid_cases or len(items) != 3 or set(modes) != set(MODES):
            raise EvaluationConfigurationError(f"Resume checkpoint contains a partial or duplicate pair: {key} modes={modes}")
        if not all(bool(item.get("run_valid_for_comparison")) for item in items):
            raise EvaluationConfigurationError(f"Resume checkpoint contains an invalid accepted pair: {key}")
        completed.add(key)

    accepted_ids = {str(item.get("run_id")) for item in records}
    invalid_ids = {str(item.get("run_id")) for item in invalid_runs}
    for item in raw_run_index:
        run_id = str(item.get("run_id") or "")
        key = (int(item.get("trial_index", -1)), str(item.get("case_id") or ""))
        if key not in completed and run_id not in accepted_ids and run_id not in invalid_ids:
            invalid_runs.append({**item, "status": "interrupted_incomplete_pair", "run_valid_for_comparison": False})
            invalid_ids.add(run_id)
    return manifest, records, invalid_runs, raw_run_index, completed


def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    workspace = Path(args.workspace).resolve()
    if _benchmark_code_dirty(workspace) and not args.manifest_only:
        raise RuntimeError("Context ablation requires a clean tracked worktree so every run maps to one Git commit.")
    tokenizer = DeepSeekV4Tokenizer(args.tokenizer_path)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_dir).resolve() if args.output_dir else workspace / "runs" / "benchmarks" / f"context_ablation_fixed_{timestamp}"
    execution_root = Path(args.execution_root)
    if not execution_root.is_absolute():
        raise EvaluationConfigurationError("--execution-root must be an absolute path.")
    execution_root = execution_root.resolve()
    execution_root.mkdir(parents=True, exist_ok=True)
    validate_execution_path(execution_root / "path_probe_A_t0_abcdef")
    resume = bool(getattr(args, "resume", False))
    if output_dir.exists() and any(output_dir.iterdir()) and not resume:
        raise FileExistsError(f"Benchmark output directory is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    trials = 1 if args.smoke else int(args.trials)
    if trials < 1:
        raise EvaluationConfigurationError("--trials must be at least 1.")
    max_pair_attempts = int(getattr(args, "max_pair_attempts", 4))
    run_timeout_seconds = int(getattr(args, "run_timeout_seconds", 3600))
    if max_pair_attempts < 1 or run_timeout_seconds < 1:
        raise EvaluationConfigurationError("Pair attempts and run timeout must be positive.")
    tokenizer_metadata = tokenizer.metadata()
    model = os.environ.get("DL_OP_TO_HLS_LLM_MODEL", "deepseek-v4-pro")
    base_url = os.environ.get("DL_OP_TO_HLS_LLM_BASE_URL", "https://api.deepseek.com")
    source_db = workspace / "runs" / "metadata.db"
    memory_snapshot = output_dir / "memory_snapshot.db"
    completed_pairs: set[tuple[int, str]] = set()
    if resume:
        manifest, records, invalid_runs, raw_run_index, completed_pairs = validate_resume_checkpoint(
            workspace=workspace,
            output_dir=output_dir,
            execution_root=execution_root,
            trials=trials,
            smoke=bool(args.smoke),
            model=model,
            base_url=base_url,
            tokenizer_sha256=tokenizer_metadata["aggregate_sha256"],
            max_pair_attempts=max_pair_attempts,
            run_timeout_seconds=run_timeout_seconds,
        )
        resume_history = list(_json_load(output_dir / "resume_history.json", []) or [])
        resume_history.append(
            {
                "resumed_at": datetime.now().isoformat(),
                "completed_pair_count": len(completed_pairs),
                "accepted_run_count": len(records),
                "isolated_invalid_or_interrupted_count": len(invalid_runs),
            }
        )
        _json_write(output_dir / "resume_history.json", resume_history)
        _json_write(output_dir / "invalid_runs.json", invalid_runs)
    else:
        manifest = build_manifest(workspace, (workspace / args.suite).resolve(), output_dir, args.smoke)
        manifest["trials"] = trials
        manifest["execution_root"] = str(execution_root)
        manifest["max_pair_attempts"] = max_pair_attempts
        manifest["run_timeout_seconds"] = run_timeout_seconds
        _json_write(output_dir / "context_ablation_manifest.json", manifest)
        _json_write(output_dir / "tokenizer_metadata.json", tokenizer_metadata)
        _sqlite_snapshot(source_db, memory_snapshot)
        environment = {
            "git_commit": manifest["git_commit"],
            "git_status_porcelain": _git(workspace, "status", "--porcelain"),
            "model": model,
            "base_url": base_url,
            "execution_root": str(execution_root),
            "prompt_version": _git(workspace, "rev-parse", "HEAD:src/dl_op_to_hls/llm/prompts.py"),
            "python": sys.version,
            "platform": platform.platform(),
            "vivado_hls_path": os.environ.get("DL_OP_TO_HLS_VIVADO_HLS_PATH", r"D:\Xilinx\Vivado\2018.3\bin\vivado_hls.bat"),
            "tokenizer_sha256": tokenizer_metadata["aggregate_sha256"],
            "memory_snapshot_sha256": _sha256(memory_snapshot),
        }
        _json_write(output_dir / "environment.json", environment)
        records = []
        invalid_runs = []
        raw_run_index = []
    if args.manifest_only:
        return {"status": "manifest_created", "output_dir": str(output_dir), "manifest": manifest}
    if not os.environ.get("DL_OP_TO_HLS_LLM_API_KEY") and not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("Real benchmark requires DL_OP_TO_HLS_LLM_API_KEY or OPENAI_API_KEY in the environment.")
    api_key = os.environ.get("DL_OP_TO_HLS_LLM_API_KEY") or os.environ["OPENAI_API_KEY"]
    preflight = api_preflight(base_url, api_key, model)
    _json_write(output_dir / "api_preflight.json", preflight)
    if preflight.get("status") != "success":
        raise RuntimeError(f"LLM API preflight failed: {preflight.get('external_failure_type')}: {preflight.get('external_failure_message')}")

    for trial in range(trials):
        for case in manifest["cases"]:
            pair_key = (trial, str(case["case_id"]))
            if pair_key in completed_pairs:
                continue
            pair_completed = False
            previous_attempt = max(
                (int(item.get("pair_attempt") or 0) for item in raw_run_index if int(item.get("trial_index", -1)) == trial and str(item.get("case_id")) == str(case["case_id"])),
                default=0,
            )
            for pair_attempt in range(previous_attempt + 1, max_pair_attempts + 1):
                pair_records: list[dict[str, Any]] = []
                pair_has_external_failure = False
                for mode in _mode_order(trial):
                    run_id = make_benchmark_run_id(case["case_id"], mode, trial)
                    actual_run = execution_root / run_id
                    path_preflight = validate_execution_path(actual_run)
                    isolated_db = execution_root / f"{run_id}.db"
                    _sqlite_snapshot(memory_snapshot, isolated_db)
                    env = os.environ.copy()
                    env.update(
                        {
                            "DL_OP_TO_HLS_INPUT_CONTEXT_MODE": MODES[mode]["input_context_mode"],
                            "DL_OP_TO_HLS_RESULT_CONTEXT_MODE": MODES[mode]["result_context_mode"],
                            "DL_OP_TO_HLS_RUNS_ROOT": str(execution_root),
                            "DL_OP_TO_HLS_RUN_ID": run_id,
                            "DL_OP_TO_HLS_DB_PATH": str(isolated_db),
                            "DL_OP_TO_HLS_RUNTIME_MODE": "strict",
                            "DL_OP_TO_HLS_MOCK_TOOLS": "0",
                            "DL_OP_TO_HLS_MOCK_HLS4ML": "0",
                            "DL_OP_TO_HLS_MOCK_VIVADO": "0",
                            "DL_OP_TO_HLS_LLM_ENABLED": "1",
                            "DL_OP_TO_HLS_LLM_MODEL": model,
                            "DL_OP_TO_HLS_LLM_BASE_URL": base_url,
                            "DL_OP_TO_HLS_PIN_LLM_RUNTIME_CONFIG": "1",
                            "DL_OP_TO_HLS_VIVADO_HLS_PATH": os.environ.get("DL_OP_TO_HLS_VIVADO_HLS_PATH", r"D:\Xilinx\Vivado\2018.3\bin\vivado_hls.bat"),
                            "DL_OP_TO_HLS_REUSE_VERIFIED_IMPLEMENTATIONS": "0",
                        }
                    )
                    command = [sys.executable, "-m", "dl_op_to_hls.cli", "run-llm", case["frozen_task"], "--real-tools"]
                    start = time.perf_counter()
                    stdout = ""
                    stderr = ""
                    exit_code: int | None = None
                    try:
                        process = subprocess.run(
                            command, cwd=workspace, env=env, capture_output=True, text=True,
                            errors="replace", check=False, timeout=run_timeout_seconds,
                        )
                        stdout, stderr, exit_code = process.stdout, process.stderr, process.returncode
                    except subprocess.TimeoutExpired as exc:
                        stdout = str(exc.stdout or "")
                        stderr = str(exc.stderr or "") + "\nBenchmark process timeout"
                    wall_s = round(time.perf_counter() - start, 3)
                    io_dir = output_dir / "runner_io" / run_id
                    io_dir.mkdir(parents=True, exist_ok=True)
                    (io_dir / "stdout.txt").write_text(stdout, encoding="utf-8", errors="replace")
                    (io_dir / "stderr.txt").write_text(stderr, encoding="utf-8", errors="replace")
                    combined = stdout + "\n" + stderr
                    external = classify_external_failure(combined)
                    if actual_run.is_dir() and (actual_run / "state.json").is_file():
                        record = analyze_run(actual_run, mode, case, tokenizer, wall_s)
                        record.update({"trial_index": trial, "pair_attempt": pair_attempt, "process_exit_code": exit_code, "path_preflight": path_preflight})
                        record.update(external)
                        record["run_valid_for_comparison"] = not external["external_failure"] and record["api_usage"]["llm_calls"] > 0
                    else:
                        record = _runner_failure_record(
                            case=case, mode=mode, trial=trial, attempt=pair_attempt, run_id=run_id,
                            run_dir=actual_run, wall_s=wall_s, exit_code=exit_code, output=combined,
                        )
                    pair_records.append(record)
                    raw_run_index.append({"case_id": case["case_id"], "mode": mode, "trial_index": trial, "pair_attempt": pair_attempt, "run_id": run_id, "run_dir": str(actual_run), "valid": record["run_valid_for_comparison"]})
                    if record.get("external_failure"):
                        pair_has_external_failure = True
                        if record.get("external_failure_type") in {"authentication_failure", "insufficient_balance"}:
                            invalid_runs.extend(pair_records)
                            _json_write(output_dir / "invalid_runs.json", invalid_runs)
                            _json_write(output_dir / "raw_run_index.json", raw_run_index)
                            raise RuntimeError(
                                "Benchmark stopped immediately because the LLM provider reported "
                                f"{record.get('external_failure_type')}."
                            )
                        break
                if pair_has_external_failure or not all(item.get("run_valid_for_comparison") for item in pair_records):
                    invalid_runs.extend(pair_records)
                    _json_write(output_dir / "invalid_runs.json", invalid_runs)
                    continue
                records.extend(pair_records)
                pair_completed = True
                _json_write(output_dir / "context_ablation_results.partial.json", {"status": "running", "runs": records})
                _json_write(output_dir / "raw_run_index.json", raw_run_index)
                break
            if not pair_completed:
                raise RuntimeError(f"Could not obtain a valid A/B/C pair for {case['case_id']} trial {trial} after {max_pair_attempts} attempts.")

    complete_records = [item for item in records if item.get("run_valid_for_comparison")]
    expected_runs = len(manifest["cases"]) * 3 * trials
    paired = [
        paired_comparison(complete_records, "A", "B"),
        paired_comparison(complete_records, "B", "C"),
        paired_comparison(complete_records, "A", "C"),
    ]
    results = {
        "schema_version": "2.0",
        "status": "complete" if len(complete_records) == expected_runs else "partial",
        "runs": records,
        "valid_run_count": len(complete_records),
        "expected_valid_run_count": expected_runs,
        "total_attempt_count": len(raw_run_index),
        "external_failure_count": sum(bool(item.get("external_failure")) for item in invalid_runs),
        "unique_logical_run_ids": len({item.get("run_id") for item in complete_records}) == len(complete_records),
        "all_paths_valid": all(bool((item.get("path_preflight") or {}).get("valid")) for item in complete_records),
        "aggregate": _aggregate(complete_records),
        "paired_comparisons": paired,
    }
    if args.smoke:
        smoke_gate = {
            "api_calls_succeeded": all(item["api_usage"]["llm_calls"] > 0 for item in complete_records),
            "golden_csim_passed": all(item["golden_csim_passed"] for item in complete_records),
            "real_csynth_completed": all(item["real_csynth_completed"] for item in complete_records),
            "completion_gate_passed": all(item["completion_gate_passed"] for item in complete_records),
            "constraint_retention_100_percent": all(item["critical_constraint_retention"]["rate"] == 1.0 for item in complete_records),
            "unique_run_ids": results["unique_logical_run_ids"],
            "paths_under_limit": results["all_paths_valid"],
            "current_run_evidence_only": all(item["evidence_complete"] for item in complete_records),
        }
        smoke_gate["passed"] = len(complete_records) == 3 and all(smoke_gate.values())
        results["smoke_gate"] = smoke_gate
        if not smoke_gate["passed"]:
            results["status"] = "smoke_failed"
    _json_write(output_dir / "context_ablation_results.json", results)
    _json_write(output_dir / "invalid_runs.json", invalid_runs)
    _json_write(output_dir / "raw_run_index.json", raw_run_index)
    from .context_ablation_aggregate import divergence_analysis

    _json_write(output_dir / "divergence_analysis.json", {"pairs": divergence_analysis(complete_records)})
    _write_reports(output_dir, manifest, results)
    return {"status": results["status"], "output_dir": str(output_dir), "run_count": len(complete_records), "aggregate": results["aggregate"], "smoke_gate": results.get("smoke_gate")}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run real paired context compression ablations.")
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--suite", default="benchmarks/context_ablation_suite.json")
    parser.add_argument("--tokenizer-path", required=True)
    parser.add_argument("--output-dir")
    parser.add_argument("--execution-root", required=True)
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--max-pair-attempts", type=int, default=4)
    parser.add_argument("--run-timeout-seconds", type=int, default=3600)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--manifest-only", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    payload = run_benchmark(args)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload["status"] in {"complete", "manifest_created"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
