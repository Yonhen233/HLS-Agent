"""Durable sequential comparison runner for the local HLS Agent and Claude CLI.

API credentials are read only from the process environment. Every subprocess
has its own output directory and the manifest is checkpointed after each
system/case, so an interrupted parent process can be restarted safely.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUITE = ROOT / "benchmarks" / "claude_cli_comparison_suite.json"


def utc_now() -> str:
    """Return an ISO timestamp suitable for durable checkpoints."""
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, payload: Any) -> None:
    """Atomically write a JSON checkpoint."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    temporary.replace(path)


def redact_bytes(data: bytes, secrets: list[str]) -> bytes:
    """Prevent accidental credential leakage in captured subprocess logs."""
    text = data.decode("utf-8", errors="replace")
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return text.encode("utf-8")


def pump(stream, target: Path, secrets: list[str]) -> None:
    """Stream one child-process pipe to a redacted log file."""
    with target.open("ab") as handle:
        while True:
            chunk = stream.read(8192)
            if not chunk:
                break
            handle.write(redact_bytes(chunk, secrets))
            handle.flush()


def kill_tree(process: subprocess.Popen) -> None:
    """Terminate a timed-out Windows process tree without touching unrelated processes."""
    if process.poll() is not None:
        return
    subprocess.run(
        ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def run_process(command: list[str], cwd: Path, env: dict[str, str], output_dir: Path, timeout: int, secrets: list[str]) -> dict[str, Any]:
    """Run one long-lived child with streamed logs and a durable result record."""
    output_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = output_dir / "stdout.log"
    stderr_path = output_dir / "stderr.log"
    start = time.perf_counter()
    write_json(output_dir / "process.json", {"status": "running", "started_at": utc_now(), "command": command})
    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
    stdout_thread = threading.Thread(target=pump, args=(process.stdout, stdout_path, secrets), daemon=True)
    stderr_thread = threading.Thread(target=pump, args=(process.stderr, stderr_path, secrets), daemon=True)
    stdout_thread.start()
    stderr_thread.start()
    timed_out = False
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        kill_tree(process)
        process.wait(timeout=30)
    stdout_thread.join(timeout=30)
    stderr_thread.join(timeout=30)
    elapsed = round(time.perf_counter() - start, 3)
    result = {
        "status": "timeout" if timed_out else ("process_success" if process.returncode == 0 else "process_failed"),
        "exit_code": process.returncode,
        "timed_out": timed_out,
        "elapsed_seconds": elapsed,
        "started_at": json.loads((output_dir / "process.json").read_text(encoding="utf-8"))["started_at"],
        "finished_at": utc_now(),
        "stdout": str(stdout_path),
        "stderr": str(stderr_path),
        "command": command,
    }
    write_json(output_dir / "process.json", result)
    return result


def iter_json_lines(path: Path) -> list[dict[str, Any]]:
    """Read structured trace lines while tolerating partial final writes."""
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def summarize_hls(result_dir: Path, process_result: dict[str, Any]) -> dict[str, Any]:
    """Extract HLS Agent status and usage from its durable artifacts."""
    states = sorted(result_dir.rglob("state.json"), key=lambda item: item.stat().st_mtime)
    state: dict[str, Any] = {}
    if states:
        try:
            state = json.loads(states[-1].read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            state = {}
    traces = [item for item in result_dir.rglob("trace.jsonl")]
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "llm_calls": 0}
    for trace in traces:
        for event in iter_json_lines(trace):
            if event.get("event") != "LLMUsageRecorded":
                continue
            usage["prompt_tokens"] += int(event.get("prompt_tokens") or 0)
            usage["completion_tokens"] += int(event.get("completion_tokens") or 0)
            usage["total_tokens"] += int(event.get("total_tokens") or 0)
            usage["llm_calls"] += 1
    completion = state.get("completion") or {}
    pipeline = state.get("pipeline_status") or {}
    return {
        **process_result,
        "status": state.get("status") or process_result["status"],
        "agent_status": state.get("status"),
        "selected_path": state.get("selected_path"),
        "terminal_outcome": state.get("terminal_outcome"),
        "verified": bool(completion.get("passed") or pipeline.get("functional_verified")),
        "completion_passed": completion.get("passed"),
        "pipeline_level": pipeline.get("level"),
        "usage": usage,
        "state_path": str(states[-1]) if states else None,
    }


def summarize_claude(result_dir: Path, process_result: dict[str, Any]) -> dict[str, Any]:
    """Extract Claude CLI usage when its JSON envelope exposes it."""
    stdout = Path(process_result["stdout"])
    text = stdout.read_text(encoding="utf-8", errors="replace") if stdout.exists() else ""
    payload: dict[str, Any] = {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}\s*$", text)
        if match:
            try:
                payload = json.loads(match.group(0))
            except json.JSONDecodeError:
                payload = {}
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    total = usage.get("total_tokens")
    if total is None:
        total = (usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0)
    evidence = []
    for path in result_dir.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".log", ".json", ".md", ".cpp", ".h", ".tcl"}:
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if "GOLDEN_CHECK_PASSED" in content or '"passed": true' in content.lower():
                evidence.append(str(path))
    return {
        **process_result,
        "agent_status": payload.get("result") if isinstance(payload, dict) else None,
        "verified": bool(evidence),
        "usage": {
            "prompt_tokens": usage.get("input_tokens"),
            "completion_tokens": usage.get("output_tokens"),
            "total_tokens": total,
            "llm_calls": 1 if process_result["status"] != "timeout" else None,
        },
        "evidence_files": evidence,
    }


