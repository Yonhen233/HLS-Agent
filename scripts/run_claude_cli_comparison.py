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
import shutil
import subprocess
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from comparison_baseline import task_hash, validate_baseline_reference


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUITE = ROOT / "benchmarks" / "claude_cli_comparison_suite.json"
RUNNER_VERSION = "durable-multi-turn-v4-llm-candidate-only"
LAUNCH_REVISION = "native-stdin-stream-v1"


@contextmanager
def suite_lock(root: Path):
    """The OS releases this lock even when the runner is killed."""
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".runner.lock").open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def claude_executable() -> str:
    """Avoid cmd.exe reparsing multiline prompts and dropping trailing flags."""
    configured = os.environ.get("CLAUDE_EXECUTABLE")
    if configured:
        executable = Path(configured)
    elif os.name == "nt":
        native = shutil.which("claude.exe")
        shim = shutil.which("claude.cmd")
        executable = Path(native) if native else (
            Path(shim).parent / "node_modules/@anthropic-ai/claude-code/bin/claude.exe"
            if shim else Path("claude.exe")
        )
    else:
        executable = Path(shutil.which("claude") or "claude")
    if not executable.is_file() or executable.suffix.lower() in {".cmd", ".bat"}:
        raise RuntimeError("Set CLAUDE_EXECUTABLE to the native Claude executable, not a shell wrapper.")
    return str(executable.resolve())


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
            chunk = stream.readline()
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


