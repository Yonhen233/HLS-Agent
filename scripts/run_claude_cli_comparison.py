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
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUITE = ROOT / "benchmarks" / "claude_cli_comparison_suite.json"
RUNNER_VERSION = "durable-multi-turn-v2"


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
    with target.open("wb") as handle:
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


def parse_json_envelope(path: Path) -> dict[str, Any]:
    """Parse Claude's JSON envelope even when a wrapper adds trailing output."""
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return {}
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}\s*$", text)
        if not match:
            return {}
        try:
            value = json.loads(match.group(0))
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}


def usage_from_envelope(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize per CLI invocation token data without inventing unavailable detail."""
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    prompt_tokens = usage.get("input_tokens")
    completion_tokens = usage.get("output_tokens")
    total = usage.get("total_tokens")
    if total is None and (prompt_tokens is not None or completion_tokens is not None):
        total = (prompt_tokens or 0) + (completion_tokens or 0)
    api_turns = payload.get("num_turns")
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total,
        "api_turns": api_turns if isinstance(api_turns, int) else None,
        "cache_creation_input_tokens": usage.get("cache_creation_input_tokens"),
        "cache_read_input_tokens": usage.get("cache_read_input_tokens"),
    }


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
        "comparison_completed": True,
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


def collect_verification_evidence(result_dir: Path) -> list[str]:
    """Collect conservative, externally observable verification evidence."""
    evidence: list[str] = []
    ignored_names = {"case.json", "session.json", "claude_completion.json"}
    for path in result_dir.rglob("*"):
        if not path.is_file() or path.name in ignored_names:
            continue
        if path.suffix.lower() not in {".log", ".json", ".md", ".cpp", ".h", ".tcl", ".rpt"}:
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lowered = content.lower()
        if "golden_check_passed" in lowered or '"passed": true' in lowered or "functional verification: passed" in lowered:
            evidence.append(str(path))
    return sorted(set(evidence))


def completion_marker(result_dir: Path) -> dict[str, Any]:
    """Read the model's explicit completion protocol, if it wrote one."""
    marker = result_dir / "claude_completion.json"
    if not marker.exists():
        return {}
    try:
        value = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def classify_completion(result_dir: Path) -> dict[str, Any]:
    """Apply an external completion gate to the model's self-reported status."""
    marker = completion_marker(result_dir)
    evidence = collect_verification_evidence(result_dir)
    claimed = str(marker.get("status", "")).lower()
    reason = str(marker.get("reason", "")).strip()
    if claimed in {"success", "completed"} and evidence:
        return {"terminal": True, "outcome": "success", "verified": True, "reason": reason, "evidence_files": evidence}
    if claimed in {"blocked", "unsupported", "partial_success"} and reason:
        return {"terminal": True, "outcome": claimed, "verified": False, "reason": reason, "evidence_files": evidence}
    return {
        "terminal": False,
        "outcome": "incomplete",
        "verified": False,
        "reason": "missing independent completion evidence or completion marker",
        "evidence_files": evidence,
    }


def summarize_claude_turn(turn_dir: Path, process_result: dict[str, Any]) -> dict[str, Any]:
    """Summarize one durable Claude CLI invocation."""
    payload = parse_json_envelope(Path(process_result["stdout"]))
    usage = usage_from_envelope(payload)
    return {
        **process_result,
        "payload_result": payload.get("result"),
        "is_error": bool(payload.get("is_error")),
        "session_id": payload.get("session_id"),
        "usage": usage,
        "turn_dir": str(turn_dir),
    }


def cli_error_code(turn_dir: Path) -> str | None:
    """Identify errors that continuation cannot repair and should not burn tokens."""
    stderr = turn_dir / "stderr.log"
    text = stderr.read_text(encoding="utf-8", errors="replace").lower() if stderr.exists() else ""
    if "unrecognized_model" in text or "isn't described by this version's model catalog" in text:
        return "model_catalog_mismatch"
    if "authentication" in text or "invalid api key" in text or "401" in text or "403" in text:
        return "api_authentication_error"
    if "rate limit" in text or "429" in text:
        return "api_rate_limit"
    return None


def aggregate_usage(turns: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate only values actually exposed by the CLI envelopes."""
    total_prompt = 0
    total_completion = 0
    total_tokens = 0
    known_prompt = known_completion = known_total = 0
    api_turns = 0
    llm_invocations = 0
    for turn in turns:
        if turn.get("status") != "process_success":
            continue
        llm_invocations += 1
        usage = turn.get("usage") or {}
        if usage.get("prompt_tokens") is not None:
            total_prompt += int(usage["prompt_tokens"])
            known_prompt += 1
        if usage.get("completion_tokens") is not None:
            total_completion += int(usage["completion_tokens"])
            known_completion += 1
        if usage.get("total_tokens") is not None:
            total_tokens += int(usage["total_tokens"])
            known_total += 1
        if usage.get("api_turns") is not None:
            api_turns += int(usage["api_turns"])
    return {
        "prompt_tokens": total_prompt if known_prompt == llm_invocations else None,
        "completion_tokens": total_completion if known_completion == llm_invocations else None,
        "total_tokens": total_tokens if known_total == llm_invocations else None,
        "llm_calls": llm_invocations,
        "api_turns": api_turns or None,
        "per_invocation": [turn.get("usage", {}) for turn in turns],
    }


def summarize_claude(result_dir: Path, process_result: dict[str, Any], session_state: dict[str, Any]) -> dict[str, Any]:
    """Build the durable multi-turn result used by reports and later diagnosis."""
    gate = classify_completion(result_dir)
    turns = session_state.get("turns", [])
    return {
        "runner_version": RUNNER_VERSION,
        "comparison_completed": True,
        "status": session_state.get("status", "incomplete"),
        "outcome": gate["outcome"],
        "verified": gate["verified"],
        "completion_reason": gate["reason"],
        "evidence_files": gate["evidence_files"],
        "session_id": session_state.get("session_id"),
        "turn_count": len(turns),
        "interruption_count": session_state.get("interruption_count", 0),
        "continuation_count": max(0, len(turns) - 1),
        "usage": aggregate_usage(turns),
        "turns": turns,
        "last_process": process_result,
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
    """Build the initial durable multi-turn baseline prompt."""
    return f"""Work independently on the real end-to-end HLS task described by {task_path}.

Use only Claude CLI's native capabilities (Read, Glob, Grep, Bash, Edit, Write and normal shell tools). Do not invoke the dl-op-to-hls Agent CLI, import its Python runtime, or use its Agent/Skill/benchmark orchestration as a shortcut. You may use the repository's existing hls4ml/Vivado binaries and inspect the repository as read-only source material.

Write all generated code, logs, reports and temporary files under {output_dir}. Do not modify the source repository or other comparison cases. Execute the task end to end as far as the local toolchain permits, run functional verification when possible, and do not claim latency, resources or verification without evidence. Maintain progress in {output_dir}/progress.json so a later turn can continue without repeating completed work.

Completion protocol: only after the end-to-end work is actually finished, or after an honest irrecoverable block, write {output_dir}/claude_completion.json with JSON fields status (success, blocked, unsupported or partial_success), reason, verified, evidence and last_stage. A success status must name concrete evidence files. Never write success merely because code was generated. If a command fails or you reach a partial stop, leave the workspace usable and wait for the next continuation turn. Do not ask the user questions; work autonomously."""


def claude_continuation_prompt(output_dir: Path, turn_number: int, max_turns: int) -> str:
    """Build a deterministic recovery/replan prompt for the same Claude session."""
    return f"""Continue the same HLS task from the current workspace and artifacts under {output_dir}. This is continuation turn {turn_number} of at most {max_turns}. Inspect progress.json, the latest command output and generated artifacts first; do not repeat completed work. Find the first unfinished or failed stage, repair or replan it, and run the strongest available functional verification. Check that any claimed result is supported by concrete files and command output. If the task is genuinely unsupported after investigation, write claude_completion.json with status blocked or unsupported and an evidence-backed reason. Otherwise, do not stop early: keep working until end-to-end completion. Update progress.json and the completion marker only when appropriate."""


def mark_interrupted_turn(turn: dict[str, Any], reason: str) -> None:
    """Make an interrupted in-flight turn explicit before durable resumption."""
    if turn.get("status") == "running":
        turn["status"] = "interrupted"
        turn["interrupted"] = True
        turn["interruption_reason"] = reason


def run_claude_case(
    case_task: Path,
    system_root: Path,
    timeout_seconds: int,
    max_turns: int,
    model: str,
    cli_model: str,
    base_url: str,
    api_key: str,
    secrets: list[str],
    env_base: dict[str, str],
) -> dict[str, Any]:
    """Run one Claude case as a durable, resumable multi-turn session."""
    system_root.mkdir(parents=True, exist_ok=True)
    session_path = system_root / "session.json"
    if session_path.exists():
        try:
            session_state = json.loads(session_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            session_state = {}
    else:
        session_state = {}
    if session_state.get("runner_version") != RUNNER_VERSION:
        session_state = {}
    session_state.setdefault("runner_version", RUNNER_VERSION)
    session_state.setdefault("session_id", str(uuid.uuid4()))
    session_state.setdefault("started_at", utc_now())
    session_state.setdefault("turns", [])
    session_state.setdefault("interruption_count", 0)
    session_state.setdefault("status", "running")
    for turn in session_state["turns"]:
        was_running = turn.get("status") == "running"
        mark_interrupted_turn(turn, "runner_restarted_during_turn")
        if was_running:
            session_state["interruption_count"] += 1
    write_json(session_path, session_state)

    start = time.perf_counter()
    last_process: dict[str, Any] = {}
    while len(session_state["turns"]) < max_turns:
        gate = classify_completion(system_root)
        if gate["terminal"]:
            session_state["status"] = "completed"
            break
        elapsed = time.perf_counter() - start
        remaining = timeout_seconds - int(elapsed)
        if remaining <= 0:
            session_state["status"] = "timeout"
            session_state["interruption_count"] += 1
            break
        turn_number = len(session_state["turns"]) + 1
        turn_dir = system_root / f"turn_{turn_number:02d}"
        turn_dir.mkdir(parents=True, exist_ok=True)
        prompt = claude_prompt(case_task, system_root) if turn_number == 1 else claude_continuation_prompt(system_root, turn_number, max_turns)
        if turn_number == 1:
            command = [
                "claude.cmd", "-p", prompt,
                "--output-format", "json", "--session-id", session_state["session_id"],
                "--permission-mode", "bypassPermissions", "--model", cli_model,
                "--add-dir", str(ROOT), "--add-dir", str(system_root),
            ]
        else:
            command = [
                "claude.cmd", "-p", prompt,
                "--output-format", "json", "--resume", session_state["session_id"],
                "--permission-mode", "bypassPermissions", "--model", cli_model,
                "--add-dir", str(ROOT), "--add-dir", str(system_root),
            ]
        turn_record = {
            "turn": turn_number,
            "status": "running",
            "started_at": utc_now(),
            "prompt_type": "initial" if turn_number == 1 else "continuation",
            "session_id": session_state["session_id"],
        }
        session_state["turns"].append(turn_record)
        write_json(session_path, session_state)
        env = env_base.copy()
        env["ANTHROPIC_BASE_URL"] = base_url
        env["ANTHROPIC_AUTH_TOKEN"] = api_key
        env["ANTHROPIC_MODEL"] = model
        env["ANTHROPIC_DEFAULT_SONNET_MODEL"] = cli_model
        env["ANTHROPIC_DEFAULT_OPUS_MODEL"] = cli_model
        env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
        env["CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT"] = "1"
        last_process = run_process(command, system_root, env, turn_dir, max(60, remaining), secrets)
        turn_summary = summarize_claude_turn(turn_dir, last_process)
        turn_record.update(turn_summary)
        turn_record["finished_at"] = utc_now()
        gate = classify_completion(system_root)
        fatal_error = cli_error_code(turn_dir)
        if fatal_error:
            turn_record["interrupted"] = True
            turn_record["interruption_reason"] = fatal_error
            session_state["status"] = fatal_error
            session_state["interruption_count"] += 1
        elif gate["terminal"]:
            turn_record["interrupted"] = False
            session_state["status"] = "completed"
        else:
            turn_record["interrupted"] = True
            if last_process["status"] == "timeout":
                turn_record["interruption_reason"] = "turn_timeout"
            elif last_process["status"] == "process_failed":
                turn_record["interruption_reason"] = "claude_process_failed"
            else:
                turn_record["interruption_reason"] = "early_stop_without_completion_gate"
            session_state["interruption_count"] += 1
        write_json(session_path, session_state)
        interim = summarize_claude(system_root, last_process, session_state)
        write_json(system_root / "result.json", interim)
        if gate["terminal"] or fatal_error:
            break
    else:
        session_state["status"] = "max_turns_reached"

    if session_state.get("status") == "running":
        session_state["status"] = "max_turns_reached" if len(session_state["turns"]) >= max_turns else "incomplete"
    session_state["finished_at"] = utc_now()
    write_json(session_path, session_state)
    result = summarize_claude(system_root, last_process, session_state)
    result["comparison_completed"] = True
    write_json(system_root / "result.json", result)
    return result


def run_suite(
    suite_path: Path,
    output_root: Path,
    only: set[str] | None = None,
    systems: set[str] | None = None,
) -> None:
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
            if systems is not None and system not in systems:
                continue
            system_root = case_root / system
            result_path = system_root / "result.json"
            if result_path.exists():
                try:
                    existing = json.loads(result_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    existing = {}
                valid_version = system == "hls_agent" or existing.get("runner_version") == RUNNER_VERSION
                if existing.get("comparison_completed") and valid_version and existing.get("status") not in {"process_failed", "incomplete", "max_turns_reached", "timeout"}:
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
                summary = run_claude_case(
                    case_task=case_task,
                    system_root=system_root,
                    timeout_seconds=case_timeout(case, policy),
                    max_turns=int(policy.get("claude_max_turns", 4)),
                    model=suite["model"],
                    cli_model=str(policy.get("claude_cli_model", "sonnet")),
                    base_url=suite["base_url"],
                    api_key=claude_key,
                    secrets=secrets,
                    env_base=env,
                )
                case_record[system] = summary
                checkpoint["cases"][case["id"]] = case_record
                write_json(master_path, checkpoint)
                continue
            process_result = run_process(command, cwd, env, system_root, case_timeout(case, policy), secrets)
            summary = summarize_hls(system_root, process_result)
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
    parser.add_argument("--output-root", type=Path, default=ROOT / "runs" / "benchmarks" / "claude_cli_comparison_durable_v2")
    parser.add_argument("--only", nargs="*", default=[])
    parser.add_argument("--systems", nargs="*", choices=["hls_agent", "claude_cli"], default=[])
    args = parser.parse_args()
    run_suite(args.suite.resolve(), args.output_root.resolve(), set(args.only) or None, set(args.systems) or None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
