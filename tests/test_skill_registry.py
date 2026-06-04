from pathlib import Path

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


def test_unsupported_boundary_skill_allows_schema_validation():
    registry = SkillRegistry(Path("skills"))
    registry.load_all()
    skill = registry.get("unsupported_boundary_flow")
    assert "task.validate_schema" in skill.allowed_tools
    assert skill.recommended_todos[0]["assigned_tool"] == "task.validate_schema"
