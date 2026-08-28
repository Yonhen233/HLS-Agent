from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


EVIDENCE_CLASSES = {
    "unit",
    "mock",
    "fixture",
    "real_csim",
    "real_csynth",
    "rtl_cosim",
    "implementation",
}


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class EvidenceAssessment:
    evidence_class: str
    valid: bool
    reasons: list[str]
    artifact_path: str | None = None
    sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_class": self.evidence_class,
            "valid": self.valid,
            "reasons": self.reasons,
            "artifact_path": self.artifact_path,
            "sha256": self.sha256,
        }


def assess_tool_evidence(
    tool_name: str,
    result: dict[str, Any],
    context: dict[str, Any],
    *,
    mock_evidence: bool,
    arguments: dict[str, Any] | None = None,
) -> EvidenceAssessment:
    """Classify evidence conservatively; absence of proof never becomes real evidence."""

    mode = str(result.get("mode") or "").lower()
    if mock_evidence or mode in {"mock", "demo"}:
        return EvidenceAssessment("mock", True, ["tool or runtime explicitly marked mock"])

    path_value = _primary_evidence_path(tool_name, result, arguments or {})
    path = _resolve_path(path_value, context) if path_value else None
    if path is not None and _is_fixture(path):
        return EvidenceAssessment("fixture", path.exists(), ["artifact is under tests/fixtures"], str(path))

    expected = _expected_class(tool_name)
    if expected == "unit":
        return EvidenceAssessment("unit", True, ["atomic action has no real-tool evidence contract"])

    reasons: list[str] = []
    valid = True
    run_dir = Path(context.get("run_dir") or "").resolve() if context.get("run_dir") else None
    if path is None or not path.exists() or not path.is_file():
        valid = False
        reasons.append("primary evidence artifact is missing")
    else:
        if run_dir is None or not (path == run_dir or run_dir in path.parents):
            valid = False
            reasons.append("artifact is not inside the current run directory")
        run_started = _parse_time(context.get("run_started_at"))
        if run_started is not None:
            modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            if modified < run_started:
                valid = False
                reasons.append("artifact predates the current run")
        reasons.extend(_content_checks(expected, path, result))
        if any(reason.startswith("missing ") or reason.startswith("failure marker") for reason in reasons):
            valid = False

    return EvidenceAssessment(
        expected if valid else "unit",
        valid,
        reasons or ["current-run provenance and semantic markers verified"],
        str(path) if path else None,
        _sha256(path) if path and path.is_file() else None,
    )


def _primary_evidence_path(tool_name: str, result: dict[str, Any], arguments: dict[str, Any]) -> str | None:
    if tool_name in {"verify_candidate.run", "verify.run_csim"}:
        csynth_path = (result.get("csynth") or {}).get("report_path")
        return csynth_path or (result.get("csim") or {}).get("log_path") or result.get("log_path")
    if "csim" in tool_name:
        return result.get("log_path") or (result.get("csim") or {}).get("log_path")
    if "csynth" in tool_name or tool_name in {"vivado.parse_report", "vivado.parse_csynth_report"}:
        return result.get("report_path") or (result.get("csynth") or {}).get("report_path") or arguments.get("report_path")
    if "cosim" in tool_name:
        return result.get("report_path") or result.get("log_path")
    return None


def _expected_class(tool_name: str) -> str:
    if "cosim" in tool_name:
        return "rtl_cosim"
    if tool_name == "verify_candidate.run":
        return "real_csynth"
    if "csim" in tool_name or tool_name == "verify.run_csim":
        return "real_csim"
    if "csynth" in tool_name or tool_name in {"vivado.parse_report", "vivado.parse_csynth_report"}:
        return "real_csynth"
    return "unit"


def _resolve_path(value: Any, context: dict[str, Any]) -> Path:
    path = Path(str(value))
    if path.is_absolute():
        return path.resolve()
    workspace = getattr(context.get("config"), "workspace_root", None)
    return (Path(workspace or Path.cwd()) / path).resolve()


def _is_fixture(path: Path) -> bool:
    normalized = str(path).replace("\\", "/").lower()
    return "/tests/fixtures/" in normalized or normalized.endswith("/tests/fixtures")


def _content_checks(evidence_class: str, path: Path, result: dict[str, Any]) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    lowered = text.lower()
    reasons: list[str] = []
    if evidence_class == "real_csim":
        marker = "golden_check_passed" in lowered or "csim done with 0 errors" in lowered
        structured = (result.get("verification") or result.get("csim") or {}).get("passed") is True
        if not marker and not structured:
            reasons.append("missing independent CSim golden-pass marker")
        if any(token in lowered for token in ("csim_design failed", "golden_check_failed", "compiler error")):
            reasons.append("failure marker exists in CSim log")
    elif evidence_class == "real_csynth":
        required = ("latency", "interval", "utilization estimates", "timing")
        if path.suffix.lower() == ".json":
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                payload = {}
            if not all(isinstance(payload.get(key), dict) for key in ("latency", "resources", "timing")):
                reasons.append("missing parsed latency/resources/timing sections")
        elif not all(token in lowered for token in required):
            reasons.append("missing latency/II/resource/timing report sections")
        if "synthesis failed" in lowered or "unexpected exception occurred" in lowered:
            reasons.append("failure marker exists in synthesis report")
    return reasons
