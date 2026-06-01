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


def test_llm_candidate_verification_skill_exists():
    registry = SkillRegistry(Path("skills"))
    registry.load_all()
    skill = registry.get("llm_candidate_verification_flow")
    assert "llm.generate_hls_candidate" in skill.allowed_tools
