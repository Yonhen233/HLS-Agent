"""Bounded raw-tool evidence for targeted Agent repair decisions."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


_PATH_KEYS = {
    "log_path",
    "stderr_path",
    "stdout_path",
    "report_path",
    "project_dir",
    "work_dir",
}
_LOG_SUFFIXES = {".log", ".rpt", ".txt"}
_MARKERS = (
    "dataflow strict check failed",
    "csynth_design' failed",
    "csim_design' failed",
    "failed before report",
    "cannot allocate memory",
    "out of memory",
    "timed out",
    "no rule to make target",
    "no such file or directory",
    "error:",
    "fatal error",
    "exiting vivado_hls",
)


def _candidate_paths(value: Any, key: str = "") -> set[Path]:
    paths: set[Path] = set()
    if isinstance(value, dict):
        for child_key, child in value.items():
            paths.update(_candidate_paths(child, str(child_key)))
    elif isinstance(value, (list, tuple)):
        for child in value:
            paths.update(_candidate_paths(child, key))
    elif isinstance(value, str) and (key in _PATH_KEYS or key.endswith("_path")):
        path = Path(value)
        if path.is_file() or path.is_dir():
            paths.add(path)
        elif path.suffix.lower() in _LOG_SUFFIXES:
            paths.add(path)
    return paths


def _read_text(path: Path) -> str:
    try:
        if path.is_file():
            return path.read_text(encoding="utf-8", errors="replace")
        if path.is_dir():
            candidates = sorted(
                (item for item in path.rglob("*") if item.is_file() and item.suffix.lower() in _LOG_SUFFIXES),
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            )
            return "\n".join(_read_text(item) for item in candidates[:3])
    except OSError:
        return ""
    return ""


def _classify(text: str, paths: list[str]) -> tuple[str, str]:
    lowered = text.lower()
    if "dataflow strict check failed" in lowered:
        return "synthesis_schedule_error", "Vivado reported a dataflow/scheduling failure; repair the schedule hypothesis using the captured log evidence."
    if "cannot allocate memory" in lowered or "out of memory" in lowered:
        return "host_resource_error", "The host could not allocate synthesis resources; do not rewrite valid candidate semantics before checking host capacity."
    if "no rule to make target" in lowered or "no such file or directory" in lowered:
        return "tool_input_staging_error", "Vivado could not resolve a staged source or testbench path; repair the project/Tcl artifact paths before changing candidate semantics."
    if "timed out" in lowered:
        return "synthesis_timeout", "Synthesis did not finish; use the last completed phase and log tail to choose a bounded schedule repair."
    if "csim_design' failed" in lowered or "golden_check_failed" in lowered:
        return "functional_verification_error", "Functional verification failed; preserve the independent golden contract and repair the candidate/testbench mismatch."
    if "error:" in lowered or "fatal error" in lowered or "failed before report" in lowered:
        return "synthesis_compile_error", "Vivado reported a compile or synthesis error; repair only the evidenced source/toolchain issue."
    if paths:
        return "synthesis_incomplete", "The tool stopped without a complete report; use the last log phase and bounded raw excerpt before replanning."
    return "unknown_tool_failure", "The tool failure has no readable log yet; request targeted artifact inspection before another candidate rewrite."


def collect_repair_evidence(*payloads: Any, max_chars: int = 12000, max_lines: int = 160) -> dict[str, Any]:
    """Read only bounded, relevant tool output and turn it into repair evidence."""

    paths = sorted({path.resolve() for payload in payloads for path in _candidate_paths(payload)})
    excerpts: list[dict[str, Any]] = []
    all_text: list[str] = []
    for path in paths:
        text = _read_text(path)
        if not text:
            continue
        lines = text.splitlines()
        matching = [line.strip() for line in lines if any(marker in line.lower() for marker in _MARKERS)]
        tail = "\n".join(lines[-max_lines:])
        try:
            size_bytes = path.stat().st_size if path.is_file() else None
        except OSError:
            size_bytes = None
        excerpts.append({
            "path": str(path),
            "size_bytes": size_bytes,
            "matched_lines": matching[-40:],
            "tail": tail[-max_chars:],
        })
        all_text.append(text)
    combined = "\n".join(all_text)
    diagnosis, repair_hint = _classify(combined, [item["path"] for item in excerpts])
    matched = [line for item in excerpts for line in item["matched_lines"]]
    return {
        "status": "available" if excerpts else "missing",
        "diagnosis": diagnosis,
        "repair_hint": repair_hint,
        "log_paths": [item["path"] for item in excerpts],
        "matched_lines": matched[-60:],
        "excerpts": excerpts,
        "raw_content_truncated": True,
        "max_chars_per_excerpt": max_chars,
    }
