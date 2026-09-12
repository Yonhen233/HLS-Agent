"""Explicit task identity and read-only provenance for reused Claude baselines."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def task_hash(task: dict[str, Any]) -> str:
    canonical = json.dumps(task, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_baseline_reference(task_path: Path, reference: dict[str, Any]) -> None:
    """Fail closed if either the source case or the submitted task has drifted."""
    source = Path(reference["source_dir"]).resolve()
    case = load_json(source.parent / "case.json")
    if case["id"] != reference["source_case"]:
        raise ValueError("Claude baseline case identity changed")
    if Path(case["task"]).resolve() != task_path.resolve():
        raise ValueError("Claude baseline and HLS input task paths differ")
    if task_hash(load_json(task_path)) != reference["task_sha256"]:
        raise ValueError("Task content differs from the audited Claude baseline snapshot")
    if not (source / "result.json").is_file():
        raise ValueError("Claude baseline result is missing")


def align_suite(suite: dict[str, Any], root: Path, baseline_root: Path, revision: str) -> dict[str, Any]:
    """Use the task each historical Claude run actually received, without edits."""
    rename = {"relu_llm_candidate": "relu_operator", "add_llm_candidate": "add_operator"}
    commit = subprocess.check_output(["git", "rev-parse", revision], cwd=root, text=True).strip()
    cases = []
    for original in suite["cases"]:
        source_case = rename.get(original["id"], original["id"])
        source = (baseline_root / source_case / "claude_cli").resolve()
        recorded = load_json(source.parent / "case.json")
        task_path = Path(recorded["task"]).resolve()
        relative = task_path.relative_to(root.resolve()).as_posix()
        task = load_json(task_path)
        snapshot = json.loads(subprocess.check_output(["git", "show", f"{commit}:{relative}"], cwd=root))
        if task != snapshot:
            raise ValueError(f"Task has changed since baseline revision: {relative}")
        reference = {
            "source_case": source_case,
            "source_dir": str(source),
            "task_sha256": task_hash(snapshot),
            "git_revision": commit,
            "identity_basis": "recorded_task_path_and_git_snapshot",
            "historical_runtime_task_hash_available": False,
        }
        validate_baseline_reference(task_path, reference)
        cases.append({"id": source_case, "task": relative, "family": original["family"], "claude_baseline": reference})
    return {**suite, "policy": {**suite["policy"], "systems": ["hls_agent"], "reuse_claude_baseline": True}, "cases": cases}
