from dl_op_to_hls.benchmarks.operator_case_generator import (
    FixedPointSpec,
    evaluate_case,
    generate_operator_cases,
    validate_case_schema,
)


def test_functional_suite_contains_at_least_90_independent_cases():
    cases = generate_operator_cases()
    assert len(cases) >= 90
    assert len({case["case_id"] for case in cases}) == len(cases)
    assert {case["operator"] for case in cases} == {"Dense", "MatMul", "ReLU", "Add", "ScaleShift", "Conv2D"}
    assert {case["input_family"] for case in cases} == {
        "zeros", "ones", "alternating", "random_small", "near_limits",
        "overflow_pressure", "sparse", "symmetric", "impulse", "near_boundary",
    }


def test_every_generated_case_has_valid_schema_and_reference():
    for case in generate_operator_cases():
        assert validate_case_schema(case) == []
        result = evaluate_case(case)
        assert result["passed"] is True, case["case_id"]
        assert result["output_count"] > 0
        assert result["evidence_class"] == "unit"


def test_fixed_point_reference_tracks_wrap_and_saturation():
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
    case = next(case for case in generate_operator_cases() if case["operator"] == "Conv2D")
    case["params"] = {**case["params"], "groups": 2}
    assert "Conv2D groups must equal 1" in validate_case_schema(case)
    case["params"] = {**case["params"], "groups": 1}
    case["shape"] = [8, "dynamic", 3]
    assert "Conv2D shape must be static positive integers" in validate_case_schema(case)
