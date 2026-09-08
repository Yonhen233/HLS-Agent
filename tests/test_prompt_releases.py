"""Test contracts and regression checks for test_prompt_releases.py.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from dl_op_to_hls.llm import prompts


def test_prompt_release_manifest_controls_runtime_text():
    """Verify the test_prompt_release_manifest_controls_runtime_text contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    context = {
        "release_manifest": {
            "prompt:runtime-prompts": {
                "selected_config": {"prompts": {"todo_planner": "candidate planner prompt"}}
            }
        }
    }
    assert prompts.resolve_prompt(context, "todo_planner") == "candidate planner prompt"
    assert prompts.resolve_prompt(context, "react") == prompts.REACT_SYSTEM_PROMPT


def test_prompt_fingerprints_cover_all_runtime_prompts():
    """Verify the test_prompt_fingerprints_cover_all_runtime_prompts contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    fingerprints = prompts.prompt_fingerprints()
    assert set(fingerprints) == set(prompts.PROMPT_DEFAULTS)
    assert all(len(value) == 12 for value in fingerprints.values())
