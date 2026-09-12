"""Summarize durable HLS Agent versus native Claude CLI runs.

The report is intentionally post-hoc: it reads only persisted case/result/session
files, so an interrupted benchmark can be diagnosed and summarized later without
rerunning the expensive HLS or LLM work.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from run_claude_cli_comparison import aggregate_usage, usage_from_envelope, parse_json_envelope, claude_call_ledger, classify_completion


ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(p * len(ordered)) - 1))
    return round(ordered[index], 3)


def diagnosis(result: dict[str, Any]) -> str:
    """Classify the dominant observable failure without guessing hidden causes."""
    status = result.get("status")
    outcome = result.get("outcome")
    if status in {"running", "pending", "interrupted"}:
        return status
    if result.get("timed_out") or result.get("last_process", {}).get("status") == "timeout":
        return "timeout"
    if result.get("verified") and outcome == "success":
        return "success_after_recovery" if result.get("interruption_count") else "success"
    interruption_reasons = " ".join(str(turn.get("interruption_reason", "")) for turn in result.get("turns", []))
    if any(code in interruption_reasons for code in ("model_catalog_mismatch", "api_authentication_error", "api_rate_limit")):
        return "cli_configuration_or_api_error"
    if status == "timeout" or result.get("last_process", {}).get("status") == "timeout":
        return "timeout"
    if status == "process_failed" or result.get("last_process", {}).get("status") == "process_failed":
        return "process_failed_or_api_error"
    if outcome in {"blocked", "unsupported", "partial_success"}:
        return "honest_block_or_unsupported"
    if result.get("interruption_count", 0) or status in {"incomplete", "max_turns_reached"}:
        return "early_stop_or_incomplete"
    if not result.get("verified"):
        return "no_independent_verification"
    return "success"


def collect(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case_json in root.glob("*/case.json"):
        case = load_json(case_json)
        for system in ("hls_agent", "claude_cli"):
            system_root = case_json.parent / system
            baseline = case.get("claude_baseline") if system == "claude_cli" else None
            if baseline:
                system_root = Path(baseline["source_dir"])
            result = load_json(system_root / "result.json")
            session = load_json(system_root / "session.json") if system == "claude_cli" else {}
            if session:
                result = {**result, "status": session.get("status"), "turns": session.get("turns", []),
                          "interruption_count": session.get("interruption_count", 0),
                          "session_recovery_count": session.get("session_recovery_count", 0)}
                if session.get("status") == "running":
                    result.update(verified=False, outcome="incomplete", comparison_completed=False)
                turns = result["turns"]
                for turn in turns:
                    log = Path(turn.get("stdout") or system_root / f"turn_{turn['turn']:02d}" / "stdout.log")
                    envelope = parse_json_envelope(log)
                    calls = claude_call_ledger(log)
                    if envelope:
                        turn["usage"] = usage_from_envelope(envelope)
                    elif calls:
                        turn["usage"] = {key: sum(call["usage"].get(key) or 0 for call in calls)
                                         for key in ("prompt_tokens", "completion_tokens", "total_tokens")}
                    turn.setdefault("usage", {})["llm_calls"] = len(calls) if calls else None
                    turn["usage"]["ledger_partial"] = not bool(envelope)
                result["usage"] = aggregate_usage(turns)
                result["elapsed_seconds"] = sum(turn.get("elapsed_seconds", 0) for turn in turns)
                if turns and turns[-1].get("status") == "timeout":
                    result.update(status="timeout", timed_out=True, verified=False)
                if result.get("status") == "completed" and result.get("outcome") == "success":
                    result["reported_verified"] = result.get("verified")
                    result["verified"] = classify_completion(system_root)["verified"]
                    result["verification_basis"] = "artifact_corroboration_not_hidden_tests"
            if system == "hls_agent":
                process = load_json(system_root / "process.json")
                if process.get("status") == "running":
                    result.update(status="running", verified=False, comparison_completed=False)
                elif process.get("status") in {"timeout", "process_failed"}:
                    result.update(status=process["status"], verified=False)
            if not result:
                continue
            rows.append({
                "case": case.get("id", case_json.parent.name),
                "family": case.get("family"),
                "system": system,
                "result": result,
            })
    return rows


def system_summary(rows: list[dict[str, Any]], system: str) -> dict[str, Any]:
    all_rows = [row for row in rows if row["system"] == system]
    selected = [row for row in all_rows if row["result"].get("status") not in {"running", "pending", "interrupted"}]
    runtimes = []
    for row in selected:
        result = row["result"]
        elapsed = result.get("elapsed_seconds")
        if elapsed is None and result.get("turns"):
            elapsed = sum(turn.get("elapsed_seconds", 0) for turn in result["turns"])
        if elapsed is not None:
            runtimes.append(float(elapsed))
    verified = sum(bool(row["result"].get("verified")) for row in selected)
    usage_rows = [row["result"].get("usage", {}) for row in selected]
    total_tokens = [int(item["total_tokens"]) for item in usage_rows if item.get("total_tokens") is not None]
    known_tokens = [int(item.get("known_total_tokens", item.get("total_tokens")) or 0) for item in usage_rows]
    llm_calls = [int(item["llm_calls"]) for item in usage_rows if item.get("llm_calls") is not None]
    reasons: dict[str, int] = {}
    for row in selected:
        key = diagnosis(row["result"])
        reasons[key] = reasons.get(key, 0) + 1
    return {
        "cases": len(selected),
        "in_progress_cases": len(all_rows) - len(selected),
        "verified_successes": verified,
        "verified_success_rate": round(verified / len(selected), 4) if selected else None,
        "runtime_seconds": {"p50": percentile(runtimes, 0.50), "p95": percentile(runtimes, 0.95), "mean": round(sum(runtimes) / len(runtimes), 3) if runtimes else None},
        "tokens_per_run": {
            "mean": round(sum(total_tokens) / len(total_tokens), 3) if total_tokens else None,
            "known_runs": len(total_tokens),
            "missing_runs": max(0, len(selected) - len(total_tokens)),
            "known_token_lower_bound_sum": sum(known_tokens),
        },
        "llm_calls_per_run": {"mean": round(sum(llm_calls) / len(llm_calls), 3) if llm_calls else None, "known_runs": len(llm_calls)},
        "diagnoses": reasons,
    }


def write_report(root: Path, rows: list[dict[str, Any]]) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    summary = {
        "output_root": str(root),
        "case_count": len({row["case"] for row in rows}),
        "systems": {system: system_summary(rows, system) for system in ("hls_agent", "claude_cli")},
        "cases": [
            {
                "case": row["case"],
                "family": row["family"],
                "system": row["system"],
                "status": row["result"].get("status"),
                "outcome": row["result"].get("outcome"),
                "verified": row["result"].get("verified"),
                "diagnosis": diagnosis(row["result"]),
                "elapsed_seconds": row["result"].get("elapsed_seconds"),
                "interruption_count": row["result"].get("interruption_count"),
                "llm_calls": row["result"].get("usage", {}).get("llm_calls"),
                "total_tokens": row["result"].get("usage", {}).get("total_tokens"),
                "known_token_lower_bound": row["result"].get("usage", {}).get("known_total_tokens"),
                "missing_usage_invocations": row["result"].get("usage", {}).get("missing_usage_invocations"),
            }
            for row in rows
        ],
    }
    json_path = root / "comparison_summary.json"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Durable Claude CLI Comparison Summary", "", f"Cases observed: {summary['case_count']}", "",
             "Only terminal runs enter success rates and latency distributions. Runtime sums all turns, including failed turns.",
             "Tokens include cache read/write input. Unknown totals are not zero; partial usage is a lower bound.",
             "CLI invocation count and num_turns are not measured LLM API call counts. Legacy runs may lack per-call telemetry.", ""]
    lines.extend(["Success evidence is artifact corroboration; this is not an independent hidden-test benchmark.", ""])
    for system, values in summary["systems"].items():
        lines.extend([
            f"## {system}",
            f"- Verified success: {values['verified_successes']}/{values['cases']} ({values['verified_success_rate']})",
            f"- Runtime p50/p95: {values['runtime_seconds']['p50']} / {values['runtime_seconds']['p95']} seconds",
            f"- Mean tokens/run: {values['tokens_per_run']['mean']}",
            f"- Runs missing full token totals: {values['tokens_per_run']['missing_runs']}; known token lower bound sum: {values['tokens_per_run']['known_token_lower_bound_sum']}",
            f"- Mean LLM calls/run: {values['llm_calls_per_run']['mean']}",
            f"- Diagnoses: {values['diagnoses']}",
            "",
        ])
    lines.extend(["## Case Details", "", "| Case | System | Status | Outcome | Verified | Diagnosis | Interruptions | LLM calls | Tokens |", "|---|---|---|---|---:|---|---:|---:|---:|"])
    for item in summary["cases"]:
        lines.append(f"| {item['case']} | {item['system']} | {item['status']} | {item['outcome']} | {item['verified']} | {item['diagnosis']} | {item['interruption_count']} | {item['llm_calls']} | {item['total_tokens']} |")
    md_path = root / "comparison_summary.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=ROOT / "runs" / "benchmarks" / "claude_cli_comparison_durable_v2")
    args = parser.parse_args()
    root = args.output_root.resolve()
    json_path, md_path = write_report(root, collect(root))
    print(json_path)
    print(md_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
