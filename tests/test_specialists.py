from __future__ import annotations

import json
from pathlib import Path

from dl_op_to_hls.main_agent.agent import MainAgent
from dl_op_to_hls.main_agent.state import AgentState
from dl_op_to_hls.main_agent.todo import TodoItem
from dl_op_to_hls.main_agent.workflow import run_task
from dl_op_to_hls.specialists import (
    ContextBuilder,
    HLS4MLSpecialist,
    MemorySpecialist,
    OptimizationSpecialist,
    SpecialistResult,
    SpecialistRouter,
    VerificationSpecialist,
    VivadoSpecialist,
)


def _todo(title: str, tool: str, specialist: str | None = None) -> TodoItem:
    return TodoItem(
        id="todo_001",
        title=title,
        description=title,
        status="pending",
        priority=1,
        dependencies=[],
        assigned_tool=tool,
        assigned_specialist=specialist,
        inputs={},
        outputs=None,
        error=None,
    )


def _dense_state(temp_workspace: Path) -> AgentState:
    task = json.loads((temp_workspace / "examples" / "dense_operator.json").read_text(encoding="utf-8"))
    state = AgentState(run_id="r1", task=task, objective="latency")
    state.hls_project_dir = str(temp_workspace / "examples" / "hls_projects" / "dense")
    state.artifacts["trace"] = str(temp_workspace / "runs" / "r1" / "trace.jsonl")
    state.artifacts["tcl"] = str(temp_workspace / "examples" / "hls_projects" / "dense" / "run_hls.tcl")
    state.report = {
        "status": "success",
        "latency": {"min_cycles": 45, "max_cycles": 45},
        "interval": {"min_ii": 1, "max_ii": 1},
        "resources": {"bram": 0, "dsp": 32, "ff": 2100, "lut": 3500},
        "timing": {"target_ns": 5.0, "estimated_ns": 4.3, "met": True},
    }
    state.rag_context = [{"summary": "Dense high DSP can improve by increasing reuse factor.", "source": "unit"}]
    state.retrieved_memories = [{"text": "Dense reuse factor tradeoff", "source_run_id": "old"}]
    return state


def test_context_builder_scopes_hls4ml_context(temp_workspace):
    state = AgentState(
        run_id="r1",
        task=json.loads((temp_workspace / "examples" / "mlp_onnx_example.json").read_text(encoding="utf-8")),
        objective="latency",
    )
    envelope = ContextBuilder().build_for_specialist(state, _todo("Check hls4ml support", "hls4ml.check_support"), "HLS4MLSpecialist")
    assert envelope.scoped_state["model_path"]
    assert "vivado_work_dir" not in envelope.scoped_state
    assert "full_trace" in envelope.constraints["exclude"]


def test_context_builder_scopes_vivado_context(temp_workspace):
    state = _dense_state(temp_workspace)
    envelope = ContextBuilder().build_for_specialist(state, _todo("Run Vivado HLS synthesis", "vivado.run_csynth"), "VivadoSpecialist")
    assert envelope.scoped_state["hls_project_dir"]
    assert envelope.scoped_state["top_function"] == "dense_16x32"
    assert "task" not in envelope.scoped_state


def test_context_builder_excludes_raw_logs(temp_workspace):
    state = _dense_state(temp_workspace)
    state.artifacts["vivado_log"] = str(temp_workspace / "runs" / "r1" / "vivado_hls.log")
    envelope = ContextBuilder().build_for_specialist(state, _todo("Generate optimization suggestions", "suggestion.suggest_optimization"), "OptimizationSpecialist")
    assert "raw_logs" in envelope.constraints["exclude"]
    assert all(ref["type"] != "vivado_log" for ref in envelope.artifact_refs)


def test_context_builder_excludes_full_trace(temp_workspace):
    state = _dense_state(temp_workspace)
    envelope = ContextBuilder().build_for_specialist(state, _todo("Run Vivado HLS synthesis", "vivado.run_csynth"), "VivadoSpecialist")
    assert all(ref["type"] != "trace" for ref in envelope.artifact_refs)


