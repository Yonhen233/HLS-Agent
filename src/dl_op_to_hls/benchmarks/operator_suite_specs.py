"""benchmarks layer implementation for operator_suite_specs.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

from typing import Any


def real_csim_suite() -> dict[str, Any]:
    """Execute real_csim_suite at the operator_suite_specs boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Returns:
        The structured value promised by the function signature.
    """
    anchors = {
        "Dense": ["dense_8x8_fx8", "dense_16x32_boundary", "dense_32x16_fx16"],
        "MatMul": ["matmul_4x4_fx8", "matmul_8x8_boundary", "matmul_8x16x4_fx16"],
        "ReLU": ["relu_16_default", "relu_64_boundary", "relu_256_fx8"],
        "Add": ["add_16_default", "add_64_overflow", "add_256_fx12"],
        "ScaleShift": ["scale_shift_16_default", "scale_shift_64_boundary", "scale_shift_256_fx8"],
        "Conv2D": ["conv_6x6x1_valid", "conv_8x8x3_same", "conv_8x8x3_boundary"],
    }
    return _suite("operator_real_csim_suite", "real_csim", anchors, "llm_candidate", 18)


def real_csynth_suite() -> dict[str, Any]:
    """Execute real_csynth_suite at the operator_suite_specs boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Returns:
        The structured value promised by the function signature.
    """
    cases = [
        ("Dense", "dense_latency", "latency"),
        ("Dense", "dense_resource", "resource"),
        ("MatMul", "matmul_latency", "latency"),
        ("MatMul", "matmul_resource", "resource"),
        ("Conv2D", "conv_small_latency", "latency"),
        ("Conv2D", "conv_medium_resource", "resource"),
        ("ReLU", "relu_latency", "latency"),
        ("Add", "add_latency", "latency"),
        ("ScaleShift", "scale_shift_resource", "resource"),
        ("Dense", "dense_timing_pressure", "timing_failure_detection"),
    ]
    return {
        "schema_version": "1.0",
        "suite_name": "operator_real_csynth_suite",
        "evidence_class": "real_csynth",
        "mock_tools": False,
        "minimum_case_count": 10,
        "cases": [
            {
                "case_id": case_id,
                "operator": operator,
                "objective": objective,
                "generation_path": "llm_candidate",
                "required_fields": [
                    "latency", "interval", "resources", "timing", "tool_version", "part",
                    "run_id", "git_commit", "artifact_hash", "functional_verification",
                ],
                "status": "pending_real_run",
            }
            for operator, case_id, objective in cases
        ],
    }


def llm_candidate_suite() -> dict[str, Any]:
    """Execute llm_candidate_suite at the operator_suite_specs boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Returns:
        The structured value promised by the function signature.
    """
    cases = []
    for operator in ("Dense", "MatMul", "ReLU", "Add", "ScaleShift"):
        for repeat in range(1, 4):
            cases.append(
                {
                    "case_id": f"{operator.lower()}_pass3_{repeat}",
                    "operator": operator,
                    "repeat": repeat,
                    "generation_path": "llm_candidate",
                    "real_llm": True,
                    "real_vivado": True,
                    "required_metrics": [
                        "plan_valid", "files_complete", "signature_match", "sandbox_passed",
                        "csim_passed", "csynth_passed", "repair_count", "false_success",
                        "input_tokens", "output_tokens", "llm_calls", "tool_calls", "runtime_seconds",
                    ],
                    "status": "pending_real_run",
                }
            )
    return {
        "schema_version": "1.0",
        "suite_name": "operator_llm_candidate_suite",
        "minimum_runs": 15,
        "selection_policy": "report_all_repetitions_no_best_of_selection",
        "cases": cases,
    }


def template_vs_llm_suite() -> dict[str, Any]:
    """Execute template_vs_llm_suite at the operator_suite_specs boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Returns:
        The structured value promised by the function signature.
    """
    return {
        "schema_version": "1.0",
        "suite_name": "operator_template_vs_llm_suite",
        "primary_path": "llm_candidate",
        "template_role": "fair_baseline_only",
        "cases": [
            {"case_id": f"{operator.lower()}_{objective}_fair", "operator": operator, "objective": objective, "status": "pending_real_run"}
            for operator in ("Dense", "MatMul")
            for objective in ("latency", "resource")
        ],
        "fixed_constraints": ["shape", "dtype", "part", "clock", "input_data", "golden_reference", "vivado_version"],
    }


def onnx_graph_suite() -> dict[str, Any]:
    """Execute onnx_graph_suite at the operator_suite_specs boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Returns:
        The structured value promised by the function signature.
    """
    positive = [
        "Gemm->Dense", "MatMul+static bias Add->Dense", "Gemm+ReLU", "Conv+ReLU",
        "Conv+BatchNorm fold", "Conv+MaxPool", "Conv+AveragePool", "Conv+GlobalAveragePool",
        "Conv+ReduceMean global pool", "static Flatten", "static Reshape", "Q/DQ metadata",
        "static Shape/Gather/Concat elimination", "restricted NCHW->NHWC",
    ]
    negative = [
        "residual Add branch", "grouped Conv", "depthwise Conv", "dynamic Reshape",
        "non-static MatMul weight", "Gemm transA", "Gemm non-unit alpha/beta",
        "unsupported Transpose perm", "multiple model inputs", "dynamic Shape", "Loop/If", "custom domain",
    ]
    return {
        "schema_version": "1.0",
        "suite_name": "operator_onnx_graph_suite",
        "hls_generation_path": "llm_candidate",
        "adapter_role": "graph inspection and static contract extraction only",
        "positive_cases": [{"case_id": f"onnx_pos_{index:02d}", "pattern": pattern, "status": "pending"} for index, pattern in enumerate(positive, 1)],
        "negative_cases": [{"case_id": f"onnx_neg_{index:02d}", "pattern": pattern, "expected": "structured_rejection", "status": "pending"} for index, pattern in enumerate(negative, 1)],
    }


def bad_case_suite() -> dict[str, Any]:
    """Execute bad_case_suite at the operator_suite_specs boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Returns:
        The structured value promised by the function signature.
    """
    failures = [
        ("shape mismatch", "InvalidTaskError"),
        ("invalid dtype", "InvalidTaskError"),
        ("dynamic array", "UnsupportedOperatorError"),
        ("dynamic memory", "PermissionDeniedError"),
        ("file/network/system call", "PermissionDeniedError"),
        ("non-byte-aligned m_axi", "PermissionDeniedError"),
        ("dangerous array partition", "PermissionDeniedError"),
        ("candidate missing header", "VerificationFailedError"),
        ("candidate signature mismatch", "VerificationFailedError"),
        ("CSim compile failure", "VerificationFailedError"),
        ("CSim missing golden marker", "VerificationFailedError"),
        ("golden numeric mismatch", "VerificationFailedError"),
        ("CSynth exit zero with compiler error", "VivadoSynthesisError"),
        ("CSynth report missing timing", "ReportParseError"),
        ("stale report from another run", "ToolPostconditionError"),
        ("Vivado binary missing", "VivadoNotFoundError"),
        ("tool timeout", "ToolTimeoutError"),
        ("timing failure", "VivadoSynthesisError"),
        ("maximum repair attempts", "VerificationFailedError"),
        ("unsupported fake metrics", "ToolPostconditionError"),
    ]
    return {
        "schema_version": "1.0",
        "suite_name": "operator_bad_case_suite",
        "release_targets": {
            "false_success_rate": 0.0,
            "stale_artifact_acceptance": 0.0,
            "unsafe_candidate_acceptance": 0.0,
            "unsupported_fake_metric_rate": 0.0,
        },
        "cases": [
            {
                "case_id": f"bad_{index:02d}",
                "fault": fault,
                "expected_error_type": error,
                "required_fields": ["failure_stage", "error_type", "recoverable", "repair_action", "attempt_count", "final_outcome", "artifact_evidence"],
                "status": "pending",
            }
            for index, (fault, error) in enumerate(failures, 1)
        ],
    }


def all_suite_payloads() -> dict[str, dict[str, Any]]:
    """Execute all_suite_payloads at the operator_suite_specs boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Returns:
        The structured value promised by the function signature.
    """
    return {
        "operator_real_csim_suite.json": real_csim_suite(),
        "operator_real_csynth_suite.json": real_csynth_suite(),
        "operator_llm_candidate_suite.json": llm_candidate_suite(),
        "operator_template_vs_llm_suite.json": template_vs_llm_suite(),
        "operator_onnx_graph_suite.json": onnx_graph_suite(),
        "operator_bad_case_suite.json": bad_case_suite(),
    }


def _suite(name: str, evidence_class: str, anchors: dict[str, list[str]], generation_path: str, minimum: int) -> dict[str, Any]:
    """Implement the internal _suite helper.

    Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

    Args:
        name: Value supplied by the caller and validated by the surrounding schema.
        evidence_class: Value supplied by the caller and validated by the surrounding schema.
        anchors: Value supplied by the caller and validated by the surrounding schema.
        generation_path: Value supplied by the caller and validated by the surrounding schema.
        minimum: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    cases = [
        {
            "case_id": case_id,
            "operator": operator,
            "generation_path": generation_path,
            "evidence_class": evidence_class,
            "mock_tools": False,
            "required_marker": "GOLDEN_CHECK_PASSED",
            "status": "pending_real_run",
        }
        for operator, case_ids in anchors.items()
        for case_id in case_ids
    ]
    return {"schema_version": "1.0", "suite_name": name, "evidence_class": evidence_class, "minimum_case_count": minimum, "cases": cases}
