"""Test contracts and regression checks for test_skill_prompt_context.py.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from dl_op_to_hls.skills.prompt_context import SkillPromptContextBuilder
from dl_op_to_hls.skills.registry import SkillRegistry


def test_skill_prompt_context_contains_recommended_todos():
    """Verify the test_skill_prompt_context_contains_recommended_todos contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
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