def test_context_builder_includes_artifact_refs(temp_workspace):
    state = _dense_state(temp_workspace)
    envelope = ContextBuilder().build_for_specialist(state, _todo("Run Vivado HLS synthesis", "vivado.run_csynth"), "VivadoSpecialist")
    assert {"type": "tcl", "path": state.artifacts["tcl"]} in envelope.artifact_refs


def test_specialist_receives_context_envelope_not_full_state(temp_workspace):
    state = _dense_state(temp_workspace)
    envelope = ContextBuilder().build_for_specialist(state, _todo("Run Vivado HLS synthesis", "vivado.run_csynth"), "VivadoSpecialist")
    payload = envelope.to_dict()
    assert "tool_results" not in payload
    assert "todos" not in payload


def test_specialist_cannot_call_disallowed_tool(temp_workspace):
    agent = MainAgent(temp_workspace, console=False)
    context = agent.create_run_context("r1")
    specialist = OptimizationSpecialist(context)
    envelope = ContextBuilder().build_for_specialist(_dense_state(temp_workspace), _todo("Generate optimization suggestions", "suggestion.suggest_optimization"), "OptimizationSpecialist")
    result = specialist._call_tool("hls4ml.inspect_model", {}, envelope, agent.registry, agent.permission_gate)
    assert result["error"]["error_type"] == "PermissionDeniedError"


def test_specialist_result_schema():
    result = SpecialistResult("VivadoSpecialist", "todo_001", "success", "ok", context_usage={"compression_ratio": 0.1})
    payload = result.to_dict()
    assert payload["specialist_name"] == "VivadoSpecialist"
    assert payload["context_usage"]["compression_ratio"] == 0.1


def test_specialist_result_context_usage(temp_workspace):
    agent = MainAgent(temp_workspace, console=False)
    context = agent.create_run_context("r1")
    specialist = HLS4MLSpecialist(context)
    state = AgentState(
        run_id="r1",
        task=json.loads((temp_workspace / "examples" / "dense_operator.json").read_text(encoding="utf-8")),
        objective="latency",
    )
    envelope = ContextBuilder().build_for_specialist(state, _todo("Check hls4ml support", "hls4ml.check_support"), "HLS4MLSpecialist")
    result = specialist.handle(envelope, agent.registry, agent.permission_gate)
    assert "compression_ratio" in result.context_usage


def test_router_routes_hls4ml_todo():
    router = SpecialistRouter([HLS4MLSpecialist(), VivadoSpecialist(), VerificationSpecialist(), OptimizationSpecialist(), MemorySpecialist()])
    assert router.route(_todo("Check hls4ml support", "hls4ml.check_support")).name == "HLS4MLSpecialist"


def test_router_routes_vivado_todo():
    router = SpecialistRouter([HLS4MLSpecialist(), VivadoSpecialist(), VerificationSpecialist(), OptimizationSpecialist(), MemorySpecialist()])
    assert router.route(_todo("Run Vivado HLS synthesis", "vivado.run_csynth")).name == "VivadoSpecialist"


def test_router_routes_verification_todo():
    router = SpecialistRouter([HLS4MLSpecialist(), VivadoSpecialist(), VerificationSpecialist(), OptimizationSpecialist(), MemorySpecialist()])
    assert router.route(_todo("Verify LLM candidate", "verify_candidate.run")).name == "VerificationSpecialist"


def test_router_routes_optimization_todo():
    router = SpecialistRouter([HLS4MLSpecialist(), VivadoSpecialist(), VerificationSpecialist(), OptimizationSpecialist(), MemorySpecialist()])
    assert router.route(_todo("Generate optimization suggestions", "suggestion.suggest_optimization")).name == "OptimizationSpecialist"


