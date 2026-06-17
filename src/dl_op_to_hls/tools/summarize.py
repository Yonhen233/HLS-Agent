from __future__ import annotations

import json
from typing import Any


def _error_lines(errors: list[dict] | list[str]) -> str:
    if not errors:
        return "- None"
    normalized = []
    for item in errors:
        if isinstance(item, dict):
            normalized.append(f"- {item.get('error_type', 'Error')}: {item.get('message', '')}")
        else:
            normalized.append(f"- {item}")
    return "\n".join(normalized)


def _todo_table(state: dict[str, Any]) -> str:
    rows = ["| ID | Title | Status | Tool | Notes |", "|---|---|---|---|---|"]
    for item in state.get("todos", []):
        outputs = item.get("outputs") or {}
        error = item.get("error") or {}
        note = outputs.get("summary") or outputs.get("note") or error.get("message") or "OK"
        rows.append(
            f"| {item.get('id')} | {item.get('title')} | {item.get('status')} | {item.get('assigned_tool')} | {str(note).replace('|', '/')} |"
        )
    return "\n".join(rows)


def _memory_section(state: dict[str, Any]) -> str:
    retrieved = state.get("retrieved_memories", [])[:5]
    short_term = state.get("short_term_memory", {})
    promoted = state.get("promoted_memories", [])
    skills_used = []
    selected_path = state.get("selected_path")
    if selected_path == "fallback_template_path":
        skills_used.append("fallback_template_skill")
    if state.get("vivado_work_dir") or state.get("report"):
        skills_used.append("vivado_synthesis_skill")
    if selected_path == "hls4ml_path":
        skills_used.append("hls4ml_path_skill")
    if selected_path == "unsupported_path":
        skills_used.append("unsupported_operator_skill")

    retrieved_lines = "\n".join(f"- {item.get('text', '')[:160]}" for item in retrieved) or "- None"
    short_term_lines = "\n".join(f"- {key}: {value.get('summary', value.get('status', ''))}" for key, value in short_term.items()) or "- None"
    promoted_lines = "\n".join(
        f"- {item.get('memory_type')}: {item.get('summary') or item.get('key', '')}" for item in promoted
    ) or "- None"
    skills_lines = "\n".join(f"- {name}" for name in skills_used) or "- None"
    return (
        "## Memory Summary\n\n"
        "### Retrieved Memories\n"
        f"{retrieved_lines}\n\n"
        "### Short-term Memory Created\n"
        f"{short_term_lines}\n\n"
        "### Long-term Memories Promoted\n"
        f"{promoted_lines}\n\n"
        "### Skills Used\n"
        f"{skills_lines}\n"
    )


def _specialist_section(state: dict[str, Any]) -> str:
    rows = ["| Todo | Specialist | Status | Context Compression | Notes |", "|---|---|---|---|---|"]
    found = False
    for item in state.get("todos", []):
        result = item.get("specialist_result")
        if not result:
            continue
        found = True
        usage = result.get("context_usage") or {}
        ratio = usage.get("compression_ratio")
        ratio_text = f"{ratio:.3f}" if isinstance(ratio, (int, float)) else "n/a"
        rows.append(
            "| {todo} | {specialist} | {status} | {ratio} | {notes} |".format(
                todo=item.get("id"),
                specialist=result.get("specialist_name"),
                status=result.get("status"),
                ratio=ratio_text,
                notes=str(result.get("summary", "")).replace("|", "/"),
            )
        )
    if not found:
        rows.append("| None | None | n/a | n/a | No specialist was selected for this run. |")
    return "## Specialist Execution Summary\n\n" + "\n".join(rows)


