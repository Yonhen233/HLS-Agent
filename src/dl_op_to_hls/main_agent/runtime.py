from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ..core.context import ContextCompressor
from ..core.errors import AgentRuntimeError, build_error
from ..core.goal_contract import CompletionGate, GoalContractBuilder, PlanCoverageValidator
from ..core.progress import ProgressSupervisor
from ..memory.short_term import build_short_term_entry
from ..rag.evidence import ClaimEvidenceVerifier
from ..schemas.hls_project_schema import normalize_hls_project_task
from ..schemas.model_schema import normalize_model_task
from ..schemas.operator_schema import normalize_operator_task
from ..schemas.report_schema import empty_report
from ..schemas.task_schema import load_task
from ..specialists.context import ContextBuilder
from ..specialists.router import build_default_router
from .executor import AgentExecutor
from .finalizer import finalize_state
from .planner import build_plan
from .reflector import reflect_on_errors, update_status_from_todos
from .state import AgentState
from .status import compute_pipeline_status
from .todo import DONE_STATUSES, TodoItem, TodoManager


def _load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _normalize_task(task: dict[str, Any]) -> dict[str, Any]:
    validated = load_task(task)
    if validated["task_type"] == "operator":
        return normalize_operator_task(validated)
    if validated["task_type"] == "model":
        return normalize_model_task(validated)
    return normalize_hls_project_task(validated)


