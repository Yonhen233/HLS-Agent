import json
from pathlib import Path

from dl_op_to_hls.skills.registry import SkillRegistry
from dl_op_to_hls.skills.schema import evaluate_conditions


ROOT = Path(__file__).parents[1]


def _selected(task_path: str) -> str:
    registry = SkillRegistry(ROOT / "skills")
    registry.load_all()
    task = json.loads((ROOT / task_path).read_text(encoding="utf-8"))
    return registry.find_candidates(task)[0].name


def test_primary_skill_routing_on_realistic_task_distribution():
    assert _selected("examples/mnist_recognition_mlp.json") == "hls4ml_model_flow"
    assert _selected("examples/dense_operator.json") == "operator_fallback_flow"
    assert _selected("examples/existing_hls_project.json") == "existing_hls_project_flow"
    assert _selected("examples/resnet18_boundary.json") == "unsupported_boundary_flow"
    assert _selected("examples/scale_shift_llm_candidate.json") == "llm_candidate_verification_flow"


def test_unknown_named_condition_fails_closed():
    assert evaluate_conditions(["unknown_future_predicate"], {"task_type": "model"}) is False