def run_process(command: list[str], cwd: Path, env: dict[str, str], output_dir: Path, timeout: int, secrets: list[str], input_text: str | None = None) -> dict[str, Any]:
    """Run one long-lived child with streamed logs and a durable result record."""
    output_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = output_dir / "stdout.log"
    stderr_path = output_dir / "stderr.log"
    if (output_dir / "process.json").exists():
        history = output_dir / "process_history" / uuid.uuid4().hex
        history.mkdir(parents=True)
        for name in ("process.json", "stdout.log", "stderr.log", "prompt.txt"):
            if (output_dir / name).exists():
                shutil.copy2(output_dir / name, history / name)
    prompt_file = None
    if input_text is not None:
        (output_dir / "prompt.txt").write_bytes(redact_bytes(input_text.encode("utf-8"), secrets))
        prompt_file = (output_dir / "prompt.txt").open("rb")
    start = time.perf_counter()
    write_json(output_dir / "process.json", {"status": "running", "started_at": utc_now(), "command": command})
    try:
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            env=env,
            stdin=prompt_file if prompt_file else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
    except OSError as exc:
        stdout_path.write_bytes(b"")
        stderr_path.write_bytes(redact_bytes(str(exc).encode("utf-8"), secrets))
        result = {"status": "process_failed", "exit_code": None, "timed_out": False,
                  "elapsed_seconds": round(time.perf_counter() - start, 3),
                  "failure_stage": "spawn", "finished_at": utc_now(),
                  "stdout": str(stdout_path), "stderr": str(stderr_path), "command": command}
        write_json(output_dir / "process.json", result)
        return result
    finally:
        if prompt_file:
            prompt_file.close()
    running = json.loads((output_dir / "process.json").read_text(encoding="utf-8"))
    running.update(pid=process.pid, parent_pid=os.getpid())
    write_json(output_dir / "process.json", running)
    stdout_thread = threading.Thread(target=pump, args=(process.stdout, stdout_path, secrets), daemon=True)
    stderr_thread = threading.Thread(target=pump, args=(process.stderr, stderr_path, secrets), daemon=True)
    stdout_thread.start()
    stderr_thread.start()
    timed_out = False
    try:
        while process.poll() is None:
            remaining = timeout - (time.perf_counter() - start)
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, timeout)
            try:
                process.wait(timeout=min(5, remaining))
            except subprocess.TimeoutExpired:
                write_json(output_dir / "process.json", {**running, "heartbeat_at": utc_now(),
                                                          "elapsed_seconds": round(time.perf_counter() - start, 3)})
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
        "pid": process.pid,
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
    results = [row for row in iter_json_lines(path) if row.get("type") == "result"]
    if results:
        return results[-1]
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
    usage_source = "response_usage" if usage else "missing"
    if not usage and isinstance(payload.get("modelUsage"), dict):
        # Claude Code's final envelope can expose the provider ledger under
        # modelUsage even when the top-level usage object is absent.  Normalize
        # both Anthropic-style camelCase and OpenAI-style snake_case fields.
        totals = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        observed = False
        for model_usage in payload["modelUsage"].values():
            if not isinstance(model_usage, dict):
                continue
            observed = observed or any(
                key in model_usage
                for key in (
                    "inputTokens", "input_tokens", "prompt_tokens",
                    "outputTokens", "output_tokens", "completion_tokens",
                )
            )
            model_cache_read = int(model_usage.get("cacheReadInputTokens") or model_usage.get("cache_read_input_tokens") or 0)
            model_cache_write = int(model_usage.get("cacheCreationInputTokens") or model_usage.get("cache_creation_input_tokens") or 0)
            model_input = model_usage.get("inputTokens", model_usage.get("input_tokens"))
            if model_input is None and model_usage.get("prompt_tokens") is not None:
                model_input = max(0, int(model_usage["prompt_tokens"]) - model_cache_read - model_cache_write)
            totals["input_tokens"] += int(model_input or 0)
            totals["output_tokens"] += int(model_usage.get("outputTokens") or model_usage.get("output_tokens") or model_usage.get("completion_tokens") or 0)
            totals["cache_read_input_tokens"] += model_cache_read
            totals["cache_creation_input_tokens"] += model_cache_write
        if observed:
            usage = totals
            usage_source = "model_usage"

    uncached = usage.get("input_tokens")
    cache_read = usage.get("cache_read_input_tokens")
    if cache_read is None:
        cache_read = usage.get("cacheReadInputTokens")
    cache_read = cache_read or 0
    cache_write = usage.get("cache_creation_input_tokens")
    if cache_write is None:
        cache_write = usage.get("cacheCreationInputTokens")
    cache_write = cache_write or 0
    # OpenAI prompt_tokens already includes cached input; Anthropic input_tokens
    # excludes cache reads/writes. Normalize both to total processed input.
    prompt_tokens = usage.get("prompt_tokens")
    if prompt_tokens is None:
        prompt_tokens = None if uncached is None else int(uncached) + int(cache_read) + int(cache_write)
    elif uncached is None:
        uncached = max(0, int(prompt_tokens) - int(cache_read) - int(cache_write))
    completion_tokens = usage.get("output_tokens")
    if completion_tokens is None:
        completion_tokens = usage.get("completion_tokens")
    total = usage.get("total_tokens")
    if total is None and (prompt_tokens is not None or completion_tokens is not None):
        total = (prompt_tokens or 0) + (completion_tokens or 0)
    api_turns = payload.get("num_turns")
    return {
        "prompt_tokens": prompt_tokens,
        "uncached_input_tokens": uncached,
        "completion_tokens": completion_tokens,
        "total_tokens": total,
        "api_turns": api_turns if isinstance(api_turns, int) else None,
        "cache_creation_input_tokens": cache_write,
        "cache_read_input_tokens": cache_read,
        "usage_source": usage_source,
    }