def test_router_routes_memory_todo():
    router = SpecialistRouter([HLS4MLSpecialist(), VivadoSpecialist(), VerificationSpecialist(), OptimizationSpecialist(), MemorySpecialist()])
    assert router.route(_todo("Promote memories", "memory.promote_to_long_term")).name == "MemorySpecialist"


def test_hls4ml_specialist_mock_success(temp_workspace):
    agent = MainAgent(temp_workspace, console=False)
    context = agent.create_run_context("r1")
    specialist = HLS4MLSpecialist(context)
    state = AgentState(run_id="r1", task=json.loads((temp_workspace / "examples" / "dense_operator.json").read_text(encoding="utf-8")), objective="latency")
    envelope = ContextBuilder().build_for_specialist(state, _todo("Check hls4ml support", "hls4ml.check_support"), "HLS4MLSpecialist")
    result = specialist.handle(envelope, agent.registry, agent.permission_gate)
    assert result.status == "partial_success"
    assert any(item.get("tool") == "hls4ml.check_support" for item in result.observations)


def test_vivado_specialist_mock_success(temp_workspace):
    agent = MainAgent(temp_workspace, console=False)
    context = agent.create_run_context("r1")
    specialist = VivadoSpecialist(context)
    envelope = ContextBuilder().build_for_specialist(_dense_state(temp_workspace), _todo("Run Vivado HLS synthesis", "vivado.run_csynth"), "VivadoSpecialist")
    result = specialist.handle(envelope, agent.registry, agent.permission_gate)
    assert result.status == "success"
    assert result.metrics["latency"]["min_cycles"] == 45


def test_vivado_specialist_missing_binary_partial_success(temp_workspace, monkeypatch):
    monkeypatch.setenv("DL_OP_TO_HLS_MOCK_VIVADO", "0")
    agent = MainAgent(temp_workspace, console=False)
    context = agent.create_run_context("r1")
    specialist = VivadoSpecialist(context)
    envelope = ContextBuilder().build_for_specialist(_dense_state(temp_workspace), _todo("Run Vivado HLS synthesis", "vivado.run_csynth"), "VivadoSpecialist")
    result = specialist.handle(envelope, agent.registry, agent.permission_gate)
    assert result.status == "partial_success"
    assert result.errors[0]["error_type"] == "VivadoNotFoundError"


def test_verification_specialist_mock_success(temp_workspace):
    agent = MainAgent(temp_workspace, console=False)
    context = agent.create_run_context("r1")
    state = _dense_state(temp_workspace)
    specialist = VerificationSpecialist(context)
    envelope = ContextBuilder().build_for_specialist(state, _todo("Verify LLM candidate", "verify_candidate.run"), "VerificationSpecialist")
    result = specialist.handle(envelope, agent.registry, agent.permission_gate)
    assert result.status == "success"
    assert result.memory_candidates


def test_optimization_specialist_uses_rag_context(temp_workspace):
    agent = MainAgent(temp_workspace, console=False)
    context = agent.create_run_context("r1")
    specialist = OptimizationSpecialist(context)
    envelope = ContextBuilder().build_for_specialist(_dense_state(temp_workspace), _todo("Generate optimization suggestions", "suggestion.suggest_optimization"), "OptimizationSpecialist")
    result = specialist.handle(envelope, agent.registry, agent.permission_gate)
    assert result.status == "success"
    assert result.metrics["suggestions"]


def test_memory_specialist_promotes_candidates(temp_workspace):
    agent = MainAgent(temp_workspace, console=False)
    context = agent.create_run_context("r1")
    state = _dense_state(temp_workspace)
    state.status = "partial_success"
    state.selected_path = "fallback_template_path"
    context["artifact_manager"].write_json("state.json", state.to_dict(), "state")
    specialist = MemorySpecialist(context)
    envelope = ContextBuilder().build_for_specialist(state, _todo("Promote memories", "memory.promote_to_long_term"), "MemorySpecialist")
    result = specialist.handle(envelope, agent.registry, agent.permission_gate)
    assert result.status == "success"
    assert result.metrics["promoted_memories"]


