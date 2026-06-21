"""Low-cost architecture screening for the CIFAR-10 HLS exploration.

This is deliberately a *gate*, not a resource estimator that claims to replace
Vivado HLS.  It combines operation counts with two real, same-device Vivado
measurements.  The output is useful for deciding which candidates are worth a
long CSim/csynth run; every accepted candidate still requires real functional
verification and synthesis.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable


TARGET_CAPACITY = {"bram": 280, "dsp": 220, "ff": 106_400, "lut": 53_200}


@dataclass(frozen=True)
class CifarArchitectureSpec:
    """Three-stage Conv/ReLU/Pool/Conv/ReLU/Pool/Conv/ReLU/GAP classifier."""

    name: str
    channels: tuple[int, int, int]
    convs_per_stage: tuple[int, int, int] = (1, 1, 1)

    def validate(self) -> None:
        if len(self.channels) != 3 or len(self.convs_per_stage) != 3:
            raise ValueError("CIFAR architecture screening requires exactly three stages.")
        if any(int(value) < 1 for value in self.channels):
            raise ValueError("Channel counts must be positive.")
        if any(int(value) not in {1, 2} for value in self.convs_per_stage):
            raise ValueError("Each stage must contain one or two convolutions.")


@dataclass(frozen=True)
class ArchitectureScreenResult:
    spec: CifarArchitectureSpec
    conv_layers: int
    macs: int
    parameters: int
    peak_activation_elements: int
    estimated_resources: dict[str, int]
    estimated_utilization: dict[str, float]
    decision: str
    reasons: list[str]
    confidence: str

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["spec"]["channels"] = list(self.spec.channels)
        payload["spec"]["convs_per_stage"] = list(self.spec.convs_per_stage)
        return payload


def _conv_cost(height: int, width: int, in_channels: int, out_channels: int) -> tuple[int, int, int]:
    """Return MACs, weights including bias, and output activation elements."""

    macs = height * width * in_channels * out_channels * 3 * 3
    parameters = out_channels * (in_channels * 3 * 3 + 1)
    activation_elements = height * width * out_channels
    return macs, parameters, activation_elements


def _analytical_cost(spec: CifarArchitectureSpec) -> tuple[int, int, int, int]:
    spec.validate()
    stage_shapes = ((32, 32), (16, 16), (8, 8))
    channels = spec.channels
    total_macs = 0
    total_parameters = 0
    peak_activation = 0
    in_channels = 3
    conv_layers = 0

    for (height, width), out_channels, count in zip(stage_shapes, channels, spec.convs_per_stage):
        for _ in range(count):
            macs, parameters, activations = _conv_cost(height, width, in_channels, out_channels)
            total_macs += macs
            total_parameters += parameters
            peak_activation = max(peak_activation, activations)
            in_channels = out_channels
            conv_layers += 1

    # GAP has no multipliers; account for the final affine classifier.
    total_macs += channels[-1] * 10
    total_parameters += (channels[-1] + 1) * 10
    return conv_layers, total_macs, total_parameters, peak_activation


def _estimate_resources(macs: int, conv_layers: int) -> dict[str, int]:
    """Calibrate a conservative screen using two real Vivado HLS 2018.3 runs.

    Anchors, both with fixed<10,4> and FIFO-depth profiling on xc7z020:
    - 16->32->64, 3 conv layers: BRAM 56, LUT 47,459.
    - 12->24->48 VGG-GAP, 6 conv layers: BRAM 394, LUT 71,276.

    The estimates intentionally contain no claim about DSP/FF, because those
    values varied with scheduling.  Their fields remain a sentinel so callers
    cannot mistake this for a complete resource report.
    """

    baseline_macs = 2_802_304
    baseline_lut = 47_459
    baseline_bram = 56
    vgg_macs = 5_640_672
    vgg_lut = 71_276
    vgg_bram = 394

    lut_per_mac = (vgg_lut - baseline_lut) / float(vgg_macs - baseline_macs)
    lut_intercept = baseline_lut - lut_per_mac * baseline_macs

    # Empirical FIFO cost is strongly affected by every streamed convolution.
    # Reserve a small MAC component, then fit the remaining 3-layer delta.
    bram_per_million_macs = 10.0
    bram_per_extra_conv = (
        (vgg_bram - baseline_bram) - bram_per_million_macs * ((vgg_macs - baseline_macs) / 1_000_000)
    ) / 3.0
    estimated_lut = max(0, round(lut_intercept + lut_per_mac * macs))
    estimated_bram = max(
        0,
        round(
            baseline_bram
            + bram_per_million_macs * ((macs - baseline_macs) / 1_000_000)
            + bram_per_extra_conv * (conv_layers - 3)
        ),
    )
    return {"bram": estimated_bram, "lut": estimated_lut, "dsp": -1, "ff": -1}


def screen_architecture(spec: CifarArchitectureSpec, *, conservative_margin: float = 0.90) -> ArchitectureScreenResult:
    """Return a conservative decision before sending a candidate to Vivado.

    ``conservative_margin`` reserves headroom for estimation error.  A result
    of ``synthesis_candidate`` means only that it is worth real HLS validation.
    """

    if not 0.5 <= conservative_margin <= 1.0:
        raise ValueError("conservative_margin must be within [0.5, 1.0].")
    conv_layers, macs, parameters, peak_activation = _analytical_cost(spec)
    estimated = _estimate_resources(macs, conv_layers)
    utilization = {
        key: round(estimated[key] / TARGET_CAPACITY[key], 4)
        for key in ("bram", "lut")
    }
    reasons = [
        "Static screen is calibrated from two real Vivado HLS 2018.3 dataflow runs; it is not a synthesis result.",
        f"Analytical workload: {macs:,} MACs, {parameters:,} parameters, {conv_layers} streamed convolutions.",
    ]
    if estimated["bram"] > TARGET_CAPACITY["bram"] or estimated["lut"] > TARGET_CAPACITY["lut"]:
        decision = "reject_before_synthesis"
        reasons.append("Predicted BRAM or LUT exceeds the reference device capacity.")
    elif utilization["bram"] > conservative_margin or utilization["lut"] > conservative_margin:
        decision = "borderline_requires_explicit_approval"
        reasons.append("Predicted resource use consumes the screening safety margin; synthesize only if accuracy evidence is strong.")
    else:
        decision = "synthesis_candidate"
        reasons.append("Predicted BRAM/LUT retains screening headroom; proceed to training and real CSim/csynth only after accuracy gates pass.")
    return ArchitectureScreenResult(
        spec=spec,
        conv_layers=conv_layers,
        macs=macs,
        parameters=parameters,
        peak_activation_elements=peak_activation,
        estimated_resources=estimated,
        estimated_utilization=utilization,
        decision=decision,
        reasons=reasons,
        confidence="low: two real synthesis anchors; use for ranking only",
    )


def default_candidates() -> list[CifarArchitectureSpec]:
    """Human-designed interpolation candidates between the two measured anchors."""

    return [
        CifarArchitectureSpec("baseline_gap_16_32_64", (16, 32, 64), (1, 1, 1)),
        CifarArchitectureSpec("compact_depth_12_24_48", (12, 24, 48), (1, 2, 1)),
        CifarArchitectureSpec("compact_width_12_24_64", (12, 24, 64), (1, 2, 1)),
        CifarArchitectureSpec("compact_depth_14_24_48", (14, 24, 48), (1, 2, 1)),
        CifarArchitectureSpec("high_capacity_16_24_48", (16, 24, 48), (1, 2, 1)),
        CifarArchitectureSpec("depth_late_12_20_40", (12, 20, 40), (1, 2, 2)),
        CifarArchitectureSpec("vgg_gap_12_24_48", (12, 24, 48), (2, 2, 2)),
    ]


def screen_many(specs: Iterable[CifarArchitectureSpec], *, conservative_margin: float = 0.90) -> list[ArchitectureScreenResult]:
    return sorted(
        (screen_architecture(spec, conservative_margin=conservative_margin) for spec in specs),
        key=lambda result: (result.decision != "synthesis_candidate", result.estimated_resources["lut"], result.estimated_resources["bram"]),
    )