def claude_call_ledger(path: Path) -> list[dict[str, Any]]:
    """A message ID may occur for text and tool blocks; count it only once."""
    calls: dict[str, dict[str, Any]] = {}
    for row in iter_json_lines(path):
        message = row.get("message") or {}
        if row.get("type") != "assistant" or not message.get("id") or not message.get("usage"):
            continue
        key = message["id"]
        usage = message["usage"]
        prior = calls.get(key, {}).get("provider_usage", {})
        merged = {**prior, **usage}
        for field in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
            if field in prior and field in usage:
                merged[field] = max(prior[field] or 0, usage[field] or 0)
        calls[key] = {
            "call_id": key, "model": message.get("model"), "session_id": row.get("session_id"),
            "parent_tool_use_id": row.get("parent_tool_use_id"), "provider_usage": merged,
            "usage": usage_from_envelope({"usage": merged}),
        }
    return list(calls.values())


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
    states = sorted((result_dir / "runs").glob("agent-*/state.json"), key=lambda item: item.stat().st_mtime)
    state: dict[str, Any] = {}
    if states:
        try:
            state = json.loads(states[-1].read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            state = {}
    traces = list((result_dir / "runs").glob("agent-*/trace.jsonl"))
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "llm_calls": 0}
    ledger = []
    seen = set()
    for trace in traces:
        for event in iter_json_lines(trace):
            if event.get("event") != "LLMUsageRecorded":
                continue
            key = (event.get("run_id", str(trace)), event.get("call_id", event.get("ts")))
            if key in seen:
                continue
            seen.add(key)
            ledger.append(event)
            usage["prompt_tokens"] += int(event.get("input_tokens", event.get("prompt_tokens")) or 0)
            usage["completion_tokens"] += int(event.get("output_tokens", event.get("completion_tokens")) or 0)
            usage["total_tokens"] += int(event.get("total_tokens") or 0)
            usage["llm_calls"] += 1
    completion = state.get("completion") or {}
    pipeline = state.get("pipeline_status") or {}
    write_json(result_dir / "llm_calls.json", ledger)
    failed_process = process_result["status"] in {"timeout", "process_failed"}
    return {
        **process_result,
        "comparison_completed": True,
        "status": process_result["status"] if failed_process else state.get("status") or process_result["status"],
        "process_status": process_result["status"],
        "agent_status": state.get("status"),
        "selected_path": state.get("selected_path"),
        "terminal_outcome": state.get("terminal_outcome"),
        "verified": not failed_process and bool(completion.get("passed") or pipeline.get("functional_verified")),
        "completion_passed": completion.get("passed"),
        "pipeline_level": pipeline.get("level"),
        "usage": usage,
        "state_path": str(states[-1]) if states else None,
        "llm_calls_path": str(result_dir / "llm_calls.json"),
    }


def collect_verification_evidence(result_dir: Path) -> list[str]:
    """Check toolchain artifacts, not source strings or the model's own prose.

    This is artifact corroboration, not an independent hidden-test rerun.
    """
    evidence: list[str] = []
    synth: list[str] = []
    for path in result_dir.rglob("*"):
        if not path.is_file() or "process_history" in path.parts:
            continue
        name = path.name.lower()
        if path.suffix.lower() not in {".log", ".rpt"} or not any(word in name for word in ("csim", "csynth", "vivado")):
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lowered = content.lower()
        if ("csim done with 0 errors" in lowered
                and re.search(r"(?m)^\s*GOLDEN_CHECK_PASSED\s*$", content)):
            evidence.append(str(path))
        if (path.suffix.lower() == ".rpt" and "hls report for" in lowered
                and "performance estimates" in lowered and "utilization estimates" in lowered):
            synth.append(str(path))
    return sorted(set(evidence + synth)) if evidence and synth else []


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
    ledger = claude_call_ledger(Path(process_result["stdout"]))
    write_json(turn_dir / "llm_calls.json", ledger)
    if not payload and ledger:
        usage = {key: sum(call["usage"].get(key) or 0 for call in ledger)
                 for key in ("prompt_tokens", "completion_tokens", "total_tokens")}
    usage["llm_calls"] = len(ledger) if ledger else None
    usage["ledger_partial"] = not bool(payload)
    return {
        **process_result,
        "payload_result": payload.get("result"),
        "is_error": bool(payload.get("is_error")),
        "session_id": payload.get("session_id"),
        "usage": usage,
        "turn_dir": str(turn_dir),
        "llm_calls_path": str(turn_dir / "llm_calls.json"),
    }


def cli_error_code(turn_dir: Path, process_result: dict[str, Any]) -> str | None:
    """Identify non-recoverable errors while ignoring benign stderr warnings."""
    stderr = turn_dir / "stderr.log"
    text = stderr.read_text(encoding="utf-8", errors="replace").lower() if stderr.exists() else ""
    if process_result.get("timed_out") or process_result.get("status") == "timeout":
        return "timeout"
    if process_result.get("status") == "process_success":
        return None
    if "no conversation found" in text or "session not found" in text:
        return "session_not_found"
    if "model_not_found" in text or "invalid model" in text:
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
        llm_invocations += 1
        usage = turn.get("usage") or {}
        complete = not usage.get("ledger_partial", False)
        if usage.get("prompt_tokens") is not None:
            total_prompt += int(usage["prompt_tokens"])
            known_prompt += int(complete)
        if usage.get("completion_tokens") is not None:
            total_completion += int(usage["completion_tokens"])
            known_completion += int(complete)
        if usage.get("total_tokens") is not None:
            total_tokens += int(usage["total_tokens"])
            known_total += int(complete)
        if usage.get("api_turns") is not None:
            api_turns += int(usage["api_turns"])
    return {
        "prompt_tokens": total_prompt if known_prompt == llm_invocations else None,
        "completion_tokens": total_completion if known_completion == llm_invocations else None,
        "total_tokens": total_tokens if known_total == llm_invocations else None,
        "llm_calls": (sum(turn.get("usage", {}).get("llm_calls") or 0 for turn in turns)
                      if turns and all(turn.get("usage", {}).get("llm_calls") is not None and not turn.get("usage", {}).get("ledger_partial") for turn in turns) else None),
        "observed_llm_calls": sum(turn.get("usage", {}).get("llm_calls") or 0 for turn in turns),
        "cli_invocations": llm_invocations,
        "known_total_tokens": total_tokens,
        "missing_usage_invocations": llm_invocations - known_total,
        "api_turns": api_turns or None,
        "per_invocation": [turn.get("usage", {}) for turn in turns],
    }


