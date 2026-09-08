"""Test contracts and regression checks for test_conv2d_llm_candidate_contract.py.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

import json
from pathlib import Path
from types import SimpleNamespace

from dl_op_to_hls.core.config import AppConfig
from dl_op_to_hls.llm.candidate_generator import LLMCandidateGenerator
from dl_op_to_hls.llm.prompts import CANDIDATE_GENERATOR_SYSTEM_PROMPT
from dl_op_to_hls.main_agent.llm_runtime import LLMFirstRuntime


def _task() -> dict:
    """Verify the _task contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    return json.loads(Path("examples/conv2d_llm_candidate.json").read_text(encoding="utf-8"))


def test_conv2d_llm_contract_is_static_and_complete():
    """Verify the test_conv2d_llm_contract_is_static_and_complete contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    task = _task()
    assert LLMCandidateGenerator.validate_operator_contract(task) == []
    contract = LLMCandidateGenerator._hls_contract(task)
    assert contract["operator"] == "Conv2D"
    assert contract["conv2d"]["layout"] == "NHWC"
    assert len(contract["conv2d"]["weights"]) == 18


def test_conv2d_llm_contract_rejects_grouped_dynamic_or_missing_weights():
    """Verify the test_conv2d_llm_contract_rejects_grouped_dynamic_or_missing_weights contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    task = _task()
    task["input_shape"] = [8, "dynamic", 3]
    task["operator_params"]["groups"] = 3
    task["operator_params"].pop("weights")
    errors = LLMCandidateGenerator.validate_operator_contract(task)
    assert any("static" in error for error in errors)
    assert any("Grouped/depthwise" in error for error in errors)
    assert any("weights and bias" in error for error in errors)


def test_candidate_reuse_accepts_only_verified_same_operator_memory():
    """Verify the test_candidate_reuse_accepts_only_verified_same_operator_memory contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    context = [
        {"kind": "verified_implementation", "text": "Conv2D 6x6 NHWC passed", "score": 0.9, "source_run_id": "good"},
        {"kind": "verified_implementation", "text": "Dense 16x32 passed", "score": 1.0, "source_run_id": "wrong_op"},
        {"kind": "optimization", "text": "Conv2D looked promising but was not verified", "score": 0.95, "source_run_id": "unverified"},
    ]
    selected = LLMCandidateGenerator._select_reuse_context(_task(), context)
    assert [item["source_run_id"] for item in selected] == ["good"]


def test_candidate_reuse_accepts_typed_parameter_experience_from_rag():
    """Verify the test_candidate_reuse_accepts_typed_parameter_experience_from_rag contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    context = [
        {
            "memory_type": "parameter_experience",
            "text": "Verified Conv2D 6x6 implementation with timing met.",
            "score": 0.9,
            "source_run_id": "verified_parameter_run",
        },
        {
            "memory_type": "episodic",
            "text": "Conv2D failed before verification.",
            "score": 1.0,
            "source_run_id": "failed_episode",
        },
    ]
    selected = LLMCandidateGenerator._select_reuse_context(_task(), context)
    assert [item["source_run_id"] for item in selected] == ["verified_parameter_run"]


def test_candidate_reuse_deduplicates_same_source_run():
    """Verify the test_candidate_reuse_deduplicates_same_source_run contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    context = [
        {
            "memory_type": "verified_implementation",
            "text": "Conv2D verified implementation",
            "score": 0.9,
            "source_run_id": "conv_run_1",
        },
        {
            "memory_type": "parameter_experience",
            "text": "Conv2D verified parameters",
            "score": 0.8,
            "source_run_id": "conv_run_1",
        },
    ]
    selected = LLMCandidateGenerator._select_reuse_context(_task(), context)
    assert len(selected) == 1
    assert selected[0]["memory_type"] == "verified_implementation"


def test_runtime_generation_policy_forces_operator_to_llm_candidate(tmp_path):
    """Verify the test_runtime_generation_policy_forces_operator_to_llm_candidate contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    config = AppConfig.load(Path.cwd())
    runtime = SimpleNamespace(agent=SimpleNamespace(config=config))
    task = {"task_type": "operator", "op_type": "Dense", "name": "dense"}
    normalized = LLMFirstRuntime._apply_generation_policy(runtime, task)
    assert normalized["llm_candidate"]["required"] is True
    assert normalized["generation_policy"]["hls4ml_allowed"] is False
    assert normalized["generation_policy"]["template_role"] == "fair_baseline_only"


def test_runtime_rejects_unknown_operator_without_golden_oracle_before_candidate_generation(tmp_path):
    """Verify the test_runtime_rejects_unknown_operator_without_golden_oracle_before_candidate_generation contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    config = AppConfig.load(Path.cwd())
    runtime = SimpleNamespace(agent=SimpleNamespace(config=config))
    task = {
        "task_type": "operator",
        "op_type": "CustomUnsupported",
        "name": "custom_unknown",
        "input_shape": [8],
        "output_shape": [8],
    }

    normalized = LLMFirstRuntime._apply_generation_policy(runtime, task)

    assert normalized["generation_policy"]["primary_path"] == "unsupported"
    assert normalized["llm_candidate"]["eligible"] is False
    assert normalized["demo"]["expected_path"] == "unsupported_report"
    assert normalized["capability_boundary"]["decision"] == "reject_before_llm_or_vivado"


def test_candidate_prompt_requires_compact_sandbox_safe_testbench():
    """Verify the test_candidate_prompt_requires_compact_sandbox_safe_testbench contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    assert "Keep the JSON and source files compact" in CANDIDATE_GENERATOR_SYSTEM_PROMPT
    assert "Do not include <cstdlib>, <fstream>" in CANDIDATE_GENERATOR_SYSTEM_PROMPT
    assert "Never invent or expand large literal weight/bias tables" in CANDIDATE_GENERATOR_SYSTEM_PROMPT
