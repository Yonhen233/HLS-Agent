from __future__ import annotations

import json
import math
import statistics
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .operator_case_generator import evaluate_case, suite_payload
from .operator_support import build_support_matrix, render_support_matrix_markdown
from .operator_suite_specs import all_suite_payloads


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def wilson_rate(numerator: int, denominator: int, *, minimum_usable_n: int = 20) -> dict[str, Any]:
    if denominator <= 0:
        return {
            "numerator": numerator,
            "denominator": denominator,
            "sample_size": denominator,
            "rate": None,
            "wilson_95": None,
            "statistically_usable": False,
            "status": "insufficient_data",
        }
    z = 1.959963984540054
    rate = numerator / denominator
    denominator_adjusted = 1 + z * z / denominator
    center = (rate + z * z / (2 * denominator)) / denominator_adjusted
    margin = z * math.sqrt((rate * (1 - rate) + z * z / (4 * denominator)) / denominator) / denominator_adjusted
    usable = denominator >= minimum_usable_n
    return {
        "numerator": numerator,
        "denominator": denominator,
        "sample_size": denominator,
        "rate": rate,
        "wilson_95": [max(0.0, center - margin), min(1.0, center + margin)],
        "statistically_usable": usable,
        "status": "usable" if usable else "insufficient_data",
    }


def analyze_token_usage(runs_root: str | Path) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    for trace_path in Path(runs_root).glob("*/trace.jsonl"):
        for line in trace_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("event") == "LLMUsageRecorded":
                events.append({"run_id": trace_path.parent.name, **event})
    totals = [int(item.get("input_tokens") or 0) + int(item.get("output_tokens") or 0) for item in events]
    input_tokens = [int(item.get("input_tokens") or 0) for item in events]
    anomaly_events: list[dict[str, Any]] = []
    for item in events:
        reasons = list(item.get("token_anomalies") or [])
        if int(item.get("output_tokens") or 0) >= int(item.get("max_output_tokens") or 4096) * 0.95:
            reasons.append("output_near_limit")
        if int(item.get("input_tokens") or 0) > 12_000:
            reasons.append("large_input_context")
        if reasons:
            anomaly_events.append({"run_id": item.get("run_id"), "call_id": item.get("call_id"), "reasons": sorted(set(reasons))})
    return {
        "llm_call_count": len(events),
        "input_tokens": sum(input_tokens),
        "output_tokens": sum(int(item.get("output_tokens") or 0) for item in events),
        "total_tokens": sum(totals),
        "p50_tokens_per_call": statistics.median(totals) if totals else None,
        "p95_tokens_per_call": _percentile(totals, 0.95),
        "p95_input_tokens": _percentile(input_tokens, 0.95),
        "anomaly_count": len(anomaly_events),
        "anomalies": anomaly_events[:100],
        "note": "Historical calls without call_id/stage remain visible but are marked legacy by omission.",
    }


def run_operator_benchmark(workspace_root: str | Path, output_path: str | Path) -> dict[str, Any]:
    root = Path(workspace_root).resolve()
    suite = suite_payload()
    results = [evaluate_case(case) for case in suite["cases"]]
    passed = sum(bool(result.get("passed")) for result in results)
    by_operator: dict[str, dict[str, Any]] = {}
    for operator in sorted({case["operator"] for case in suite["cases"]}):
        selected = [result for result in results if result.get("operator") == operator]
        operator_passed = sum(bool(item.get("passed")) for item in selected)
        by_operator[operator] = wilson_rate(operator_passed, len(selected))
        by_operator[operator]["evidence_class"] = "unit"
    matrix = build_support_matrix(suite["cases"], root / "runs")
    evidence_counts = Counter()
    for operator in matrix["operators"]:
        evidence_counts["real_csim"] += operator["real_csim_count"]
        evidence_counts["real_csynth"] += operator["real_csynth_count"]
        evidence_counts["mock"] += operator["mock_case_count"]
        evidence_counts["fixture"] += operator["fixture_case_count"]
    report = {
        "schema_version": "1.0",
        "generated_at": _utc_now(),
        "interview_ready": False,
        "generation_policy": "llm_candidate_first",
        "functional": {
            "evidence_class": "unit",
            "rate": wilson_rate(passed, len(results)),
            "by_operator": by_operator,
            "case_results": results,
        },
        "evidence_counts": dict(evidence_counts),
        "token_usage": analyze_token_usage(root / "runs"),
        "release_gates": {
            "functional_cases_at_least_90": len(results) >= 90,
            "six_operator_classes": len(matrix["operators"]) >= 6,
            "real_csim_at_least_18": evidence_counts["real_csim"] >= 18,
            "real_csynth_at_least_10": evidence_counts["real_csynth"] >= 10,
            "llm_pass3_complete": False,
            "false_success_rate_zero": None,
            "stale_artifact_acceptance_zero": None,
            "unsafe_candidate_acceptance_zero": None,
        },
    }
    report["interview_ready"] = all(value is True for value in report["release_gates"].values())

    output = Path(output_path)
    if not output.is_absolute():
        output = root / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    markdown = _render_release_markdown(report)
    output.with_suffix(".md").write_text(markdown, encoding="utf-8")

    benchmarks = root / "benchmarks"
    benchmarks.mkdir(parents=True, exist_ok=True)
    (benchmarks / "operator_functional_suite.json").write_text(json.dumps(suite, indent=2, ensure_ascii=False), encoding="utf-8")
    (benchmarks / "operator_support_matrix.json").write_text(json.dumps(matrix, indent=2, ensure_ascii=False), encoding="utf-8")
    for filename, payload in all_suite_payloads().items():
        target = benchmarks / filename
        if not target.exists():
            target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    docs = root / "docs"
    (docs / "operator_support_matrix.md").write_text(render_support_matrix_markdown(matrix), encoding="utf-8")
    return report


def _percentile(values: list[int], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1))
    return float(ordered[index])


def _render_release_markdown(report: dict[str, Any]) -> str:
    rate = report["functional"]["rate"]
    token = report["token_usage"]
    lines = [
        "# Operator Benchmark Release Report",
        "",
        f"- Interview Ready: `{report['interview_ready']}`",
        f"- Functional Golden Cases: `{rate['numerator']}/{rate['denominator']}` (unit evidence only)",
        f"- Real CSim evidence: `{report['evidence_counts'].get('real_csim', 0)}`",
        f"- Real CSynth evidence: `{report['evidence_counts'].get('real_csynth', 0)}`",
        f"- Mock evidence: `{report['evidence_counts'].get('mock', 0)}`",
        f"- Historical LLM calls observed: `{token['llm_call_count']}`",
        f"- Historical total tokens: `{token['total_tokens']}`",
        f"- Token anomalies: `{token['anomaly_count']}`",
        "",
        "## Release Gates",
        "",
    ]
    for name, value in report["release_gates"].items():
        lines.append(f"- {name}: `{value}`")
    lines.extend(
        [
            "",
            "当前报告刻意不把纯 Python Golden、Mock 或 Fixture 计为真实 HLS 成功。Real Suite 与 LLM pass^3 未完成前，Interview Ready 必须保持 false。",
        ]
    )
    return "\n".join(lines) + "\n"
