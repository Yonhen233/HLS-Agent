from __future__ import annotations


def build_skill_candidates(state: dict) -> list[dict]:
    skills: list[dict] = []
    selected_path = state.get("selected_path")
    if selected_path == "fallback_template_path":
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
                    "Run synthesis or gracefully skip if Vivado is unavailable.",
                ],
                "trigger_conditions": {"selected_path": "fallback_template_path"},
                "success_criteria": {"generated_hls_project": True},
            }
        )
    if state.get("report"):
        skills.append(
            {
                "kind": "skill",
                "key": "skill.vivado_synthesis_skill",
                "name": "vivado_synthesis_skill",
                "description": "Create a Vivado project, run csynth, and parse the report.",
                "steps": [
                    "Create Vivado HLS project TCL.",
                    "Run csynth.",
                    "Parse report.",
                    "Record metrics and suggestions.",
                ],
                "trigger_conditions": {"needs_report": True},
                "success_criteria": {"report_available": True},
            }
        )
    if selected_path == "hls4ml_path":
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

