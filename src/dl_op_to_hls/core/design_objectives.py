from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ObjectiveMode:
    name: str
    aliases: tuple[str, ...]
    description: str
    primary_metric: str
    secondary_metrics: tuple[str, ...]
    preferred_path_policy: str
    candidate_policy: str
    acceptance_rule: str
    planner_effect: str
    specialist_effect: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


OBJECTIVE_MODES: dict[str, ObjectiveMode] = {
    "standard": ObjectiveMode(
        name="standard",
        aliases=("default", "maintainable", "hls4ml"),
        description="Prefer the stable hls4ml path and only use LLM candidates when explicitly requested or when no safe standard path exists.",
        primary_metric="maintainability",
        secondary_metrics=("functional_verification", "synthesis_success"),
        preferred_path_policy="hls4ml_path > fallback_template_path > llm_candidate_path",
        candidate_policy="Do not start LLM architecture search unless the task explicitly requests it or the standard path is unsupported.",
        acceptance_rule="Conversion, csim/csynth, and report parsing must succeed; no objective-specific resource/latency win is required.",
        planner_effect="Planner keeps the canonical model-to-hls4ml workflow and avoids speculative candidate generation.",
        specialist_effect="HLS4MLSpecialist and VivadoSpecialist dominate; OptimizationSpecialist focuses on safe suggestions.",
    ),
    "resource": ObjectiveMode(
        name="resource",
        aliases=("area", "size", "min_area"),
        description="Minimize FPGA resource pressure, especially LUT/FF/DSP/BRAM, while preserving functional correctness.",
        primary_metric="resource_score",
        secondary_metrics=("timing_met", "functional_verification"),
        preferred_path_policy="verified low-resource LLM candidate or fallback template may beat hls4ml when the objective explicitly asks for area.",
        candidate_policy="Generate serial or shared-compute candidates; prefer fewer multipliers and less partitioning even if latency increases.",
        acceptance_rule="Golden verification must pass, resources must fit the target part, and resource_score should improve versus baseline.",
        planner_effect="Planner may add candidate-generation or parameter-advisor todos after a baseline report exposes high resource pressure.",
        specialist_effect="OptimizationSpecialist ranks low resource_score; MemorySpecialist promotes only verified low-resource profiles.",
    ),
    "latency": ObjectiveMode(
        name="latency",
        aliases=("low_latency", "min_latency"),
        description="Minimize latency cycles for a single inference while keeping resources within the target device.",
        primary_metric="latency_cycles",
        secondary_metrics=("resource_feasible", "timing_met", "functional_verification"),
        preferred_path_policy="hls4ml remains the baseline; LLM candidates are accepted when verified latency improves and resources fit.",
        candidate_policy="Increase safe parallelism and partition local arrays when it reduces latency without violating the board budget.",
        acceptance_rule="Golden verification must pass, latency must improve versus baseline, and resources must fit the target part.",
        planner_effect="Planner can request latency-oriented candidate generation after baseline synthesis establishes the latency target.",
        specialist_effect="OptimizationSpecialist emphasizes latency; VivadoSpecialist must report resource feasibility, not only timing.",
    ),
    "throughput": ObjectiveMode(
        name="throughput",
        aliases=("ii", "interval", "pipeline"),
        description="Minimize initiation interval / top interval so repeated inferences can start more frequently.",
        primary_metric="ii_cycles",
        secondary_metrics=("latency_cycles", "resource_feasible", "functional_verification"),
        preferred_path_policy="Choose verified candidates that improve II/top interval and still fit the target device.",
        candidate_policy="Explore pipelining, local buffering, and limited partition/unroll; reject designs that win II but exceed board capacity.",
        acceptance_rule="Golden verification must pass, II/top interval must improve versus baseline, and resources must fit the target part.",
        planner_effect="Planner treats II as first-class evidence and should not mark a low-latency but over-capacity candidate as success.",
        specialist_effect="VivadoSpecialist must parse interval and available resources; OptimizationSpecialist ranks II before latency.",
    ),
    "performance": ObjectiveMode(
        name="performance",
        aliases=("speed", "fast", "perf"),
        description="Optimize overall speed by jointly reducing latency and II, accepting more resources if the target part still fits.",
        primary_metric="performance_score",
        secondary_metrics=("latency_cycles", "ii_cycles", "resource_feasible"),
        preferred_path_policy="Allow LLM candidate exploration when hls4ml is functionally correct but not fast enough.",
        candidate_policy="Use aggressive but guarded parallelism; resource growth is acceptable only under explicit board feasibility checks.",
        acceptance_rule="Golden verification must pass, resources must fit, and the weighted latency/II score should improve versus baseline.",
        planner_effect="Planner may schedule both baseline synthesis and candidate exploration so the selector can compare Pareto points.",
        specialist_effect="OptimizationSpecialist balances latency and II; VerificationSpecialist gates correctness before speed claims.",
    ),
    "balanced": ObjectiveMode(
        name="balanced",
        aliases=("tradeoff", "pareto"),
        description="Find a Pareto-balanced point: keep resource usage under a budget while improving latency/II versus the smallest resource candidate.",
        primary_metric="weighted_pareto_score",
        secondary_metrics=("resource_score", "latency_cycles", "ii_cycles"),
        preferred_path_policy="Compare hls4ml, fallback, and verified LLM candidates using an explicit resource budget.",
        candidate_policy="Use moderate parallelism and safe fixed-point widths; reject both over-serial and over-parallel extremes.",
        acceptance_rule="Golden verification must pass, resources must fit, and the candidate must satisfy the configured resource budget.",
        planner_effect="Planner creates comparison-oriented todos rather than assuming one path is globally best.",
        specialist_effect="OptimizationSpecialist returns trade-off notes; MemorySpecialist stores the budget and score with the verified profile.",
    ),
}


_ALIASES: dict[str, str] = {
    alias: name for name, mode in OBJECTIVE_MODES.items() for alias in (name, *mode.aliases)
}


def normalize_objective_mode(value: Any, default: str = "latency", *, strict: bool = False) -> str:
    text = str(value or default).strip().lower().replace("-", "_")
    normalized = _ALIASES.get(text)
    if normalized:
        return normalized
    if strict:
        supported = ", ".join(sorted(OBJECTIVE_MODES))
        raise ValueError(f"Unsupported objective mode '{value}'. Supported modes: {supported}")
    return text or default


def get_objective_mode(value: Any, default: str = "latency") -> ObjectiveMode:
    normalized = normalize_objective_mode(value, default=default, strict=False)
    if normalized not in OBJECTIVE_MODES:
        normalized = default if default in OBJECTIVE_MODES else "latency"
    return OBJECTIVE_MODES[normalized]


def list_objective_modes() -> list[dict[str, Any]]:
    return [mode.to_dict() for mode in OBJECTIVE_MODES.values()]


def objective_requires_llm_search(value: Any) -> bool:
    mode = normalize_objective_mode(value, default="latency")
    return mode in {"resource", "latency", "throughput", "performance", "balanced"}
