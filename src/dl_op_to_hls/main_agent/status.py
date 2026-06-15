from __future__ import annotations

from typing import Any


VERIFIED_MODES = {"golden_testbench", "hls4ml_reference_compare", "reference_compare"}


def is_functionally_verified(verification: dict[str, Any] | None) -> bool:
    if not isinstance(verification, dict):
        return False
    mode = verification.get("mode")
    if verification.get("passed") is True and mode in VERIFIED_MODES:
        return True
    comparison = verification.get("comparison") if isinstance(verification.get("comparison"), dict) else {}
    return verification.get("passed") is True and comparison.get("passed") is True


def compute_pipeline_status(state: Any) -> dict[str, Any]:
    task = getattr(state, "task", {}) or {}
    report = getattr(state, "report", None) or {}
    verification = getattr(state, "verification", None) or {}
    selected_path = getattr(state, "selected_path", None)
    hls_project_dir = getattr(state, "hls_project_dir", None)
    errors = getattr(state, "errors", []) or []
    timing = report.get("timing") if isinstance(report, dict) else {}
    synthesis_success = isinstance(report, dict) and report.get("status") == "success"
    conversion_success = bool(
        hls_project_dir
        or selected_path
        in {
            "fallback_template_path",
            "hls4ml_path",
            "existing_hls_project_path",
            "llm_candidate_path",
        }
    )
    functional_verified = is_functionally_verified(verification)
    timing_met = None if not isinstance(timing, dict) else timing.get("met")
    deployment_ready_candidate = bool(
        conversion_success
        and synthesis_success
        and functional_verified
        and timing_met is not False
        and not errors
        and selected_path != "unsupported_path"
    )
    if deployment_ready_candidate:
        level = "deployment_ready_candidate"
    elif functional_verified:
        level = "functional_verified"
    elif synthesis_success:
        level = "synthesis_success"
    elif conversion_success:
        level = "conversion_success"
    elif selected_path == "unsupported_path":
        level = "unsupported"
    else:
        level = "initialized"
    return {
        "level": level,
        "conversion_success": conversion_success,
        "synthesis_success": synthesis_success,
        "functional_verified": functional_verified,
        "deployment_ready_candidate": deployment_ready_candidate,
        "timing_met": timing_met,
        "verification_mode": verification.get("mode") if isinstance(verification, dict) else None,
        "verification_status": verification.get("status") if isinstance(verification, dict) else None,
        "selected_path": selected_path,
        "task_type": task.get("task_type"),
    }
