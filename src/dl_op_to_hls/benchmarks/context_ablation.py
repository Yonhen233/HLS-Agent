from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import random
import shutil
import sqlite3
import statistics
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .agent_quality_benchmark import collect_run_metrics


MODES = {
    "A": {"input_context_mode": "full", "result_context_mode": "raw"},
    "B": {"input_context_mode": "scoped", "result_context_mode": "raw"},
    "C": {"input_context_mode": "scoped", "result_context_mode": "compressed"},
}
TEXT_SUFFIXES = {".txt", ".log", ".rpt", ".json", ".jsonl", ".md", ".cpp", ".cc", ".c", ".h", ".hpp", ".tcl", ".yml", ".yaml"}


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
        cases = cases[:2]
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


def _retention(run_dir: Path) -> dict[str, Any]:
    state = _json_load(run_dir / "state.json", {})
    task = state.get("task") or {}
    report = state.get("report") or {}
    required = {
        "operator_or_model": task.get("op_type") or task.get("model_path") or task.get("hls_project_dir"),
        "shape": task.get("input_shape") or task.get("model_path") or task.get("hls_project_dir"),
        "dtype": task.get("dtype") or (task.get("hls4ml") or {}).get("precision") or task.get("task_type") != "operator",
        "top_function": task.get("top_function") or task.get("name"),
        "part": (task.get("target") or {}).get("part"),
        "clock": (task.get("target") or {}).get("clock_period"),
        "objective": state.get("objective") or task.get("objective") or (task.get("optimization") or {}).get("objective"),
        "verification": state.get("verification") or state.get("selected_path") == "unsupported_path",
        "report_or_rejection": report or state.get("selected_path") == "unsupported_path",
        "current_artifacts": state.get("artifacts"),
    }
    kept = {key: bool(value) for key, value in required.items()}
    return {"items": kept, "rate": sum(kept.values()) / max(1, len(kept))}


def analyze_run(run_dir: Path, mode: str, case: dict[str, Any], tokenizer: DeepSeekV4Tokenizer, wall_s: float) -> dict[str, Any]:
    base = collect_run_metrics(run_dir)
    events = _trace(run_dir)
    api = _api_usage(events)
    tokens = _token_payload_metrics(run_dir, tokenizer)
    verification = _json_load(run_dir / "state.json", {}).get("verification") or {}
    csim_passed = bool((verification.get("csim") or {}).get("passed") or verification.get("passed"))
    csynth_passed = base.get("report_status") == "success" and base.get("synthesis", {}).get("latency_max_cycles") is not None
    false_success = base.get("status") == "success" and not (base.get("agent_task_success") and (csynth_passed or base.get("selected_path") == "unsupported_path"))
    retention = _retention(run_dir)
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
        "selected_path": base.get("selected_path"),
        "task_completed": bool(base.get("agent_task_success") and not false_success),
        "golden_csim_passed": csim_passed,
        "real_csynth_completed": csynth_passed,
        "tool_selection_correct": base.get("toolchain_quality", {}).get("correct_for_selected_path"),
        "tool_parameter_correct": base.get("bad_case_governance", {}).get("tool_postcondition_failure_count", 0) == 0,
        "critical_constraint_retention": retention,
        "evidence_complete": evidence_complete,
        "false_success": false_success,
        "correct_rejection": bool(base.get("selected_path") == "unsupported_path" and base.get("status") in {"partial_success", "unsupported", "success"}),
        "repair_final_success": bool(base.get("repair_quality", {}).get("repair_success")),
        "wall_runtime_s": wall_s,
        "tool_calls": base.get("tool_call_count", 0),
        "tool_failures": base.get("tool_failure_count", 0),
        "tool_retries": retries,
        "invalid_duplicate_calls": duplicate_calls,
        "llm_format_errors": base.get("llm_harness", {}).get("json_repair_count", 0),
        "replans": base.get("bad_case_governance", {}).get("progress_replan_event_count", 0),
        "early_termination": base.get("bad_case_governance", {}).get("progress_terminate_event_count", 0),
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
    by_case = {(item["case_id"], item["mode"]): item for item in records}
    pairs = [(by_case[(case, left)], by_case[(case, right)]) for case in sorted({item["case_id"] for item in records}) if (case, left) in by_case and (case, right) in by_case]
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
        items = [item for item in records if item["mode"] == mode]
        groups[mode] = {
            "n": len(items),
            "task_completion_rate": sum(item["task_completed"] for item in items) / max(1, len(items)),
            "golden_csim_rate": sum(item["golden_csim_passed"] for item in items) / max(1, len(items)),
            "real_csynth_rate": sum(item["real_csynth_completed"] for item in items) / max(1, len(items)),
            "false_success_rate": sum(item["false_success"] for item in items) / max(1, len(items)),
            "constraint_retention_rate": statistics.mean(item["critical_constraint_retention"]["rate"] for item in items) if items else 0,
            "median_api_prompt_tokens": statistics.median(item["api_usage"]["prompt_tokens"] for item in items) if items else None,
            "median_api_total_tokens": statistics.median(item["api_usage"]["total_tokens"] for item in items) if items else None,
            "median_offline_input_tokens": statistics.median(item["offline_tokens"]["specialist_input_tokens"] for item in items) if items else None,
            "median_runtime_s": statistics.median(item["wall_runtime_s"] for item in items) if items else None,
        }
    return groups


