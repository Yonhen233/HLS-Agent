from copy import deepcopy

from dl_op_to_hls.main_agent.agent import MainAgent
from dl_op_to_hls.skills.policy import SkillPolicy
from dl_op_to_hls.skills.registry import SkillRegistry
from dl_op_to_hls.specialists.router import build_default_router


def test_skill_policy_rejects_unknown_tool(temp_workspace):
    agent = MainAgent(temp_workspace, console=False)
    registry = SkillRegistry(temp_workspace / "skills")
    registry.load_all()
    skill = registry.get("operator_fallback_flow")
    plan = {
        "selected_skill": "operator_fallback_flow",
        "skill_usage": "adapted",
        "reason_summary": "test",
        "todos": [{"title": "x", "assigned_tool": "unknown.tool", "assigned_specialist": None}],
    }
    result = SkillPolicy().validate_llm_plan_against_skill(plan, skill)
    assert result["status"] == "invalid"


def test_validate_skill_references_existing_tools(temp_workspace):
    agent = MainAgent(temp_workspace, console=False)
    registry = SkillRegistry(temp_workspace / "skills")
    registry.load_all()
    skill = registry.get("hls4ml_model_flow")
    result = SkillPolicy().validate_skill(skill, agent.registry, build_default_router())
    assert result["status"] == "valid"