def case_timeout(case: dict[str, Any], policy: dict[str, Any]) -> int:
    """Choose a fixed timeout class before the run starts."""
    family = str(case.get("family", "")).lower()
    if "boundary" in family or "recovery" in family:
        return int(policy["recovery_timeout_seconds"])
    if "mnist" in family or "real" in family:
        return int(policy["model_timeout_seconds"])
    return int(policy["operator_timeout_seconds"])


def claude_prompt(task_path: Path, output_dir: Path) -> str:
    """Build the native Claude CLI baseline prompt."""
    return f"""Work independently on the HLS task described by {task_path}.

Use only Claude CLI's native capabilities (Read, Glob, Grep, Bash, Edit, Write and normal shell tools). Do not invoke the dl-op-to-hls Agent CLI, import its Python runtime, or use its Agent/Skill/benchmark orchestration as a shortcut. You may use the repository's existing hls4ml/Vivado binaries and inspect the repository as read-only source material.

Write all generated code, logs, reports and temporary files under {output_dir}. Do not modify the source repository or other comparison cases. Execute the task end to end as far as the local toolchain permits, run functional verification when possible, and do not claim latency, resources or verification without evidence. If the task is unsupported, report that honestly with the reason and evidence. Do not ask the user questions; finish autonomously and summarize the result in your final response."""


