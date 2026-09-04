from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from ..adapters.vivado_hls_adapter import VivadoHLSAdapter
from ..core.errors import build_error, error_result


MOCK_REPORT = """== Utilization Estimates
Latency (cycles): min = 45, max = 45
Interval (cycles): min = 1, max = 1
BRAM_18K = 0
DSP48E = 32
FF = 2100
LUT = 3500
Timing (ns): Target = 5.00, Estimated = 4.30
"""


def _use_mock_verification(arguments: dict[str, Any], context: dict[str, Any]) -> bool:
    requested = arguments.get("mode") or context.get("verification_mode") or os.environ.get("DL_OP_TO_HLS_VERIFY_MODE")
    if requested:
        return str(requested).lower() in {"mock", "demo", "fixture"}
    config = context.get("config")
    if config is not None and hasattr(config, "mock_vivado"):
        return bool(config.mock_vivado)
    return os.environ.get("DL_OP_TO_HLS_MOCK_VIVADO", "1") != "0"


def _find_testbench(candidate_dir: Path) -> Path | None:
    patterns = ["testbench.cpp", "*testbench*.cpp", "tb_*.cpp", "*_tb.cpp"]
    for pattern in patterns:
        for candidate in sorted(candidate_dir.glob(pattern)):
            if candidate.is_file():
                return candidate
    return None


def _candidate_failed(message: str, *, source: str = "verify_candidate", details: dict[str, Any] | None = None) -> dict[str, Any]:
    return error_result(
        build_error(
            "VerificationFailedError",
            message,
            recoverable=True,
            source=source,
            suggested_action="Provide a real candidate directory with design C++, header, testbench, and reference checks before marking it verified.",
            details=details,
        ),
        status="failed",
    )


def _record_composite_phase(
    context: dict[str, Any],
    *,
    phase: str,
    capability: str,
    status: str,
    artifact_path: str | None = None,
) -> None:
    hooks = context.get("hooks")
    if hooks is None:
        return
    hooks.emit(
        "CompositeToolPhaseObserved",
        {
            "run_id": context.get("run_id"),
            "composite_tool": "verify_candidate.run",
            "phase": phase,
            "capability": capability,
            "status": status,
            "artifact_path": artifact_path,
        },
    )


def validate_candidate_contract(candidate_dir: Path, contract: dict[str, Any] | None) -> dict[str, Any]:
    contract = contract or {}
    missing: list[str] = []
    for raw_path in contract.get("required_files", []):
        relative = Path(str(raw_path))
        if relative.parts and relative.parts[0].lower() == "candidate":
            relative = Path(*relative.parts[1:])
        if not (candidate_dir / relative).is_file():
            missing.append(str(raw_path))
    if missing:
        return _candidate_failed(
            "Candidate contract required files are missing.",
            details={"candidate_dir": str(candidate_dir), "missing_files": missing},
        )

    signature = str(contract.get("signature") or "").strip()
    expected_top = str(contract.get("top_function") or "").strip()
    if signature and not expected_top:
        match = re.search(r"([A-Za-z_]\w*)\s*\(", signature)
        expected_top = match.group(1) if match else ""
    if expected_top:
        source_text = "\n".join(
            path.read_text(encoding="utf-8", errors="ignore")
            for pattern in ("*.h", "*.hpp", "*.cpp", "*.cc")
            for path in sorted(candidate_dir.glob(pattern))
            if path.is_file()
        )
        if not re.search(rf"\b{re.escape(expected_top)}\s*\(", source_text):
            return _candidate_failed(
                "Candidate top-function signature does not match the task contract.",
                details={
                    "candidate_dir": str(candidate_dir),
                    "expected_top_function": expected_top,
                    "expected_signature": signature or None,
                },
            )
    return {"status": "valid"}


def _mock_verify(candidate_dir: Path, report_dir: Path, context: dict[str, Any]) -> dict[str, Any]:
    report_path = report_dir / f"{candidate_dir.name}_csynth.rpt"
    report_path.write_text(MOCK_REPORT, encoding="utf-8")
    artifact_manager = context.get("artifact_manager")
    if artifact_manager:
        artifact_manager.register_file(report_path, "vivado_report")
    return {
        "status": "verified",
        "mode": "mock",
        "csim": {"status": "passed", "max_abs_error": 0.0},
        "csynth": {"status": "passed", "report_path": str(report_path)},
    }