def _functional_verification_section(state: dict[str, Any]) -> str:
    verification = state.get("verification") or {}
    if not verification:
        return (
            "## Functional Verification\n\n"
            "- Status: not_run\n"
            "- Reason: No functional verification result was recorded.\n"
        )
    comparison = verification.get("comparison") or {}
    lines = [
        "## Functional Verification",
        "",
        f"- Status: {verification.get('status')}",
        f"- Passed: {verification.get('passed')}",
        f"- Mode: {verification.get('mode')}",
        f"- CSim executed: {verification.get('csim_executed')}",
    ]
    if comparison:
        lines.extend(
            [
                f"- Samples: {comparison.get('sample_count')}",
                f"- Max abs error: {comparison.get('max_abs_error')}",
                f"- Max rel error: {comparison.get('max_rel_error')}",
                f"- Tolerance: {comparison.get('tolerance')}",
            ]
        )
    classification = verification.get("classification")
    if not classification and comparison:
        classification = comparison.get("classification")
    if classification:
        lines.extend(
            [
                f"- Recognition samples: {classification.get('sample_count')}",
                f"- Python/ONNX reference accuracy: {classification.get('reference_accuracy')}",
                f"- HLS csim accuracy: {classification.get('hls_accuracy')}",
                f"- HLS vs reference argmax match rate: {classification.get('argmax_match_rate')}",
                f"- HLS correct predictions: {classification.get('hls_correct')}",
            ]
        )
    if verification.get("log_path"):
        lines.append(f"- CSim log: {verification.get('log_path')}")
    if verification.get("reference_path"):
        lines.append(f"- Reference output: {verification.get('reference_path')}")
    if verification.get("output_path"):
        lines.append(f"- CSim output: {verification.get('output_path')}")
    if verification.get("reason"):
        lines.append(f"- Reason: {verification.get('reason')}")
    return "\n".join(lines) + "\n"


def _pipeline_status_section(state: dict[str, Any]) -> str:
    pipeline = state.get("pipeline_status") or {}
    if not pipeline:
        return "## Pipeline Status\n\n- Status level: unknown\n"
    return (
        "## Pipeline Status\n\n"
        f"- Status level: {pipeline.get('level')}\n"
        f"- Conversion success: {pipeline.get('conversion_success')}\n"
        f"- Synthesis success: {pipeline.get('synthesis_success')}\n"
        f"- Functional verified: {pipeline.get('functional_verified')}\n"
        f"- Deployment-ready candidate: {pipeline.get('deployment_ready_candidate')}\n"
        f"- Timing met: {pipeline.get('timing_met')}\n"
    )


def _parameter_advice_section(state: dict[str, Any]) -> str:
    advice = state.get("parameter_advice") or {}
    if not advice:
        return "## Parameter Advisor\n\n- Status: not_run\n"
    lines = [
        "## Parameter Advisor",
        "",
        f"- Status: {advice.get('status')}",
        f"- Mode: {advice.get('mode')}",
        f"- Confidence: {advice.get('confidence')}",
        f"- Verified sources: {advice.get('source_count')}",
    ]
    if advice.get("reason"):
        lines.append(f"- Reason: {advice.get('reason')}")
    if advice.get("applied_updates"):
        lines.append(f"- Applied updates: {advice.get('applied_updates')}")
    if advice.get("proposed_updates"):
        lines.append(f"- Proposed updates: {advice.get('proposed_updates')}")
    recommendations = advice.get("recommendations") or []
    if recommendations:
        lines.append("")
        lines.append("| Parameter | Recommended Value | Reason |")
        lines.append("|---|---|---|")
        for item in recommendations:
            lines.append(
                "| {parameter} | {value} | {reason} |".format(
                    parameter=item.get("parameter"),
                    value=item.get("recommended_value"),
                    reason=str(item.get("reason", "")).replace("|", "/"),
                )
            )
    return "\n".join(lines) + "\n"


