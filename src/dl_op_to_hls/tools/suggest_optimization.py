from __future__ import annotations

import os
from typing import Any

from ..core.errors import build_error, error_result
from ..llm.optimizer import LLMOptimizationEngine


def _report_value(report: dict[str, Any], group: str, key: str) -> Any:
    return (report.get(group) or {}).get(key)


def build_suggestions(report: dict[str, Any], rag_context: list[dict], objective: str | None) -> list[str]:
    objective_name = objective or "latency"
    suggestions: list[str] = []
    ii = _report_value(report, "interval", "max_ii")
    dsp = _report_value(report, "resources", "dsp")
    lut = _report_value(report, "resources", "lut")
    bram = _report_value(report, "resources", "bram")
    timing_met = _report_value(report, "timing", "met")

    if objective_name == "latency":
        if ii and ii > 1:
            suggestions.append("II still exceeds 1; inspect loop-carried dependencies and add array partition/pipeline directives.")
        else:
            suggestions.append("Current path is already close to latency-oriented tuning; keep II at 1 before exploring more parallelism.")
        if timing_met and dsp is not None and dsp < 128:
            suggestions.append("Timing meets target and DSP usage is moderate; try more parallelism or lower reuse_factor for lower latency.")
    else:
        if dsp is not None and dsp > 16:
            suggestions.append("DSP usage is relatively high; try increasing reuse_factor from 1 to 2 or 4.")
        if lut is not None and lut > 4000:
            suggestions.append("LUT pressure is noticeable; reduce unroll/partition aggressiveness and simplify interfaces.")
        if bram is not None and bram > 0:
            suggestions.append("BRAM usage is non-zero; consider lowering precision or packing weights more compactly.")

    if timing_met is False:
        suggestions.append("Timing is not met; relax clock period or reduce parallelism before further optimization.")
    if not suggestions:
        suggestions.append("No strong issue stands out from the current report; compare reuse_factor and precision sweeps next.")
    if rag_context:
        first = rag_context[0]
        summary = first.get("summary") or first.get("text", "")
        if summary:
            suggestions.append(f"Prior experience hint: {summary}")
    return suggestions


def render_suggestions_markdown(report: dict[str, Any], rag_context: list[dict], objective: str | None, suggestions: list[str]) -> str:
    latency = report.get("latency", {})
    interval = report.get("interval", {})
    resources = report.get("resources", {})
    timing = report.get("timing", {})
    history_lines = "\n".join(f"- {item.get('summary') or item.get('text', '')}" for item in rag_context[:3]) or "- None"
    suggestion_lines = "\n".join(f"{idx}. {item}" for idx, item in enumerate(suggestions, start=1))
    return (
        "# Optimization Suggestions\n\n"
        "## Current Result\n"
        f"- Objective: {objective or 'latency'}\n"
        f"- Latency: {latency.get('min_cycles')} / {latency.get('max_cycles')} cycles\n"
        f"- II: {interval.get('min_ii')} / {interval.get('max_ii')}\n"
        f"- DSP: {resources.get('dsp')}\n"
        f"- BRAM: {resources.get('bram')}\n"
        f"- LUT: {resources.get('lut')}\n"
        f"- FF: {resources.get('ff')}\n"
        f"- Timing met: {'yes' if timing.get('met') else 'no' if timing.get('met') is False else 'unknown'}\n\n"
        "## Prior Experience Hints\n"
        f"{history_lines}\n\n"
        "## Suggestions\n"
        f"{suggestion_lines}\n"
    )


def suggest_optimization(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    state = arguments["state"]
    report = arguments["report"]
    rag_context = arguments.get("rag_context", [])
    objective = arguments.get("objective") or state.get("objective")
    llm_client = context.get("llm_client")
    llm_result = None
    fallback_mode = (
        arguments.get("fallback_mode")
        or context.get("optimization_fallback_mode")
        or os.environ.get("DL_OP_TO_HLS_OPTIMIZATION_FALLBACK_MODE")
        or "demo"
    ).lower()
    allow_rule_fallback = fallback_mode == "demo"

    def _rule_fallback() -> dict[str, Any]:
        return {
            "summary": "Rule-based fallback suggestions were used.",
            "suggestions": [
                {
                    "title": "RuleSuggestion",
                    "reason": item,
                    "expected_tradeoff": "n/a",
                    "confidence": 0.5,
                }
                for item in build_suggestions(report, rag_context, objective)
            ],
            "memory_used": rag_context[:3],
        }

    if llm_client is None:
        if not allow_rule_fallback:
            return error_result(
                build_error(
                    "LLMGenerationError",
                    "Optimization suggestions require LLM in strict mode; rule fallback is disabled.",
                    recoverable=True,
                    source="suggestion.suggest_optimization",
                    suggested_action="Configure LLM or set DL_OP_TO_HLS_OPTIMIZATION_FALLBACK_MODE=demo for demo-only rule suggestions.",
                    details={"fallback_mode": fallback_mode},
                )
            )
        llm_result = _rule_fallback()
        llm_result["llm_fallback_used"] = True
    else:
        try:
            llm_result = LLMOptimizationEngine().generate(
                report=report,
                objective=objective,
                rag_context=rag_context,
                state_summary=state,
                client=llm_client,
                fallback=_rule_fallback,
                allow_rule_fallback=allow_rule_fallback,
            )
        except Exception as exc:
            return error_result(
                build_error(
                    "LLMGenerationError",
                    f"LLM optimization failed in strict mode: {exc}",
                    recoverable=True,
                    source="suggestion.suggest_optimization",
                    suggested_action="Fix LLM/API/configuration issue or explicitly switch to demo fallback mode.",
                    details={"fallback_mode": fallback_mode},
                )
            )

    suggestions = []
    for item in llm_result.get("suggestions", []):
        if isinstance(item, dict):
            title = item.get("title") or "Suggestion"
            reason = item.get("reason") or ""
            suggestions.append(f"{title}: {reason}".strip(": "))
        else:
            suggestions.append(str(item))
    if not suggestions:
        suggestions = build_suggestions(report, rag_context, objective)
    markdown = render_suggestions_markdown(report, rag_context, objective, suggestions)
    artifact_manager = context.get("artifact_manager")
    path = None
    if artifact_manager:
        path = artifact_manager.write_text("suggestions.md", markdown, "suggestions")
    return {
        "status": "success",
        "suggestions": suggestions,
        "markdown": markdown,
        "path": str(path) if path else None,
        "llm_fallback_used": bool(llm_result.get("llm_fallback_used")),
        "fallback_mode": fallback_mode,
    }
