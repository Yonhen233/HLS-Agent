from pathlib import Path

from dl_op_to_hls.skills.prompt_context import SkillPromptContextBuilder
from dl_op_to_hls.skills.registry import SkillRegistry


def test_skill_registry_loads_yaml():
    registry = SkillRegistry(Path("skills"))
    registry.load_all()
    assert registry.list_skills()


def test_operator_fallback_skill_exists():
    registry = SkillRegistry(Path("skills"))
    registry.load_all()
    skill = registry.get("operator_fallback_flow")
    assert skill.intent == "operator_to_hls_fallback"


def test_hls4ml_model_skill_exists():
    registry = SkillRegistry(Path("skills"))
    registry.load_all()
    skill = registry.get("hls4ml_model_flow")
    assert skill.trigger["task_type"] == "model"


def test_hls4ml_model_skill_accepts_qonnx_frontend():
    registry = SkillRegistry(Path("skills"))
    registry.load_all()
    candidates = registry.find_candidates(
        {
            "task_type": "model",
            "name": "mnist_qonnx_cnn",
            "frontend": "qonnx",
            "objective": "resource",
        }
    )
    assert candidates[0].name == "hls4ml_model_flow"


def test_llm_candidate_verification_skill_exists():
    registry = SkillRegistry(Path("skills"))
    registry.load_all()
    skill = registry.get("llm_candidate_verification_flow")
    assert "llm.generate_hls_candidate" in skill.allowed_tools
    assert "llm.generate_candidate" in skill.allowed_tools
    assert skill.failure_policy["VerificationFailedError"]["max_repair_attempts"] >= 4


def test_scale_shift_routes_to_llm_candidate_skill():
    registry = SkillRegistry(Path("skills"))
    registry.load_all()
    candidates = registry.find_candidates(
        {
            "task_type": "operator",
            "op_type": "ScaleShift",
            "name": "scale_shift_llm",
            "llm_candidate": {"required": True},
        }
    )
    assert candidates
    assert candidates[0].name == "llm_candidate_verification_flow"


def test_llm_candidate_required_prompt_context_exposes_only_candidate_skill():
    registry = SkillRegistry(Path("skills"))
    registry.load_all()
    context = SkillPromptContextBuilder().build(
        {
            "task_type": "operator",
            "op_type": "Dense",
            "name": "dense_16x32_llm",
            "llm_candidate": {"required": True},
        },
        registry,
    )

    assert [skill["name"] for skill in context["available_skills"]] == ["llm_candidate_verification_flow"]
    assert "do not route back to fallback_template" in context["selection_notes"][0]


def test_unverifiable_capability_boundary_exposes_only_unsupported_skill():
    registry = SkillRegistry(Path("skills"))
    registry.load_all()
    context = SkillPromptContextBuilder().build(
        {
            "task_type": "operator",
            "op_type": "CustomUnsupported",
            "name": "custom_unknown",
            "capability_boundary": {"kind": "unverifiable_operator_semantics"},
            "demo": {"expected_path": "unsupported_report"},
            "llm_candidate": {"required": False, "eligible": False},
        },
        registry,
    )

    assert [skill["name"] for skill in context["available_skills"]] == ["unsupported_boundary_flow"]
    assert "do not call LLM candidate or Vivado tools" in context["selection_notes"][0]


def test_unsupported_boundary_skill_allows_schema_validation():
    registry = SkillRegistry(Path("skills"))
    registry.load_all()
    skill = registry.get("unsupported_boundary_flow")
    assert "task.validate_schema" in skill.allowed_tools
    assert skill.recommended_todos[0]["assigned_tool"] == "task.validate_schema"
