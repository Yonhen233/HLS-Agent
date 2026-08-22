import json

from dl_op_to_hls.llm.client import FakeLLMClient
from dl_op_to_hls.main_agent.agent import MainAgent
from dl_op_to_hls.main_agent.llm_runtime import LLMFirstRuntime
from dl_op_to_hls.main_agent.todo import TodoItem, TodoList
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


def test_llm_plan_repairs_private_tool_with_unambiguous_specialist(temp_workspace, monkeypatch):
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
    assert state.status == "success"
    repaired = [item for item in state.todos if item.assigned_tool == "hls4ml.check_support"]
    assert repaired and repaired[0].assigned_specialist == "HLS4MLSpecialist"
    trace_path = temp_workspace / "runs" / state.run_id / "trace.jsonl"
    events = [json.loads(line)["event"] for line in trace_path.read_text(encoding="utf-8").splitlines()]
    assert "LLMPlanOwnershipRepaired" in events


def test_llm_plan_dependencies_are_normalized_for_hls4ml_flow(temp_workspace, monkeypatch):
    monkeypatch.setenv("DL_OP_TO_HLS_LLM_ENABLED", "1")
    monkeypatch.setenv("DL_OP_TO_HLS_LLM_API_KEY", "fake")
    agent = MainAgent(temp_workspace, console=False)
    runtime = LLMFirstRuntime(agent, llm_client=FakeLLMClient(json_responses=[]))
    state = runtime.initialize(str(temp_workspace / "examples" / "mnist_mlp_hls4ml.json"))
    plan = {
        "selected_skill": "hls4ml_model_flow",
        "skill_usage": "adapted",
        "reason_summary": "Simulate an LLM plan that forgot dependency edges.",
        "todos": [
            {"title": "Validate task schema", "assigned_tool": "task.validate_schema", "assigned_specialist": None, "dependencies": [], "inputs": {}},
            {"title": "Inspect ONNX model", "assigned_tool": "hls4ml.inspect_model", "assigned_specialist": "HLS4MLSpecialist", "dependencies": [], "inputs": {}},
            {"title": "Check hls4ml support for model layers", "assigned_tool": "hls4ml.check_support", "assigned_specialist": "HLS4MLSpecialist", "dependencies": [], "inputs": {}},
            {"title": "Generate hls4ml configuration", "assigned_tool": "hls4ml.generate_config", "assigned_specialist": "HLS4MLSpecialist", "dependencies": [], "inputs": {}},
            {"title": "Convert model to HLS C++", "assigned_tool": "hls4ml.convert", "assigned_specialist": "HLS4MLSpecialist", "dependencies": [], "inputs": {}},
            {"title": "Create Vivado HLS project", "assigned_tool": "vivado.create_project", "assigned_specialist": "VivadoSpecialist", "dependencies": [], "inputs": {}},
            {"title": "Run C synthesis", "assigned_tool": "vivado.run_csynth", "assigned_specialist": "VivadoSpecialist", "dependencies": [], "inputs": {}},
            {"title": "Parse synthesis report", "assigned_tool": "vivado.parse_report", "assigned_specialist": "VivadoSpecialist", "dependencies": [], "inputs": {}},
            {"title": "Generate optimization suggestions", "assigned_tool": "suggestion.suggest_optimization", "assigned_specialist": "OptimizationSpecialist", "dependencies": [], "inputs": {}},
            {"title": "Write run summary", "assigned_tool": "summary.write_summary", "assigned_specialist": None, "dependencies": [], "inputs": {}},
            {"title": "Promote memories", "assigned_tool": "memory.promote_to_long_term", "assigned_specialist": "MemorySpecialist", "dependencies": [], "inputs": {}},
        ],
    }

    runtime._create_todos_from_llm_plan(state, plan)
    by_tool = {item.assigned_tool: item for item in state.todos}

    assert by_tool["hls4ml.check_support"].dependencies == [by_tool["hls4ml.inspect_model"].id]
    assert by_tool["hls4ml.generate_config"].dependencies == [by_tool["hls4ml.check_support"].id]
    assert by_tool["hls4ml.convert"].dependencies == [by_tool["hls4ml.generate_config"].id]
    assert by_tool["vivado.create_project"].dependencies == [by_tool["hls4ml.convert"].id]
    assert by_tool["vivado.run_csynth"].dependencies == [by_tool["vivado.create_project"].id]
    assert by_tool["vivado.parse_report"].dependencies == [by_tool["vivado.run_csynth"].id]
    assert by_tool["suggestion.suggest_optimization"].dependencies == [by_tool["vivado.parse_report"].id]
    assert by_tool["summary.write_summary"].dependencies == [by_tool["suggestion.suggest_optimization"].id]
    assert by_tool["memory.promote_to_long_term"].dependencies == [by_tool["summary.write_summary"].id]


