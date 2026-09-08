"""Test contracts and regression checks for test_llm_task_interpreter_schema.py.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from dl_op_to_hls.llm.client import FakeLLMClient
from dl_op_to_hls.llm.schemas import TASK_INTERPRETATION_SCHEMA, validate_required
from dl_op_to_hls.llm.task_interpreter import LLMTaskInterpreter
from dl_op_to_hls.llm.prompts import TASK_INTERPRETER_SYSTEM_PROMPT
import pytest


def test_llm_task_interpreter_schema():
    """Verify the test_llm_task_interpreter_schema contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    fake = FakeLLMClient(
        json_responses=[
            {
                "task": {
                    "task_type": "operator",
                    "name": "dense_16x32",
                    "op_type": "Dense",
                    "input_shape": [16],
                    "output_shape": [32],
                    "dtype": "ap_fixed<16,6>",
                    "target": {"backend": "VivadoHLS", "part": "xc7z020clg400-1", "clock_period": 5},
                    "objective": "latency",
                },
                "assumptions": ["static shape"],
                "reason_summary": "converted from NL",
            }
        ]
    )
    result = LLMTaskInterpreter().interpret("convert dense", fake)
    assert result["task"]["task_type"] == "operator"
    assert result["assumptions"]


def test_task_interpretation_schema_rejects_string_task():
    """Verify the test_task_interpretation_schema_rejects_string_task contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    with pytest.raises(ValueError, match="Invalid type"):
        validate_required(
            {"task": "operator JSON", "assumptions": [], "reason_summary": "bad nesting"},
            TASK_INTERPRETATION_SCHEMA,
        )


def test_task_interpretation_schema_rejects_invalid_nested_enum():
    """Verify the test_task_interpretation_schema_rejects_invalid_nested_enum contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    payload = {
        "task": {
            "task_type": "chat",
            "name": "invalid",
            "target": {"backend": "VivadoHLS", "part": "xc7z020", "clock_period": 10},
            "objective": "fastest",
        },
        "assumptions": [],
        "reason_summary": "invalid enum",
    }
    with pytest.raises(ValueError, match="Invalid enum"):
        validate_required(payload, TASK_INTERPRETATION_SCHEMA)


def test_task_interpreter_canonicalizes_onnx_source_alias():
    """Verify the test_task_interpreter_canonicalizes_onnx_source_alias contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    result = LLMTaskInterpreter._canonicalize_task_fields(
        {
            "task": {
                "task_type": "hls_project",
                "name": "network",
                "source": {"format": "onnx", "path": "models/network.onnx"},
                "constraints": {"stability": True, "maintainability": True},
                "target": {"backend": "VivadoHLS", "part": "xc7z020", "clock_period": 10},
                "objective": "balanced",
            },
            "assumptions": [],
            "reason_summary": "model source",
        }
    )
    assert result["task"]["task_type"] == "model"
    assert result["task"]["model_path"] == "models/network.onnx"
    assert result["task"]["frontend"] == "onnx"
    assert result["task"]["objective"] == "standard"


def test_task_interpreter_prompt_requires_complete_fixed_point_dtype():
    """Verify the test_task_interpreter_prompt_requires_complete_fixed_point_dtype contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    assert "Never emit a bare \"ap_fixed\"" in TASK_INTERPRETER_SYSTEM_PROMPT
    assert "ap_fixed<16,6>" in TASK_INTERPRETER_SYSTEM_PROMPT