def summarize_claude(result_dir: Path, process_result: dict[str, Any], session_state: dict[str, Any]) -> dict[str, Any]:
    """Build the durable multi-turn result used by reports and later diagnosis."""
    gate = classify_completion(result_dir)
    turns = session_state.get("turns", [])
    return {
        "runner_version": RUNNER_VERSION,
        "launch_revision": LAUNCH_REVISION,
        "comparison_completed": session_state.get("status") != "running",
        "status": session_state.get("status", "incomplete"),
        "outcome": gate["outcome"],
        "verified": gate["verified"],
        "completion_reason": gate["reason"],
        "evidence_files": gate["evidence_files"],
        "session_id": session_state.get("session_id"),
        "turn_count": len(turns),
        "interruption_count": session_state.get("interruption_count", 0),
        "session_recovery_count": session_state.get("session_recovery_count", 0),
        "elapsed_seconds": round(sum(turn.get("elapsed_seconds", 0) for turn in turns), 3),
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
    if session_state and session_state.get("runner_version") != RUNNER_VERSION:
        raise RuntimeError("Incompatible session version; preserve artifacts and use an explicit new experiment directory.")
    session_state.setdefault("runner_version", RUNNER_VERSION)
    session_state.setdefault("session_id", str(uuid.uuid4()))
    session_state.setdefault("started_at", utc_now())
    session_state.setdefault("turns", [])
    session_state.setdefault("interruption_count", 0)
    session_state.setdefault("session_recovery_count", 0)
    session_state.setdefault("force_new_session", False)
    session_state.setdefault("status", "running")
    session_state["launch_revision"] = LAUNCH_REVISION
    for turn in session_state["turns"]:
        was_running = turn.get("status") == "running"
        mark_interrupted_turn(turn, "runner_restarted_during_turn")
        if was_running:
            turn_dir = system_root / f"turn_{turn['turn']:02d}"
            process_path = turn_dir / "process.json"
            if process_path.exists():
                prior = json.loads(process_path.read_text(encoding="utf-8"))
                if prior.get("started_at"):
                    turn["elapsed_seconds"] = prior.get("elapsed_seconds", 0)
                    turn["elapsed_is_lower_bound"] = True
                if (turn_dir / "stdout.log").exists():
                    prior["stdout"] = str(turn_dir / "stdout.log")
                    recovered = summarize_claude_turn(turn_dir, prior)
                    turn["usage"] = recovered["usage"]
            session_state["interruption_count"] += 1
    write_json(session_path, session_state)

    start = time.perf_counter()
    prior_elapsed = sum(turn.get("elapsed_seconds", 0) for turn in session_state["turns"])
    last_process: dict[str, Any] = {}
    while len(session_state["turns"]) < max_turns:
        gate = classify_completion(system_root)
        if gate["terminal"]:
            session_state["status"] = "completed"
            break
        elapsed = time.perf_counter() - start
        remaining = timeout_seconds - int(elapsed + prior_elapsed)
        if remaining <= 0:
            session_state["status"] = "timeout"
            break
        turn_number = len(session_state["turns"]) + 1
        turn_dir = system_root / f"turn_{turn_number:02d}"
        turn_dir.mkdir(parents=True, exist_ok=True)
        force_new_session = bool(session_state.pop("force_new_session", False))
        initial_session_turn = turn_number == 1 or force_new_session
        prompt = claude_prompt(case_task, system_root) if turn_number == 1 else claude_continuation_prompt(system_root, turn_number, max_turns)
        if initial_session_turn:
            command = [
                claude_executable(), "-p",
                "--output-format", "stream-json", "--verbose", "--forward-subagent-text", "--session-id", session_state["session_id"],
                "--permission-mode", "bypassPermissions", "--model", cli_model,
                "--add-dir", str(ROOT), "--add-dir", str(system_root),
            ]
        else:
            command = [
                claude_executable(), "-p",
                "--output-format", "stream-json", "--verbose", "--forward-subagent-text", "--resume", session_state["session_id"],
                "--permission-mode", "bypassPermissions", "--model", cli_model,
                "--add-dir", str(ROOT), "--add-dir", str(system_root),
            ]
        turn_record = {
            "turn": turn_number,
            "status": "running",
            "started_at": utc_now(),
            "prompt_type": "initial" if turn_number == 1 else ("fresh_session_recovery" if force_new_session else "continuation"),
            "session_id": session_state["session_id"],
        }
        session_state["turns"].append(turn_record)
        write_json(session_path, session_state)
        env = env_base.copy()
        env.pop("HLS_AGENT_API_KEY", None)
        env.pop("CLAUDE_API_KEY", None)
        env["ANTHROPIC_BASE_URL"] = base_url
        env["ANTHROPIC_AUTH_TOKEN"] = api_key
        env["ANTHROPIC_MODEL"] = model
        env["ANTHROPIC_DEFAULT_SONNET_MODEL"] = model
        env["ANTHROPIC_DEFAULT_OPUS_MODEL"] = model
        env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
        env["CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT"] = "1"
        last_process = run_process(command, system_root, env, turn_dir, remaining, secrets, input_text=prompt)
        turn_summary = summarize_claude_turn(turn_dir, last_process)
        turn_record.update(turn_summary)
        turn_record["session_id"] = turn_summary.get("session_id") or session_state["session_id"]
        turn_record["session_persistence_confirmed"] = bool(turn_summary.get("session_id"))
        if turn_summary.get("session_id"):
            session_state["session_id"] = turn_summary["session_id"]
        turn_record["finished_at"] = utc_now()
        gate = classify_completion(system_root)
        fatal_error = cli_error_code(turn_dir, last_process)
        recover_session = fatal_error == "session_not_found" and not session_state.get("session_recovery_count")
        if recover_session:
            session_state["session_recovery_count"] += 1
            session_state["session_id"] = str(uuid.uuid4())
            session_state["force_new_session"] = True
            turn_record["interrupted"] = True
            turn_record["interruption_reason"] = "session_not_found_fresh_session_recovery"
            session_state["interruption_count"] += 1
        elif fatal_error:
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
        if gate["terminal"] or (fatal_error and not recover_session):
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
    from dl_op_to_hls.llm.candidate_generator import candidate_generation_contract_errors

    for case in suite.get("cases", []):
        task_path = (ROOT / case["task"]).resolve()
        task = json.loads(task_path.read_text(encoding="utf-8"))
        if task.get("task_type") != "operator" or candidate_generation_contract_errors(task):
            raise ValueError(
                f"Comparison requires an operator with built-in semantics or an independent candidate contract: {case.get('id')}"
            )
        if case.get("claude_baseline"):
            validate_baseline_reference(task_path, case["claude_baseline"])
    output_root.mkdir(parents=True, exist_ok=True)
    policy = suite["policy"]
    systems = systems if systems is not None else set(policy.get("systems", ["hls_agent", "claude_cli"]))
    if policy.get("reuse_claude_baseline") and systems != {"hls_agent"}:
        raise ValueError("This suite reuses Claude baselines; only HLS Agent may execute")
    hls_key = os.environ.get("HLS_AGENT_API_KEY", "")
    claude_key = os.environ.get("CLAUDE_API_KEY", "")
    if ("hls_agent" in systems and not hls_key) or ("claude_cli" in systems and not claude_key):
        raise SystemExit("Set the API key for each system selected for execution.")
    secrets = [hls_key, claude_key]
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
        current_task_hash = task_hash(json.loads(case_task.read_text(encoding="utf-8")))
        previous_case_path = case_root / "case.json"
        if previous_case_path.exists():
            previous_case = json.loads(previous_case_path.read_text(encoding="utf-8"))
            if Path(previous_case["task"]).resolve() != case_task:
                raise ValueError(f"Cannot reuse results from a different input task: {case['id']}")
            if previous_case.get("task_sha256", current_task_hash) != current_task_hash:
                raise ValueError(f"Input task changed since this case was started: {case['id']}")
        case_record = checkpoint["cases"].setdefault(case["id"], {"id": case["id"], "task": case["task"], "family": case["family"]})
        case_record["updated_at"] = utc_now()
        checkpoint.pop("finished_at", None)
        checkpoint["launch_revision"] = LAUNCH_REVISION
        write_json(case_root / "case.json", {**case, "task": str(case_task), "task_sha256": current_task_hash,
                                           "timeout_seconds": case_timeout(case, policy)})
        for system in ("hls_agent", "claude_cli"):
            if systems is not None and system not in systems:
                continue
            system_root = case_root / system
            checkpoint["active"] = {"case": case["id"], "system": system, "updated_at": utc_now()}
            write_json(master_path, checkpoint)
            result_path = system_root / "result.json"
            if result_path.exists():
                try:
                    existing = json.loads(result_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    existing = {}
                valid_version = system == "hls_agent" or existing.get("runner_version") == RUNNER_VERSION
                if existing.get("comparison_completed") and valid_version and existing.get("status") != "running":
                    case_record[system] = existing
                    continue
            env = os.environ.copy()
            env.pop("HLS_AGENT_API_KEY", None)
            env.pop("CLAUDE_API_KEY", None)
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
                resumed_elapsed = 0
                prior_process_path = system_root / "process.json"
                prior_process = json.loads(prior_process_path.read_text(encoding="utf-8")) if prior_process_path.exists() else {}
                env["DL_OP_TO_HLS_LLM_API_KEY"] = hls_key
                env["DL_OP_TO_HLS_RUNS_ROOT"] = str((system_root / "runs").resolve())
                env["DL_OP_TO_HLS_DB_PATH"] = str((system_root / "metadata.db").resolve())
                env["DL_OP_TO_HLS_RUN_ID"] = f"agent-{int(time.time())}"
                command = [sys.executable, "-m", "dl_op_to_hls.cli", "agent-run", str(case_task), "--real-tools"]
                sessions = sorted((system_root / "runs/sessions").glob("*/session.json"), key=lambda path: path.stat().st_mtime)
                if prior_process.get("status") == "running" and sessions:
                    command = [sys.executable, "-m", "dl_op_to_hls.cli", "session-resume", sessions[-1].parent.name]
                    resumed_elapsed = prior_process.get("elapsed_seconds", 0)
                    if not resumed_elapsed:
                        traces = list((system_root / "runs").glob("agent-*/trace.jsonl"))
                        if traces:
                            last_ts = max(path.stat().st_mtime for path in traces)
                            resumed_elapsed = max(0, last_ts - datetime.fromisoformat(prior_process["started_at"]).timestamp())
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
            process_result = run_process(command, cwd, env, system_root, max(1, case_timeout(case, policy) - int(resumed_elapsed)), secrets)
            if resumed_elapsed:
                process_result["elapsed_seconds"] += resumed_elapsed
                process_result["elapsed_is_lower_bound"] = True
                process_result["interruption_count"] = 1
            summary = summarize_hls(system_root, process_result)
            write_json(result_path, summary)
            case_record[system] = summary
            checkpoint["cases"][case["id"]] = case_record
            write_json(master_path, checkpoint)
        case_record["completed_at"] = utc_now()
        write_json(master_path, checkpoint)
    checkpoint["finished_at"] = utc_now()
    checkpoint.pop("active", None)
    write_json(master_path, checkpoint)


def main() -> int:
    """Parse launcher arguments and start/resume the durable suite."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--output-root", type=Path, default=ROOT / "runs" / "benchmarks" / "claude_cli_comparison_durable_v2")
    parser.add_argument("--only", nargs="*", default=[])
    parser.add_argument("--systems", nargs="*", choices=["hls_agent", "claude_cli"], default=[])
    args = parser.parse_args()
    with suite_lock(args.output_root.resolve()):
        run_suite(args.suite.resolve(), args.output_root.resolve(), set(args.only) or None, set(args.systems) or None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
