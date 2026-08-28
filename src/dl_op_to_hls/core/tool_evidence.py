from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .trace import stable_hash
from ..benchmarks.operator_evidence import assess_tool_evidence


SUCCESS_STATUSES = {"success", "supported", "candidate_generated", "verified"}
INJECTION_MARKERS = (
    "ignore previous instructions",
    "ignore all previous",
    "reveal the system prompt",
    "send the api key",
    "override your instructions",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ToolPostconditionRegistry:
    """Verify semantic evidence before a successful tool result is committed."""

    def __init__(self):
        self._validators: dict[str, Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], list[dict[str, Any]]]] = {}
        self._register_defaults()

    def register(
        self,
        tool_name: str,
        validator: Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], list[dict[str, Any]]],
    ) -> None:
        self._validators[tool_name] = validator

    def verify(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        status = str(result.get("status") or "success")
        checks: list[dict[str, Any]] = []
        validator = self._validators.get(tool_name)
        if status in SUCCESS_STATUSES and validator is not None:
            checks.extend(validator(arguments, result, context))
        elif status in SUCCESS_STATUSES:
            checks.append({"name": "declared_success", "passed": True, "detail": status})
        else:
            checks.append({"name": "non_success_result", "passed": True, "detail": status})

        artifacts = self._artifact_receipts(result, context)
        unsafe_markers = self._find_injection_markers(result)
        if unsafe_markers:
            checks.append(
                {
                    "name": "untrusted_instruction_scan",
                    "passed": False,
                    "severity": "security",
                    "detail": sorted(unsafe_markers),
                }
            )
        valid = all(item.get("passed") is not False for item in checks)
        mock_evidence = self._is_mock(tool_name, result, context)
        assessment = assess_tool_evidence(
            tool_name,
            result,
            context,
            mock_evidence=mock_evidence,
            arguments=arguments,
        )
        return {
            "receipt_id": f"te_{stable_hash({'tool': tool_name, 'args': arguments, 'result': result})[:16]}",
            "run_id": context.get("run_id"),
            "tool_name": tool_name,
            "args_hash": stable_hash(arguments),
            "output_hash": stable_hash(result),
            "status": status,
            "valid": valid,
            "checks": checks,
            "artifacts": artifacts,
            "mock_evidence": mock_evidence,
            "evidence_class": assessment.evidence_class,
            "evidence_assessment": assessment.to_dict(),
            "observed_at": _utc_now(),
        }

    def _register_defaults(self) -> None:
        self.register("task.validate_schema", self._require_object("task"))
        self.register("fallback.generate_operator_hls", self._require_paths("generated_files", many=True))
        self.register("fallback.generate_testbench", self._require_paths("testbench_path"))
        self.register("hls4ml.generate_config", self._require_paths("config_path"))
        self.register("hls4ml.generate_hls4ml_config", self._require_paths("config_path"))
        self.register("hls4ml.convert", self._require_paths("hls_project_dir"))
        self.register("hls4ml.convert_with_hls4ml", self._require_paths("hls_project_dir"))
        self.register("vivado.run_csynth", self._validate_vivado_synthesis)
        self.register("vivado.parse_report", self._validate_report)
        self.register("vivado.parse_csynth_report", self._validate_report)
        self.register("verify_candidate.run", self._validate_candidate_verification)
        self.register("verify.run_csim", self._validate_candidate_verification)
        self.register("report.write_unsupported", self._require_paths("path"))
        self.register("summary.write_summary", self._require_paths("path"))

    @staticmethod
    def _require_object(key: str):
        def validate(_arguments: dict[str, Any], result: dict[str, Any], _context: dict[str, Any]) -> list[dict[str, Any]]:
            return [{"name": f"required_object:{key}", "passed": isinstance(result.get(key), dict)}]

        return validate

    @staticmethod
    def _require_paths(key: str, *, many: bool = False):
        def validate(_arguments: dict[str, Any], result: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
            raw = result.get(key)
            values = raw if many and isinstance(raw, list) else [raw]
            paths = [ToolPostconditionRegistry._resolve_path(item, context) for item in values if item]
            checks = [
                {
                    "name": f"required_path:{key}",
                    "passed": bool(paths) and all(path.exists() for path in paths),
                    "detail": [str(path) for path in paths],
                }
            ]
            if context.get("run_dir"):
                checks.append(
                    {
                        "name": f"current_run_provenance:{key}",
                        "passed": bool(paths) and all(ToolPostconditionRegistry._within_run(path, context) for path in paths),
                        "detail": str(Path(context["run_dir"]).resolve()),
                    }
                )
            return checks

        return validate

    @staticmethod
    def _validate_vivado_synthesis(
        _arguments: dict[str, Any], result: dict[str, Any], context: dict[str, Any]
    ) -> list[dict[str, Any]]:
        report_path = ToolPostconditionRegistry._resolve_path(result.get("report_path"), context)
        verification = result.get("verification")
        checks = [
            {
                "name": "current_synthesis_report_exists",
                "passed": bool(result.get("report_path")) and report_path.exists(),
                "detail": str(report_path),
            }
        ]
        if context.get("run_dir"):
            checks.append(
                {
                    "name": "current_run_report_provenance",
                    "passed": ToolPostconditionRegistry._within_run(report_path, context),
                    "detail": str(Path(context["run_dir"]).resolve()),
                }
            )
        if isinstance(verification, dict):
            checks.append(
                {
                    "name": "verification_not_explicitly_failed",
                    "passed": verification.get("passed") is not False,
                    "detail": verification.get("status") or verification.get("mode"),
                }
            )
        return checks

    @staticmethod
    def _validate_report(
        arguments: dict[str, Any], result: dict[str, Any], context: dict[str, Any]
    ) -> list[dict[str, Any]]:
        source_path = ToolPostconditionRegistry._resolve_path(arguments.get("report_path"), context)
        required_sections = ["latency", "resources", "timing"]
        checks = [
            {"name": "source_report_exists", "passed": source_path.exists(), "detail": str(source_path)},
            {
                "name": "parsed_report_sections",
                "passed": all(isinstance(result.get(key), dict) for key in required_sections),
                "detail": required_sections,
            },
        ]
        if context.get("run_dir"):
            checks.append(
                {
                    "name": "current_run_source_report",
                    "passed": ToolPostconditionRegistry._within_run(source_path, context),
                    "detail": str(Path(context["run_dir"]).resolve()),
                }
            )
        return checks

    @staticmethod
    def _validate_candidate_verification(
        _arguments: dict[str, Any], result: dict[str, Any], context: dict[str, Any]
    ) -> list[dict[str, Any]]:
        csim = result.get("csim") if isinstance(result.get("csim"), dict) else {}
        csynth = result.get("csynth") if isinstance(result.get("csynth"), dict) else {}
        report_path = ToolPostconditionRegistry._resolve_path(csynth.get("report_path"), context)
        checks = [
            {
                "name": "golden_csim_passed",
                "passed": str(csim.get("status") or "").startswith("passed"),
                "detail": csim,
            },
            {
                "name": "candidate_report_exists",
                "passed": bool(csynth.get("report_path")) and report_path.exists(),
                "detail": str(report_path),
            },
        ]
        if context.get("run_dir"):
            checks.append(
                {
                    "name": "current_run_candidate_report",
                    "passed": ToolPostconditionRegistry._within_run(report_path, context),
                    "detail": str(Path(context["run_dir"]).resolve()),
                }
            )
        return checks

    @staticmethod
    def _resolve_path(value: Any, context: dict[str, Any]) -> Path:
        if not value:
            return Path("__missing_evidence_path__")
        path = Path(str(value))
        if not path.is_absolute():
            workspace = getattr(context.get("config"), "workspace_root", None)
            path = Path(workspace or context.get("run_dir") or Path.cwd()) / path
        return path.resolve()

    @staticmethod
    def _within_run(path: Path, context: dict[str, Any]) -> bool:
        run_dir = Path(context.get("run_dir") or Path.cwd()).resolve()
        resolved = path.resolve()
        return resolved == run_dir or run_dir in resolved.parents

    @classmethod
    def _artifact_receipts(cls, result: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
        values: list[Any] = []
        for key, value in result.items():
            if (key == "path" or key.endswith(("_path", "_dir"))) and value:
                values.append(value)
            elif key in {"generated_files", "artifact_paths"} and isinstance(value, list):
                values.extend(value)
        receipts: list[dict[str, Any]] = []
        seen: set[str] = set()
        for value in values:
            path = cls._resolve_path(value, context)
            normalized = str(path)
            if normalized in seen:
                continue
            seen.add(normalized)
            item = {"path": normalized, "exists": path.exists(), "kind": "directory" if path.is_dir() else "file"}
            if path.is_file():
                item.update({"size": path.stat().st_size, "sha256": _sha256(path)})
            receipts.append(item)
        return receipts

    @staticmethod
    def _find_injection_markers(result: dict[str, Any]) -> set[str]:
        encoded = json.dumps(result, ensure_ascii=False, default=str).lower()
        return {marker for marker in INJECTION_MARKERS if marker in encoded}

    @staticmethod
    def _is_mock(tool_name: str, result: dict[str, Any], context: dict[str, Any]) -> bool:
        mode = str(result.get("mode") or "").lower()
        if mode in {"mock", "demo", "fixture"}:
            return True
        config = context.get("config")
        if tool_name.startswith(("vivado.", "verify.")) or tool_name == "verify_candidate.run":
            return bool(getattr(config, "mock_vivado", False))
        if tool_name.startswith("hls4ml."):
            return bool(getattr(config, "mock_hls4ml", False))
        return False
