from dl_op_to_hls.llm.client import FakeLLMClient
from dl_op_to_hls.main_agent.agent import MainAgent
from dl_op_to_hls.main_agent.workflow import run_task_llm


def test_llm_plan_rejects_unknown_tool(temp_workspace, monkeypatch):
    monkeypatch.setenv("DL_OP_TO_HLS_LLM_ENABLED", "1")
    monkeypatch.setenv("DL_OP_TO_HLS_LLM_API_KEY", "fake")
    plan = {
        "selected_skill": "operator_fallback_flow",
        "skill_usage": "adapted",
        "reason_summary": "test",
        "todos": [
            {
                "title": "Bad",
                "assigned_tool": "unknown.tool",
                "assigned_specialist": None,
                "dependencies": [],
                "inputs": {},
            }
        ],
    }
    fake = FakeLLMClient(json_responses=[plan, plan])
    agent = MainAgent(temp_workspace, console=False)
    state = run_task_llm(str(temp_workspace / "examples" / "dense_operator.json"), agent=agent, llm_client=fake)
    assert state.status == "failed"
    assert any("unknown.tool" in item.get("message", "") for item in state.errors)


def test_llm_plan_rejects_unknown_specialist(temp_workspace, monkeypatch):
    monkeypatch.setenv("DL_OP_TO_HLS_LLM_ENABLED", "1")
    monkeypatch.setenv("DL_OP_TO_HLS_LLM_API_KEY", "fake")
    plan = {
        "selected_skill": "operator_fallback_flow",
        "skill_usage": "adapted",
        "reason_summary": "test",
        "todos": [
            {
                "title": "Bad Specialist",
                "assigned_tool": "task.validate_schema",
                "assigned_specialist": "UnknownSpecialist",
                "dependencies": [],
                "inputs": {},
            }
        ],
    }
    fake = FakeLLMClient(json_responses=[plan, plan])
    agent = MainAgent(temp_workspace, console=False)
    state = run_task_llm(str(temp_workspace / "examples" / "dense_operator.json"), agent=agent, llm_client=fake)
    assert state.status == "failed"
    assert any("UnknownSpecialist" in item.get("message", "") for item in state.errors)


def test_llm_plan_rejects_tool_specialist_mismatch(temp_workspace, monkeypatch):
    monkeypatch.setenv("DL_OP_TO_HLS_LLM_ENABLED", "1")
    monkeypatch.setenv("DL_OP_TO_HLS_LLM_API_KEY", "fake")
    plan = {
        "selected_skill": "hls4ml_model_flow",
        "skill_usage": "adapted",
        "reason_summary": "test",
        "todos": [
            {
                "title": "Bad Assignment",
                "assigned_tool": "task.validate_schema",
                "assigned_specialist": "HLS4MLSpecialist",
                "dependencies": [],
                "inputs": {},
            }
        ],
    }
    fake = FakeLLMClient(json_responses=[plan, plan])
    agent = MainAgent(temp_workspace, console=False)
    state = run_task_llm(str(temp_workspace / "examples" / "mlp_onnx_example.json"), agent=agent, llm_client=fake)
    assert state.status == "failed"
    assert any("outside allowed_tools" in item.get("message", "") for item in state.errors)


def test_llm_plan_rejects_private_tool_without_specialist(temp_workspace, monkeypatch):
    monkeypatch.setenv("DL_OP_TO_HLS_LLM_ENABLED", "1")
    monkeypatch.setenv("DL_OP_TO_HLS_LLM_API_KEY", "fake")
    plan = {
        "selected_skill": "hls4ml_model_flow",
        "skill_usage": "adapted",
        "reason_summary": "test",
        "todos": [
            {
                "title": "Private Tool Without Owner",
                "assigned_tool": "hls4ml.check_support",
                "assigned_specialist": None,
                "dependencies": [],
                "inputs": {},
            }
        ],
    }
    fake = FakeLLMClient(json_responses=[plan, plan])
    agent = MainAgent(temp_workspace, console=False)
    state = run_task_llm(str(temp_workspace / "examples" / "mlp_onnx_example.json"), agent=agent, llm_client=fake)
    assert state.status == "failed"
    assert any("specialist-private tool" in item.get("message", "") for item in state.errors)
