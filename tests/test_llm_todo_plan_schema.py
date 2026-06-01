import json

from dl_op_to_hls.llm.actions import build_layered_tool_view
from dl_op_to_hls.llm.client import FakeLLMClient
from dl_op_to_hls.llm.planner import LLMTodoPlanner
from dl_op_to_hls.main_agent.agent import MainAgent
from dl_op_to_hls.specialists.router import build_default_router


def test_llm_todo_plan_schema():
    fake = FakeLLMClient(
        json_responses=[
            {
                "selected_skill": "operator_fallback_flow",
                "skill_usage": "adapted",
                "reason_summary": "dense fallback is suitable",
                "todos": [
                    {
                        "title": "Validate task schema",
                        "assigned_tool": "task.validate_schema",
                        "assigned_specialist": None,
                        "dependencies": [],
                        "inputs": {},
                    }
                ],
            }
        ]
    )
    plan = LLMTodoPlanner().plan(
        task={"task_type": "operator", "name": "dense_16x32", "op_type": "Dense"},
        skill_context={"available_skills": []},
        available_tools=["task.validate_schema"],
        available_specialists=[],
        retrieved_memories=[],
        client=fake,
    )
    assert plan["selected_skill"] == "operator_fallback_flow"


def test_llm_planner_receives_layered_tool_view_without_specialist_private_tools(temp_workspace):
    class RecordingFakeLLMClient(FakeLLMClient):
        user_prompt = ""

        def complete_json(self, system_prompt, user_prompt, schema, temperature=0.0):
            self.user_prompt = user_prompt
            return super().complete_json(system_prompt, user_prompt, schema, temperature)

    agent = MainAgent(temp_workspace, console=False)
    layered = build_layered_tool_view(agent.registry, build_default_router({}))
    fake = RecordingFakeLLMClient(
        json_responses=[
            {
                "selected_skill": "operator_fallback_flow",
                "skill_usage": "adapted",
                "reason_summary": "dense fallback is suitable",
                "todos": [
                    {
                        "title": "Validate task schema",
                        "assigned_tool": "task.validate_schema",
                        "assigned_specialist": None,
                        "dependencies": [],
                        "inputs": {},
                    }
                ],
            }
        ]
    )
    LLMTodoPlanner().plan(
        task={"task_type": "operator", "name": "dense_16x32", "op_type": "Dense"},
        skill_context={"available_skills": []},
        available_tools=layered["direct_tools"],
        available_specialists=[item["name"] for item in layered["specialists"]],
        retrieved_memories=[],
        layered_tool_view=layered,
        client=fake,
    )
    payload = json.loads(fake.user_prompt)
    assert "hls4ml.check_support" not in payload["direct_tools"]
    assert payload["main_agent_actions"]["actions"][0]["name"] == "delegate_to_specialist"
    assert payload["available_specialists"][0]["name"]
    assert "allowed_tools" not in payload["available_specialists"][0]


def test_llm_planner_filters_direct_tools_to_candidate_skill_contract(temp_workspace):
    class RecordingFakeLLMClient(FakeLLMClient):
        user_prompt = ""

        def complete_json(self, system_prompt, user_prompt, schema, temperature=0.0):
            self.user_prompt = user_prompt
            return super().complete_json(system_prompt, user_prompt, schema, temperature)

    agent = MainAgent(temp_workspace, console=False)
    layered = build_layered_tool_view(agent.registry, build_default_router({}))
    fake = RecordingFakeLLMClient(
        json_responses=[
            {
                "selected_skill": "unsupported_boundary_flow",
                "skill_usage": "strict",
                "reason_summary": "boundary task",
                "todos": [
                    {
                        "title": "Generate unsupported report",
                        "assigned_tool": "report.write_unsupported",
                        "assigned_specialist": None,
                        "dependencies": [],
                        "inputs": {},
                    }
                ],
            }
        ]
    )
    LLMTodoPlanner().plan(
        task={"task_type": "model", "name": "resnet18_boundary_demo"},
        skill_context={
            "available_skills": [
                {
                    "name": "unsupported_boundary_flow",
                    "allowed_tools": ["report.write_unsupported", "summary.write_summary"],
                    "allowed_specialists": ["MemorySpecialist"],
                }
            ]
        },
        available_tools=layered["direct_tools"],
        available_specialists=[item["name"] for item in layered["specialists"]],
        retrieved_memories=[],
        layered_tool_view=layered,
        client=fake,
    )
    payload = json.loads(fake.user_prompt)
    assert set(payload["direct_tools"]) <= {"report.write_unsupported", "summary.write_summary"}
    assert payload["skill_tool_contracts"][0]["skill"] == "unsupported_boundary_flow"