def _context_isolation_section(state: dict[str, Any]) -> str:
    run_id = state.get("run_id")
    return (
        "## Context Isolation\n\n"
        "- Main Agent did not ingest raw Vivado logs, raw csynth reports, full HLS code, or full trace content.\n"
        f"- Raw artifacts were stored under runs/{run_id}/ and referenced by path in ContextEnvelope objects.\n"
        "- Specialists returned compressed SpecialistResult objects with summaries, metrics, artifact refs, and context_usage.\n"
    )


def _llm_section(state: dict[str, Any]) -> str:
    selected_skill = state.get("selected_skill")
    usage = state.get("skill_usage_mode")
    decisions = state.get("llm_decisions", [])
    if not selected_skill and not decisions:
        return ""
    lines = [
        "## LLM Decisions",
        "",
        f"- Selected skill: {selected_skill or 'n/a'}",
        f"- Skill usage mode: {usage or 'n/a'}",
    ]
    if decisions:
        lines.append("- Decision traces:")
        for item in decisions[:12]:
            phase = item.get("phase", "unknown")
            todo_id = item.get("todo_id")
            decision = item.get("decision")
            reason = item.get("reason_summary", "")
            prefix = f"{phase}:{todo_id}" if todo_id else phase
            lines.append(f"  - {prefix} -> {decision}; {reason}")
    return "\n".join(lines) + "\n"


def write_summary(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    state = arguments["state"]
    report = state.get("report") or {}
    hls4ml_support = state.get("hls4ml_support") or {}
    latency = report.get("latency", {})
    interval = report.get("interval", {})
    resources = report.get("resources", {})
    timing = report.get("timing", {})
    suggestions = state.get("suggestions", [])
    markdown = (
        "# Run Summary\n\n"
        "## Task\n"
        f"- Task type: {state['task'].get('task_type')}\n"
        f"- Name: {state['task'].get('name')}\n"
        f"- Objective: {state.get('objective')}\n\n"
        "## Selected Path\n"
        f"- {state.get('selected_path')}\n\n"
        "## hls4ml Support\n"
        f"- Supported: {hls4ml_support.get('status')}\n"
        f"- Unsupported layers: {hls4ml_support.get('unsupported_layers', [])}\n"
        f"- Recommendation: {hls4ml_support.get('recommendation')}\n\n"
        "## Artifacts\n"
        f"- HLS project: {state.get('hls_project_dir')}\n"
        f"- Vivado work dir: {state.get('vivado_work_dir')}\n"
        f"- Report: {state.get('artifacts', {}).get('report_json')}\n"
        f"- Trace: {state.get('artifacts', {}).get('trace')}\n\n"
        "## Synthesis Result\n"
        f"- Latency min/max: {latency.get('min_cycles')} / {latency.get('max_cycles')}\n"
        f"- II min/max: {interval.get('min_ii')} / {interval.get('max_ii')}\n"
        f"- DSP: {resources.get('dsp')}\n"
        f"- BRAM: {resources.get('bram')}\n"
        f"- LUT: {resources.get('lut')}\n"
        f"- FF: {resources.get('ff')}\n"
        f"- Timing met: {timing.get('met')}\n\n"
        f"{_pipeline_status_section(state)}\n"
        f"{_functional_verification_section(state)}\n"
        "## Errors / Warnings\n"
        f"{_error_lines(state.get('errors', []))}\n\n"
        "## Todo Execution Summary\n\n"
        f"{_todo_table(state)}\n\n"
        f"{_specialist_section(state)}\n\n"
        f"{_context_isolation_section(state)}\n"
        f"{_memory_section(state)}\n"
        f"{_parameter_advice_section(state)}\n"
        f"{_llm_section(state)}\n"
        "\n## Suggestions\n"
        + ("\n".join(f"- {item}" for item in suggestions) if suggestions else "- None")
        + "\n"
    )
    artifact_manager = context.get("artifact_manager")
    path = None
    if artifact_manager:
        path = artifact_manager.write_text("summary.md", markdown, "summary")
    return {"status": "success", "markdown": markdown, "path": str(path) if path else None}