def test_llm_plan_normalization_breaks_summary_memory_cycles(temp_workspace, monkeypatch):
    monkeypatch.setenv("DL_OP_TO_HLS_LLM_ENABLED", "1")
    monkeypatch.setenv("DL_OP_TO_HLS_LLM_API_KEY", "fake")
    agent = MainAgent(temp_workspace, console=False)
    runtime = LLMFirstRuntime(agent, llm_client=FakeLLMClient(json_responses=[]))
    state = runtime.initialize(str(temp_workspace / "examples" / "mnist_tiny_cnn.json"))
    plan = {
        "selected_skill": "hls4ml_model_flow",
        "skill_usage": "adapted",
        "reason_summary": "Simulate a real LLM plan that created a finalization cycle.",
        "todos": [
            {"title": "Validate task schema", "assigned_tool": "task.validate_schema", "assigned_specialist": None, "dependencies": [], "inputs": {}},
            {"title": "Inspect ONNX model", "assigned_tool": "hls4ml.inspect_model", "assigned_specialist": "HLS4MLSpecialist", "dependencies": [], "inputs": {}},
            {"title": "Check hls4ml support", "assigned_tool": "hls4ml.check_support", "assigned_specialist": "HLS4MLSpecialist", "dependencies": [], "inputs": {}},
            {"title": "Generate hls4ml configuration", "assigned_tool": "hls4ml.generate_config", "assigned_specialist": "HLS4MLSpecialist", "dependencies": [], "inputs": {}},
            {"title": "Convert model to HLS", "assigned_tool": "hls4ml.convert", "assigned_specialist": "HLS4MLSpecialist", "dependencies": [], "inputs": {}},
            {"title": "Create Vivado HLS project", "assigned_tool": "vivado.create_project", "assigned_specialist": "VivadoSpecialist", "dependencies": [], "inputs": {}},
            {"title": "Run C synthesis", "assigned_tool": "vivado.run_csynth", "assigned_specialist": "VivadoSpecialist", "dependencies": [], "inputs": {}},
            {"title": "Parse synthesis report", "assigned_tool": "vivado.parse_report", "assigned_specialist": "VivadoSpecialist", "dependencies": [], "inputs": {}},
            {"title": "Suggest balanced optimization", "assigned_tool": "suggestion.suggest_optimization", "assigned_specialist": "OptimizationSpecialist", "dependencies": [], "inputs": {}},
            {"title": "Promote run to long-term memory", "assigned_tool": "memory.promote_to_long_term", "assigned_specialist": "MemorySpecialist", "dependencies": ["Write final summary"], "inputs": {}},
            {"title": "Write final summary", "assigned_tool": "summary.write_summary", "assigned_specialist": None, "dependencies": ["Promote run to long-term memory"], "inputs": {}},
        ],
    }

    runtime._create_todos_from_llm_plan(state, plan)
    by_tool = {item.assigned_tool: item for item in state.todos}

    assert by_tool["summary.write_summary"].dependencies == [by_tool["suggestion.suggest_optimization"].id]
    assert by_tool["memory.promote_to_long_term"].dependencies == [by_tool["summary.write_summary"].id]


def test_llm_runtime_auto_delegates_preassigned_specialist_todo(temp_workspace, monkeypatch):
    monkeypatch.setenv("DL_OP_TO_HLS_LLM_ENABLED", "1")
    monkeypatch.setenv("DL_OP_TO_HLS_LLM_API_KEY", "fake")
    agent = MainAgent(temp_workspace, console=False)
    runtime = LLMFirstRuntime(agent, llm_client=FakeLLMClient(json_responses=[]))
    state = runtime.initialize(str(temp_workspace / "examples" / "dense_operator.json"))
    todo = TodoItem(
        id="todo_001",
        title="Promote memories",
        description="Promote run context and memory candidates.",
        status="pending",
        priority=1,
        dependencies=[],
        assigned_tool="memory.promote_to_long_term",
        assigned_specialist="MemorySpecialist",
        inputs={},
        outputs=None,
        error=None,
    )
    runtime.todo_manager.todo_list = TodoList(run_id=state.run_id, items=[todo])
    state.todos = [todo]

    observation = runtime.execute_todo_with_react(state, todo)

    assert observation["status"] == "completed"
    assert todo.status == "completed"
    assert todo.specialist_result["specialist_name"] == "MemorySpecialist"
    assert todo.react_steps[-1]["action"]["type"] == "delegate_to_specialist"
    trace_path = temp_workspace / "runs" / state.run_id / "trace.jsonl"
    events = [json.loads(line)["event"] for line in trace_path.read_text(encoding="utf-8").splitlines()]
    assert "LLMReActAutoDelegated" in events
    assert "LLMReActFailed" not in events


def test_llm_runtime_auto_executes_preassigned_atomic_tool(temp_workspace, monkeypatch):
    monkeypatch.setenv("DL_OP_TO_HLS_LLM_ENABLED", "1")
    monkeypatch.setenv("DL_OP_TO_HLS_LLM_API_KEY", "fake")
    agent = MainAgent(temp_workspace, console=False)
    runtime = LLMFirstRuntime(agent, llm_client=FakeLLMClient(json_responses=[]))
    state = runtime.initialize(str(temp_workspace / "examples" / "dense_operator.json"))
    todo = TodoItem(
        id="todo_001",
        title="Validate task",
        description="Validate task",
        status="pending",
        priority=1,
        dependencies=[],
        assigned_tool="task.validate_schema",
        assigned_specialist=None,
        inputs={"task": state.task},
        outputs=None,
        error=None,
    )
    runtime.todo_manager.todo_list = TodoList(run_id=state.run_id, items=[todo])
    state.todos = [todo]

    observation = runtime.execute_todo_with_react(state, todo)

    assert observation["status"] == "completed"
    assert todo.status == "completed"
    assert todo.react_steps[-1]["action"]["type"] == "direct_tool_only_when_no_specialist"
    trace_path = temp_workspace / "runs" / state.run_id / "trace.jsonl"
    events = [json.loads(line)["event"] for line in trace_path.read_text(encoding="utf-8").splitlines()]
    assert "LLMReActAutoDirect" in events
    assert "LLMCallStarted" not in events
