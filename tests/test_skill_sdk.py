"""Test contracts and regression checks for test_skill_sdk.py.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from dl_op_to_hls.skills.schema import SkillValidator, evaluate_conditions


def _payload():
    """Verify the _payload contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    return {
        "name": "test_skill",
        "version": "1.2.0",
        "status": "candidate",
        "description": "A test skill",
        "intent": "test",
        "trigger": {"conditions": [{"field": "task.frontend", "op": "eq", "value": "onnx"}]},
        "preconditions": [],
        "recommended_todos": [
            {"id": "inspect", "title": "Inspect", "assigned_tool": "workspace.search", "dependencies": []},
            {"id": "convert", "title": "Convert", "assigned_tool": "hls4ml.convert", "dependencies": ["inspect"]},
        ],
        "allowed_tools": ["workspace.search", "hls4ml.convert"],
        "allowed_specialists": [],
        "required_artifacts": [],
        "failure_policy": {},
        "verification_policy": {},
        "memory_policy": {},
        "dependencies": [{"name": "base", "version": ">=1.0.0"}],
        "permissions": {"risk_level": "medium", "capabilities": ["workspace.read"]},
        "budget_policy": {"max_steps": 5, "max_tool_calls": 10},
        "concurrency_policy": {"max_parallel_tools": 2},
    }


def test_skill_schema_and_condition_dsl():
    """Verify the test_skill_schema_and_condition_dsl contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    report = SkillValidator().validate_document(_payload())
    assert report.valid
    assert evaluate_conditions(
        [{"field": "task.frontend", "op": "eq", "value": "onnx"}],
        {"task": {"frontend": "onnx"}},
    )
    assert not evaluate_conditions(
        [{"field": "task.frontend", "op": "eq", "value": "onnx"}],
        {"task": {"frontend": "keras"}},
    )


def test_skill_linter_rejects_cycle_and_unbounded_concurrency():
    """Verify the test_skill_linter_rejects_cycle_and_unbounded_concurrency contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    payload = _payload()
    payload["recommended_todos"][0]["dependencies"] = ["convert"]
    payload["concurrency_policy"]["max_parallel_tools"] = 100
    report = SkillValidator().validate_document(payload)
    assert not report.valid
    assert any("cycle" in item for item in report.errors)
    assert any("exceed" in item for item in report.errors)
