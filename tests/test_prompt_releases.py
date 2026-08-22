from dl_op_to_hls.llm import prompts


def test_prompt_release_manifest_controls_runtime_text():
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
    fingerprints = prompts.prompt_fingerprints()
    assert set(fingerprints) == set(prompts.PROMPT_DEFAULTS)
    assert all(len(value) == 12 for value in fingerprints.values())