def run_suite(suite_path: Path, output_root: Path, only: set[str] | None = None) -> None:
    """Run or resume the complete sequential comparison suite."""
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    output_root.mkdir(parents=True, exist_ok=True)
    hls_key = os.environ.get("HLS_AGENT_API_KEY", "")
    claude_key = os.environ.get("CLAUDE_API_KEY", "")
    if not hls_key or not claude_key:
        raise SystemExit("HLS_AGENT_API_KEY and CLAUDE_API_KEY must be set in the launcher environment.")
    secrets = [hls_key, claude_key]
    policy = suite["policy"]
    master_path = output_root / "comparison_checkpoint.json"
    checkpoint = json.loads(master_path.read_text(encoding="utf-8")) if master_path.exists() else {
        "suite": suite["suite_name"], "started_at": utc_now(), "cases": {}
    }
    for case in suite["cases"]:
        if only and case["id"] not in only:
            continue
        case_root = output_root / case["id"]
        case_root.mkdir(parents=True, exist_ok=True)
        case_task = (ROOT / case["task"]).resolve()
        case_record = checkpoint["cases"].setdefault(case["id"], {"id": case["id"], "task": case["task"], "family": case["family"]})
        case_record["updated_at"] = utc_now()
        write_json(case_root / "case.json", {**case, "task": str(case_task), "timeout_seconds": case_timeout(case, policy)})
        for system in ("hls_agent", "claude_cli"):
            system_root = case_root / system
            result_path = system_root / "result.json"
            if result_path.exists():
                try:
                    existing = json.loads(result_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    existing = {}
                if existing.get("status") in {"process_success", "timeout"}:
                    case_record[system] = existing
                    continue
            env = os.environ.copy()
            env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
            env["DL_OP_TO_HLS_LLM_ENABLED"] = "1"
            env["DL_OP_TO_HLS_LLM_PROVIDER"] = "openai-compatible"
            env["DL_OP_TO_HLS_LLM_BASE_URL"] = suite["base_url"]
            env["DL_OP_TO_HLS_LLM_MODEL"] = suite["model"]
            env["DL_OP_TO_HLS_LLM_MIN_REQUEST_INTERVAL_SEC"] = "1"
            env["DL_OP_TO_HLS_MOCK_TOOLS"] = "0"
            env["DL_OP_TO_HLS_MOCK_HLS4ML"] = "0"
            env["DL_OP_TO_HLS_MOCK_VIVADO"] = "0"
            if system == "hls_agent":
                env["DL_OP_TO_HLS_LLM_API_KEY"] = hls_key
                env["DL_OP_TO_HLS_RUNS_ROOT"] = str((system_root / "runs").resolve())
                env["DL_OP_TO_HLS_DB_PATH"] = str((system_root / "metadata.db").resolve())
                env["DL_OP_TO_HLS_RUN_ID"] = f"agent-{int(time.time())}"
                command = [sys.executable, "-m", "dl_op_to_hls.cli", "agent-run", str(case_task), "--real-tools"]
                cwd = ROOT
            else:
                env.pop("DL_OP_TO_HLS_LLM_API_KEY", None)
                env["ANTHROPIC_BASE_URL"] = suite["base_url"]
                env["ANTHROPIC_AUTH_TOKEN"] = claude_key
                env["ANTHROPIC_MODEL"] = suite["model"]
                env["ANTHROPIC_DEFAULT_SONNET_MODEL"] = suite["model"]
                env["ANTHROPIC_DEFAULT_OPUS_MODEL"] = suite["model"]
                env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
                command = [
                    "claude.cmd", "-p", claude_prompt(case_task, system_root),
                    "--output-format", "json", "--no-session-persistence",
                    "--dangerously-skip-permissions", "--model", suite["model"],
                    "--add-dir", str(ROOT), "--add-dir", str(system_root),
                ]
                cwd = system_root
            process_result = run_process(command, cwd, env, system_root, case_timeout(case, policy), secrets)
            summary = summarize_hls(system_root, process_result) if system == "hls_agent" else summarize_claude(system_root, process_result)
            write_json(result_path, summary)
            case_record[system] = summary
            checkpoint["cases"][case["id"]] = case_record
            write_json(master_path, checkpoint)
        case_record["completed_at"] = utc_now()
        write_json(master_path, checkpoint)
    checkpoint["finished_at"] = utc_now()
    write_json(master_path, checkpoint)


def main() -> int:
    """Parse launcher arguments and start/resume the durable suite."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--output-root", type=Path, default=ROOT / "runs" / "benchmarks" / "claude_cli_comparison")
    parser.add_argument("--only", nargs="*", default=[])
    args = parser.parse_args()
    run_suite(args.suite.resolve(), args.output_root.resolve(), set(args.only) or None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
