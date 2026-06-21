from __future__ import annotations

from dl_op_to_hls.tools.cifar_architecture_screen import (
    CifarArchitectureSpec,
    default_candidates,
    screen_architecture,
    screen_many,
)


def test_screen_marks_measured_three_conv_shape_as_synthesis_candidate():
    result = screen_architecture(CifarArchitectureSpec("gap", (16, 32, 64), (1, 1, 1)))

    assert result.macs == 2_802_304
    assert result.estimated_resources["lut"] == 47_459
    assert result.estimated_resources["bram"] == 56
    assert result.decision == "synthesis_candidate"


def test_screen_rejects_measured_vgg_shape_before_synthesis():
    result = screen_architecture(CifarArchitectureSpec("vgg", (12, 24, 48), (2, 2, 2)))

    assert result.estimated_resources["bram"] > 280
    assert result.estimated_resources["lut"] > 53_200
    assert result.decision == "reject_before_synthesis"


def test_screen_prioritizes_compact_depth_candidate_over_rejected_vgg():
    results = screen_many(default_candidates())
    by_name = {result.spec.name: result for result in results}

    assert by_name["compact_depth_12_24_48"].decision == "borderline_requires_explicit_approval"
    assert by_name["vgg_gap_12_24_48"].decision == "reject_before_synthesis"