def _write_reports(output_dir: Path, manifest: dict[str, Any], results: dict[str, Any]) -> None:
    aggregate = results["aggregate"]
    lines = [
        "# Context Ablation Report",
        "",
        f"Git commit: `{manifest['git_commit']}`",
        f"Paired tasks: `{len(manifest['cases'])}`",
        "",
        "## Core Results",
        "",
        "| Mode | Completion | Golden CSim | Real CSynth | False success | Constraint retention | Median API prompt tokens | Median offline specialist input | Median runtime (s) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for mode in MODES:
        item = aggregate[mode]
        lines.append(
            f"| {mode} | {item['task_completion_rate']:.3f} | {item['golden_csim_rate']:.3f} | {item['real_csynth_rate']:.3f} | {item['false_success_rate']:.3f} | {item['constraint_retention_rate']:.3f} | {item['median_api_prompt_tokens']} | {item['median_offline_input_tokens']} | {item['median_runtime_s']} |"
        )
    lines.extend(["", "## Paired Comparisons", ""])
    for comparison in results["paired_comparisons"]:
        lines.append(f"- `{comparison['comparison']}`: {comparison['n_pairs']} paired tasks; full machine-readable CIs are in `context_ablation_results.json`.")
    differences = []
    by_case: dict[str, list[dict[str, Any]]] = {}
    for item in results["runs"]:
        by_case.setdefault(item["case_id"], []).append(item)
    for case_id, items in by_case.items():
        outcomes = {(item["task_completed"], item["selected_path"], item["false_success"]) for item in items}
        if len(outcomes) > 1:
            differences.append(case_id)
    lines.extend(["", "## Divergent Tasks", ""])
    lines.extend(
        [f"- `{item}`: inspect paired traces for the first divergent step." for item in differences]
        or ["- None."]
    )
    lines.extend(
        [
            "",
            "## Limitations",
            "",
            "- This is a paired engineering benchmark, not proof of causal superiority outside the frozen task distribution.",
            "- Small binary samples are reported with discordant counts and bootstrap intervals; statistical power is limited.",
            "- API provider caching and workstation load remain measured but not perfectly controllable.",
        ]
    )
    (output_dir / "context_ablation_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    a = aggregate["A"]
    c = aggregate["C"]
    allowed = (
        c["task_completion_rate"] >= a["task_completion_rate"] - 0.05
        and c["false_success_rate"] == 0
        and c["constraint_retention_rate"] == 1.0
        and (c["median_api_prompt_tokens"] or 0) < (a["median_api_prompt_tokens"] or 0)
    )
    conclusion = ["# Resume Conclusion", ""]
    if allowed:
        conclusion.append("允许表述：在冻结真实 HLS 配对任务上，面向 Specialist 的作用域上下文与结构化返回降低了输入 Token，且任务完成率下降不超过 5 个百分点，未出现错误成功判定。")
    else:
        conclusion.append("当前不允许声称“降低 Token 且不降低效果”；至少一项预注册门槛未满足，应报告具体失败任务和限制。")
    conclusion.append("")
    conclusion.append("不能声称：该结果适用于任意模型、任意 FPGA 工具链或证明压缩是唯一因果因素。")
    (output_dir / "context_ablation_resume_conclusion.md").write_text("\n".join(conclusion) + "\n", encoding="utf-8")


def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    workspace = Path(args.workspace).resolve()
    if _benchmark_code_dirty(workspace) and not args.manifest_only:
        raise RuntimeError("Context ablation requires a clean tracked worktree so every run maps to one Git commit.")
    tokenizer = DeepSeekV4Tokenizer(args.tokenizer_path)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_dir).resolve() if args.output_dir else workspace / "runs" / "benchmarks" / f"context_ablation_{timestamp}"
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"Benchmark output directory is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(workspace, (workspace / args.suite).resolve(), output_dir, args.smoke)
    _json_write(output_dir / "context_ablation_manifest.json", manifest)
    tokenizer_metadata = tokenizer.metadata()
    _json_write(output_dir / "tokenizer_metadata.json", tokenizer_metadata)
    environment = {
        "git_commit": manifest["git_commit"],
        "git_status_porcelain": _git(workspace, "status", "--porcelain"),
        "model": "deepseek-v4-pro",
        "base_url": os.environ.get("DL_OP_TO_HLS_LLM_BASE_URL", "https://api.deepseek.com"),
        "prompt_version": _git(workspace, "rev-parse", "HEAD:src/dl_op_to_hls/llm/prompts.py"),
        "python": sys.version,
        "platform": platform.platform(),
        "vivado_hls_path": os.environ.get("DL_OP_TO_HLS_VIVADO_HLS_PATH", r"D:\Xilinx\Vivado\2018.3\bin\vivado_hls.bat"),
        "tokenizer_sha256": tokenizer_metadata["aggregate_sha256"],
    }
    _json_write(output_dir / "environment.json", environment)
    if args.manifest_only:
        return {"status": "manifest_created", "output_dir": str(output_dir), "manifest": manifest}
    if not os.environ.get("DL_OP_TO_HLS_LLM_API_KEY") and not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("Real benchmark requires DL_OP_TO_HLS_LLM_API_KEY or OPENAI_API_KEY in the environment.")

    source_db = workspace / "runs" / "metadata.db"
    records = []
    for index, case in enumerate(manifest["cases"]):
        for mode in _mode_order(index):
            run_root = output_dir / "raw_runs" / case["case_id"] / mode
            run_root.mkdir(parents=True, exist_ok=True)
            isolated_db = output_dir / "db_snapshots" / case["case_id"] / f"{mode}.db"
            _sqlite_snapshot(source_db, isolated_db)
            env = os.environ.copy()
            env.update(
                {
                    "DL_OP_TO_HLS_INPUT_CONTEXT_MODE": MODES[mode]["input_context_mode"],
                    "DL_OP_TO_HLS_RESULT_CONTEXT_MODE": MODES[mode]["result_context_mode"],
                    "DL_OP_TO_HLS_RUNS_ROOT": str(run_root),
                    "DL_OP_TO_HLS_DB_PATH": str(isolated_db),
                    "DL_OP_TO_HLS_RUNTIME_MODE": "strict",
                    "DL_OP_TO_HLS_MOCK_TOOLS": "0",
                    "DL_OP_TO_HLS_MOCK_HLS4ML": "0",
                    "DL_OP_TO_HLS_MOCK_VIVADO": "0",
                    "DL_OP_TO_HLS_LLM_ENABLED": "1",
                    "DL_OP_TO_HLS_LLM_MODEL": "deepseek-v4-pro",
                    "DL_OP_TO_HLS_LLM_BASE_URL": os.environ.get("DL_OP_TO_HLS_LLM_BASE_URL", "https://api.deepseek.com"),
                    "DL_OP_TO_HLS_VIVADO_HLS_PATH": os.environ.get("DL_OP_TO_HLS_VIVADO_HLS_PATH", r"D:\Xilinx\Vivado\2018.3\bin\vivado_hls.bat"),
                    "DL_OP_TO_HLS_REUSE_VERIFIED_IMPLEMENTATIONS": "0",
                }
            )
            command = [sys.executable, "-m", "dl_op_to_hls.cli", "run-llm", case["frozen_task"], "--real-tools"]
            start = time.perf_counter()
            process = subprocess.run(command, cwd=workspace, env=env, capture_output=True, text=True, errors="replace", check=False)
            wall_s = round(time.perf_counter() - start, 3)
            (run_root / "benchmark_stdout.txt").write_text(process.stdout, encoding="utf-8", errors="replace")
            (run_root / "benchmark_stderr.txt").write_text(process.stderr, encoding="utf-8", errors="replace")
            actual_run = _find_run_dir(run_root)
            if actual_run is None:
                records.append({"case_id": case["case_id"], "mode": mode, "process_exit_code": process.returncode, "status": "runner_failed", "wall_runtime_s": wall_s})
                continue
            record = analyze_run(actual_run, mode, case, tokenizer, wall_s)
            record["process_exit_code"] = process.returncode
            records.append(record)
            trace_target = output_dir / "traces" / f"{case['case_id']}_{mode}.jsonl"
            trace_target.parent.mkdir(parents=True, exist_ok=True)
            if (actual_run / "trace.jsonl").exists():
                shutil.copy2(actual_run / "trace.jsonl", trace_target)
            partial = {"status": "running", "runs": records, "manifest": str(output_dir / "context_ablation_manifest.json")}
            _json_write(output_dir / "context_ablation_results.partial.json", partial)

    complete_records = [item for item in records if "api_usage" in item]
    results = {
        "schema_version": "1.0",
        "status": "complete" if len(complete_records) == len(manifest["cases"]) * 3 else "partial",
        "runs": records,
        "aggregate": _aggregate(complete_records),
        "paired_comparisons": [
            paired_comparison(complete_records, "A", "B"),
            paired_comparison(complete_records, "B", "C"),
            paired_comparison(complete_records, "A", "C"),
        ],
    }
    _json_write(output_dir / "context_ablation_results.json", results)
    _write_reports(output_dir, manifest, results)
    return {"status": results["status"], "output_dir": str(output_dir), "run_count": len(complete_records), "aggregate": results["aggregate"]}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run real paired context compression ablations.")
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--suite", default="benchmarks/context_ablation_suite.json")
    parser.add_argument("--tokenizer-path", required=True)
    parser.add_argument("--output-dir")
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
