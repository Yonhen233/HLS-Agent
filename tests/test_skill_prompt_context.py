from dl_op_to_hls.skills.prompt_context import SkillPromptContextBuilder
from dl_op_to_hls.skills.registry import SkillRegistry


def test_skill_prompt_context_contains_recommended_todos():
    registry = SkillRegistry("skills")
    registry.load_all()
    task = {
        "task_type": "operator",
        "name": "dense_16x32",
        "op_type": "Dense",
    }
    payload = SkillPromptContextBuilder().build(task, registry, top_k=3)
    assert payload["available_skills"]
    assert payload["available_skills"][0]["recommended_steps"]
