"""Test contracts and regression checks for test_skill_routing_contracts.py.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

import json
from pathlib import Path

from dl_op_to_hls.skills.registry import SkillRegistry
from dl_op_to_hls.skills.schema import evaluate_conditions


ROOT = Path(__file__).parents[1]


def _selected(task_path: str) -> str:
    """Verify the _selected contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        task_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    registry = SkillRegistry(ROOT / "skills")
    registry.load_all()
    task = json.loads((ROOT / task_path).read_text(encoding="utf-8"))
    return registry.find_candidates(task)[0].name


def test_primary_skill_routing_on_realistic_task_distribution():
    """Verify the test_primary_skill_routing_on_realistic_task_distribution contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    assert _selected("examples/mnist_recognition_mlp.json") == "hls4ml_model_flow"
    assert _selected("examples/dense_operator.json") == "operator_fallback_flow"
    assert _selected("examples/existing_hls_project.json") == "existing_hls_project_flow"
    assert _selected("examples/resnet18_boundary.json") == "hls4ml_model_flow"
    assert _selected("examples/scale_shift_llm_candidate.json") == "llm_candidate_verification_flow"


def test_unknown_named_condition_fails_closed():
    """Verify the test_unknown_named_condition_fails_closed contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    assert evaluate_conditions(["unknown_future_predicate"], {"task_type": "model"}) is False
