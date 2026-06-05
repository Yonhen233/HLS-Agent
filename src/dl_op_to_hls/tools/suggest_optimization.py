from __future__ import annotations

import os
from typing import Any

from ..core.errors import build_error, error_result
from ..core.memory_hygiene import sanitize_memory_text
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
    prior_hints = _select_prior_hints(rag_context, limit=1)
    if prior_hints:
        suggestions.append(f"Prior experience hint: {prior_hints[0]}")
    return suggestions


def _is_actionable_prior_hint(summary: str) -> bool:
    normalized = " ".join((summary or "").strip().split())
    lowered = normalized.lower()
    if not normalized:
        return False
    if lowered.startswith(("episode.", "semantic.", "failure.", "optimization.", "skill.")):
        return False
    if "{" in normalized and "}" in normalized:
        return False
    if any(marker in lowered for marker in ['{"run_id"', '"task_type"', '"selected_path"', "unsupported {"]):
        return False
    if "prior experience hint" in lowered:
        return False
    return True


def _select_prior_hints(rag_context: list[dict], limit: int = 3) -> list[str]:
    hints: list[str] = []
    seen: set[str] = set()
    for item in rag_context:
        summary = sanitize_memory_text(item.get("summary") or item.get("text", ""))
        if not _is_actionable_prior_hint(summary):
            continue
        normalized = " ".join(summary.split())
        dedupe_key = normalized.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        hints.append(normalized[:240])
        if len(hints) >= limit:
            break
    return hints


def render_suggestions_markdown(report: dict[str, Any], rag_context: list[dict], objective: str | None, suggestions: list[str]) -> str:
    latency = report.get("latency", {})
    interval = report.get("interval", {})
    resources = report.get("resources", {})
    timing = report.get("timing", {})
    history_lines = "\n".join(f"- {cleaned}" for cleaned in _select_prior_hints(rag_context, limit=3)) or "- None"
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


def _write_suggestions_markdown(context: dict[str, Any], markdown: str):
    artifact_manager = context.get("artifact_manager")
    if artifact_manager:
        return artifact_manager.write_text("suggestions.md", markdown, "suggestions")
    return None


def _is_placeholder_suggestion(text: str) -> bool:
    normalized = " ".join(text.strip().lower().split())
    return normalized in {"", "suggestion", "suggestions", "suggestion:", "n/a", "none", "todo"}


def _normalize_llm_suggestions(llm_result: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
    suggestions: list[str] = []
    invalid: list[dict[str, Any]] = []
    for item in llm_result.get("suggestions", []):
        if isinstance(item, dict):
            title = str(item.get("title") or item.get("action") or item.get("recommendation") or "").strip()
            reason = str(
                item.get("reason")
                or item.get("justification")
                or item.get("rationale")
                or item.get("description")
                or ""
            ).strip()
            if _is_placeholder_suggestion(title) and reason:
                title = "Optimization action"
            text = f"{title}: {reason}".strip(": ")
            if _is_placeholder_suggestion(title) and not reason:
                invalid.append({"item": item, "reason": "placeholder_title_without_reason"})
                continue
            if _is_placeholder_suggestion(text):
                invalid.append({"item": item, "reason": "placeholder_text"})
                continue
            suggestions.append(text)
        else:
            text = str(item).strip()
            if _is_placeholder_suggestion(text):
                invalid.append({"item": item, "reason": "placeholder_text"})
                continue
            suggestions.append(text)
    return suggestions, invalid


def suggest_optimization(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    state = arguments["state"]
    report = arguments["report"]
    rag_context = arguments.get("rag_context", [])
    objective = arguments.get("objective") or state.get("objective")
    if state.get("selected_path") == "unsupported_path" and report.get("status") in {"missing", "skipped", "report_missing"}:
        suggestions = [
            "Optimization is not applicable yet because no synthesizable HLS implementation/report is available.",
            "Use the unsupported report to choose a safe next engineering step: graph rewrite, custom hls4ml layer, fallback template, or smaller subgraph.",
        ]
        markdown = render_suggestions_markdown(report, [], objective, suggestions)
        path = _write_suggestions_markdown(context, markdown)
        return {
            "status": "skipped",
            "reason": "No synthesis metrics are available for unsupported_path; LLM optimization was intentionally skipped.",
            "suggestions": suggestions,
            "markdown": markdown,
            "path": str(path) if path else None,
            "llm_skipped": True,
            "fallback_mode": "not_applicable",
        }
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

    suggestions, invalid_suggestions = _normalize_llm_suggestions(llm_result)
    if invalid_suggestions:
        if not allow_rule_fallback:
            return error_result(
                build_error(
                    "LLMGenerationError",
                    "LLM optimization returned placeholder or empty suggestions in strict mode.",
                    recoverable=True,
                    source="suggestion.suggest_optimization",
                    suggested_action="Improve the optimizer prompt/model response; do not accept placeholder suggestions as successful output.",
                    details={"invalid_suggestions": invalid_suggestions[:5], "fallback_mode": fallback_mode},
                )
            )
        llm_result = _rule_fallback()
        llm_result["llm_fallback_used"] = True
        suggestions, _ = _normalize_llm_suggestions(llm_result)
    if not suggestions:
        if not allow_rule_fallback:
            return error_result(
                build_error(
                    "LLMGenerationError",
                    "LLM optimization returned no usable suggestions in strict mode.",
                    recoverable=True,
                    source="suggestion.suggest_optimization",
                    suggested_action="Improve the optimizer prompt/model response or explicitly switch to demo fallback mode.",
                    details={"fallback_mode": fallback_mode},
                )
            )
        suggestions = build_suggestions(report, rag_context, objective)
    markdown = render_suggestions_markdown(report, rag_context, objective, suggestions)
    path = _write_suggestions_markdown(context, markdown)
    return {
        "status": "success",
        "suggestions": suggestions,
        "markdown": markdown,
        "path": str(path) if path else None,
        "llm_fallback_used": bool(llm_result.get("llm_fallback_used")),
        "fallback_mode": fallback_mode,
    }
