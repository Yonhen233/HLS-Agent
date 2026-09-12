"""Boundary handoff: preserve the first HLS case, then switch to exact Claude tasks."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from comparison_baseline import align_suite


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--runner-pid", type=int, required=True)
    parser.add_argument("--revision", default="3c07e2f")
    args = parser.parse_args()
    root = args.root.resolve()
    output = root / "runs/benchmarks/claude_cli_comparison_durable_v4"
    first = output / "dense_llm_candidate/hls_agent/result.json"
    first_process = output / "dense_llm_candidate/hls_agent/process.json"
    marker = output / "handoff.json"
    while True:
        process = load(first_process) if first_process.exists() else {}
        result = load(first) if first.exists() else {}
        if process.get("status") not in {"running", "pending"} and result.get("comparison_completed"):
            break
        time.sleep(5)
    write(marker, {"phase": "first_hls_case_finished", "first_result": result, "observed_at": time.time()})
    subprocess.run(["taskkill.exe", "/PID", str(args.runner_pid), "/T", "/F"], check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)
    aligned = align_suite(load(args.suite), root, args.baseline_root.resolve(), args.revision)
    aligned_path = output / "aligned_suite.json"
    write(aligned_path, aligned)
    write(output / "baseline_alignment.json", {
        "policy": "exact_historical_claude_task_identity",
        "suite": str(aligned_path),
        "cases": [case["claude_baseline"] for case in aligned["cases"]],
        "first_case_preserved": True,
    })
    env = os.environ.copy()
    env["HLS_AGENT_API_KEY"] = os.environ["HLS_AGENT_API_KEY"]
    env.pop("CLAUDE_API_KEY", None)
    env["PYTHONPATH"] = str(root / "src") + os.pathsep + env.get("PYTHONPATH", "")
    command = [sys.executable, "scripts/run_claude_cli_comparison.py", "--suite", str(aligned_path),
               "--output-root", str(output), "--systems", "hls_agent"]
    log = output / "aligned_runner.log"
    with log.open("a", encoding="utf-8") as handle:
        handle.write("\nStarting exact-task HLS-only continuation.\n")
        completed = subprocess.run(command, cwd=root, env=env, stdout=handle, stderr=subprocess.STDOUT)
    write(marker, {"phase": "aligned_hls_finished", "exit_code": completed.returncode, "suite": str(aligned_path)})
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