def test_each_specialist_local_react_contract_uses_only_envelope_and_allowed_tools(temp_workspace):
    agent = MainAgent(temp_workspace, console=False)
    context = agent.create_run_context("r1")
    state = _dense_state(temp_workspace)
    state.status = "partial_success"
    state.selected_path = "fallback_template_path"
    context["artifact_manager"].write_json("state.json", state.to_dict(), "state")
    cases = [
        (HLS4MLSpecialist(context), _todo("Check hls4ml support", "hls4ml.check_support"), "HLS4MLSpecialist"),
        (VivadoSpecialist(context), _todo("Run Vivado HLS synthesis", "vivado.run_csynth"), "VivadoSpecialist"),
        (VerificationSpecialist(context), _todo("Verify LLM candidate", "verify_candidate.run"), "VerificationSpecialist"),
        (OptimizationSpecialist(context), _todo("Generate optimization suggestions", "suggestion.suggest_optimization"), "OptimizationSpecialist"),
        (MemorySpecialist(context), _todo("Promote memories", "memory.promote_to_long_term"), "MemorySpecialist"),
    ]
    for specialist, todo, name in cases:
        envelope = ContextBuilder().build_for_specialist(state, todo, name)
        result = specialist.handle(envelope, agent.registry, agent.permission_gate)
        assert isinstance(result, SpecialistResult)
        assert result.specialist_name == name
        assert "todos" not in envelope.to_dict()
        assert "tool_results" not in envelope.to_dict()
        assert any(item.get("type") == "local_react" for item in result.observations)
        assert all(item.get("tool") in specialist.allowed_tools for item in result.observations if item.get("tool"))
        payload = json.dumps(result.to_dict(), ensure_ascii=False)
        assert "raw_log" not in payload
        assert "stdout" not in payload
        assert "stderr" not in payload


def test_main_agent_assigns_specialist_to_todo(temp_workspace):
    state = run_task(str(temp_workspace / "examples" / "dense_operator.json"), agent=MainAgent(temp_workspace, console=False))
    assert any(item.assigned_specialist == "VivadoSpecialist" for item in state.todos)


def test_main_agent_merges_specialist_result(temp_workspace):
    state = run_task(str(temp_workspace / "examples" / "dense_operator.json"), agent=MainAgent(temp_workspace, console=False))
    synth_todo = next(item for item in state.todos if item.title == "Run Vivado HLS synthesis")
    assert synth_todo.specialist_result["specialist_name"] == "VivadoSpecialist"
    assert state.report["status"] == "success"


def test_main_agent_does_not_merge_raw_log(temp_workspace):
    state = run_task(str(temp_workspace / "examples" / "dense_operator.json"), agent=MainAgent(temp_workspace, console=False))
    payload = json.dumps(state.to_dict(), ensure_ascii=False)
    assert "Vivado HLS raw log" not in payload
    assert "full_trace" in payload


def test_trace_specialist_events_written(temp_workspace):
    state = run_task(str(temp_workspace / "examples" / "dense_operator.json"), agent=MainAgent(temp_workspace, console=False))
    trace = (temp_workspace / "runs" / state.run_id / "trace.jsonl").read_text(encoding="utf-8")
    for event in ["SpecialistSelected", "ContextEnvelopeCreated", "SpecialistStarted", "SpecialistFinished", "SpecialistResultMerged"]:
        assert event in trace


def test_summary_contains_specialist_execution_summary(temp_workspace):
    state = run_task(str(temp_workspace / "examples" / "dense_operator.json"), agent=MainAgent(temp_workspace, console=False))
    summary = (temp_workspace / "runs" / state.run_id / "summary.md").read_text(encoding="utf-8")
    assert "Specialist Execution Summary" in summary
    assert "Context Isolation" in summary
