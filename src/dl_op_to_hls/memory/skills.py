"""memory layer implementation for skills.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations


def _verified(state: dict) -> bool:
    """Implement the internal _verified helper.

    Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

    Args:
        state: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    verification = state.get("verification") or {}
    mode = verification.get("mode")
    if verification.get("passed") is True and mode in {"golden_testbench", "hls4ml_reference_compare", "reference_compare"}:
        return True
    comparison = verification.get("comparison") if isinstance(verification.get("comparison"), dict) else {}
    return verification.get("passed") is True and comparison.get("passed") is True


def build_skill_candidates(state: dict) -> list[dict]:
    """Execute build_skill_candidates at the skills boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Args:
        state: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    skills: list[dict] = []
    selected_path = state.get("selected_path")
    verified = _verified(state)
    if selected_path == "fallback_template_path" and verified:
        skills.append(
            {
                "kind": "skill",
                "key": "skill.fallback_template_skill",
                "name": "fallback_template_skill",
                "description": "Generate fallback HLS code when hls4ml support is unavailable or not suitable.",
                "steps": [
                    "Check hls4ml support.",
                    "Generate fallback HLS template.",
                    "Create Vivado HLS project.",
                    "Run synthesis or gracefully skip with VivadoNotFoundError if Vivado is unavailable.",
                ],
                "trigger_conditions": {"selected_path": "fallback_template_path"},
                "success_criteria": {"generated_hls_project": True},
            }
        )
    if state.get("report") and verified:
        skills.append(
            {
                "kind": "skill",
                "key": "skill.vivado_synthesis_skill",
                "name": "vivado_synthesis_skill",
                "description": "Create a Vivado project, run csynth, and parse the report.",
                "steps": [
                    "Create Vivado HLS project TCL.",
                    "Run csynth, or mark skipped synthesis with partial_success on VivadoNotFoundError.",
                    "Parse report.",
                    "Record metrics and suggestions.",
                ],
                "trigger_conditions": {"needs_report": True},
                "success_criteria": {"report_available": True},
            }
        )
    if selected_path == "hls4ml_path" and verified:
        skills.append(
            {
                "kind": "skill",
                "key": "skill.hls4ml_path_skill",
                "name": "hls4ml_path_skill",
                "description": "Inspect, configure, and convert a supported model with hls4ml.",
                "steps": [
                    "Inspect model structure.",
                    "Check support.",
                    "Generate hls4ml config.",
                    "Convert to HLS project.",
                ],
                "trigger_conditions": {"selected_path": "hls4ml_path"},
                "success_criteria": {"hls_project_generated": True},
            }
        )
    if selected_path == "unsupported_path":
        skills.append(
            {
                "kind": "skill",
                "key": "skill.unsupported_operator_skill",
                "name": "unsupported_operator_skill",
                "description": "Emit an actionable unsupported report when no safe path is available.",
                "steps": [
                    "Record unsupported reason.",
                    "Suggest rewrite/custom layer/fallback/reference implementation.",
                    "Persist unsupported report artifact.",
                ],
                "trigger_conditions": {"selected_path": "unsupported_path"},
                "success_criteria": {"unsupported_report_written": True},
            }
        )
    return skills
