"""Test contracts and regression checks for test_operator_case_generator.py.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from dl_op_to_hls.benchmarks.operator_case_generator import (
    FixedPointSpec,
    evaluate_case,
    generate_operator_cases,
    validate_case_schema,
)


def test_functional_suite_contains_at_least_90_independent_cases():
    """Verify the test_functional_suite_contains_at_least_90_independent_cases contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    cases = generate_operator_cases()
    assert len(cases) >= 90
    assert len({case["case_id"] for case in cases}) == len(cases)
    assert {case["operator"] for case in cases} == {"Dense", "MatMul", "ReLU", "Add", "ScaleShift", "Conv2D"}
    assert {case["input_family"] for case in cases} == {
        "zeros", "ones", "alternating", "random_small", "near_limits",
        "overflow_pressure", "sparse", "symmetric", "impulse", "near_boundary",
    }


def test_every_generated_case_has_valid_schema_and_reference():
    """Verify the test_every_generated_case_has_valid_schema_and_reference contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    for case in generate_operator_cases():
        assert validate_case_schema(case) == []
        result = evaluate_case(case)
        assert result["passed"] is True, case["case_id"]
        assert result["output_count"] > 0
        assert result["evidence_class"] == "unit"


def test_fixed_point_reference_tracks_wrap_and_saturation():
    """Verify the test_fixed_point_reference_tracks_wrap_and_saturation contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    wrap = FixedPointSpec.parse("ap_fixed<8,3>")
    _, overflowed, saturated = wrap.quantize(20.0)
    assert overflowed is True
    assert saturated is False

    sat = FixedPointSpec.parse("ap_fixed<8,3,AP_TRN,AP_SAT>")
    value, overflowed, saturated = sat.quantize(20.0)
    assert value == sat.maximum
    assert overflowed is True
    assert saturated is True


def test_conv2d_rejects_grouped_or_dynamic_contracts():
    """Verify the test_conv2d_rejects_grouped_or_dynamic_contracts contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    case = next(case for case in generate_operator_cases() if case["operator"] == "Conv2D")
    case["params"] = {**case["params"], "groups": 2}
    assert "Conv2D groups must equal 1" in validate_case_schema(case)
    case["params"] = {**case["params"], "groups": 1}
    case["shape"] = [8, "dynamic", 3]
    assert "Conv2D shape must be static positive integers" in validate_case_schema(case)
