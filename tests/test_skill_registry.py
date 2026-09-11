"""Test contracts and regression checks for test_skill_registry.py.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from pathlib import Path

from dl_op_to_hls.skills.prompt_context import SkillPromptContextBuilder
from dl_op_to_hls.skills.registry import SkillRegistry
from dl_op_to_hls.skills.schema import SkillValidator
from dl_op_to_hls.main_agent.state import AgentState
from dl_op_to_hls.main_agent.todo import TodoItem
from dl_op_to_hls.specialists.context import ContextBuilder


def test_skill_registry_loads_yaml():
    """Verify the test_skill_registry_loads_yaml contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    registry = SkillRegistry(Path("skills"))
    registry.load_all()
    assert registry.list_skills()


def test_operator_fallback_skill_exists():
    """Verify the test_operator_fallback_skill_exists contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    registry = SkillRegistry(Path("skills"))
    registry.load_all()
    skill = registry.get("operator_fallback_flow")
    assert skill.intent == "operator_to_hls_fallback"


def test_hls4ml_model_skill_exists():
    """Verify the test_hls4ml_model_skill_exists contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    registry = SkillRegistry(Path("skills"))
    registry.load_all()
    skill = registry.get("hls4ml_model_flow")
    assert skill.trigger["task_type"] == "model"


def test_hls4ml_model_skill_accepts_qonnx_frontend():
    """Verify the test_hls4ml_model_skill_accepts_qonnx_frontend contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
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
    """Verify the test_llm_candidate_verification_skill_exists contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    registry = SkillRegistry(Path("skills"))
    registry.load_all()
    skill = registry.get("llm_candidate_verification_flow")
    assert "llm.generate_hls_candidate" in skill.allowed_tools
    assert "llm.generate_candidate" in skill.allowed_tools
    assert skill.failure_policy["VerificationFailedError"]["max_repair_attempts"] >= 4


def test_scale_shift_routes_to_llm_candidate_skill():
    """Verify the test_scale_shift_routes_to_llm_candidate_skill contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
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
    """Verify the test_llm_candidate_required_prompt_context_exposes_only_candidate_skill contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
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


def test_unverifiable_capability_boundary_exposes_no_planner_skill():
    """Verify the test_unverifiable_capability_boundary_exposes_only_unsupported_skill contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
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

    assert context["available_skills"] == []
    assert "runtime capability gate owns this terminal outcome" in context["selection_notes"][0]


def test_unsupported_boundary_skill_allows_schema_validation():
    """Verify the test_unsupported_boundary_skill_allows_schema_validation contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    registry = SkillRegistry(Path("skills"))
    registry.load_all()
    skill = registry.get("unsupported_boundary_flow")
    assert "task.validate_schema" in skill.allowed_tools
    assert skill.recommended_todos[0]["assigned_tool"] == "task.validate_schema"


def test_all_approved_skills_include_playbook_guidance():
    """Every shipped skill exposes both a contract and execution guidance."""
    registry = SkillRegistry(Path("skills"))
    registry.load_all()

    assert len(registry.list_skills()) >= 10
    for skill in registry.list_skills():
        assert skill.purpose
        assert skill.procedure
        assert skill.decision_rules
        assert skill.pitfalls
        assert skill.verification_guidance
        assert skill.examples


def test_skill_prompt_context_exposes_guidance_to_planner():
    """Planner context includes the natural-language layer, not only tool names."""
    registry = SkillRegistry(Path("skills"))
    registry.load_all()
    context = SkillPromptContextBuilder().build(
        {"task_type": "operator", "op_type": "Dense", "objective": "latency"},
        registry,
    )

    skill = next(item for item in context["available_skills"] if item["name"] == "operator_fallback_flow")
    assert skill["purpose"]
    assert skill["procedure"]
    assert skill["decision_rules"]
    assert skill["pitfalls"]
    assert skill["verification_guidance"]


def test_skill_guidance_schema_rejects_non_text_procedure():
    """Guidance remains machine-checkable even though it is written for the LLM."""
    payload = {
        "name": "guidance_test",
        "version": "1.0.0",
        "status": "candidate",
        "description": "A test skill",
        "intent": "test",
        "trigger": {},
        "recommended_todos": [{"title": "Run", "assigned_tool": "tool.run"}],
        "allowed_tools": ["tool.run"],
        "allowed_specialists": [],
        "required_artifacts": [],
        "failure_policy": {},
        "verification_policy": {},
        "memory_policy": {},
        "purpose": "Test guidance",
        "procedure": ["valid", 42],
        "decision_rules": ["valid"],
        "pitfalls": ["valid"],
        "verification_guidance": ["valid"],
        "examples": [{"scenario": "test"}],
    }
    report = SkillValidator().validate_document(payload)
    assert not report.valid
    assert any("procedure" in error for error in report.errors)


def test_selected_skill_guidance_is_scoped_into_specialist_context():
    """Only the selected role's playbook guidance enters ContextEnvelope."""
    registry = SkillRegistry(Path("skills"))
    registry.load_all()
    state = AgentState(
        run_id="skill-guidance-run",
        task={"task_type": "operator", "name": "dense", "op_type": "Dense", "target": {}},
        objective="latency",
    )
    state.selected_skill = "operator_fallback_flow"
    todo = TodoItem(
        id="todo_001",
        title="Generate fallback HLS",
        description="Generate fallback HLS",
        status="pending",
        priority=1,
        dependencies=[],
        assigned_tool="fallback.generate_operator_hls",
        assigned_specialist="CodegenSpecialist",
        inputs={},
        outputs=None,
        error=None,
    )
    envelope = ContextBuilder(skill_registry=registry).build_for_specialist(state, todo, "CodegenSpecialist")
    guidance = envelope.scoped_state.get("skill_guidance")
    assert "skill_guidance" not in envelope.scoped_state

    todo.assigned_specialist = "VivadoSpecialist"
    envelope = ContextBuilder(skill_registry=registry).build_for_specialist(state, todo, "VivadoSpecialist")
    guidance = envelope.scoped_state["skill_guidance"]
    assert guidance["name"] == "operator_fallback_flow"
    assert "allowed_tools" not in guidance


def test_skill_catalog_is_compact_first_disclosure():
    """Candidate selection receives a bounded preview, not the full playbook."""
    registry = SkillRegistry(Path("skills"))
    registry.load_all()
    skill = registry.get("operator_fallback_flow")
    catalog = skill.to_catalog_summary()
    assert catalog["disclosure_level"] == "catalog"
    assert len(catalog["procedure"]) <= 3
    assert len(catalog["decision_rules"]) <= 3
    assert len(catalog["verification_guidance"]) <= 2