def _real_verify(candidate_dir: Path, report_dir: Path, arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    if not candidate_dir.exists() or not candidate_dir.is_dir():
        return _candidate_failed("Candidate directory does not exist.", details={"candidate_dir": str(candidate_dir)})

    contract_result = validate_candidate_contract(candidate_dir, arguments.get("candidate_contract"))
    if contract_result.get("status") != "valid":
        return contract_result

    testbench = Path(arguments["testbench_path"]) if arguments.get("testbench_path") else _find_testbench(candidate_dir)
    if testbench is None or not testbench.exists():
        return _candidate_failed(
            "Real candidate verification requires a testbench; no testbench file was found.",
            details={"candidate_dir": str(candidate_dir)},
        )

    adapter = context.get("vivado_adapter")
    if adapter is None or getattr(adapter, "mock_mode", False):
        config = context.get("config")
        adapter = VivadoHLSAdapter(
            mock_mode=False,
            vivado_hls_path=getattr(config, "vivado_hls_path", None) or os.environ.get("DL_OP_TO_HLS_VIVADO_HLS_PATH"),
        )

    work_dir = Path(arguments.get("work_dir") or report_dir / f"{candidate_dir.name}_verify_vivado")
    create_result = adapter.create_project(
        {
            "hls_project_dir": str(candidate_dir),
            "work_dir": str(work_dir),
            "top_function": arguments.get("top_function"),
            "part": arguments.get("part", "xc7z020clg400-1"),
            "clock_period": arguments.get("clock_period", 5),
        }
    )
    _record_composite_phase(
        context,
        phase="project_creation",
        capability="vivado.create_project",
        status=str(create_result.get("status") or "error"),
        artifact_path=create_result.get("tcl_path"),
    )
    if create_result.get("status") != "success":
        error = create_result.get("error") or build_error(
            "VerificationFailedError",
            "Vivado project creation failed during candidate verification.",
            recoverable=True,
            source="verify_candidate",
            details={"result": create_result},
        ).to_dict()
        return {"status": "failed", "error": error}

    synth_result = adapter.run_csynth(
        {
            "work_dir": create_result["work_dir"],
            "tcl_path": create_result["tcl_path"],
            "top_function": create_result.get("top_function") or arguments.get("top_function"),
        }
    )
    verification = synth_result.get("verification") if isinstance(synth_result.get("verification"), dict) else {}
    _record_composite_phase(
        context,
        phase="golden_csim",
        capability="vivado.run_csim",
        status="success" if verification.get("passed") is True else str(verification.get("status") or "not_run"),
        artifact_path=verification.get("log_path") or synth_result.get("log_path"),
    )
    _record_composite_phase(
        context,
        phase="csynth",
        capability="vivado.run_csynth",
        status=str(synth_result.get("status") or "error"),
        artifact_path=synth_result.get("report_path"),
    )
    if synth_result.get("status") != "success":
        error = synth_result.get("error") or build_error(
            "VerificationFailedError",
            "Real candidate verification did not complete Vivado HLS csim/csynth successfully.",
            recoverable=True,
            source="verify_candidate",
            details={"result": synth_result},
        ).to_dict()
        return {"status": "failed", "error": error}

    report_path = synth_result.get("report_path")
    if not report_path:
        return _candidate_failed(
            "Vivado HLS completed but did not produce a csynth report.",
            details={"work_dir": create_result["work_dir"]},
        )

    parsed_report = adapter.parse_report({"report_path": report_path})
    _record_composite_phase(
        context,
        phase="report_parse",
        capability="vivado.parse_report",
        status=str(parsed_report.get("status") or "error"),
        artifact_path=report_path,
    )
    if parsed_report.get("status") != "success":
        error = parsed_report.get("error") or build_error(
            "ReportParseError",
            "Candidate verification report could not be parsed.",
            recoverable=True,
            source="verify_candidate",
            details={"report_path": report_path},
        ).to_dict()
        return {"status": "failed", "error": error}

    artifact_manager = context.get("artifact_manager")
    if artifact_manager and Path(report_path).exists():
        artifact_manager.register_file(report_path, "vivado_report")
    return {
        "status": "verified",
        "mode": "real",
        "csim": {"status": "passed_via_vivado_tcl", "log_path": synth_result.get("log_path")},
        "csynth": {"status": "passed", "report_path": report_path},
        "report": parsed_report,
        "executed_subactions": [
            {"capability": "vivado.create_project", "status": create_result.get("status")},
            {"capability": "vivado.run_csim", "status": verification.get("status")},
            {"capability": "vivado.run_csynth", "status": synth_result.get("status")},
            {"capability": "vivado.parse_report", "status": parsed_report.get("status")},
        ],
    }


def verify_candidate(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    candidate_dir = Path(arguments["candidate_dir"])
    report_dir = Path(arguments["report_dir"])
    report_dir.mkdir(parents=True, exist_ok=True)
    force_fail = bool(arguments.get("force_fail"))
    if force_fail:
        return error_result(
            build_error(
                "VerificationFailedError",
                "Candidate verification failed in mock flow.",
                recoverable=True,
                source="verify_candidate",
                suggested_action="Inspect candidate code and retry with a simpler operator contract.",
            ),
            status="failed",
        )
    if _use_mock_verification(arguments, context):
        return _mock_verify(candidate_dir, report_dir, context)
    return _real_verify(candidate_dir, report_dir, arguments, context)
