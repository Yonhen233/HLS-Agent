from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from itertools import product
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _safe_name(value: Any) -> str:
    text = str(value)
    text = text.replace("<", "").replace(">", "").replace(",", "_").replace(".", "p")
    return re.sub(r"[^0-9A-Za-z_]+", "_", text).strip("_")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _extract_json_object(text: str) -> dict[str, Any] | None:
    stripped = text.strip("\ufeff\r\n\t ")
    if not stripped:
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None


def _metric(state: dict[str, Any], group: str, key: str) -> Any:
    report = state.get("report") or {}
    return (report.get(group) or {}).get(key)


def _latest_run_dir_for_variant(root: Path, variant_name: str) -> Path | None:
    prefix = variant_name.lower()
    candidates = [
        path
        for path in (root / "runs").iterdir()
        if path.is_dir() and path.name.lower().startswith(prefix)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _load_partial_state_or_report(root: Path, variant_name: str) -> dict[str, Any] | None:
    run_dir = _latest_run_dir_for_variant(root, variant_name)
    if run_dir is None:
        return None
    state_path = run_dir / "state.json"
    if state_path.exists():
        return _load_json(state_path)
    report_candidates = sorted(run_dir.glob("**/myproject_csynth.rpt"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not report_candidates:
        report_candidates = sorted(run_dir.glob("**/*_csynth.rpt"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not report_candidates:
        return {"run_id": run_dir.name, "status": "timeout", "selected_path": None, "report": {"status": "missing"}, "errors": []}
    try:
        from dl_op_to_hls.tools.report_parser import parse_csynth_report_file

        report = parse_csynth_report_file(str(report_candidates[0]))
    except Exception as exc:
        report = {"status": "parse_error", "error": str(exc), "report_path": str(report_candidates[0])}
    return {
        "run_id": run_dir.name,
        "status": "timeout_report_available" if report.get("status") == "success" else "timeout",
        "selected_path": "hls4ml_path",
        "report": report,
        "errors": [],
    }


def _run_command(command: list[str], *, cwd: Path, env: dict[str, str], timeout: int) -> tuple[int, str, str, bool]:
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=creationflags,
    )
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:  # pragma: no cover - Windows is the primary HLS environment here.
            process.kill()
        stdout, stderr = process.communicate(timeout=30)
    return process.returncode if process.returncode is not None else -9, stdout or "", stderr or "", timed_out


def _row_from_state(
    *,
    variant_name: str,
    task_path: Path,
    returncode: int,
    duration_s: float,
    state: dict[str, Any] | None,
    stdout_path: Path,
    stderr_path: Path,
    timed_out: bool = False,
) -> dict[str, Any]:
    if not state:
        return {
            "variant": variant_name,
            "task_path": str(task_path),
            "returncode": returncode,
            "duration_s": round(duration_s, 3),
            "status": "timeout" if timed_out else "parse_failed",
            "timed_out": timed_out,
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
        }
    errors = state.get("errors") or []
    return {
        "variant": variant_name,
        "task_path": str(task_path),
        "returncode": returncode,
        "duration_s": round(duration_s, 3),
        "timed_out": timed_out,
        "run_id": state.get("run_id"),
        "status": state.get("status"),
        "selected_path": state.get("selected_path"),
        "report_status": (state.get("report") or {}).get("status"),
        "latency_min": _metric(state, "latency", "min_cycles"),
        "latency_max": _metric(state, "latency", "max_cycles"),
        "ii_min": _metric(state, "interval", "min_ii"),
        "ii_max": _metric(state, "interval", "max_ii"),
        "bram": _metric(state, "resources", "bram"),
        "dsp": _metric(state, "resources", "dsp"),
        "ff": _metric(state, "resources", "ff"),
        "lut": _metric(state, "resources", "lut"),
        "timing_met": _metric(state, "timing", "met"),
        "estimated_ns": _metric(state, "timing", "estimated_ns"),
        "target_ns": _metric(state, "timing", "target_ns"),
        "error_types": ",".join(str(item.get("error_type")) for item in errors if item.get("error_type")),
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
    }


def _write_results(output_root: Path, rows: list[dict[str, Any]]) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "results.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    if not rows:
        return
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    with (output_root / "results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)
    lines = [
        "# hls4ml Model Sweep Summary",
        "",
        "| Variant | Status | Latency | II | DSP | BRAM | LUT | FF | Timing | Run |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for row in rows:
        lines.append(
            "| {variant} | {status} | {latency_max} | {ii_max} | {dsp} | {bram} | {lut} | {ff} | {timing_met} | {run_id} |".format(
                **{key: row.get(key, "") for key in ["variant", "status", "latency_max", "ii_max", "dsp", "bram", "lut", "ff", "timing_met", "run_id"]}
            )
        )
    (output_root / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a real hls4ml/Vivado sweep for model task variants.")
    parser.add_argument("--base-task", default="examples/mnist_mlp_hls4ml.json")
    parser.add_argument("--output-root", default=None)
    parser.add_argument("--precisions", nargs="+", default=["fixed<8,3>", "fixed<10,4>", "fixed<12,5>"])
    parser.add_argument("--reuse-factors", nargs="+", type=int, default=[128, 256])
    parser.add_argument("--clock-periods", nargs="+", type=float, default=[10.0])
    parser.add_argument("--strategies", nargs="+", default=["Resource"])
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--hls-timeout", type=int, default=0, help="Set DL_OP_TO_HLS_VIVADO_TIMEOUT_SECONDS for each real HLS run; 0 keeps the environment/default.")
    parser.add_argument("--max-runs", type=int, default=0, help="Limit variants for quick experiments; 0 means no limit.")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--mock-tools", action="store_true", help="Force mock tools for smoke testing the sweep script only.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = _repo_root()
    base_task_path = (root / args.base_task).resolve()
    base_task = _load_json(base_task_path)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_root = Path(args.output_root) if args.output_root else root / "runs" / "sweeps" / f"{base_task.get('name', 'model')}_{timestamp}"
    if not output_root.is_absolute():
        output_root = root / output_root
    task_dir = output_root / "tasks"
    log_dir = output_root / "logs"
    task_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    variants = list(product(args.precisions, args.reuse_factors, args.clock_periods, args.strategies))
    if args.max_runs and args.max_runs > 0:
        variants = variants[: args.max_runs]

    rows: list[dict[str, Any]] = []
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    if args.mock_tools:
        env["DL_OP_TO_HLS_MOCK_HLS4ML"] = "1"
        env["DL_OP_TO_HLS_MOCK_VIVADO"] = "1"
    if args.hls_timeout and args.hls_timeout > 0:
        env["DL_OP_TO_HLS_VIVADO_TIMEOUT_SECONDS"] = str(args.hls_timeout)

    for index, (precision, reuse_factor, clock_period, strategy) in enumerate(variants, start=1):
        variant_name = f"{base_task.get('name', 'model')}_p{_safe_name(precision)}_rf{reuse_factor}_clk{_safe_name(clock_period)}_{_safe_name(strategy)}"
        task = json.loads(json.dumps(base_task))
        task["name"] = variant_name
        task.setdefault("hls4ml", {})
        task["hls4ml"]["precision"] = precision
        task["hls4ml"]["reuse_factor"] = reuse_factor
        task["hls4ml"]["strategy"] = strategy
        task.setdefault("target", {})
        task["target"]["clock_period"] = clock_period
        task.setdefault("sweep", {})
        task["sweep"].update(
            {
                "base_task": str(base_task_path),
                "precision": precision,
                "reuse_factor": reuse_factor,
                "clock_period": clock_period,
                "strategy": strategy,
                "variant_index": index,
            }
        )
        task_path = task_dir / f"{variant_name}.json"
        task_path.write_text(json.dumps(task, indent=2, ensure_ascii=False), encoding="utf-8")
        stdout_path = log_dir / f"{variant_name}.stdout.json"
        stderr_path = log_dir / f"{variant_name}.stderr.log"
        started = time.time()
        returncode, stdout, stderr, timed_out = _run_command(
            [args.python, "-m", "dl_op_to_hls.cli", "run", str(task_path)],
            cwd=root,
            env=env,
            timeout=args.timeout,
        )
        duration_s = time.time() - started
        stdout_path.write_text(stdout, encoding="utf-8", errors="replace")
        stderr_path.write_text(stderr, encoding="utf-8", errors="replace")
        state = _extract_json_object(stdout)
        if state is None and timed_out:
            state = _load_partial_state_or_report(root, variant_name)
        rows.append(
            _row_from_state(
                variant_name=variant_name,
                task_path=task_path,
                returncode=returncode,
                duration_s=duration_s,
                state=state,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                timed_out=timed_out,
            )
        )
        _write_results(output_root, rows)

    print(json.dumps({"status": "success", "output_root": str(output_root), "runs": len(rows), "results": rows}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