class PlanExecuteReactRuntime:
    def __init__(self, agent, session_id: str | None = None):
        self.agent = agent
        self.session_id = session_id
        self.context: dict[str, Any] | None = None
        self.executor: AgentExecutor | None = None
        self.todo_manager: TodoManager | None = None
        self.compressor: ContextCompressor | None = None
        self.context_builder = ContextBuilder()
        self.specialist_router = None
        self.goal_contract_builder = GoalContractBuilder()
        self.plan_coverage_validator = PlanCoverageValidator()
        self.completion_gate = CompletionGate()
        self.progress_supervisor = ProgressSupervisor(
            max_steps=int(os.environ.get("DL_OP_TO_HLS_MAX_AGENT_STEPS", "64")),
            replan_after=int(os.environ.get("DL_OP_TO_HLS_REPLAN_AFTER_REPEATS", "2")),
            terminate_after=int(os.environ.get("DL_OP_TO_HLS_TERMINATE_AFTER_REPEATS", "3")),
        )

    def run(self, task_path: str) -> AgentState:
        state = self.initialize(task_path)
        hooks = self.context["hooks"]
        hooks.emit("RunStarted", {"run_id": state.run_id, "message": f"Starting run for {state.task.get('name')}"})
        try:
            state = self.retrieve_initial_memory(state)
            state = self.plan(state)
            state = self.create_todos(state)
            state = self.execute_todos(state)
            if state.status != "interrupted":
                state = self.finalize(state)
        except AgentRuntimeError as exc:
            state.errors.append(exc.error.to_dict())
            state.status = "failed"
        except Exception as exc:  # pragma: no cover - defensive
            state.errors.append(
                build_error("InvalidTaskError", str(exc), recoverable=True, source="runtime.run").to_dict()
            )
            state.status = "failed"
        finally:
            reflect_on_errors(state)
            update_status_from_todos(state)
            state.pipeline_status = compute_pipeline_status(state)
            if state.status != "interrupted":
                self._apply_completion_gate(state)
            trace_path = self.context["run_dir"] / "trace.jsonl"
            if trace_path.exists():
                self.context["artifact_manager"].register_file(trace_path, "trace")
                state.artifacts["trace"] = str(trace_path)
            finalize_state(state, self.context["artifact_manager"])
            state_path = self.context["artifact_manager"].write_json("state.json", state.to_dict(), "state")
            state.artifacts["state"] = str(state_path)
            Path(state_path).write_text(json.dumps(state.to_dict(), indent=2, ensure_ascii=False, default=str), encoding="utf-8")
            hooks.emit("RunFinished", {"run_id": state.run_id, "status": state.status})
        return state

    def initialize(self, task_path: str) -> AgentState:
        raw_task = _load_json(task_path)
        task = _normalize_task(raw_task)
        run_id = self.agent.make_run_id(task)
        self.context = self.agent.create_run_context(run_id, self.session_id)
        self.executor = AgentExecutor(self.agent.registry, self.context)
        self.todo_manager = TodoManager(self.context["run_dir"], hooks=self.context["hooks"], artifact_manager=self.context["artifact_manager"])
        self.compressor = ContextCompressor(hooks=self.context["hooks"], run_id=run_id)
        self.specialist_router = build_default_router(self.context)
        state = AgentState(run_id=run_id, task=task, objective=task.get("objective"))
        state.release_manifest = dict(self.context.get("release_manifest") or {})
        state.telemetry = {"format": "otlp-jsonl", "path": str(self.context["run_dir"] / "otel_spans.jsonl")}
        state.artifacts["run_dir"] = str(self.context["run_dir"])
        state.artifacts["telemetry"] = state.telemetry["path"]
        self._initialize_governance(state)
        self.context["artifact_manager"].write_json("input.json", raw_task, "input_task")
        self.context["artifact_manager"].write_json("normalized_task.json", task, "normalized_task")
        self._call_tool(
            state,
            "db.save_experiment",
            {
                "run_id": run_id,
                "task_type": task["task_type"],
                "name": task["name"],
                "objective": state.objective,
                "selected_path": state.selected_path,
                "status": state.status,
            },
        )
        return state

    def _initialize_governance(self, state: AgentState) -> None:
        if not state.goal_contract:
            state.goal_contract = self.goal_contract_builder.build(state.task)
        self.context["goal_contract"] = state.goal_contract
        contract_path = self.context["artifact_manager"].write_json(
            "goal_contract.json", state.goal_contract, "goal_contract"
        )
        state.artifacts["goal_contract"] = str(contract_path)

    def _update_plan_coverage(self, state: AgentState) -> dict[str, Any]:
        for item in state.todos:
            item.requirement_ids = self.plan_coverage_validator.requirement_ids_for_tool(
                state.goal_contract, item.assigned_tool
            )
        report = self.plan_coverage_validator.validate(
            state.goal_contract,
            [item.to_dict() for item in state.todos],
        )
        state.plan_coverage = report
        path = self.context["artifact_manager"].write_json("plan_coverage.json", report, "plan_coverage")
        state.artifacts["plan_coverage"] = str(path)
        self.context["hooks"].emit(
            "PlanCoverageEvaluated",
            {
                "run_id": state.run_id,
                "status": report["status"],
                "missing_requirements": [item["requirement_id"] for item in report["missing_requirements"]],
            },
        )
        return report

    def retrieve_initial_memory(self, state: AgentState) -> AgentState:
        query = f"{state.task.get('name')} {state.task.get('op_type', '')} {state.objective} reuse factor DSP Vivado HLS"
        tool_jobs = {
            "similar": lambda: self.executor.call("memory.retrieve_similar_experiences", {"query": query, "top_k": 5}),
            "failures": lambda: self.executor.call("memory.retrieve_failure_cases", {"query": query, "top_k": 5}),
            "optimization": lambda: self.executor.call("memory.retrieve_optimization_rules", {"query": query, "top_k": 5}),
            "conversation": lambda: self.executor.call("memory.retrieve_conversation", {"query": query, "top_k": 3}),
        }
        scheduler = self.context.get("scheduler")
        results = scheduler.run_independent(tool_jobs, kind="tool") if scheduler else {name: job() for name, job in tool_jobs.items()}
        similar = results["similar"]
        failures = results["failures"]
        optimization = results["optimization"]
        conversation = results["conversation"]
        state.tool_results.extend(
            [
                {"tool": "memory.retrieve_similar_experiences", "result": similar},
                {"tool": "memory.retrieve_failure_cases", "result": failures},
                {"tool": "memory.retrieve_optimization_rules", "result": optimization},
                {"tool": "memory.retrieve_conversation", "result": conversation},
            ]
        )
        retrieved = {
            "similar_experiences": similar.get("results", []),
            "failure_cases": failures.get("results", []),
            "optimization_rules": optimization.get("results", []),
            "conversation_memories": conversation.get("results", []),
        }
        path = self.context["artifact_manager"].write_json("memory/retrieved_memories.json", retrieved, "memory_retrieved")
        raw_memories = (
            retrieved["similar_experiences"]
            + retrieved["failure_cases"]
            + retrieved["optimization_rules"]
            + retrieved["conversation_memories"]
        )
        evidence_report = self.agent.rag_memory.evidence_grader.grade_many(
            query,
            raw_memories,
            require_citation=False,
        )
        state.retrieved_memories = evidence_report["results"]
        state.rag_evidence_report = evidence_report
        state.rag_context = [
            {
                "id": item.get("id"),
                "memory_type": item.get("memory_type"),
                "summary": item.get("text", "")[:200],
                "source": item.get("source_run_id") or item.get("id"),
                "source_run_id": item.get("source_run_id"),
                "citation": item.get("citation") or {"memory_id": item.get("id"), "run_id": item.get("source_run_id")},
                "text": item.get("text", ""),
                "metadata": item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
                "verification": item.get("verification") if isinstance(item.get("verification"), dict) else None,
                "evidence_grade": item.get("evidence_grade"),
            }
            for item in state.retrieved_memories[:10]
        ]
        state.artifacts["retrieved_memories"] = str(path)
        evidence_path = self.context["artifact_manager"].write_json(
            "memory/rag_evidence_report.json", evidence_report, "rag_evidence_report"
        )
        state.artifacts["rag_evidence_report"] = str(evidence_path)
        self.context["hooks"].emit(
            "RagEvidenceGraded",
            {
                "run_id": state.run_id,
                "raw_count": len(raw_memories),
                "accepted_count": len(state.retrieved_memories),
                "rejected_count": len(evidence_report["rejected"]),
                "evidence_status": evidence_report["status"],
            },
        )
        state.parameter_advice = self._call_tool(state, "parameter_advisor.recommend", {"state": state.to_dict()})
        self._apply_parameter_advice(state)
        advice_path = self.context["artifact_manager"].write_json("parameter_advice.json", state.parameter_advice, "parameter_advice")
        state.artifacts["parameter_advice"] = str(advice_path)
        return state

    def _apply_parameter_advice(self, state: AgentState) -> None:
        advice = state.parameter_advice or {}
        updates = advice.get("recommended_updates") or {}
        if not isinstance(updates, dict):
            return
        policy = state.task.get("parameter_advisor") or {}
        allow_override = bool(policy.get("allow_override") or policy.get("apply_overrides"))
        applied: dict[str, dict[str, Any]] = {}
        proposed: dict[str, dict[str, Any]] = {}
        for section, section_updates in updates.items():
            if not isinstance(section_updates, dict):
                continue
            target = state.task.setdefault(section, {})
            if not isinstance(target, dict):
                proposed[section] = section_updates
                continue
            for key, value in section_updates.items():
                current = target.get(key)
                if current is None or allow_override:
                    target[key] = value
                    applied.setdefault(section, {})[key] = value
                elif current == value:
                    applied.setdefault(section, {})[key] = value
                else:
                    proposed.setdefault(section, {})[key] = value
        advice["applied_updates"] = applied
        advice["proposed_updates"] = proposed
        advice["auto_apply_policy"] = {
            "missing_values": True,
            "override_existing_values": allow_override,
        }

    def plan(self, state: AgentState) -> AgentState:
        state.plan = build_plan(state.task)
        return state

    def create_todos(self, state: AgentState) -> AgentState:
        todo_list = self.todo_manager.create_from_plan(state.run_id, state.plan, state.task)
        state.todos = todo_list.items
        self._update_plan_coverage(state)
        state.artifacts["todos"] = str(self.context["run_dir"] / "todos.json")
        self._create_session_checkpoint(state, "todo_plan_created")
        return state

    def execute_todos(self, state: AgentState) -> AgentState:
        while self.todo_manager.has_pending_or_ready():
            if self._interrupt_if_requested(state):
                break
            todo = self.todo_manager.get_next_ready_item(self.todo_manager.todo_list)
            if todo is None:
                break
            observation = self.execute_todo_with_react(state, todo)
            state = self.reflect(state, todo, observation)
            self._update_plan_coverage(state)
            progress = self.progress_supervisor.observe(
                state,
                todo,
                observation,
                completion_gate=self.completion_gate,
                goal_contract=state.goal_contract,
            )
            self.context["hooks"].emit("AgentProgressEvaluated", {"run_id": state.run_id, **progress})
            self._create_session_checkpoint(state, f"todo_boundary:{todo.id}:{todo.status}")
            if progress["decision"] == "terminate":
                error = build_error(
                    "AgentStagnationError",
                    f"Agent execution stopped by progress supervisor: {progress['reason']}.",
                    recoverable=True,
                    source="runtime.progress_supervisor",
                    suggested_action="Replan from the latest checkpoint with a different tool or narrower goal.",
                    details=progress,
                ).to_dict()
                state.errors.append(error)
                state.status = "partial_success" if state.selected_path or state.artifacts else "failed"
                break
            if self.should_stop(state):
                break
        update_status_from_todos(state)
        return state

    def execute_todo_with_react(self, state: AgentState, todo: TodoItem) -> dict[str, Any]:
        state.current_todo_id = todo.id
        self.todo_manager.mark_started(todo.id)
        reason = self._reason_for_todo(state, todo)
        specialist = self.specialist_router.route(todo) if self.specialist_router else None
        if specialist is not None:
            observation = self._execute_todo_with_specialist(state, todo, specialist)
        else:
            observation = self._execute_todo_actions(state, todo)
        decision = self._decision_from_observation(state, todo, observation)
        todo.react_steps.append(
            {
                "reason": reason,
                "action": observation.get("action"),
                "observation": observation.get("observation"),
                "decision": decision,
            }
        )
        todo.updated_at = self.todo_manager._find(todo.id).updated_at
        self._write_short_term_for_todo(state, todo, observation)
        return observation

    def _execute_todo_with_specialist(self, state: AgentState, todo: TodoItem, specialist) -> dict[str, Any]:
        hooks = self.context["hooks"]
        message_bus = self.context.get("message_bus")
        delegation_message = None
        if message_bus is not None:
            delegation_message = message_bus.publish(
                message_type="delegation_request",
                sender="MainAgent",
                recipient=specialist.name,
                payload={
                    "run_id": state.run_id,
                    "todo_id": todo.id,
                    "title": todo.title,
                    "assigned_tool": todo.assigned_tool,
                    "dependencies": list(todo.dependencies),
                },
            )
        hooks.emit(
            "SpecialistSelected",
            {"run_id": state.run_id, "todo_id": todo.id, "specialist": specialist.name},
        )
        if specialist.name == "MemorySpecialist":
            state_path = self._write_memory_ready_state_snapshot(state)
            state.artifacts["state"] = str(state_path)
        envelope = self.context_builder.build_for_specialist(state=state, todo=todo, specialist_name=specialist.name)
        hooks.emit(
            "ContextEnvelopeCreated",
            {
                "run_id": state.run_id,
                "todo_id": todo.id,
                "specialist": specialist.name,
                "max_context_tokens": envelope.max_context_tokens,
                **(envelope.constraints.get("token_budget", {})),
            },
        )
        hooks.emit("SpecialistStarted", {"run_id": state.run_id, "todo_id": todo.id, "specialist": specialist.name})
        try:
            result = specialist.handle(envelope, self.agent.registry, self.context["permission_gate"])
            event = "SpecialistFinished" if result.status != "failed" else "SpecialistFailed"
            hooks.emit(
                event,
                {
                    "run_id": state.run_id,
                    "todo_id": todo.id,
                    "specialist": specialist.name,
                    "status": result.status,
                },
            )
        except Exception as exc:  # pragma: no cover - defensive
            error = build_error(
                "InvalidTaskError",
                str(exc),
                recoverable=True,
                source=f"{specialist.name}.handle",
            ).to_dict()
            from ..specialists.result import SpecialistResult

            result = SpecialistResult(
                specialist_name=specialist.name,
                todo_id=todo.id,
                status="failed",
                summary=f"{specialist.name} failed unexpectedly.",
                errors=[error],
            )
            hooks.emit(
                "SpecialistFailed",
                {
                    "run_id": state.run_id,
                    "todo_id": todo.id,
                    "specialist": specialist.name,
                    "status": result.status,
                    "error_type": error["error_type"],
                    "message": error["message"],
                },
            )
        hooks.emit(
            "ContextCompressionMeasured",
            {
                "run_id": state.run_id,
                "todo_id": todo.id,
                    "specialist": specialist.name,
                    **result.context_usage,
                },
            )
        state = self.executor.merge_specialist_result(state, todo, result)
        if message_bus is not None and delegation_message is not None:
            message_bus.publish(
                message_type="delegation_result",
                sender=specialist.name,
                recipient="MainAgent",
                correlation_id=delegation_message.correlation_id,
                parent_message_id=delegation_message.message_id,
                payload={
                    "run_id": state.run_id,
                    "todo_id": todo.id,
                    "status": result.status,
                    "summary": result.summary,
                    "artifact_count": len(result.artifacts),
                    "error_count": len(result.errors),
                },
            )
        hooks.emit(
            "SpecialistResultMerged",
            {"run_id": state.run_id, "todo_id": todo.id, "specialist": specialist.name},
        )
        return self._apply_specialist_observation(state, todo, result)

    def _apply_specialist_observation(self, state: AgentState, todo: TodoItem, result) -> dict[str, Any]:
        observation = {
            "status": self._todo_status_from_specialist(result.status),
            "action": {"specialist": result.specialist_name},
            "observation": {
                "status": result.status,
                "summary": result.summary,
                "metrics": result.metrics,
                "errors": result.errors,
                "warnings": result.warnings,
                "suggested_todos": result.suggested_todos,
                "verification": result.verification,
                "context_usage": result.context_usage,
            },
            "specialist_status": result.status,
            "specialist_name": result.specialist_name,
        }
        if result.specialist_name == "HLS4MLSpecialist":
            support_observation = next(
                (
                    item.get("result", {})
                    for item in result.observations
                    if item.get("tool") in {"hls4ml.check_support", "hls4ml.check_hls4ml_support"}
                ),
                {},
            )
            if support_observation:
                state.hls4ml_support = {**support_observation, "model_path": state.task.get("model_path")}
                observation["hls4ml_status"] = support_observation.get("status")
            config_path = self._first_artifact_path(result, "hls4ml_config")
            if config_path:
                state.hls4ml_config_path = config_path
            hls_project = self._first_artifact_path(result, "hls_project")
            if hls_project:
                state.selected_path = "hls4ml_path"
                state.hls_project_dir = hls_project
            convert_observation = next(
                (
                    item.get("result", {})
                    for item in result.observations
                    if item.get("tool") in {"hls4ml.convert", "hls4ml.convert_with_hls4ml"}
                ),
                {},
            )
            top_function = convert_observation.get("top_function")
            if top_function:
                state.task["top_function"] = top_function
            if observation["status"] == "failed":
                first_error = (result.errors[0] if result.errors else {}) or {}
                if first_error.get("recoverable") and first_error.get("error_type") in {
                    "HLS4MLConversionError",
                    "HLS4MLNotInstalledError",
                }:
                    observation["status"] = "completed_with_warning"
                    observation["error_type"] = first_error.get("error_type")
                    observation["hls4ml_status"] = "unsupported"
                    if not result.warnings:
                        result.warnings.append({"message": first_error.get("message", "Recoverable hls4ml issue.")})
                    observation["observation"]["warnings"] = result.warnings
        if result.specialist_name == "VivadoSpecialist":
            for item in result.observations:
                if item.get("tool") == "vivado.create_project":
                    create_result = item.get("result", {})
                    if create_result.get("work_dir"):
                        state.vivado_work_dir = create_result["work_dir"]
            if result.status == "partial_success":
                observation["error_type"] = (result.errors[0] if result.errors else {}).get("error_type")
                if observation["error_type"] == "VivadoNotFoundError":
                    observation["status"] = "skipped"
            if result.verification:
                state.verification = result.verification
        if result.specialist_name == "VerificationSpecialist" and result.errors:
            observation["error_type"] = result.errors[0].get("error_type")
            if observation["error_type"] == "VerificationFailedError":
                observation["status"] = "completed_with_warning"
        if (
            result.specialist_name == "VerificationSpecialist"
            and result.status == "success"
            and isinstance(result.metrics, dict)
            and result.metrics.get("status") == "success"
        ):
            # verify_candidate.run already performs real golden CSim and CSynth.
            # Re-running the same project through Vivado adds cost and can race a
            # repaired candidate, so downstream synthesis/report todos are redundant.
            self._cancel_pending_tools(
                {"vivado.create_project", "vivado.create_vivado_project", "vivado.run_csynth", "vivado.parse_report", "vivado.parse_csynth_report"},
                "Candidate verification already produced a current-run real CSynth report.",
            )
            self._switch_finalization_to_terminal(state, todo.id)
        if result.specialist_name == "OptimizationSpecialist" and result.metrics:
            state.suggestions = result.metrics.get("suggestions", state.suggestions)
            suggestions_path = self._first_artifact_path(result, "suggestions")
            if suggestions_path:
                state.artifacts["suggestions"] = suggestions_path
        if result.specialist_name == "MemorySpecialist" and result.metrics:
            state.memory_candidates = result.metrics.get("memory_candidates", state.memory_candidates)
            state.promoted_memories = result.metrics.get("promoted_memories", state.promoted_memories)
            for artifact in result.artifacts:
                if artifact.get("type") in {"compressed_context", "memory_candidates", "promoted_memories"}:
                    state.artifacts[artifact["type"]] = artifact["path"]

        if observation["status"] == "completed":
            self.todo_manager.mark_completed(todo.id, todo.outputs or {"status": result.status, "summary": result.summary})
        elif observation["status"] == "completed_with_warning":
            warning = result.warnings[0] if result.warnings else {"message": result.summary}
            self.todo_manager.mark_completed_with_warning(todo.id, todo.outputs or {"status": result.status, "summary": result.summary}, warning)
        elif observation["status"] == "skipped":
            self.todo_manager.mark_skipped(todo.id, result.summary)
        elif observation["status"] == "blocked":
            self.todo_manager.mark_blocked(todo.id, result.summary)
        else:
            error = result.errors[0] if result.errors else {"message": result.summary}
            self.todo_manager.mark_failed(todo.id, error)
        return observation

    def _todo_status_from_specialist(self, status: str) -> str:
        mapping = {
            "success": "completed",
            "partial_success": "completed_with_warning",
            "skipped": "skipped",
            "blocked": "blocked",
            "failed": "failed",
        }
        return mapping.get(status, "failed")

    def _first_artifact_path(self, result, artifact_type: str) -> str | None:
        for artifact in result.artifacts:
            if artifact.get("type") == artifact_type:
                return artifact.get("path")
        return None

    def reflect(self, state: AgentState, todo: TodoItem, observation: dict) -> AgentState:
        status = observation.get("status")
        assigned_tool = todo.assigned_tool or ""
        if status == "completed":
            self._resolve_errors_after_success(state, todo)
        is_hls4ml_support = todo.title == "Check hls4ml support" or assigned_tool in {
            "hls4ml.check_support",
            "hls4ml.check_hls4ml_support",
        }
        is_hls4ml_config_or_convert = todo.title in {"Generate hls4ml config", "Convert with hls4ml"} or assigned_tool in {
            "hls4ml.generate_config",
            "hls4ml.generate_hls4ml_config",
            "hls4ml.convert",
            "hls4ml.convert_with_hls4ml",
        }
        is_graph_rewrite = todo.title == "Try graph rewrite" or assigned_tool == "graph_rewrite.rewrite"
        is_fallback_template = todo.title == "Generate fallback HLS template" or assigned_tool == "fallback.generate_operator_hls"
        if is_hls4ml_support and observation.get("hls4ml_status") == "unsupported":
            if state.task["task_type"] == "operator":
                graph_todo = self.todo_manager.append_item(
                    title="Try graph rewrite",
                    description="Attempt simple graph rewrite rules for unsupported path.",
                    priority=todo.priority + 1,
                    assigned_tool="graph_rewrite.rewrite",
                    dependencies=[todo.id],
                    inputs={"task": state.task},
                )
                fallback_todo = self.todo_manager.append_item(
                    title="Generate fallback HLS template",
                    description="Generate fallback operator HLS template.",
                    priority=graph_todo.priority + 1,
                    assigned_tool="fallback.generate_operator_hls",
                    dependencies=[graph_todo.id],
                    inputs={"task": state.task},
                )
                self._rewire_vivado_chain_after_implementation(state, fallback_todo.id)
                state.todos = self.todo_manager.todo_list.items
            else:
                if state.task.get("original_model_path") or str(state.task.get("model_path", "")).endswith("_gemm_rewritten.onnx"):
                    unsupported_todo = self.todo_manager.append_item(
                        title="Generate unsupported report",
                        description="Write actionable unsupported report after graph rewrite did not make the model hls4ml-compatible.",
                        priority=todo.priority + 1,
                        assigned_tool="report.write_unsupported",
                        dependencies=[todo.id],
                        inputs={"reason": "hls4ml still reports unsupported operators after graph rewrite."},
                    )
                    self._add_dependency_to_title(state, "Write run summary", unsupported_todo.id)
                    self._switch_finalization_to_terminal(state, unsupported_todo.id)
                    self._add_dependency_to_tool(
                        state,
                        {"suggestion.suggest_optimization", "summary.write_summary", "memory.promote_to_long_term"},
                        unsupported_todo.id,
                    )
                    self._cancel_pending_tools(
                        {
                            "hls4ml.generate_config",
                            "hls4ml.generate_hls4ml_config",
                            "hls4ml.convert",
                            "hls4ml.convert_with_hls4ml",
                            "vivado.create_project",
                            "vivado.create_vivado_project",
                            "vivado.run_csynth",
                            "vivado.parse_report",
                            "vivado.parse_csynth_report",
                        },
                        "Graph rewrite did not produce a hls4ml-compatible model; switching to unsupported report.",
                    )
                    state.selected_path = "unsupported_path"
                    state.status = "partial_success"
                    if state.report is None:
                        state.report = empty_report("missing")
                else:
                    graph_todo = self.todo_manager.append_item(
                        title="Try graph rewrite",
                        description="Attempt simple graph rewrite rules for unsupported hls4ml model path.",
                        priority=todo.priority + 1,
                        assigned_tool="graph_rewrite.rewrite",
                        dependencies=[todo.id],
                        inputs={"task": state.task},
                    )
                    self._add_dependency_to_tool(state, {"hls4ml.generate_config", "hls4ml.generate_hls4ml_config"}, graph_todo.id)
                    self._add_dependency_to_tool(state, {"hls4ml.convert", "hls4ml.convert_with_hls4ml"}, graph_todo.id)
                    self._add_dependency_to_tool(
                        state,
                        {
                            "vivado.create_project",
                            "vivado.create_vivado_project",
                            "vivado.run_csynth",
                            "vivado.parse_report",
                            "vivado.parse_csynth_report",
                            "suggestion.suggest_optimization",
                            "summary.write_summary",
                            "memory.promote_to_long_term",
                        },
                        graph_todo.id,
                    )
                    self._switch_finalization_to_terminal(state, graph_todo.id)
                state.todos = self.todo_manager.todo_list.items
        elif is_hls4ml_support and observation.get("hls4ml_status") == "partially_supported":
            graph_todo = self.todo_manager.append_item(
                title="Try graph rewrite",
                description="Attempt graph rewrite and folding rules for partial hls4ml support.",
                priority=todo.priority + 1,
                assigned_tool="graph_rewrite.rewrite",
                dependencies=[todo.id],
                inputs={"task": state.task},
            )
            unsupported_todo = self.todo_manager.append_item(
                title="Generate unsupported report",
                description="Write boundary report for partially supported model.",
                priority=graph_todo.priority + 1,
                assigned_tool="report.write_unsupported",
                dependencies=[graph_todo.id],
                inputs={"reason": state.hls4ml_support.get("recommendation") if state.hls4ml_support else "Model is only partially supported by hls4ml."},
            )
            self._add_dependency_to_title(state, "Write run summary", unsupported_todo.id)
            self._switch_finalization_to_terminal(state, unsupported_todo.id)
            self._add_dependency_to_tool(
                state,
                {"suggestion.suggest_optimization", "summary.write_summary", "memory.promote_to_long_term"},
                unsupported_todo.id,
            )
            for item in self.todo_manager.todo_list.items:
                if item.title == "Run Vivado HLS synthesis" and item.status in {"pending", "blocked"}:
                    self.todo_manager.mark_skipped(item.id, "Boundary demo selected: skip full synthesis and emit boundary report.")
            state.selected_path = "unsupported_path"
            state.status = "partial_success"
            state.todos = self.todo_manager.todo_list.items
        elif is_hls4ml_support and observation.get("hls4ml_status") == "not_recommended":
            recommendation = state.hls4ml_support.get("recommendation") if state.hls4ml_support else "Model is outside MVP scope."
            name = str(state.task.get("name", "")).lower()
            model_path = str(state.task.get("model_path", "")).lower()
            if "resnet18" in name or "resnet18" in model_path:
                reason = (
                    "Full ResNet-18 is outside the recommended scope for this MVP. "
                    f"{recommendation}"
                )
            else:
                reason = recommendation
            unsupported_todo = self.todo_manager.append_item(
                title="Generate unsupported report",
                description="Write unsupported/not-recommended report.",
                priority=todo.priority + 1,
                assigned_tool="report.write_unsupported",
                dependencies=[todo.id],
                inputs={"reason": reason},
            )
            self._add_dependency_to_title(state, "Write run summary", unsupported_todo.id)
            self._switch_finalization_to_terminal(state, unsupported_todo.id)
            self._add_dependency_to_tool(
                state,
                {"suggestion.suggest_optimization", "summary.write_summary", "memory.promote_to_long_term"},
                unsupported_todo.id,
            )
            for item in self.todo_manager.todo_list.items:
                if item.title == "Run Vivado HLS synthesis" and item.status in {"pending", "blocked"}:
                    self.todo_manager.mark_skipped(item.id, "Not recommended boundary demo: skip full synthesis.")
            state.selected_path = "unsupported_path"
            state.status = "partial_success"
            state.todos = self.todo_manager.todo_list.items
        elif is_hls4ml_support and observation.get("hls4ml_status") == "supported" and state.task["task_type"] == "model":
            config_todo = self._ensure_active_todo(
                title="Generate hls4ml config",
                description="Create hls4ml config for the supported model.",
                priority=todo.priority + 1,
                assigned_tool="hls4ml.generate_config",
                dependencies=[todo.id],
                inputs={"task": state.task},
                tool_names={"hls4ml.generate_config", "hls4ml.generate_hls4ml_config"},
            )
            convert_todo = self._ensure_active_todo(
                title="Convert with hls4ml",
                description="Convert model into an HLS project with hls4ml.",
                priority=config_todo.priority + 1,
                assigned_tool="hls4ml.convert",
                dependencies=[config_todo.id],
                inputs={"task": state.task},
                tool_names={"hls4ml.convert", "hls4ml.convert_with_hls4ml"},
            )
            self._add_dependency_to_tool(state, {"vivado.create_project", "vivado.run_csynth"}, convert_todo.id)
            state.todos = self.todo_manager.todo_list.items
        elif is_graph_rewrite:
            rewrite_result = observation.get("observation", {}) or {}
            if rewrite_result.get("status") == "success" and rewrite_result.get("implemented") and rewrite_result.get("rewritten_model_path"):
                state.task["original_model_path"] = state.task.get("original_model_path") or state.task.get("model_path")
                state.task["model_path"] = rewrite_result["rewritten_model_path"]
                state.artifacts["rewritten_model"] = rewrite_result["rewritten_model_path"]
                retry_todo = self.todo_manager.append_item(
                    title="Check hls4ml support",
                    description="Re-check hls4ml support after graph rewrite.",
                    priority=todo.priority + 1,
                    assigned_tool="hls4ml.check_support",
                    dependencies=[todo.id],
                    inputs={"task": state.task},
                )
                config_todo = self._ensure_active_todo(
                    title="Generate hls4ml config",
                    description="Create hls4ml config after graph rewrite.",
                    priority=retry_todo.priority + 1,
                    assigned_tool="hls4ml.generate_config",
                    dependencies=[retry_todo.id],
                    inputs={"task": state.task},
                    tool_names={"hls4ml.generate_config", "hls4ml.generate_hls4ml_config"},
                )
                self._replace_dependencies(config_todo.id, [retry_todo.id])
                convert_todo = self._ensure_active_todo(
                    title="Convert with hls4ml",
                    description="Convert rewritten model into an HLS project.",
                    priority=config_todo.priority + 1,
                    assigned_tool="hls4ml.convert",
                    dependencies=[config_todo.id],
                    inputs={"task": state.task},
                    tool_names={"hls4ml.convert", "hls4ml.convert_with_hls4ml"},
                )
                self._replace_dependencies(convert_todo.id, [config_todo.id])
                vivado_todo = self._ensure_active_todo(
                    title="Run Vivado HLS synthesis",
                    description="Run synthesis on the recovered HLS project.",
                    priority=convert_todo.priority + 1,
                    assigned_tool="vivado.run_csynth",
                    dependencies=[convert_todo.id],
                    inputs={"task": state.task},
                    tool_names={"vivado.create_project", "vivado.run_csynth"},
                )
                self._replace_dependencies(vivado_todo.id, [convert_todo.id])
                parse_todo = self._ensure_active_todo(
                    title="Parse synthesis report",
                    description="Parse synthesis report after recovered Vivado run.",
                    priority=vivado_todo.priority + 1,
                    assigned_tool="vivado.parse_report",
                    dependencies=[vivado_todo.id],
                    inputs={"task": state.task},
                    tool_names={"vivado.parse_report", "vivado.parse_csynth_report"},
                )
                self._replace_dependencies(parse_todo.id, [vivado_todo.id])
                self._switch_finalization_to_terminal(state, parse_todo.id)
                state.todos = self.todo_manager.todo_list.items
            elif state.task["task_type"] == "model":
                reason = (
                    rewrite_result.get("recommendation")
                    or "hls4ml unsupported and no safe automatic graph rewrite was applied."
                )
                unsupported_todo = self._ensure_active_todo(
                    title="Generate unsupported report",
                    description="Write actionable unsupported report after graph rewrite could not safely repair the model.",
                    priority=todo.priority + 1,
                    assigned_tool="report.write_unsupported",
                    dependencies=[todo.id],
                    inputs={"reason": reason},
                    tool_names={"report.write_unsupported"},
                )
                if not isinstance(unsupported_todo.inputs, dict):
                    unsupported_todo.inputs = {}
                unsupported_todo.inputs.setdefault("reason", reason)
                self.todo_manager.save(state.run_id, self.todo_manager.todo_list)
                self._add_dependency_to_title(state, "Write run summary", unsupported_todo.id)
                self._switch_finalization_to_terminal(state, unsupported_todo.id)
                self._add_dependency_to_tool(
                    state,
                    {"suggestion.suggest_optimization", "summary.write_summary", "memory.promote_to_long_term"},
                    unsupported_todo.id,
                )
                for item in self.todo_manager.todo_list.items:
                    if item.title in {"Generate hls4ml config", "Convert with hls4ml", "Run Vivado HLS synthesis", "Parse synthesis report"}:
                        if item.status in {"pending", "blocked"}:
                            self.todo_manager.mark_cancelled(item.id, "No safe graph rewrite was available.")
                state.selected_path = "unsupported_path"
                state.status = "partial_success"
                if state.report is None:
                    state.report = empty_report("missing")
                state.todos = self.todo_manager.todo_list.items
        elif is_hls4ml_config_or_convert and observation.get("error_type") in {
            "HLS4MLConversionError",
            "HLS4MLNotInstalledError",
        }:
            if state.task.get("original_model_path") or str(state.task.get("model_path", "")).endswith("_gemm_rewritten.onnx"):
                reason = (
                    observation.get("observation", {})
                    .get("errors", [{}])[0]
                    .get("message")
                    or "hls4ml config/conversion failed after graph rewrite."
                )
                unsupported_todo = self._ensure_active_todo(
                    title="Generate unsupported report",
                    description="Write actionable unsupported report after recovered hls4ml path failed.",
                    priority=todo.priority + 1,
                    assigned_tool="report.write_unsupported",
                    dependencies=[todo.id],
                    inputs={"reason": reason},
                    tool_names={"report.write_unsupported"},
                )
                if not isinstance(unsupported_todo.inputs, dict):
                    unsupported_todo.inputs = {}
                unsupported_todo.inputs.setdefault("reason", reason)
                self.todo_manager.save(state.run_id, self.todo_manager.todo_list)
                self._add_dependency_to_title(state, "Write run summary", unsupported_todo.id)
                self._switch_finalization_to_terminal(state, unsupported_todo.id)
                self._add_dependency_to_tool(
                    state,
                    {"suggestion.suggest_optimization", "summary.write_summary", "memory.promote_to_long_term"},
                    unsupported_todo.id,
                )
                for item in self.todo_manager.todo_list.items:
                    if item.status in {"pending", "blocked"} and (
                        (item.assigned_tool or "").startswith("vivado.")
                        or item.assigned_tool
                        in {
                            "hls4ml.generate_config",
                            "hls4ml.generate_hls4ml_config",
                            "hls4ml.convert",
                            "hls4ml.convert_with_hls4ml",
                        }
                    ):
                        self.todo_manager.mark_cancelled(item.id, "Recovered hls4ml path failed; switching to unsupported report.")
                state.selected_path = "unsupported_path"
                state.status = "partial_success"
            else:
                graph_todo = self.todo_manager.append_item(
                    title="Try graph rewrite",
                    description="Attempt graph rewrite rules for unsupported hls4ml model patterns.",
                    priority=todo.priority + 1,
                    assigned_tool="graph_rewrite.rewrite",
                    dependencies=[todo.id],
                    inputs={"task": state.task},
                )
                self._add_dependency_to_tool(state, {"hls4ml.generate_config", "hls4ml.generate_hls4ml_config"}, graph_todo.id)
                self._add_dependency_to_tool(state, {"hls4ml.convert", "hls4ml.convert_with_hls4ml"}, graph_todo.id)
                self._add_dependency_to_tool(state, {"vivado.create_project", "vivado.run_csynth", "vivado.parse_report"}, graph_todo.id)
                for item in self.todo_manager.todo_list.items:
                    if item.id == todo.id:
                        continue
                    if item.status in {"pending", "blocked"} and item.assigned_tool in {
                        "hls4ml.generate_config",
                        "hls4ml.generate_hls4ml_config",
                        "hls4ml.convert",
                        "hls4ml.convert_with_hls4ml",
                        "vivado.create_project",
                        "vivado.run_csynth",
                        "vivado.parse_report",
                        "vivado.parse_csynth_report",
                    }:
                        self.todo_manager.mark_cancelled(
                            item.id,
                            "hls4ml conversion path failed; waiting for graph rewrite recovery.",
                        )
            if state.report is None:
                state.report = empty_report("missing")
            state.todos = self.todo_manager.todo_list.items
        elif is_fallback_template and status == "completed_with_warning":
            existing = next(
                (
                    item
                    for item in self.todo_manager.todo_list.items
                    if item.assigned_tool == "llm.generate_candidate" and item.status in {"pending", "blocked", "in_progress", "completed"}
                ),
                None,
            )
            if existing is None:
                llm_todo = self.todo_manager.append_item(
                    title="Generate LLM candidate",
                    description="Fallback template is unavailable; generate a candidate implementation for verification.",
                    priority=todo.priority + 1,
                    assigned_tool="llm.generate_candidate",
                    dependencies=[todo.id],
                    inputs={"task": state.task},
                )
                self._replace_dependencies(llm_todo.id, [todo.id])
            state.todos = self.todo_manager.todo_list.items
        elif todo.title == "Run Vivado HLS synthesis" and observation.get("status") == "blocked" and not state.hls_project_dir:
            existing = next(
                (
                    item
                    for item in self.todo_manager.todo_list.items
                    if item.title == "Generate LLM candidate" and item.status in {"pending", "blocked", "in_progress", "completed"}
                ),
                None,
            )
            if existing is None:
                llm_todo = self.todo_manager.append_item(
                    title="Generate LLM candidate",
                    description="Fallback templates were unavailable; try mock LLM candidate generation.",
                    priority=todo.priority + 1,
                    assigned_tool="llm.generate_candidate",
                    dependencies=todo.dependencies[:],
                    inputs={"task": state.task},
                )
                self.todo_manager.add_dependency(todo.id, llm_todo.id)
            else:
                self.todo_manager.add_dependency(todo.id, existing.id)
            state.todos = self.todo_manager.todo_list.items
        elif self._is_llm_candidate_timing_not_met(state, todo, observation):
            self._append_llm_candidate_repair_chain(
                state,
                todo,
                repair_reason="timing_not_met",
                details={
                    "report": state.report,
                    "timing": (state.report or {}).get("timing") if isinstance(state.report, dict) else None,
                    "summary": "Candidate passed functional verification, but Vivado timing was not met.",
                },
            )
        elif todo.title == "Run Vivado HLS synthesis" and observation.get("error_type") == "VivadoNotFoundError":
            state.status = "partial_success"
        elif self._is_llm_candidate_verification_failure(todo, observation):
            self._append_llm_candidate_verification_repair_chain(state, todo, observation)
        elif self._is_llm_candidate_generation_failure(todo, observation):
            self._append_llm_candidate_generation_retry(state, todo, observation)
        update_status_from_todos(state)
        return state

    def finalize(self, state: AgentState) -> AgentState:
        if not state.report:
            state.report = empty_report("missing")
        state.pipeline_status = compute_pipeline_status(state)
        message_path = self.context["run_dir"] / "agent_messages.jsonl"
        if message_path.exists():
            self.context["artifact_manager"].register_file(message_path, "agent_messages")
            state.artifacts["agent_messages"] = str(message_path)
        report_path = self.context["artifact_manager"].write_json("report.json", state.report, "report_json")
        state.artifacts["report_json"] = str(report_path)
        if state.verification:
            verification_path = self.context["artifact_manager"].write_json(
                "verification.json",
                state.verification,
                "verification",
            )
            state.artifacts["verification"] = str(verification_path)
        state.artifacts["trace"] = str(self.context["run_dir"] / "trace.jsonl")
        self.context["artifact_manager"].write_json("state.json", state.to_dict(), "state")
        if not state.artifacts.get("compressed_context"):
            compressed_result = self._call_tool(state, "memory.compress_run_context", {"run_id": state.run_id})
            state.artifacts["compressed_context"] = compressed_result.get("path")
        compressed_payload = self._compress_outputs(state)
        compressed_logs_path = self.context["artifact_manager"].write_json("compressed_logs.json", compressed_payload, "report_json")
        state.artifacts["compressed_logs"] = str(compressed_logs_path)
        update_status_from_todos(state)
        state.pipeline_status = compute_pipeline_status(state)
        if isinstance(state.memory_candidates, dict):
            state.memory_candidates = [state.memory_candidates]
        if state.memory_candidates and not state.artifacts.get("memory_candidates"):
            candidates_path = self.context["artifact_manager"].write_json(
                "memory/memory_candidates.json",
                {"run_id": state.run_id, "candidates": state.memory_candidates},
                "memory_candidates",
            )
            state.artifacts["memory_candidates"] = str(candidates_path)
        if not state.memory_candidates:
            state_path = self._write_memory_ready_state_snapshot(state)
            state.artifacts["state"] = str(state_path)
            candidates_result = self._call_tool(state, "memory.extract_memory_candidates", {"run_id": state.run_id})
            state.memory_candidates = candidates_result.get("candidates", [])
            if candidates_result.get("path"):
                state.artifacts["memory_candidates"] = candidates_result["path"]
        if not state.promoted_memories:
            promote_result = self._call_tool(
                state,
                "memory.promote_to_long_term",
                {"run_id": state.run_id, "candidates": state.memory_candidates},
            )
            state.promoted_memories = promote_result.get("promoted_memories", [])
            if promote_result.get("path"):
                state.artifacts["promoted_memories"] = promote_result["path"]
        if not state.parameter_advice:
            state.parameter_advice = self._call_tool(
                state,
                "parameter_advisor.recommend",
                {"state": state.to_dict()},
            )
        if not state.suggestions:
            suggestion_result = self._call_tool(
                state,
                "suggestion.suggest_optimization",
                {
                    "state": state.to_dict(),
                    "report": state.report,
                    "rag_context": state.rag_context,
                    "objective": state.objective,
                },
            )
            state.suggestions = suggestion_result.get("suggestions", [])
            if suggestion_result.get("path"):
                state.artifacts["suggestions"] = suggestion_result["path"]
        self._verify_rag_claims(state)
        summary_result = self._call_tool(state, "summary.write_summary", {"state": state.to_dict()})
        if summary_result.get("path"):
            state.artifacts["summary"] = summary_result["path"]
        artifact_paths = [
            path
            for path in [
                state.artifacts.get("summary"),
                state.artifacts.get("suggestions"),
                state.artifacts.get("compressed_context"),
                state.artifacts.get("report_json"),
                state.artifacts.get("verification"),
                state.artifacts.get("parameter_advice"),
                state.artifacts.get("compressed_logs"),
                state.artifacts.get("unsupported_report"),
            ]
            if path
        ]
        if artifact_paths:
            self._call_tool(state, "rag.index_artifact", {"run_id": state.run_id, "artifact_paths": artifact_paths})
        update_status_from_todos(state)
        state.pipeline_status = compute_pipeline_status(state)
        self._apply_completion_gate(state)
        self._call_tool(
            state,
            "db.save_experiment",
            {
                "run_id": state.run_id,
                "task_type": state.task["task_type"],
                "name": state.task["name"],
                "objective": state.objective,
                "selected_path": state.selected_path,
                "status": state.status,
            },
        )
        run_budget = self.context.get("run_budget")
        if run_budget is not None:
            budget_path = self.context["artifact_manager"].write_json("run_budget.json", run_budget.to_dict(), "run_budget")
            state.artifacts["run_budget"] = str(budget_path)
        self.todo_manager.save(state.run_id, self.todo_manager.todo_list)
        state.todos = self.todo_manager.todo_list.items
        return state

    def _verify_rag_claims(self, state: AgentState) -> dict[str, Any]:
        claims = [
            str(item)
            for item in state.suggestions
            if any(marker in str(item).lower() for marker in ["prior experience", "historical", "retrieved memory"])
        ]
        verification = ClaimEvidenceVerifier().verify(claims, state.rag_context)
        state.rag_evidence_report = {
            **(state.rag_evidence_report or {}),
            "claim_verification": verification,
        }
        if claims and not verification["passed"]:
            unsupported = {item["claim"] for item in verification["checks"] if not item["supported"]}
            state.suggestions = [item for item in state.suggestions if str(item) not in unsupported]
        path = self.context["artifact_manager"].write_json(
            "rag_claim_verification.json", verification, "rag_claim_verification"
        )
        state.artifacts["rag_claim_verification"] = str(path)
        self.context["hooks"].emit(
            "RagClaimsVerified",
            {
                "run_id": state.run_id,
                "claim_count": verification["claim_count"],
                "supported_count": verification["supported_count"],
                "passed": verification["passed"],
            },
        )
        return verification

    def _apply_completion_gate(self, state: AgentState) -> dict[str, Any]:
        state.evidence_receipts = list(self.context.get("evidence_receipts") or [])
        evidence_path = self.context["artifact_manager"].write_json(
            "tool_evidence.json",
            {"run_id": state.run_id, "receipts": state.evidence_receipts},
            "tool_evidence",
        )
        state.artifacts["tool_evidence"] = str(evidence_path)
        completion = self.completion_gate.apply(state, state.goal_contract, state.evidence_receipts)
        completion_path = self.context["artifact_manager"].write_json(
            "completion_gate.json", completion, "completion_gate"
        )
        state.artifacts["completion_gate"] = str(completion_path)
        self.context["hooks"].emit(
            "CompletionGateEvaluated",
            {
                "run_id": state.run_id,
                "passed": completion["passed"],
                "recommended_status": completion["recommended_status"],
                "stop_reason": completion["stop_reason"],
                "false_success_prevented": completion["false_success_prevented"],
                "evidence_level": completion["evidence_level"],
                "production_ready": completion["production_ready"],
                "missing_required": completion["missing_required"],
            },
        )
        return completion

    def _create_session_checkpoint(self, state: AgentState, reason: str) -> None:
        session_id = self.context.get("session_id") if self.context else None
        manager = self.context.get("session_manager") if self.context else None
        if not session_id or manager is None:
            return
        state.todos = self.todo_manager.todo_list.items if self.todo_manager and self.todo_manager.todo_list else state.todos
        budget = self.context.get("run_budget") if self.context else None
        runtime_snapshot = {"run_budget": budget.to_dict()} if budget is not None else {}
        checkpoint = manager.create_checkpoint(session_id, state.to_dict(), reason, runtime=runtime_snapshot)
        self.context["hooks"].emit(
            "SessionCheckpointCreated",
            {"run_id": state.run_id, "session_id": session_id, "checkpoint_id": checkpoint["checkpoint_id"], "reason": reason},
        )

    def _interrupt_if_requested(self, state: AgentState) -> bool:
        session_id = self.context.get("session_id") if self.context else None
        manager = self.context.get("session_manager") if self.context else None
        if not session_id or manager is None or not manager.pause_requested(session_id):
            return False
        state.status = "interrupted"
        reason = manager.get(session_id).get("interrupt_reason") or "User requested interruption"
        for todo in state.todos:
            error = todo.error or {}
            if error.get("error_type") == "ApprovalRequiredError" or "requires explicit session approval" in str(error.get("message", "")):
                todo.status = "pending"
                todo.error = None
                todo.outputs = None
        state.errors = [item for item in state.errors if item.get("error_type") != "ApprovalRequiredError"]
        self._create_session_checkpoint(state, "interrupt_boundary")
        manager.mark_interrupted(session_id, reason)
        self.context["hooks"].emit(
            "SessionInterrupted",
            {"run_id": state.run_id, "session_id": session_id, "reason": reason},
        )
        return True

    def _write_memory_ready_state_snapshot(self, state: AgentState) -> Path:
        state.todos = self.todo_manager.todo_list.items
        unfinished_non_memory_todos = [
            item
            for item in state.todos
            if item.title != "Promote memories" and item.status in {"pending", "blocked", "in_progress"}
        ]
        if (
            not unfinished_non_memory_todos
            and not state.errors
            and state.report
            and state.report.get("status") == "success"
            and state.report.get("timing", {}).get("met") is not False
            and state.selected_path in {"fallback_template_path", "hls4ml_path", "existing_hls_project_path", "llm_candidate_path"}
        ):
            state.status = "success"
        else:
            update_status_from_todos(state)
        state.pipeline_status = compute_pipeline_status(state)
        return self.context["artifact_manager"].write_json("state.json", state.to_dict(), "state")

    def should_stop(self, state: AgentState) -> bool:
        if state.status == "failed":
            return True
        terminal_todos = [item for item in state.todos if item.title == "Generate unsupported report" and item.status == "completed"]
        return bool(terminal_todos and state.selected_path == "unsupported_path")

    def _max_candidate_repair_attempts(self, state: AgentState) -> int:
        """Return the verification-failure budget before switching to unsupported."""

        candidate_cfg = state.task.get("llm_candidate") if isinstance(state.task.get("llm_candidate"), dict) else {}
        raw_value = (
            state.task.get("max_repair_attempts")
            or candidate_cfg.get("max_repair_attempts")
            or os.environ.get("DL_OP_TO_HLS_LLM_MAX_REPAIR_ATTEMPTS")
            or "2"
        )
        try:
            return max(0, int(raw_value))
        except (TypeError, ValueError):
            return 2

    def _llm_candidate_repair_count(self) -> int:
        return sum(
            1
            for item in self.todo_manager.todo_list.items
            if item.assigned_tool in {"llm.generate_candidate", "llm.generate_hls_candidate"}
            and isinstance(item.inputs, dict)
            and bool(item.inputs.get("repair_reason"))
        )

    def _is_llm_candidate_timing_not_met(self, state: AgentState, todo: TodoItem, observation: dict[str, Any]) -> bool:
        if state.selected_path != "llm_candidate_path":
            return False
        if todo.assigned_tool not in {"vivado.run_csynth", "vivado.parse_report", "vivado.parse_csynth_report"}:
            return False
        timing = (state.report or {}).get("timing") if isinstance(state.report, dict) else None
        if isinstance(timing, dict) and timing.get("met") is False:
            return True
        error_timing = (todo.error or {}).get("timing") if isinstance(todo.error, dict) else None
        return isinstance(error_timing, dict) and error_timing.get("met") is False

    def _append_llm_candidate_repair_chain(
        self,
        state: AgentState,
        todo: TodoItem,
        *,
        repair_reason: str,
        details: dict[str, Any],
    ) -> None:
        repair_count = self._llm_candidate_repair_count()
        max_attempts = self._max_candidate_repair_attempts(state)
        self._cancel_pending_tools(
            {"vivado.parse_report", "vivado.parse_csynth_report"},
            "A timing repair candidate will replace the previous Vivado report.",
        )
        if repair_count >= max_attempts:
            unsupported_todo = self.todo_manager.append_item(
                title="Generate unsupported report",
                description="LLM candidate repair budget exhausted before timing closure.",
                priority=todo.priority + 1,
                assigned_tool="report.write_unsupported",
                dependencies=[todo.id],
                inputs={
                    "reason": (
                        f"LLM candidate did not meet timing after {max_attempts} repair attempt(s). "
                        "Functional verification passed, but the design is not deployment-ready."
                    ),
                    "details": details,
                },
            )
            self._switch_finalization_to_terminal(state, unsupported_todo.id)
            state.status = "partial_success"
            state.todos = self.todo_manager.todo_list.items
            return

        repair_todo = self.todo_manager.append_item(
            title="Repair LLM candidate after timing failure",
            description="Regenerate the candidate with timing-closure guidance from the latest Vivado report.",
            priority=todo.priority + 1,
            assigned_tool="llm.generate_candidate",
            dependencies=[todo.id],
            inputs={
                "task": state.task,
                "repair_attempt": repair_count + 1,
                "repair_reason": repair_reason,
                "last_report": state.report,
                "timing": details.get("timing"),
                "instruction": (
                    "The previous candidate passed golden functional verification but failed timing. "
                    "Preserve the same top_function signature and testbench contract, but reduce the critical path."
                ),
            },
        )
        verify_todo = self.todo_manager.append_item(
            title="Verify repaired LLM candidate",
            description="Run golden csim and csynth verification for the repaired candidate.",
            priority=repair_todo.priority + 1,
            assigned_tool="verify_candidate.run",
            assigned_specialist="VerificationSpecialist",
            dependencies=[repair_todo.id],
            inputs={},
        )
        synth_todo = self.todo_manager.append_item(
            title="Run Vivado synthesis on repaired candidate",
            description="Run Vivado HLS after repaired candidate verification.",
            priority=verify_todo.priority + 1,
            assigned_tool="vivado.run_csynth",
            assigned_specialist="VivadoSpecialist",
            dependencies=[verify_todo.id],
            inputs={"task": state.task},
        )
        parse_todo = self.todo_manager.append_item(
            title="Parse repaired synthesis report",
            description="Parse Vivado HLS report for the repaired candidate.",
            priority=synth_todo.priority + 1,
            assigned_tool="vivado.parse_report",
            assigned_specialist="VivadoSpecialist",
            dependencies=[synth_todo.id],
            inputs={"task": state.task},
        )
        self._switch_finalization_to_terminal(state, parse_todo.id)
        state.status = "partial_success"
        state.todos = self.todo_manager.todo_list.items

    def _is_llm_candidate_generation_failure(self, todo: TodoItem, observation: dict[str, Any]) -> bool:
        if todo.assigned_tool not in {"llm.generate_candidate", "llm.generate_hls_candidate"}:
            return False
        if observation.get("status") == "failed":
            return True
        observed = observation.get("observation") if isinstance(observation.get("observation"), dict) else {}
        return observed.get("status") == "failed"

    def _is_llm_candidate_verification_failure(self, todo: TodoItem, observation: dict[str, Any]) -> bool:
        if todo.assigned_tool not in {"verify_candidate.run", "verify.run_csim", "verify.compare_reference"}:
            return False
        if observation.get("error_type") in {"VerificationFailedError", "VivadoSynthesisError"}:
            return True
        observed = observation.get("observation") if isinstance(observation.get("observation"), dict) else {}
        error = observed.get("error") if isinstance(observed.get("error"), dict) else {}
        return error.get("error_type") in {"VerificationFailedError", "VivadoSynthesisError"}

    def _append_llm_candidate_verification_repair_chain(
        self,
        state: AgentState,
        todo: TodoItem,
        observation: dict[str, Any],
    ) -> None:
        observed = observation.get("observation") if isinstance(observation.get("observation"), dict) else {}
        error = observed.get("error") or observation.get("error") or todo.error or {}
        repair_count = self._llm_candidate_repair_count()
        max_attempts = self._max_candidate_repair_attempts(state)
        self._cancel_pending_tools(
            {"vivado.run_csynth", "vivado.parse_report", "vivado.parse_csynth_report"},
            "Verification failed; a repaired LLM candidate must be generated before synthesis.",
        )
        if repair_count >= max_attempts:
            unsupported_todo = self.todo_manager.append_item(
                title="Generate unsupported report",
                description="LLM candidate verification repair budget exhausted.",
                priority=todo.priority + 1,
                assigned_tool="report.write_unsupported",
                dependencies=[],
                inputs={
                    "reason": f"LLM candidate failed verification after {max_attempts} repair attempt(s).",
                    "error": error,
                },
            )
            self._switch_finalization_to_terminal(state, unsupported_todo.id)
            state.status = "partial_success"
            state.todos = self.todo_manager.todo_list.items
            return

        self.todo_manager.mark_completed_with_warning(
            todo.id,
            todo.outputs or observed or {"status": "failed"},
            {
                "message": "LLM candidate verification failed but a repair generation was scheduled.",
                "original_error": error,
            },
        )
        self._remove_recovered_error(state, error)
        repair_todo = self.todo_manager.append_item(
            title="Repair LLM candidate after verification failure",
            description="Regenerate candidate using verification failure details.",
            priority=todo.priority + 1,
            assigned_tool="llm.generate_candidate",
            dependencies=[],
            inputs={
                "task": state.task,
                "repair_attempt": repair_count + 1,
                "repair_reason": "verification_failed",
                "last_error": error,
                "instruction": (
                    "The previous candidate failed golden verification or csim. "
                    "Regenerate the same top_function contract and fix the design/testbench mismatch. "
                    "For fixed-point math, compute golden values with matching fixed-point accumulation or an explicitly justified tolerance."
                ),
            },
        )
        verify_todo = self.todo_manager.append_item(
            title="Verify repaired LLM candidate",
            description="Verify repaired candidate through golden csim/csynth.",
            priority=repair_todo.priority + 1,
            assigned_tool="verify_candidate.run",
            assigned_specialist="VerificationSpecialist",
            dependencies=[repair_todo.id],
            inputs={},
        )
        synth_todo = self.todo_manager.append_item(
            title="Run Vivado synthesis on repaired candidate",
            description="Run Vivado HLS after repaired candidate verification.",
            priority=verify_todo.priority + 1,
            assigned_tool="vivado.run_csynth",
            assigned_specialist="VivadoSpecialist",
            dependencies=[verify_todo.id],
            inputs={"task": state.task},
        )
        parse_todo = self.todo_manager.append_item(
            title="Parse repaired synthesis report",
            description="Parse Vivado HLS report for the repaired candidate.",
            priority=synth_todo.priority + 1,
            assigned_tool="vivado.parse_report",
            assigned_specialist="VivadoSpecialist",
            dependencies=[synth_todo.id],
            inputs={"task": state.task},
        )
        self._switch_finalization_to_terminal(state, parse_todo.id)
        state.status = "partial_success"
        state.todos = self.todo_manager.todo_list.items

    def _append_llm_candidate_generation_retry(
        self,
        state: AgentState,
        todo: TodoItem,
        observation: dict[str, Any],
    ) -> None:
        observed = observation.get("observation") if isinstance(observation.get("observation"), dict) else {}
        error = observed.get("error") or observation.get("error") or todo.error or {}
        repair_count = self._llm_candidate_repair_count()
        max_attempts = self._max_candidate_repair_attempts(state)
        if repair_count >= max_attempts:
            unsupported_todo = self.todo_manager.append_item(
                title="Generate unsupported report",
                description="LLM candidate generation repair budget exhausted.",
                priority=todo.priority + 1,
                assigned_tool="report.write_unsupported",
                dependencies=[],
                inputs={
                    "reason": "LLM candidate generation failed after repair attempts and no verified implementation is available.",
                    "error": error,
                },
            )
            self._switch_finalization_to_terminal(state, unsupported_todo.id)
            self._cancel_pending_tools(
                {"verify_candidate.run", "vivado.run_csynth", "vivado.parse_report", "vivado.parse_csynth_report"},
                "No valid HLS candidate was available after the repair budget was exhausted.",
            )
            state.selected_path = "unsupported_path"
            if state.report is None:
                state.report = empty_report("missing")
            state.status = "partial_success"
            state.todos = self.todo_manager.todo_list.items
            return

        self.todo_manager.mark_completed_with_warning(
            todo.id,
            todo.outputs or observed or {"status": "failed"},
            {
                "message": "LLM candidate generation failed but a repair generation was scheduled.",
                "original_error": error,
            },
        )
        self._remove_recovered_error(state, error)
        retry_todo = self.todo_manager.append_item(
            title="Repair LLM candidate generation",
            description="Regenerate a candidate after guard or sandbox rejection.",
            priority=todo.priority + 1,
            assigned_tool="llm.generate_candidate",
            dependencies=list(todo.dependencies or []),
            inputs={
                "task": state.task,
                "repair_attempt": repair_count + 1,
                "repair_reason": "candidate_generation_failed",
                "last_error": error,
                "instruction": (
                    "The previous LLM candidate was rejected before verification. "
                    "Regenerate strict JSON with candidate_name, complete file contents, paths under candidate/, "
                    "and avoid any sandbox-prohibited APIs or includes."
                ),
            },
        )
        for item in self.todo_manager.todo_list.items:
            if item.assigned_tool in {"verify_candidate.run", "verify.run_csim"} and item.status in {"pending", "blocked"}:
                self._replace_dependencies(item.id, [retry_todo.id])
        state.status = "partial_success"
        state.todos = self.todo_manager.todo_list.items

    def _remove_recovered_error(self, state: AgentState, error: dict[str, Any]) -> None:
        if not error:
            return
        error_type = error.get("error_type")
        message = error.get("message")
        source = error.get("source")
        state.errors = [
            item
            for item in state.errors
            if not (
                item.get("error_type") == error_type
                and item.get("message") == message
                and item.get("source") == source
            )
        ]

    def _resolve_errors_after_success(self, state: AgentState, todo: TodoItem) -> None:
        from ..core.errors import mark_errors_resolved

        tool_name = todo.assigned_tool or ""
        error_types: set[str] = set()
        if tool_name in {"verify_candidate.run", "verify.run_csim", "verify.compare_reference"}:
            error_types = {"VerificationFailedError", "VivadoSynthesisError"}
        elif tool_name in {"vivado.run_csim", "vivado.run_csynth", "vivado.parse_report", "vivado.parse_csynth_report"}:
            error_types = {"VivadoSynthesisError", "ReportMissingError", "ReportParseError"}
        elif tool_name in {"llm.generate_candidate", "llm.generate_hls_candidate"}:
            error_types = {"LLMGenerationError"}
        if not error_types:
            return
        resolved = mark_errors_resolved(
            state.errors,
            error_types=error_types,
            resolved_by_todo_id=todo.id,
            resolution=f"Recovered by successful {tool_name} execution.",
        )
        for item in resolved:
            self.context["hooks"].emit(
                "ErrorResolved",
                {
                    "run_id": state.run_id,
                    "todo_id": todo.id,
                    "tool": tool_name,
                    "error_type": item.get("error_type"),
                    "original_source": item.get("source"),
                },
            )

    def _call_tool(self, state: AgentState, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.executor.call_and_record(state, tool_name, arguments)

    def _reason_for_todo(self, state: AgentState, todo: TodoItem) -> str:
        return f"Need to execute '{todo.title}' for task {state.task.get('name')} with current path {state.selected_path or 'unselected'}."

    def _execute_todo_actions(self, state: AgentState, todo: TodoItem) -> dict[str, Any]:
        if todo.title == "Validate task schema" or todo.assigned_tool == "task.validate_schema":
            result = self._call_tool(state, "task.validate_schema", {"task": state.task})
            self.todo_manager.mark_completed(todo.id, result)
            return {"status": "completed", "action": {"tool": "task.validate_schema"}, "observation": result}

        if todo.title == "Inspect model structure" or todo.assigned_tool == "hls4ml.inspect_model":
            result = self._call_tool(
                state,
                "hls4ml.inspect_model",
                {"model_path": state.task["model_path"], "frontend": state.task.get("frontend", "onnx")},
            )
            if result.get("status") == "success":
                self.todo_manager.mark_completed(todo.id, result)
                return {"status": "completed", "action": {"tool": "hls4ml.inspect_model"}, "observation": result}
            self.todo_manager.mark_failed(todo.id, result.get("error", {}))
            state.errors.append(result.get("error", {}))
            return {"status": "failed", "action": {"tool": "hls4ml.inspect_model"}, "observation": result}

        if todo.title == "Check hls4ml support" or todo.assigned_tool == "hls4ml.check_support":
            result = self._call_tool(state, "hls4ml.check_support", {"task": state.task})
            state.hls4ml_support = result
            if result.get("status") == "supported":
                self.todo_manager.mark_completed(todo.id, result)
                return {"status": "completed", "hls4ml_status": "supported", "action": {"tool": "hls4ml.check_support"}, "observation": result}
            self.todo_manager.mark_completed_with_warning(todo.id, result, {"message": result.get("recommendation")})
            return {"status": "completed_with_warning", "hls4ml_status": "unsupported", "action": {"tool": "hls4ml.check_support"}, "observation": result}

        if todo.title == "Try graph rewrite" or todo.assigned_tool == "graph_rewrite.rewrite":
            result = self._call_tool(state, "graph_rewrite.rewrite", {"task": state.task})
            if result.get("status") == "success" and result.get("implemented") and result.get("rewritten_model_path"):
                state.task["original_model_path"] = state.task.get("original_model_path") or state.task.get("model_path")
                state.task["model_path"] = result["rewritten_model_path"]
                state.artifacts["rewritten_model"] = result["rewritten_model_path"]
            self.todo_manager.mark_completed(todo.id, result)
            return {"status": "completed", "action": {"tool": "graph_rewrite.rewrite"}, "observation": result}

        if todo.title == "Generate hls4ml config" or todo.assigned_tool == "hls4ml.generate_config":
            hls4ml_args = {
                "model_path": state.task["model_path"],
                "frontend": state.task.get("frontend", "onnx"),
                "backend": state.task.get("target", {}).get("backend", "Vivado"),
                "part": state.task.get("target", {}).get("part", "xc7z020clg400-1"),
                "clock_period": state.task.get("target", {}).get("clock_period", 5),
                "precision": state.task.get("hls4ml", {}).get("precision", "fixed<16,6>"),
                "reuse_factor": state.task.get("hls4ml", {}).get("reuse_factor", 1),
                "strategy": state.task.get("hls4ml", {}).get("strategy", "Latency"),
                "output_dir": str(self.context["artifact_manager"].run_dir),
            }
            io_type = state.task.get("hls4ml", {}).get("io_type") or state.task.get("hls4ml", {}).get("IOType")
            if io_type:
                hls4ml_args["io_type"] = io_type
            accumulator_precision = (
                state.task.get("hls4ml", {}).get("accumulator_precision")
                or state.task.get("hls4ml", {}).get("accum_precision")
            )
            if accumulator_precision:
                hls4ml_args["accumulator_precision"] = accumulator_precision
            layer_overrides = (
                state.task.get("hls4ml", {}).get("layer_overrides")
                or state.task.get("hls4ml", {}).get("LayerName")
                or {}
            )
            if layer_overrides:
                hls4ml_args["layer_overrides"] = layer_overrides
            model_overrides = (
                state.task.get("hls4ml", {}).get("model_overrides")
                or state.task.get("hls4ml", {}).get("Model")
                or {}
            )
            if model_overrides:
                hls4ml_args["model_overrides"] = model_overrides
            result = self._call_tool(
                state,
                "hls4ml.generate_config",
                hls4ml_args,
            )
            state.hls4ml_config_path = result.get("config_path")
            if result.get("status") == "success":
                if state.hls4ml_config_path:
                    self.context["artifact_manager"].register_file(state.hls4ml_config_path, "hls4ml_config")
                self.todo_manager.mark_completed(todo.id, result)
                return {"status": "completed", "action": {"tool": "hls4ml.generate_config"}, "observation": result}
            self.todo_manager.mark_failed(todo.id, result.get("error", {}))
            state.errors.append(result.get("error", {}))
            return {"status": "failed", "action": {"tool": "hls4ml.generate_config"}, "observation": result}

        if todo.title == "Convert with hls4ml" or todo.assigned_tool == "hls4ml.convert":
            result = self._call_tool(
                state,
                "hls4ml.convert",
                {
                    "model_path": state.task["model_path"],
                    "frontend": state.task.get("frontend", "onnx"),
                    "config_path": state.hls4ml_config_path,
                    "output_dir": str(self.context["artifact_manager"].run_dir / "hls_project"),
                },
            )
            if result.get("status") == "success":
                state.selected_path = "hls4ml_path"
                state.hls_project_dir = result.get("hls_project_dir")
                self.todo_manager.mark_completed(todo.id, result)
                return {"status": "completed", "action": {"tool": "hls4ml.convert"}, "observation": result}
            self.todo_manager.mark_failed(todo.id, result.get("error", {}))
            state.errors.append(result.get("error", {}))
            return {"status": "failed", "action": {"tool": "hls4ml.convert"}, "observation": result}

        if todo.title == "Generate fallback HLS template" or todo.assigned_tool == "fallback.generate_operator_hls":
            generated_dir = self.context["artifact_manager"].run_dir / "generated"
            result = self._call_tool(state, "fallback.generate_operator_hls", {"task": state.task, "output_dir": str(generated_dir)})
            if result.get("status") == "success":
                state.selected_path = "fallback_template_path"
                state.hls_project_dir = str(generated_dir)
                self._call_tool(
                    state,
                    "db.save_implementation",
                    {
                        "run_id": state.run_id,
                        "operator_id": None,
                        "source": "fallback_template",
                        "status": "generated",
                        "hls_project_dir": state.hls_project_dir,
                        "hls_file_path": next((str(path) for path in Path(state.hls_project_dir).glob("*.cpp") if path.name != "testbench.cpp"), None),
                        "testbench_path": next((str(path) for path in Path(state.hls_project_dir).glob("testbench.cpp")), None),
                        "tcl_path": next((str(path) for path in Path(state.hls_project_dir).glob("*.tcl")), None),
                        "notes": "Generated from fallback template.",
                    },
                )
                self.todo_manager.mark_completed(todo.id, result)
                return {"status": "completed", "action": {"tool": "fallback.generate_operator_hls"}, "observation": result}
            self.todo_manager.mark_completed_with_warning(todo.id, result, result.get("error", {}))
            return {"status": "completed_with_warning", "action": {"tool": "fallback.generate_operator_hls"}, "observation": result}

        if todo.title == "Generate LLM candidate" or todo.assigned_tool in {"llm.generate_candidate", "llm.generate_hls_candidate"}:
            candidate_dir = self.context["artifact_manager"].run_dir / "candidate"
            op_spec = dict(state.task)
            if todo.inputs:
                op_spec["candidate_generation_context"] = {
                    "repair_attempt": todo.inputs.get("repair_attempt", 0),
                    "repair_reason": todo.inputs.get("repair_reason"),
                    "last_error": todo.inputs.get("last_error"),
                    "recent_errors": state.errors[-5:],
                    "previous_candidate_dir": state.hls_project_dir,
                    "last_report": todo.inputs.get("last_report"),
                    "timing": todo.inputs.get("timing"),
                    "instruction": todo.inputs.get(
                        "instruction",
                        "Regenerate a complete candidate if prior verification failed; preserve the same top_function contract.",
                    ),
                }
            result = self._call_tool(
                state,
                "llm.generate_candidate",
                {"op_spec": op_spec, "rag_context": state.rag_context, "output_dir": str(candidate_dir)},
            )
            if result.get("status") == "candidate_generated":
                state.selected_path = "llm_candidate_path"
                state.hls_project_dir = str(candidate_dir)
                self.todo_manager.mark_completed(todo.id, result)
                verify_todo = self._first_active_tool({"verify_candidate.run", "verify.run_csim"})
                if verify_todo is not None:
                    verify_todo.inputs = {**(verify_todo.inputs or {}), "candidate_dir": str(candidate_dir)}
                    self._replace_dependencies(verify_todo.id, [todo.id])
                else:
                    verify_todo = self.todo_manager.append_item(
                        title="Verify LLM candidate",
                        description="Verify candidate with csim/csynth flow.",
                        priority=todo.priority + 1,
                        assigned_tool="verify_candidate.run",
                        dependencies=[todo.id],
                        inputs={"candidate_dir": str(candidate_dir)},
                    )
                self._rewire_vivado_chain_after_implementation(state, verify_todo.id)
                state.todos = self.todo_manager.todo_list.items
                return {"status": "completed", "action": {"tool": "llm.generate_candidate"}, "observation": result}
            self.todo_manager.mark_failed(todo.id, result.get("error", {}))
            state.errors.append(result.get("error", {}))
            return {"status": "failed", "action": {"tool": "llm.generate_candidate"}, "observation": result}

        if todo.title == "Verify LLM candidate" or todo.assigned_tool == "verify_candidate.run":
            report_dir = self.context["artifact_manager"].run_dir / "reports"
            result = self._call_tool(
                state,
                "verify_candidate.run",
                {
                    "candidate_dir": state.hls_project_dir,
                    "report_dir": str(report_dir),
                    "force_fail": bool(state.task.get("force_fail")),
                    "top_function": state.task.get("top_function") or state.task.get("name"),
                    "part": state.task.get("target", {}).get("part", "xc7z020clg400-1"),
                    "clock_period": state.task.get("target", {}).get("clock_period", 5),
                    "candidate_contract": state.task.get("candidate_contract", {}),
                },
            )
            if result.get("status") == "verified":
                report_path = result.get("csynth", {}).get("report_path")
                if report_path:
                    state.report = self._call_tool(state, "vivado.parse_report", {"report_path": report_path})
                self.todo_manager.mark_completed(todo.id, result)
                return {"status": "completed", "action": {"tool": "verify_candidate.run"}, "observation": result}
            self.todo_manager.mark_completed_with_warning(todo.id, result, result.get("error", {}))
            state.errors.append(result.get("error", {}))
            return {"status": "completed_with_warning", "error_type": result.get("error", {}).get("error_type"), "action": {"tool": "verify_candidate.run"}, "observation": result}

        if todo.title == "Prepare existing HLS project" or todo.assigned_tool == "task.prepare_existing_project":
            state.selected_path = "existing_hls_project_path"
            state.hls_project_dir = state.task["hls_project_dir"]
            self._call_tool(
                state,
                "db.save_implementation",
                {
                    "run_id": state.run_id,
                    "operator_id": None,
                    "source": "existing_hls_project",
                    "status": "generated",
                    "hls_project_dir": state.hls_project_dir,
                    "hls_file_path": next((str(path) for path in Path(state.hls_project_dir).glob("*.cpp") if path.name != "testbench.cpp"), None),
                    "testbench_path": next((str(path) for path in Path(state.hls_project_dir).glob("testbench.cpp")), None),
                    "tcl_path": next((str(path) for path in Path(state.hls_project_dir).glob("*.tcl")), None),
                    "notes": "Using existing HLS project.",
                },
            )
            result = {"status": "success", "hls_project_dir": state.hls_project_dir}
            self.todo_manager.mark_completed(todo.id, result)
            return {"status": "completed", "action": {"tool": "task.prepare_existing_project"}, "observation": result}

        if todo.title == "Run Vivado HLS synthesis" or todo.assigned_tool == "vivado.run_csynth":
            if not state.hls_project_dir and state.task["task_type"] == "operator":
                llm_todo = self.todo_manager.append_item(
                    title="Generate LLM candidate",
                    description="Fallback templates were unavailable; try mock LLM candidate generation.",
                    priority=todo.priority - 1 if todo.priority > 1 else 1,
                    assigned_tool="llm.generate_candidate",
                    dependencies=todo.dependencies[:],
                    inputs={"task": state.task},
                )
                self.todo_manager.add_dependency(todo.id, llm_todo.id)
                self.todo_manager.mark_blocked(todo.id, "Waiting for a generated HLS implementation path.")
                state.todos = self.todo_manager.todo_list.items
                return {"status": "blocked", "action": {"tool": None}, "observation": {"status": "blocked"}}
            if not state.hls_project_dir:
                self.todo_manager.mark_skipped(todo.id, "No HLS project directory was available.")
                return {"status": "skipped", "action": {"tool": None}, "observation": {"status": "skipped"}}
            create_result = self._call_tool(
                state,
                "vivado.create_project",
                {
                    "hls_project_dir": state.hls_project_dir,
                    "top_function": state.task.get("top_function") or state.task.get("name"),
                    "part": state.task.get("target", {}).get("part", "xc7z020clg400-1"),
                    "clock_period": state.task.get("target", {}).get("clock_period", 5),
                    "work_dir": str(self.context["artifact_manager"].run_dir / "vivado_hls"),
                },
            )
            if create_result.get("status") != "success":
                self.todo_manager.mark_failed(todo.id, create_result.get("error", {}))
                state.errors.append(create_result.get("error", {}))
                return {"status": "failed", "action": {"tool": "vivado.create_project"}, "observation": create_result}
            state.vivado_work_dir = create_result.get("work_dir")
            tcl_path = create_result.get("tcl_path")
            csynth_result = self._call_tool(
                state,
                "vivado.run_csynth",
                {"work_dir": state.vivado_work_dir, "tcl_path": tcl_path, "top_function": create_result.get("top_function")},
            )
            if csynth_result.get("verification"):
                state.verification = csynth_result["verification"]
            if csynth_result.get("status") == "success":
                if state.verification and state.verification.get("passed") is False:
                    error = build_error(
                        "VerificationFailedError",
                        "Vivado C simulation functional verification failed.",
                        recoverable=True,
                        source="vivado.run_csynth",
                        suggested_action="Inspect reference/output mismatch before trusting synthesis metrics.",
                        details={"verification": state.verification},
                    ).to_dict()
                    state.errors.append(error)
                    self.todo_manager.mark_failed(todo.id, error)
                    return {"status": "failed", "action": {"tool": "vivado.run_csynth"}, "observation": csynth_result}
                report_path = csynth_result.get("report_path")
                if report_path and Path(report_path).exists():
                    self.context["artifact_manager"].register_file(report_path, "vivado_report")
                    state.report = self._call_tool(state, "vivado.parse_report", {"report_path": report_path})
                    self._call_tool(
                        state,
                        "db.save_synthesis_run",
                        {
                            "run_id": state.run_id,
                            "implementation_id": None,
                            "tool": "vivado_hls",
                            "tool_version": "mock" if "solution1" in report_path else "unknown",
                            "part": state.task.get("target", {}).get("part"),
                            "clock_period": state.task.get("target", {}).get("clock_period"),
                            "latency_min": state.report.get("latency", {}).get("min_cycles"),
                            "latency_max": state.report.get("latency", {}).get("max_cycles"),
                            "ii_min": state.report.get("interval", {}).get("min_ii"),
                            "ii_max": state.report.get("interval", {}).get("max_ii"),
                            "dsp": state.report.get("resources", {}).get("dsp"),
                            "bram": state.report.get("resources", {}).get("bram"),
                            "lut": state.report.get("resources", {}).get("lut"),
                            "ff": state.report.get("resources", {}).get("ff"),
                            "timing_met": 1 if state.report.get("timing", {}).get("met") else 0 if state.report.get("timing", {}).get("met") is False else None,
                            "report_path": report_path,
                        },
                    )
                self.todo_manager.mark_completed(todo.id, csynth_result)
                return {
                    "status": "completed",
                    "action": {"tool": "vivado.run_csynth", "args_hash": csynth_result.get("log_path")},
                    "observation": csynth_result,
                }
            error = csynth_result.get("error", {})
            if error.get("error_type") == "VivadoNotFoundError":
                state.errors.append(error)
                self._call_tool(
                    state,
                    "db.save_failure",
                    {
                        "run_id": state.run_id,
                        "implementation_id": None,
                        "error_type": error.get("error_type"),
                        "error_message": error.get("message"),
                        "log_summary": error.get("message"),
                        "suggested_fix": error.get("suggested_action"),
                    },
                )
                state.report = empty_report("skipped")
                self.todo_manager.mark_skipped(todo.id, error.get("message", "Vivado synthesis skipped."))
                return {"status": "skipped", "error_type": error.get("error_type"), "action": {"tool": "vivado.run_csynth"}, "observation": csynth_result}
            self.todo_manager.mark_failed(todo.id, error)
            state.errors.append(error)
            return {"status": "failed", "action": {"tool": "vivado.run_csynth"}, "observation": csynth_result}

        if todo.title == "Parse synthesis report" or todo.assigned_tool == "vivado.parse_report":
            if state.report and state.report.get("status") == "success":
                self.todo_manager.mark_completed(todo.id, state.report)
                return {"status": "completed", "action": {"tool": "vivado.parse_report"}, "observation": state.report}
            if state.vivado_work_dir:
                log_result = self._call_tool(state, "vivado.parse_log", {"log_path": str(Path(state.vivado_work_dir) / "csynth.log")})
                if log_result.get("warnings"):
                    self.todo_manager.mark_completed_with_warning(todo.id, log_result, {"message": log_result.get("summary")})
                    return {"status": "completed_with_warning", "action": {"tool": "vivado.parse_log"}, "observation": log_result}
                self.todo_manager.mark_skipped(todo.id, "Report unavailable; log summary captured instead.")
                return {"status": "skipped", "action": {"tool": "vivado.parse_log"}, "observation": log_result}
            self.todo_manager.mark_skipped(todo.id, "No Vivado work directory was available.")
            return {"status": "skipped", "action": {"tool": None}, "observation": {"status": "skipped"}}

        if todo.title == "Generate unsupported report" or todo.assigned_tool == "report.write_unsupported":
            result = self._call_tool(
                state,
                "report.write_unsupported",
                {"reason": todo.inputs.get("reason") or "No safe path was available for this task."},
            )
            state.selected_path = "unsupported_path"
            if result.get("path"):
                state.artifacts["unsupported_report"] = result["path"]
            self.todo_manager.mark_completed(todo.id, result)
            return {"status": "completed", "action": {"tool": "report.write_unsupported"}, "observation": result}

        if todo.title == "Generate optimization suggestions" or todo.assigned_tool == "suggestion.suggest_optimization":
            result = self._call_tool(
                state,
                "suggestion.suggest_optimization",
                {
                    "state": state.to_dict(),
                    "report": state.report or empty_report("missing"),
                    "rag_context": state.rag_context,
                    "objective": state.objective,
                },
            )
            state.suggestions = result.get("suggestions", [])
            if result.get("path"):
                state.artifacts["suggestions"] = result["path"]
            if result.get("status") == "skipped":
                self.todo_manager.mark_skipped(todo.id, result.get("reason", "Optimization suggestions were skipped."))
                return {"status": "skipped", "action": {"tool": "suggestion.suggest_optimization"}, "observation": result}
            self.todo_manager.mark_completed(todo.id, result)
            return {"status": "completed", "action": {"tool": "suggestion.suggest_optimization"}, "observation": result}

        if todo.title == "Write run summary" or todo.assigned_tool == "summary.write_summary":
            result = self._call_tool(state, "summary.write_summary", {"state": state.to_dict()})
            if result.get("path"):
                state.artifacts["summary"] = result["path"]
            self.todo_manager.mark_completed(todo.id, result)
            return {"status": "completed", "action": {"tool": "summary.write_summary"}, "observation": result}

        if todo.title == "Promote memories" or todo.assigned_tool == "memory.promote_to_long_term":
            self.todo_manager.mark_skipped(todo.id, "Memory promotion is handled during runtime finalization.")
            return {"status": "skipped", "action": {"tool": "memory.promote_to_long_term"}, "observation": {"status": "skipped"}}

        self.todo_manager.mark_skipped(todo.id, "No action mapped for this todo.")
        return {"status": "skipped", "action": {"tool": None}, "observation": {"status": "skipped"}}

    def _decision_from_observation(self, state: AgentState, todo: TodoItem, observation: dict) -> str:
        status = observation.get("status")
        if status == "completed":
            return "Mark todo as completed and continue."
        if status == "completed_with_warning":
            return "Mark todo as completed_with_warning and let the reflector decide follow-up todos."
        if status == "skipped":
            return "Mark todo as skipped and continue remaining ready todos."
        if status == "blocked":
            return "Keep todo blocked until a prerequisite implementation path is produced."
        state.status = "failed" if status == "failed" and state.report is None else state.status
        return "Mark todo as failed and surface the structured error."

    def _write_short_term_for_todo(self, state: AgentState, todo: TodoItem, observation: dict) -> None:
        entry = build_short_term_entry(
            todo.id,
            {
                "title": todo.title,
                "status": observation.get("status"),
                "summary": (todo.outputs or {}).get("summary") or (todo.error or {}).get("message") or todo.title,
                "error": todo.error,
                "selected_path": state.selected_path,
            },
        )
        result = self._call_tool(state, "memory.write_short_term", {"run_id": state.run_id, "key": entry["key"], "value": entry["value"]})
        state.short_term_memory = result.get("short_term", {}).get("entries", state.short_term_memory)
        if result.get("path"):
            state.artifacts["short_term_memory"] = result["path"]

    def _ensure_active_todo(
        self,
        *,
        title: str,
        description: str,
        priority: int,
        assigned_tool: str,
        dependencies: list[str],
        inputs: dict[str, Any],
        tool_names: set[str],
    ) -> TodoItem:
        for item in self.todo_manager.todo_list.items:
            if item.assigned_tool in tool_names and item.status in {"pending", "blocked"}:
                for dependency_id in dependencies:
                    self.todo_manager.add_dependency(item.id, dependency_id)
                return item
        return self.todo_manager.append_item(
            title=title,
            description=description,
            priority=priority,
            assigned_tool=assigned_tool,
            dependencies=dependencies,
            inputs=inputs,
        )

    def _add_dependency_to_tool(self, state: AgentState, tool_names: set[str], dependency_id: str) -> None:
        for item in self.todo_manager.todo_list.items:
            if item.assigned_tool in tool_names and item.id != dependency_id and item.status in {"pending", "blocked"}:
                self.todo_manager.add_dependency(item.id, dependency_id)
        state.todos = self.todo_manager.todo_list.items

    def _add_dependency_to_title(self, state: AgentState, title: str, dependency_id: str) -> None:
        for item in self.todo_manager.todo_list.items:
            if item.title == title and item.id != dependency_id:
                self.todo_manager.add_dependency(item.id, dependency_id)
        state.todos = self.todo_manager.todo_list.items

    def _replace_dependencies(self, todo_id: str, dependency_ids: list[str]) -> None:
        item = self.todo_manager._find(todo_id)
        item.dependencies = list(dict.fromkeys(dep for dep in dependency_ids if dep != todo_id))
        blocked_message = str((item.error or {}).get("message") or "")
        if item.status == "blocked" and (
            blocked_message == "Dependencies are not completed yet."
            or "requires an HLS project directory" in blocked_message
        ):
            item.status = "pending"
            item.error = None
        self.todo_manager.save(self.todo_manager.todo_list.run_id, self.todo_manager.todo_list)

    def _first_active_tool(self, tool_names: set[str]):
        for item in self.todo_manager.todo_list.items:
            if item.assigned_tool in tool_names and item.status in {"pending", "blocked"}:
                return item
        return None

    def _switch_finalization_to_terminal(self, state: AgentState, terminal_id: str) -> None:
        suggest = self._first_active_tool({"suggestion.suggest_optimization", "suggestion.generate"})
        summary = self._first_active_tool({"summary.write_summary"})
        memory = self._first_active_tool({"memory.promote_to_long_term"})
        tail_id = terminal_id
        if suggest is not None:
            self._replace_dependencies(suggest.id, [tail_id])
            tail_id = suggest.id
        if summary is not None:
            self._replace_dependencies(summary.id, [tail_id])
            tail_id = summary.id
        if memory is not None:
            self._replace_dependencies(memory.id, [tail_id])
        state.todos = self.todo_manager.todo_list.items

    def _rewire_vivado_chain_after_implementation(self, state: AgentState, implementation_todo_id: str) -> None:
        create = self._first_active_tool({"vivado.create_project", "vivado.create_vivado_project"})
        synth = self._first_active_tool({"vivado.run_csynth"})
        parse = self._first_active_tool({"vivado.parse_report", "vivado.parse_csynth_report"})
        terminal_id = implementation_todo_id
        if create is not None:
            self._replace_dependencies(create.id, [implementation_todo_id])
            terminal_id = create.id
        if synth is not None:
            self._replace_dependencies(synth.id, [terminal_id])
            terminal_id = synth.id
        if parse is not None:
            self._replace_dependencies(parse.id, [terminal_id])
            terminal_id = parse.id
        self._switch_finalization_to_terminal(state, terminal_id)

    def _cancel_pending_tools(self, tool_names: set[str], reason: str) -> None:
        for item in self.todo_manager.todo_list.items:
            if item.status in {"pending", "blocked"} and item.assigned_tool in tool_names:
                self.todo_manager.mark_cancelled(item.id, reason)

    def _compress_outputs(self, state: AgentState) -> dict[str, Any]:
        compressed = {"logs": [], "reports": []}
        for item in state.tool_results:
            result = item["result"]
            if isinstance(result, dict):
                log_path = result.get("log_path")
                report_path = result.get("report_path")
                if log_path:
                    compressed["logs"].append(self.compressor.compress_vivado_log(log_path))
                if report_path:
                    compressed["reports"].append(self.compressor.compress_csynth_report(report_path))
        return compressed
