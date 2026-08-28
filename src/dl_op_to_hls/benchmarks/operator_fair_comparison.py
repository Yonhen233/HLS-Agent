from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _fixed_contract(task: dict[str, Any]) -> dict[str, Any]:
    optimization = task.get("optimization") or {}
    return {
        "op_type": task.get("op_type"),
        "input_shape": task.get("input_shape"),
        "weight_shape": task.get("weight_shape"),
        "output_shape": task.get("output_shape"),
        "dtype": task.get("dtype"),
        "part": (task.get("target") or {}).get("part"),
        "clock_period": (task.get("target") or {}).get("clock_period"),
        "objective": optimization.get("objective"),
        "reuse_factor": optimization.get("reuse_factor"),
        "pipeline_ii": optimization.get("pipeline_ii"),
    }


def _real_golden_evidence(run_dir: Path) -> bool:
    payload = _read_json(run_dir / "tool_evidence.json")
    receipts = payload.get("receipts") or []
    return any(
        isinstance(receipt, dict)
        and receipt.get("valid") is True
        and receipt.get("mock_evidence") is not True
        and receipt.get("evidence_class") in {"real_csim", "real_csynth"}
        and any(
            isinstance(check, dict)
            and check.get("name") in {"golden_csim_passed", "verification_not_explicitly_failed"}
            and check.get("passed") is True
            for check in receipt.get("checks", [])
        )
        for receipt in receipts
    )


def _llm_usage(run_dir: Path) -> dict[str, Any]:
    calls = input_tokens = output_tokens = anomalies = 0
    trace_path = run_dir / "trace.jsonl"
    if trace_path.exists():
        for line in trace_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("event") != "LLMUsageRecorded":
                continue
            calls += 1
            input_tokens += int(event.get("input_tokens") or 0)
            output_tokens += int(event.get("output_tokens") or 0)
            anomalies += int(bool(event.get("token_anomalies")))
    return {
        "llm_calls": calls,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "token_anomaly_calls": anomalies,
    }


def _run_result(root: Path, run_id: str) -> dict[str, Any]:
    run_dir = root / "runs" / run_id
    state = _read_json(run_dir / "state.json")
    gate = _read_json(run_dir / "completion_gate.json")
    report = state.get("report") or _read_json(run_dir / "report.json")
    resources = report.get("resources") or {}
    latency = report.get("latency") or {}
    interval = report.get("interval") or {}
    timing = report.get("timing") or {}
    operator = str((state.get("task") or {}).get("op_type") or "")
    testbench_candidates = [run_dir / "candidate" / "testbench.cpp", run_dir / "generated" / "testbench.cpp"]
    testbench = next((path for path in testbench_candidates if path.exists()), None)
    testbench_text = testbench.read_text(encoding="utf-8", errors="ignore") if testbench else ""
    canonical_snippets = {
        "Dense": ("(i%5)-2", "o%2", "((o+i)%3)-1", "0.001"),
        "MatMul": ("((r+k)%4)-1", "((k+c)%3)-1", "0.001"),
    }
    compact_testbench = "".join(testbench_text.split())
    stimulus_matches = bool(testbench_text) and all(snippet in compact_testbench for snippet in canonical_snippets.get(operator, ()))
    return {
        "run_id": run_id,
        "exists": bool(state),
        "path": state.get("selected_path"),
        "status": state.get("status"),
        "fixed_contract": _fixed_contract(state.get("task") or {}),
        "canonical_stimulus_matches": stimulus_matches,
        "testbench_path": str(testbench.relative_to(root)) if testbench else None,
        "functional_verified": bool((state.get("verification") or {}).get("passed")) and _real_golden_evidence(run_dir),
        "real_report_produced": report.get("status") == "success",
        "production_ready": gate.get("production_ready") is True,
        "latency_cycles": latency.get("max_cycles"),
        "ii": interval.get("max_ii"),
        "dsp": resources.get("dsp"),
        "bram": resources.get("bram"),
        "lut": resources.get("lut"),
        "ff": resources.get("ff"),
        "estimated_ns": timing.get("estimated_ns"),
        "timing_met": timing.get("met"),
        "repair_count": sum(
            1 for item in state.get("todos", []) if str(item.get("title") or "").lower().startswith("repair")
        ),
        **_llm_usage(run_dir),
    }


def _delta(llm: Any, template: Any) -> Any:
    if not isinstance(llm, (int, float)) or not isinstance(template, (int, float)):
        return None
    return llm - template


def analyze_template_vs_llm(workspace_root: str | Path, manifest_path: str | Path, output_path: str | Path) -> dict[str, Any]:
    root = Path(workspace_root).resolve()
    manifest = _read_json(root / manifest_path if not Path(manifest_path).is_absolute() else Path(manifest_path))
    results: list[dict[str, Any]] = []
    metrics = ("latency_cycles", "ii", "dsp", "bram", "lut", "ff", "estimated_ns")
    for case in manifest.get("cases", []):
        template = _run_result(root, str(case.get("template_run_id") or ""))
        llm = _run_result(root, str(case.get("llm_run_id") or ""))
        same_contract = bool(template["exists"] and llm["exists"] and template["fixed_contract"] == llm["fixed_contract"])
        comparable = bool(
            same_contract
            and template["functional_verified"]
            and llm["functional_verified"]
            and template["canonical_stimulus_matches"]
            and llm["canonical_stimulus_matches"]
            and template["real_report_produced"]
            and llm["real_report_produced"]
        )
        both_production_ready = bool(comparable and template["production_ready"] and llm["production_ready"])
        results.append(
            {
                "case_id": case.get("case_id"),
                "operator": case.get("operator"),
                "objective": case.get("objective"),
                "valid_fair_pair": comparable,
                "both_production_ready": both_production_ready,
                "same_fixed_contract": same_contract,
                "template": template,
                "llm": llm,
                "llm_minus_template": {name: _delta(llm[name], template[name]) for name in metrics},
            }
        )
    valid_count = sum(bool(item["valid_fair_pair"]) for item in results)
    production_count = sum(bool(item["both_production_ready"]) for item in results)
    report = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "selection_policy": "predeclared_exact_run_ids_no_best_of",
        "fixed_constraints": manifest.get("fixed_constraints") or [],
        "case_count": len(results),
        "valid_pair_count": valid_count,
        "both_production_ready_count": production_count,
        "complete": bool(results) and valid_count == len(results),
        "llm_token_usage": {
            "calls": sum(int(item["llm"]["llm_calls"]) for item in results),
            "input_tokens": sum(int(item["llm"]["input_tokens"]) for item in results),
            "output_tokens": sum(int(item["llm"]["output_tokens"]) for item in results),
            "total_tokens": sum(int(item["llm"]["total_tokens"]) for item in results),
            "anomaly_calls": sum(int(item["llm"]["token_anomaly_calls"]) for item in results),
        },
        "results": results,
    }
    output = Path(output_path)
    if not output.is_absolute():
        output = root / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report
