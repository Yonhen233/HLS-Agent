from __future__ import annotations

from pathlib import Path
from typing import Any

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
    report_path = report_dir / f"{candidate_dir.name}_csynth.rpt"
    report_path.write_text(MOCK_REPORT, encoding="utf-8")
    artifact_manager = context.get("artifact_manager")
    if artifact_manager:
        artifact_manager.register_file(report_path, "vivado_report")
    return {
        "status": "verified",
        "csim": {"status": "passed", "max_abs_error": 0.0},
        "csynth": {"status": "passed", "report_path": str(report_path)},
    }

