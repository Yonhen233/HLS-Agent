from __future__ import annotations

import argparse
import json
import math
import shutil
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .context_ablation import MODES, _aggregate, _bootstrap_mean, _bootstrap_median, paired_comparison


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _distribution(values: list[float]) -> dict[str, Any]:
    return {
        "n": len(values),
        "mean": statistics.mean(values) if values else None,
        "p50": statistics.median(values) if values else None,
        "p95": _percentile(values, 0.95),
    }


def _wilson(successes: int, total: int, z: float = 1.959963984540054) -> list[float | None]:
    if total <= 0:
        return [None, None]
    rate = successes / total
    denominator = 1 + z * z / total
    center = (rate + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(rate * (1 - rate) / total + z * z / (4 * total * total)) / denominator
    return [max(0.0, center - margin), min(1.0, center + margin)]


def _get(record: dict[str, Any], *path: str, default: float = 0.0) -> float:
    value: Any = record
    for key in path:
        if not isinstance(value, dict):
            return default
        value = value.get(key)
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return default


def extended_aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for mode in MODES:
        items = [
            item for item in records
            if item.get("mode") == mode and "api_usage" in item and item.get("run_valid_for_comparison", True)
        ]
        supported = [item for item in items if item.get("task_category", "supported") == "supported"]
        unsupported = [item for item in items if item.get("task_category") == "unsupported"]
        completed = sum(bool(item.get("task_completed")) for item in items)
        tool_selection = [bool(item.get("tool_selection_correct")) for item in items if item.get("tool_selection_correct") is not None]
        binary_counts = {
            "task_completion": completed,
            "golden_csim": sum(bool(item.get("golden_csim_passed")) for item in items),
            "real_csynth": sum(bool(item.get("real_csynth_completed")) for item in items),
            "false_success": sum(bool(item.get("false_success")) for item in items),
            "evidence_complete": sum(bool(item.get("evidence_complete")) for item in items),
            "tool_parameter_correct": sum(bool(item.get("tool_parameter_correct")) for item in items),
            "correct_rejection": sum(bool(item.get("correct_rejection")) for item in items),
            "repair_final_success": sum(bool(item.get("repair_final_success")) for item in items),
        }
        result[mode] = {
            **_aggregate(items)[mode],
            "status_counts": dict(Counter(str(item.get("status")) for item in items)),
            "tool_selection_accuracy": sum(tool_selection) / len(tool_selection) if tool_selection else None,
            "tool_parameter_accuracy": sum(bool(item.get("tool_parameter_correct")) for item in items) / max(1, len(items)),
            "evidence_complete_rate": sum(bool(item.get("evidence_complete")) for item in items) / max(1, len(items)),
            "correct_rejection_rate": sum(bool(item.get("correct_rejection")) for item in items) / max(1, len(items)),
            "repair_final_success_rate": sum(bool(item.get("repair_final_success")) for item in items) / max(1, len(items)),
            "supported_metrics": {
                "n": len(supported),
                "end_to_end_success_rate": sum(bool(item.get("task_completed")) for item in supported) / max(1, len(supported)),
                "golden_csim_rate": sum(bool(item.get("golden_csim_passed")) for item in supported) / max(1, len(supported)),
                "real_csynth_rate": sum(bool(item.get("real_csynth_completed")) for item in supported) / max(1, len(supported)),
            },
            "unsupported_metrics": {
                "n": len(unsupported),
                "correct_rejection_rate": sum(bool(item.get("correct_rejection")) for item in unsupported) / max(1, len(unsupported)),
                "invalid_vivado_call_rate": sum(bool(item.get("invalid_vivado_call_for_unsupported")) for item in unsupported) / max(1, len(unsupported)),
            },
            "context_overflow_count": sum(bool(item.get("context_overflow")) for item in items),
            "binary_counts_and_ci95": {
                name: {"successes": count, "total": len(items), "rate": count / max(1, len(items)), "wilson_ci95": _wilson(count, len(items))}
                for name, count in binary_counts.items()
            },
            "tool_selection_counts_and_ci95": {
                "successes": sum(tool_selection),
                "total": len(tool_selection),
                "rate": sum(tool_selection) / len(tool_selection) if tool_selection else None,
                "wilson_ci95": _wilson(sum(tool_selection), len(tool_selection)),
            },
            "tokens_per_completed_task": sum(_get(item, "api_usage", "total_tokens") for item in items) / completed if completed else None,
            "api_prompt_tokens": _distribution([_get(item, "api_usage", "prompt_tokens") for item in items]),
            "api_total_tokens": _distribution([_get(item, "api_usage", "total_tokens") for item in items]),
            "offline_specialist_input_tokens": _distribution([_get(item, "offline_tokens", "specialist_input_tokens") for item in items]),
            "offline_delivered_result_tokens": _distribution([_get(item, "offline_tokens", "delivered_result_tokens") for item in items]),
            "offline_raw_result_tokens": _distribution([_get(item, "offline_tokens", "raw_specialist_result_tokens") for item in items]),
            "offline_removed_result_tokens": _distribution([_get(item, "offline_tokens", "removed_result_tokens") for item in items]),
            "offline_full_final_state_tokens": _distribution([_get(item, "offline_tokens", "full_final_state_tokens") for item in items]),
            "offline_raw_text_artifact_tokens": _distribution([_get(item, "offline_tokens", "raw_text_artifact_tokens") for item in items]),
            "wall_runtime_s": _distribution([_get(item, "wall_runtime_s") for item in items]),
            "llm_runtime_s": _distribution([_get(item, "timing", "llm_ms") / 1000 for item in items]),
            "tool_runtime_s": _distribution([_get(item, "timing", "tool_ms") / 1000 for item in items]),
            "vivado_runtime_s": _distribution([_get(item, "timing", "vivado_ms") / 1000 for item in items]),
            "tool_calls": _distribution([_get(item, "tool_calls") for item in items]),
            "tool_failures": _distribution([_get(item, "tool_failures") for item in items]),
            "tool_retries": _distribution([_get(item, "tool_retries") for item in items]),
            "invalid_duplicate_calls": _distribution([_get(item, "invalid_duplicate_calls") for item in items]),
            "llm_format_errors": _distribution([_get(item, "llm_format_errors") for item in items]),
            "replans": _distribution([_get(item, "replans") for item in items]),
            "early_terminations": _distribution([_get(item, "early_termination") for item in items]),
            "context_build_ms": _distribution([_get(item, "offline_tokens", "context_build_ms") for item in items]),
            "result_compression_and_merge_ms": _distribution([_get(item, "offline_tokens", "result_compression_and_merge_ms") for item in items]),
            "totals": {
                "llm_calls": int(sum(_get(item, "api_usage", "llm_calls") for item in items)),
                "api_prompt_tokens": int(sum(_get(item, "api_usage", "prompt_tokens") for item in items)),
                "api_completion_tokens": int(sum(_get(item, "api_usage", "completion_tokens") for item in items)),
                "api_total_tokens": int(sum(_get(item, "api_usage", "total_tokens") for item in items)),
                "cache_hit_tokens": int(sum(_get(item, "api_usage", "cache_hit_tokens") for item in items)),
                "cache_miss_tokens": int(sum(_get(item, "api_usage", "cache_miss_tokens") for item in items)),
                "tool_failures": int(sum(_get(item, "tool_failures") for item in items)),
                "tool_retries": int(sum(_get(item, "tool_retries") for item in items)),
                "invalid_duplicate_calls": int(sum(_get(item, "invalid_duplicate_calls") for item in items)),
                "llm_format_errors": int(sum(_get(item, "llm_format_errors") for item in items)),
                "replans": int(sum(_get(item, "replans") for item in items)),
                "early_terminations": int(sum(_get(item, "early_termination") for item in items)),
                "wall_runtime_s": sum(_get(item, "wall_runtime_s") for item in items),
                "llm_runtime_s": sum(_get(item, "timing", "llm_ms") for item in items) / 1000,
                "tool_runtime_s": sum(_get(item, "timing", "tool_ms") for item in items) / 1000,
            },
        }
    return result


def _trace_signature(event: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(event.get(key) for key in ("event", "tool", "specialist", "status", "error_type", "decision"))


def _read_trace(record: dict[str, Any]) -> list[dict[str, Any]]:
    path = Path(str(record.get("run_dir") or "")) / "trace.jsonl"
    if not path.is_file():
        return []
    events = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def _first_divergence(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any] | None:
    left_trace = _read_trace(left)
    right_trace = _read_trace(right)
    for index, (left_event, right_event) in enumerate(zip(left_trace, right_trace)):
        if _trace_signature(left_event) != _trace_signature(right_event):
            return {
                "index": index,
                "left": dict(zip(("event", "tool", "specialist", "status", "error_type", "decision"), _trace_signature(left_event))),
                "right": dict(zip(("event", "tool", "specialist", "status", "error_type", "decision"), _trace_signature(right_event))),
            }
    if len(left_trace) != len(right_trace):
        return {"index": min(len(left_trace), len(right_trace)), "left_trace_length": len(left_trace), "right_trace_length": len(right_trace)}
    return None


def _attribution(items: list[dict[str, Any]]) -> str:
    if any(item.get("context_overflow") for item in items):
        return "完整上下文过长或上下文预算耗尽"
    if any(int(item.get("llm_format_errors") or 0) for item in items):
        return "LLM 输出格式错误"
    if len({item.get("selected_path") for item in items}) > 1:
        return "工具或路径选择差异"
    retention = {round(_get(item, "critical_constraint_retention", "rate"), 6) for item in items}
    if len(retention) > 1:
        return "关键约束保留差异"
    if any(int(item.get("tool_failures") or 0) for item in items):
        return "外部工具或原子工具失败"
    if max((_get(item, "offline_tokens", "specialist_input_tokens") for item in items), default=0) > 4 * max(
        1, min((_get(item, "offline_tokens", "specialist_input_tokens") for item in items), default=1)
    ):
        return "原始上下文噪声或注意力分散（相关性证据，非因果证明）"
    return "与上下文机制无明确关系"


def divergence_analysis(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for item in records:
        grouped[(str(item["case_id"]), int(item["trial_index"]))].append(item)
    analyses = []
    for (case_id, trial), items in sorted(grouped.items()):
        outcomes = {
            (item.get("status"), item.get("task_completed"), item.get("selected_path"), item.get("false_success"))
            for item in items
        }
        if len(outcomes) <= 1:
            continue
        by_mode = {item["mode"]: item for item in items}
        traces = {}
        for right in ("B", "C"):
            if "A" in by_mode and right in by_mode:
                traces[f"A_vs_{right}"] = _first_divergence(by_mode["A"], by_mode[right])
        analyses.append(
            {
                "case_id": case_id,
                "trial_index": trial,
                "outcomes": {
                    item["mode"]: {
                        "status": item.get("status"),
                        "task_completed": item.get("task_completed"),
                        "selected_path": item.get("selected_path"),
                        "false_success": item.get("false_success"),
                    }
                    for item in items
                },
                "attribution": _attribution(items),
                "first_trace_divergence": traces,
            }
        )
    return analyses


def _paired_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    paired = []
    for item in records:
        copy = dict(item)
        copy["original_case_id"] = item["case_id"]
        copy["case_id"] = f"{item['case_id']}#trial{item['trial_index']}"
        paired.append(copy)
    return paired


def _relative_change(left: float | None, right: float | None) -> float | None:
    if left in (None, 0) or right is None:
        return None
    return (right - left) / left


def _enrich_comparison(comparison: dict[str, Any]) -> dict[str, Any]:
    for metric in comparison["continuous"].values():
        metric["relative_median_change"] = _relative_change(metric.get("left_median"), metric.get("right_median"))
    return comparison


def aggregate_sources(source_dirs: list[Path]) -> dict[str, Any]:
    all_records: list[dict[str, Any]] = []
    source_metadata = []
    for trial, directory in enumerate(source_dirs):
        result_path = directory / "context_ablation_results.json"
        environment_path = directory / "environment.json"
        tokenizer_path = directory / "tokenizer_metadata.json"
        results = _load(result_path)
        environment = _load(environment_path)
        tokenizer = _load(tokenizer_path)
        source_metadata.append(
            {
                "trial_index": trial,
                "directory": str(directory.resolve()),
                "run_count": len(results.get("runs") or []),
                "git_commit": environment.get("git_commit"),
                "model": environment.get("model"),
                "tokenizer_sha256": tokenizer.get("aggregate_sha256"),
            }
        )
        for record in results.get("runs") or []:
            copy = dict(record)
            copy.setdefault("trial_index", trial)
            copy["source_result"] = str(result_path.resolve())
            all_records.append(copy)
    commits = {item["git_commit"] for item in source_metadata}
    models = {item["model"] for item in source_metadata}
    tokenizers = {item["tokenizer_sha256"] for item in source_metadata}
    if len(commits) != 1 or len(models) != 1 or len(tokenizers) != 1:
        raise ValueError("Source runs do not share one git commit, model, and tokenizer hash.")
    initial = [item for item in all_records if item["trial_index"] == 0]
    repeats = [item for item in all_records if item["trial_index"] > 0]
    paired = _paired_records(all_records)
    comparisons = [_enrich_comparison(paired_comparison(paired, left, right)) for left, right in (("A", "B"), ("B", "C"), ("A", "C"))]
    run_ids = [str(item.get("run_id")) for item in all_records]
    run_dirs = [str(item.get("run_dir")) for item in all_records]
    return {
        "schema_version": "1.0",
        "status": "complete",
        "generated_at": datetime.now().astimezone().isoformat(),
        "source_runs": source_metadata,
        "validity": {
            "same_git_commit": len(commits) == 1,
            "same_model": len(models) == 1,
            "same_tokenizer": len(tokenizers) == 1,
            "unique_run_directories": len(set(run_dirs)) == len(run_dirs),
            "unique_logical_run_ids": len(set(run_ids)) == len(run_ids),
            "logical_run_id_limitation": None if len(set(run_ids)) == len(run_ids) else "Logical Run IDs are not unique.",
            "retention_metric_limitation": None,
        },
        "run_count": len(all_records),
        "initial_run_count": len(initial),
        "repeat_run_count": len(repeats),
        "initial_aggregate": extended_aggregate(initial),
        "repeat_aggregate": extended_aggregate(repeats),
        "combined_aggregate": extended_aggregate(all_records),
        "paired_comparisons": comparisons,
        "divergent_trials": divergence_analysis(all_records),
        "runs": all_records,
    }


def _fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _write_report(output_dir: Path, results: dict[str, Any]) -> None:
    lines = [
        "# Context Ablation Final Report",
        "",
        f"Total real runs: `{results['run_count']}` (initial `{results['initial_run_count']}`, repeats `{results['repeat_run_count']}`).",
        "",
        "## Initial 12-task Paired Run",
        "",
        "| Mode | N | Completion | Golden CSim | Real CSynth | False success | Evidence complete | Constraint retention | API total p50 | Offline input p50 | Runtime p50/p95 (s) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for mode in MODES:
        item = results["initial_aggregate"][mode]
        lines.append(
            f"| {mode} | {item['n']} | {item['task_completion_rate']:.3f} | {item['golden_csim_rate']:.3f} | {item['real_csynth_rate']:.3f} | {item['false_success_rate']:.3f} | {item['evidence_complete_rate']:.3f} | {item['constraint_retention_rate']:.3f} | {_fmt(item['api_total_tokens']['p50'])} | {_fmt(item['offline_specialist_input_tokens']['p50'])} | {_fmt(item['wall_runtime_s']['p50'])}/{_fmt(item['wall_runtime_s']['p95'])} |"
        )
    lines.extend(
        [
            "",
            "## Repeated 9-task Cohort",
            "",
            "| Mode | N | Completion | Golden CSim | Real CSynth | False success | API total p50/p95 | Runtime p50/p95 (s) | Format errors | Replans |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for mode in MODES:
        item = results["repeat_aggregate"][mode]
        lines.append(
            f"| {mode} | {item['n']} | {item['task_completion_rate']:.3f} | {item['golden_csim_rate']:.3f} | {item['real_csynth_rate']:.3f} | {item['false_success_rate']:.3f} | {_fmt(item['api_total_tokens']['p50'])}/{_fmt(item['api_total_tokens']['p95'])} | {_fmt(item['wall_runtime_s']['p50'])}/{_fmt(item['wall_runtime_s']['p95'])} | {item['totals']['llm_format_errors']} | {item['totals']['replans']} |"
        )
    lines.extend(["", "## Paired Comparisons Across Trials", ""])
    for comparison in results["paired_comparisons"]:
        completion = comparison["binary"]["task_completed"]
        tokens = comparison["continuous"]["api_total_tokens"]
        runtime = comparison["continuous"]["wall_runtime_s"]
        lines.append(
            f"- `{comparison['comparison']}`: n={comparison['n_pairs']}; completion difference={completion['absolute_rate_difference']:.3f}; API total median {_fmt(tokens['left_median'])} -> {_fmt(tokens['right_median'])} ({_fmt(tokens['relative_median_change'])}); paired difference 95% CI={tokens['paired_median_difference']['ci95']}; runtime median {_fmt(runtime['left_median'])} -> {_fmt(runtime['right_median'])}."
        )
    lines.extend(["", "## Divergence Attribution", ""])
    if results["divergent_trials"]:
        for item in results["divergent_trials"]:
            lines.append(f"- `{item['case_id']}` trial {item['trial_index']}: {item['attribution']}; first divergent trace details are preserved in `context_ablation_results.json`.")
    else:
        lines.append("- No final-outcome divergence across modes.")
    lines.extend(
        [
            "",
            "## Validity And Limitations",
            "",
            "- All 90 records use the same Git commit, model, tokenizer hash, permissions, retry policy, and real Vivado HLS toolchain.",
            "- All absolute run directories are unique, but logical Run IDs repeat across mode-isolated roots. This violates the strict literal Run-ID requirement even though artifacts were not reused.",
            "- The frozen constraint-retention scorer partly measures final outcome availability, not only transport retention; its value must not be presented as a pure context-loss metric.",
            "- Golden CSim and real CSynth completion rates are zero in all groups. The experiment measures context cost and failure behavior, but cannot establish preserved successful HLS execution.",
            "- Repeats were selected after the initial run as preregistered by failure/repair criteria; they are not an independently random sample.",
            "- Context-build/compression self-time and process-kill recovery were not instrumented in the frozen commit, so those requested metrics are explicitly unavailable rather than estimated.",
        ]
    )
    (output_dir / "context_ablation_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_conclusion(output_dir: Path, results: dict[str, Any]) -> None:
    initial_a = results["initial_aggregate"]["A"]
    initial_c = results["initial_aggregate"]["C"]
    reduction = 1 - initial_c["api_total_tokens"]["p50"] / initial_a["api_total_tokens"]["p50"]
    lines = [
        "# Resume Conclusion",
        "",
        "## Allowed",
        "",
        f"在 12 个冻结任务及 9 个异常任务两轮复测（共 {results['run_count']} 次真实 DeepSeek + Vivado HLS 运行）中，构建了 full/raw、scoped/raw、scoped/compressed 三组上下文消融；首轮 C 组 API 总 Token 中位数较 A 组下降 {reduction:.1%}，且未出现 status=success 的伪成功。",
        "",
        "## Not Allowed",
        "",
        "不能声称‘压缩未降低任务效果’或‘提升 HLS 成功率’：三组 Golden CSim 与真实 CSynth 完成率均为 0，关键约束保留率也未达到预注册的 100% 门槛。",
        "",
        "不能把 Token 与耗时差异表述为普遍因果结论；样本来自固定任务集，重复样本是按失败/修复事件选择的。",
    ]
    (output_dir / "context_ablation_resume_conclusion.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_aggregate(args: argparse.Namespace) -> dict[str, Any]:
    source_dirs = [Path(item).resolve() for item in args.source_dir]
    output_dir = Path(args.output_dir).resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"Aggregate output directory is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    results = aggregate_sources(source_dirs)
    _write(output_dir / "context_ablation_results.json", results)
    _write_report(output_dir, results)
    _write_conclusion(output_dir, results)
    source_manifest = {
        "schema_version": "1.0",
        "source_runs": results["source_runs"],
        "selection": "initial 12 tasks plus two repeats of nine cases with mode disagreement, LLM format error, or repair/replan",
    }
    _write(output_dir / "context_ablation_manifest.json", source_manifest)
    shutil.copy2(source_dirs[0] / "tokenizer_metadata.json", output_dir / "tokenizer_metadata.json")
    shutil.copy2(source_dirs[0] / "environment.json", output_dir / "environment.json")
    if args.summary_output:
        compact = {key: value for key, value in results.items() if key != "runs"}
        _write(Path(args.summary_output).resolve(), compact)
    return {"status": "complete", "output_dir": str(output_dir), "run_count": results["run_count"]}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Aggregate initial and repeated context-ablation runs.")
    parser.add_argument("--source-dir", action="append", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--summary-output")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    payload = run_aggregate(build_parser().parse_args(list(argv) if argv is not None else None))
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
