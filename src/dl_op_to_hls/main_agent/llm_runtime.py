from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..core.budgets import RunBudget
from ..core.errors import AgentRuntimeError, build_error
from ..llm.actions import MAIN_AGENT_ACTIONS, build_layered_tool_view
from ..llm.client import LLMClient
from ..llm.controller import LLMController
from ..llm.guards import LLMGuard
from ..llm.trace import emit_llm_event
from ..schemas.task_schema import load_task
from ..skills.expander import SkillExpander
from ..skills.policy import SkillPolicy
from ..skills.prompt_context import SkillPromptContextBuilder
from ..skills.registry import SkillRegistry
from .reflector import reflect_on_errors, update_status_from_todos
from .runtime import PlanExecuteReactRuntime, _normalize_task
from .state import AgentState
from .todo import TodoList


class LLMFirstRuntime(PlanExecuteReactRuntime):
    def __init__(
        self,
        agent,
        llm_client: LLMClient | None = None,
        session_id: str | None = None,
        user_id: str = "local-user",
        project_id: str | None = None,
    ):
        super().__init__(agent, session_id=session_id)
        self.llm_client = llm_client or LLMClient()
        self.controller = LLMController()
        self.guard = LLMGuard()
        self.skill_registry = SkillRegistry(agent.config.workspace_root / "skills")
        self.skill_policy = SkillPolicy()
        self.skill_prompt_builder = SkillPromptContextBuilder()
        self.skill_expander = SkillExpander()
        self.selected_skill = None
        self.user_id = user_id
        self.project_id = project_id or agent.config.workspace_root.name

    def run(self, input_data: str | dict[str, Any]) -> AgentState:
        session = self.agent.session_manager.create(
            input_data,
            self.session_id,
            user_id=self.user_id,
            project_id=self.project_id,
        )
        self.session_id = session["session_id"]
        session_context = self.agent.session_manager.compact_messages(self.session_id)
        session_context["last_task"] = (session.get("metadata") or {}).get("last_task")
        self.llm_client.set_context({"session_id": self.session_id, "session_context": session_context})
        state = self.initialize(input_data)
        self.agent.session_manager.bind_run(self.session_id, state.run_id)
        self.agent.session_manager.set_metadata(self.session_id, last_task=state.task)
        self.llm_client.set_context(self.context)
        hooks = self.context["hooks"]
        hooks.emit(
            "RunStarted",
            {"run_id": state.run_id, "session_id": self.session_id, "message": f"Starting LLM-first run for {state.task.get('name')}"},
        )
        try:
            self._ensure_llm_enabled()
            state = self.retrieve_initial_memory(state)
            state = self.build_skill_context(state)
            state = self.plan_todos(state)
            self._create_session_checkpoint(state, "llm_plan_accepted")
            state = self.execute_todos(state)
            if state.status != "interrupted":
                state = self.finalize(state)
        except AgentRuntimeError as exc:
            state.errors.append(exc.error.to_dict())
            state.status = "failed"
        except Exception as exc:  # pragma: no cover - defensive
            state.errors.append(
                build_error("InvalidTaskError", str(exc), recoverable=True, source="llm_runtime.run").to_dict()
            )
            state.status = "failed"
        finally:
            self._close_run(state, hooks, resumed=False)
        return state

    def resume(self, session_id: str) -> AgentState:
        self.session_id = session_id
        session = self.agent.session_manager.get(session_id)
        if (session.get("metadata") or {}).get("replan_required"):
            raise ValueError("The last user turn was retracted; submit replacement input with the same session_id to create a new plan.")
        if session.get("status") == "completed":
            raise ValueError("Completed session must be rolled back before it can be resumed")
        checkpoint = self.agent.session_manager.load_active_checkpoint(session_id)
        state = AgentState.from_dict(checkpoint["state"])
        state.session_id = session_id
        run_id = str(checkpoint.get("run_id") or state.run_id)
        self.context = self.agent.create_run_context(run_id, session_id)
        self._record_context_modes()
        if state.release_manifest:
            self.context["release_manifest"] = dict(state.release_manifest)
        self._initialize_governance(state)
        self._restore_run_budget(checkpoint)
        self.llm_client.set_context(self.context)
        self.executor = self._build_executor()
        self.todo_manager = self._build_todo_manager()
        self.compressor = self._build_compressor(run_id)
        self.specialist_router = self._build_router()
        self.todo_manager.todo_list = TodoList(run_id=run_id, items=state.todos)
        for todo in state.todos:
            if todo.status == "in_progress":
                todo.status = "pending"
        self.todo_manager.save(run_id, self.todo_manager.todo_list)
        self.skill_registry.load_all()
        self.skill_registry.pin_release_manifest(state.release_manifest)
        if state.selected_skill:
            try:
                self.selected_skill = self.skill_registry.get(state.selected_skill)
            except KeyError:
                self.selected_skill = None
        state.status = "initialized"
        self.agent.session_manager.mark_running(session_id)
        self.agent.session_manager.append_message(
            session_id,
            "system",
            f"Resumed from {checkpoint['checkpoint_id']}",
            {"kind": "resume", "checkpoint_id": checkpoint["checkpoint_id"]},
        )
        hooks = self.context["hooks"]
        hooks.emit(
            "RunResumed",
            {"run_id": run_id, "session_id": session_id, "checkpoint_id": checkpoint["checkpoint_id"]},
        )
        try:
            self._ensure_llm_enabled()
            state = self.execute_todos(state)
            if state.status != "interrupted":
                state = self.finalize(state)
        except AgentRuntimeError as exc:
            state.errors.append(exc.error.to_dict())
            state.status = "failed"
        except Exception as exc:  # pragma: no cover - defensive
            state.errors.append(build_error("InvalidTaskError", str(exc), recoverable=True, source="llm_runtime.resume").to_dict())
            state.status = "failed"
        finally:
            self._close_run(state, hooks, resumed=True)
        return state

    def _restore_run_budget(self, checkpoint: dict[str, Any]) -> None:
        budget_payload = ((checkpoint.get("runtime") or {}).get("run_budget") or {})
        if not budget_payload:
            budget_path = self.context["run_dir"] / "run_budget.json"
            if budget_path.exists():
                budget_payload = json.loads(budget_path.read_text(encoding="utf-8"))
        if not budget_payload:
            trace_path = self.context["run_dir"] / "trace.jsonl"
            events = []
            if trace_path.exists():
                for line in trace_path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        try:
                            events.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
            current = self.context["run_budget"].to_dict()
            usage_events = [item for item in events if item.get("event") == "LLMUsageRecorded"]
            budget_payload = {
                **current,
                "llm_calls": sum(1 for item in events if item.get("event") == "LLMCallStarted"),
                "tool_calls": sum(
                    1
                    for item in events
                    if item.get("event") == "PreToolUse" and int(item.get("attempt") or 1) == 1
                ),
                "input_tokens": sum(int(item.get("input_tokens") or 0) for item in usage_events),
                "output_tokens": sum(int(item.get("output_tokens") or 0) for item in usage_events),
                "cache_hits": sum(1 for item in events if item.get("event") == "ToolCacheHit"),
            }
        self.context["run_budget"] = RunBudget.from_dict(budget_payload)

    def _ensure_llm_enabled(self) -> None:
        if self.llm_client.is_enabled():
            return
        raise AgentRuntimeError(
            build_error(
                "LLMGenerationError",
                "LLM is not enabled or API key is missing.",
                recoverable=True,
                source="llm_runtime.run",
                suggested_action="Set DL_OP_TO_HLS_LLM_ENABLED=1 and DL_OP_TO_HLS_LLM_API_KEY.",
            )
        )

    def _close_run(self, state: AgentState, hooks, *, resumed: bool) -> None:
        reflect_on_errors(state)
        update_status_from_todos(state)
        if state.status != "interrupted":
            self._apply_completion_gate(state)
        trace_path = self.context["run_dir"] / "trace.jsonl"
        if trace_path.exists():
            self.context["artifact_manager"].register_file(trace_path, "trace")
            state.artifacts["trace"] = str(trace_path)
        budget = self.context.get("run_budget")
        if budget is not None:
            budget_path = self.context["artifact_manager"].write_json("run_budget.json", budget.to_dict(), "run_budget")
            state.artifacts["run_budget"] = str(budget_path)
        state_path = self.context["artifact_manager"].write_json("state.json", state.to_dict(), "state")
        state.artifacts["state"] = str(state_path)
        Path(state_path).write_text(json.dumps(state.to_dict(), indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        self._create_session_checkpoint(state, "run_interrupted" if state.status == "interrupted" else "run_finished")
        if state.status != "interrupted":
            self.agent.session_manager.append_message(
                self.session_id,
                "assistant",
                f"Run {state.run_id} finished with status {state.status}.",
                {"kind": "run_result", "run_id": state.run_id, "status": state.status, "resumed": resumed},
            )
            self.agent.session_manager.mark_finished(self.session_id, state.status)
            compacted = self.agent.session_manager.compact_messages(self.session_id)
            memory_identity = dict(self.context.get("memory_identity") or {})
            memory_identity["namespace"] = "user"
            self.context["memory_manager"].remember_conversation(
                summary=(compacted.get("summary") or f"Run {state.run_id} completed with status {state.status}."),
                identity=memory_identity,
                key=f"conversation.{self.session_id}.{state.run_id}",
                preferences={"objective": state.objective, "selected_path": state.selected_path},
            )
        hooks.emit(
            "RunFinished",
            {"run_id": state.run_id, "session_id": self.session_id, "status": state.status, "resumed": resumed},
        )

    def initialize(self, input_data: str | dict[str, Any]) -> AgentState:
        task = self._interpret_or_load_task(input_data)
        task = self._apply_generation_policy(task)
        run_id = self.agent.make_run_id(task)
        self.context = self.agent.create_run_context(run_id, self.session_id)
        self._record_context_modes()
        self.skill_registry.pin_release_manifest(self.context.get("release_manifest") or {})
        self.llm_client.set_context(self.context)
        self.executor = self.executor or self._build_executor()
        self.todo_manager = self.todo_manager or self._build_todo_manager()
        self.compressor = self.compressor or self._build_compressor(run_id)
        self.specialist_router = self.specialist_router or self._build_router()

        state = AgentState(run_id=run_id, task=task, session_id=self.session_id, objective=task.get("objective"))
        state.release_manifest = dict(self.context.get("release_manifest") or {})
        state.telemetry = {"format": "otlp-jsonl", "path": str(self.context["run_dir"] / "otel_spans.jsonl")}
        state.artifacts["run_dir"] = str(self.context["run_dir"])
        state.artifacts["telemetry"] = state.telemetry["path"]
        self._initialize_governance(state)
        self.context["artifact_manager"].write_json("input.json", task, "input_task")
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

    def _apply_generation_policy(self, task: dict[str, Any]) -> dict[str, Any]:
        """Make the configured operator path explicit before skill selection."""

        if task.get("task_type") != "operator":
            return task
        if self.agent.config.operator_generation_path != "llm_candidate":
            return task
        normalized = dict(task)
        from ..llm.candidate_generator import candidate_generation_contract_errors

        contract_errors = candidate_generation_contract_errors(normalized)
        if contract_errors:
            candidate = dict(normalized.get("llm_candidate") or {})
            candidate["required"] = False
            candidate["eligible"] = False
            candidate["rejection_reasons"] = contract_errors
            normalized["llm_candidate"] = candidate
            demo = dict(normalized.get("demo") or {})
            demo["expected_path"] = "unsupported_report"
            normalized["demo"] = demo
            normalized["capability_boundary"] = {
                "kind": "unverifiable_operator_semantics",
                "reasons": contract_errors,
                "decision": "reject_before_llm_or_vivado",
            }
            normalized["generation_policy"] = {
                "primary_path": "unsupported",
                "hls4ml_allowed": False,
                "template_role": "not_applicable",
            }
            return normalized
        candidate = dict(normalized.get("llm_candidate") or {})
        candidate["required"] = True
        candidate.setdefault("reuse_verified_implementations", self.agent.config.reuse_verified_implementations)
        candidate.setdefault("reason", "Runtime generation policy requires the verified LLM candidate path.")
        normalized["llm_candidate"] = candidate
        normalized["generation_policy"] = {
            "primary_path": "llm_candidate",
            "hls4ml_allowed": self.agent.config.allow_hls4ml_generation,
            "template_role": "fair_baseline_only",
        }
        return normalized

    def _build_executor(self):
        from .executor import AgentExecutor

        return AgentExecutor(self.agent.registry, self.context)

    def _build_todo_manager(self):
        from .todo import TodoManager

        return TodoManager(self.context["run_dir"], hooks=self.context["hooks"], artifact_manager=self.context["artifact_manager"])

    def _build_compressor(self, run_id: str):
        from ..core.context import ContextCompressor

        return ContextCompressor(hooks=self.context["hooks"], run_id=run_id)

    def _build_router(self):
        from ..specialists.router import build_default_router

        return build_default_router(self.context)

    def _interpret_or_load_task(self, input_data: str | dict[str, Any]) -> dict[str, Any]:
        try:
            interpreted = self.controller.task_interpreter.interpret(input_data, self.llm_client)
            task = load_task(interpreted["task"])
            return _normalize_task(task)
        except AgentRuntimeError:
            if isinstance(input_data, str):
                path = Path(input_data)
                if path.exists():
                    return _normalize_task(load_task(path))
            if isinstance(input_data, dict):
                return _normalize_task(load_task(input_data))
            raise

    def build_skill_context(self, state: AgentState) -> AgentState:
        self.skill_registry.load_all()
        skill_context = self.skill_prompt_builder.build(state.task, self.skill_registry, top_k=5)
        state.artifacts["skill_context"] = str(
            self.context["artifact_manager"].write_json("skill_context.json", skill_context, "summary")
        )
        emit_llm_event(
            self.context,
            "LLMSkillContextBuilt",
            {
                "run_id": state.run_id,
                "skill_count": len(skill_context.get("available_skills", [])),
            },
        )
        return state

    def plan_todos(self, state: AgentState) -> AgentState:
        layered_tool_view = build_layered_tool_view(self.agent.registry, self.specialist_router)
        available_tools = list(layered_tool_view["direct_tools"])
        available_specialists = [item["name"] for item in layered_tool_view["specialists"]]
        skill_context = json.loads(Path(state.artifacts["skill_context"]).read_text(encoding="utf-8"))
        errors: list[str] = []
        last_plan: dict[str, Any] | None = None
        for attempt in range(2):
            try:
                plan = self.controller.planner.plan(
                    task=state.task,
                    skill_context=skill_context,
                    available_tools=available_tools,
                    available_specialists=available_specialists,
                    layered_tool_view=layered_tool_view,
                    retrieved_memories=state.retrieved_memories,
                    goal_contract=state.goal_contract,
                    client=self.llm_client,
                )
            except AgentRuntimeError as exc:
                errors = [exc.error.message]
                emit_llm_event(
                    self.context,
                    "LLMPlanRejected",
                    {"run_id": state.run_id, "attempt": attempt + 1, "errors": errors},
                )
                continue
            last_plan = plan
            selected_skill = None
            if plan.get("selected_skill"):
                try:
                    selected_skill = self.skill_registry.get(plan["selected_skill"])
                except KeyError:
                    pass
            plan, coverage_repair = self.plan_coverage_validator.repair_with_skill(
                plan,
                selected_skill,
                state.goal_contract,
            )
            if coverage_repair["repaired"]:
                emit_llm_event(
                    self.context,
                    "LLMPlanCoverageRepaired",
                    {
                        "run_id": state.run_id,
                        "attempt": attempt + 1,
                        "added_tools": coverage_repair["added_tools"],
                        "missing_before": [
                            item["requirement_id"] for item in coverage_repair["before"]["missing_requirements"]
                        ],
                    },
                )
            terminal_tools = self._append_skill_terminal_todos(plan, selected_skill)
            if terminal_tools:
                emit_llm_event(
                    self.context,
                    "LLMPlanTerminalTodosAdded",
                    {"run_id": state.run_id, "attempt": attempt + 1, "added_tools": terminal_tools},
                )
            ownership_repair = self._repair_specialist_ownership(plan, layered_tool_view)
            if ownership_repair:
                emit_llm_event(
                    self.context,
                    "LLMPlanOwnershipRepaired",
                    {"run_id": state.run_id, "attempt": attempt + 1, "repairs": ownership_repair},
                )
            guard = self.guard.validate_todo_plan(plan, self.agent.registry, self.specialist_router, self.skill_registry)
            coverage = self.plan_coverage_validator.validate(state.goal_contract, plan.get("todos", []))
            skill_policy_result = self.skill_policy.validate_llm_plan_against_skill(plan, selected_skill, state.task)
            coverage_errors = [
                f"Plan does not cover required goal {item['requirement_id']}."
                for item in coverage["missing_requirements"]
            ]
            errors = guard["errors"] + skill_policy_result["errors"] + coverage_errors
            if not errors:
                emit_llm_event(
                    self.context,
                    "LLMPlanAccepted",
                    {
                        "run_id": state.run_id,
                        "selected_skill": plan.get("selected_skill"),
                        "todo_count": len(plan.get("todos", [])),
                    },
                )
                state.selected_skill = plan.get("selected_skill")
                state.skill_usage_mode = plan.get("skill_usage")
                state.plan_coverage = coverage
                state.llm_decisions.append(
                    {
                        "phase": "plan",
                        "reason_summary": plan.get("reason_summary"),
                        "selected_skill": state.selected_skill,
                    }
                )
                self.selected_skill = selected_skill
                if selected_skill is not None:
                    budget_policy = selected_skill.budget_policy
                    self.context["run_budget"].tighten(
                        max_llm_calls=budget_policy.get("max_llm_calls"),
                        max_tool_calls=budget_policy.get("max_tool_calls"),
                        max_total_tokens=budget_policy.get("max_tokens"),
                    )
                    concurrency_policy = selected_skill.concurrency_policy
                    self.context["scheduler"].apply_limits(
                        max_workers=concurrency_policy.get("max_parallel_tools"),
                        max_parallel_llm_calls=concurrency_policy.get("max_parallel_llm_calls"),
                    )
                    invocation = {
                        "skill": selected_skill.name,
                        "version": selected_skill.version,
                        "status": selected_skill.status,
                        "usage_mode": state.skill_usage_mode,
                        "allowed_tools": selected_skill.allowed_tools,
                        "allowed_specialists": selected_skill.allowed_specialists,
                        "context_policy": selected_skill.context_policy,
                        "budget_policy": selected_skill.budget_policy,
                        "concurrency_policy": selected_skill.concurrency_policy,
                    }
                    path = self.context["artifact_manager"].write_json("skill_invocation.json", invocation, "skill_invocation")
                    state.artifacts["skill_invocation"] = str(path)
                self._create_todos_from_llm_plan(state, plan)
                return state
            emit_llm_event(
                self.context,
                "LLMPlanRejected",
                {"run_id": state.run_id, "attempt": attempt + 1, "errors": errors},
            )
        raise AgentRuntimeError(
            build_error(
                "LLMGenerationError",
                "LLM plan validation failed: " + "; ".join(errors),
                recoverable=True,
                source="llm_runtime.plan_todos",
                suggested_action="Fix the planner prompt, tool exposure, specialist routing, or plan validator contract.",
                details={"last_plan": last_plan or {}},
            )
        )

    @staticmethod
    def _append_skill_terminal_todos(plan: dict[str, Any], skill: Any) -> list[str]:
        if skill is None:
            return []
        terminal_tools = {"suggestion.suggest_optimization", "memory.promote_to_long_term"}
        existing = {item.get("assigned_tool") for item in plan.get("todos", [])}
        added: list[str] = []
        for item in getattr(skill, "recommended_todos", []) or []:
            tool_name = item.get("assigned_tool") if isinstance(item, dict) else None
            if tool_name in terminal_tools and tool_name not in existing:
                plan.setdefault("todos", []).append(dict(item))
                existing.add(tool_name)
                added.append(str(tool_name))
        return added

    @staticmethod
    def _repair_specialist_ownership(plan: dict[str, Any], layered_tool_view: dict[str, Any]) -> list[dict[str, str]]:
        owners: dict[str, list[str]] = {}
        for specialist in layered_tool_view.get("specialists", []):
            for tool_name in specialist.get("capability_tools", []):
                owners.setdefault(tool_name, []).append(str(specialist["name"]))
        preferred = {
            "fallback.generate_testbench": "VerificationSpecialist",
            "vivado.run_csim": "VerificationSpecialist",
            "vivado.run_csynth": "VivadoSpecialist",
            "vivado.parse_report": "VivadoSpecialist",
            "vivado.parse_log": "VivadoSpecialist",
            "suggestion.suggest_optimization": "OptimizationSpecialist",
            "memory.promote_to_long_term": "MemorySpecialist",
        }
        repairs: list[dict[str, str]] = []
        for todo in plan.get("todos", []):
            tool_name = todo.get("assigned_tool")
            candidates = owners.get(tool_name, [])
            current = todo.get("assigned_specialist")
            if not candidates or current in candidates:
                continue
            selected = preferred.get(tool_name)
            if selected not in candidates:
                selected = candidates[0]
            todo["assigned_specialist"] = selected
            repairs.append({"title": str(todo.get("title") or ""), "tool": str(tool_name), "specialist": selected})
        return repairs

    def _create_todos_from_llm_plan(self, state: AgentState, plan: dict[str, Any]) -> None:
        expanded = list(plan.get("todos", []))
        if self.selected_skill is not None and not expanded:
            expanded = self.skill_expander.expand_recommended_todos(self.selected_skill, state.task)
        titles = [str(item.get("title", f"Todo {idx+1}")) for idx, item in enumerate(expanded)]
        todo_list = self.todo_manager.create_from_plan(state.run_id, titles, state.task)
        id_by_title = {item.title: item.id for item in todo_list.items}
        for index, item in enumerate(todo_list.items):
            spec = expanded[index] if index < len(expanded) else {}
            item.assigned_tool = spec.get("assigned_tool", item.assigned_tool)
            item.assigned_specialist = spec.get("assigned_specialist", item.assigned_specialist)
            item.description = spec.get("description", item.description)
            raw_inputs = spec.get("inputs", item.inputs)
            item.inputs = raw_inputs if isinstance(raw_inputs, dict) else {}
            if self.selected_skill is not None:
                max_context = self.selected_skill.context_policy.get("max_context_tokens")
                if max_context:
                    item.context_scope = {**item.context_scope, "max_context_tokens": int(max_context)}
            self._coerce_unsupported_recovery_todo(item)
            raw_dependencies = spec.get("dependencies")
            if isinstance(raw_dependencies, list):
                normalized: list[str] = []
                for dep in raw_dependencies:
                    if dep in id_by_title:
                        normalized.append(id_by_title[dep])
                    elif any(dep == todo.id for todo in todo_list.items):
                        normalized.append(dep)
                item.dependencies = normalized
        self._normalize_llm_plan_dependencies(todo_list, state.task)
        self.todo_manager.save(state.run_id, todo_list)
        state.todos = todo_list.items
        self._update_plan_coverage(state)
        state.artifacts["todos"] = str(self.context["run_dir"] / "todos.json")

    def _coerce_unsupported_recovery_todo(self, item) -> None:
        if item.assigned_tool:
            return
        inputs = item.inputs if isinstance(item.inputs, dict) else {}
        text = " ".join(str(value or "") for value in [item.title, item.description, inputs.get("reason"), inputs.get("action")]).lower()
        if "unsupported" not in text:
            return
        action = str(inputs.get("action") or "").lower()
        if action not in {"mark_failed", "mark_unsupported", "write_unsupported_report", ""} and "recover" not in text:
            return
        item.assigned_tool = "report.write_unsupported"
        reason = inputs.get("reason") or item.description or item.title
        item.inputs = {**inputs, "reason": reason}

    def _normalize_llm_plan_dependencies(self, todo_list, task: dict[str, Any]) -> None:
        """Project an LLM todo graph onto a valid acyclic workflow DAG.

        The LLM is allowed to propose task-specific titles and local ordering, but
        core HLS milestones have a fixed dependency contract. We keep the selected
        skill/path semantics, then normalize terminal edges so summary/memory
        finalization cannot form hidden cycles such as memory -> summary -> memory.
        """

        def first_by_tool(*tool_names: str):
            for item in todo_list.items:
                if item.assigned_tool in tool_names:
                    return item
            return None

        def require(item, dependency) -> None:
            if item is None or dependency is None or item.id == dependency.id:
                return
            if dependency.id not in item.dependencies:
                item.dependencies.append(dependency.id)

        def replace(item, dependencies) -> None:
            if item is None:
                return
            item.dependencies = list(
                dict.fromkeys(
                    dependency.id
                    for dependency in dependencies
                    if dependency is not None and dependency.id != item.id
                )
            )

        validate = first_by_tool("task.validate_schema")
        inspect = first_by_tool("hls4ml.inspect_model")
        support = first_by_tool("hls4ml.check_support", "hls4ml.check_hls4ml_support")
        graph = first_by_tool("graph_rewrite.rewrite")
        fallback = first_by_tool("fallback.generate_operator_hls")
        candidate = first_by_tool("llm.generate_candidate", "llm.generate_hls_candidate")
        verify = first_by_tool("verify_candidate.run", "verify.run_csim")
        config = first_by_tool("hls4ml.generate_config", "hls4ml.generate_hls4ml_config")
        convert = first_by_tool("hls4ml.convert", "hls4ml.convert_with_hls4ml")
        prepare_existing = first_by_tool("task.prepare_existing_project")
        vivado_create = first_by_tool("vivado.create_project", "vivado.create_vivado_project")
        vivado_synth = first_by_tool("vivado.run_csynth")
        parse = first_by_tool("vivado.parse_report", "vivado.parse_csynth_report")
        unsupported = first_by_tool("report.write_unsupported")
        suggest = first_by_tool("suggestion.suggest_optimization", "suggestion.generate")
        summary = first_by_tool("summary.write_summary")
        memory = first_by_tool("memory.promote_to_long_term")

        require(inspect, validate)
        require(support, inspect or validate)
        require(graph, support)
        require(fallback, graph or support)
        require(candidate, validate)
        require(verify, candidate)
        require(config, support)
        require(convert, config)
        require(prepare_existing, validate)

        implementation_source = verify or candidate or convert or fallback or prepare_existing
        require(vivado_create, implementation_source)
        require(vivado_synth, vivado_create or implementation_source)
        require(parse, vivado_synth)
        require(unsupported, graph or support)

        terminal = unsupported or parse or vivado_synth or implementation_source
        self._remove_dependency_cycles(todo_list)

        # Finalization has a canonical order because MemorySpecialist needs the
        # compressed summary/suggestion artifacts as inputs. Replace, do not append,
        # to remove LLM-introduced backward edges.
        replace(suggest, [terminal])
        replace(summary, [suggest or terminal])
        replace(memory, [summary or suggest or terminal])
        self._remove_dependency_cycles(todo_list)

    def _remove_dependency_cycles(self, todo_list) -> None:
        id_to_item = {item.id: item for item in todo_list.items}

        def visit(item, stack: set[str]) -> None:
            clean: list[str] = []
            for dep_id in item.dependencies:
                if dep_id not in id_to_item or dep_id == item.id:
                    continue
                if dep_id in stack:
                    continue
                visit(id_to_item[dep_id], stack | {item.id})
                if dep_id not in clean:
                    clean.append(dep_id)
            item.dependencies = clean

        for item in todo_list.items:
            visit(item, set())

    def execute_todo_with_react(self, state: AgentState, todo) -> dict[str, Any]:
        state.current_todo_id = todo.id
        self.todo_manager.mark_started(todo.id)
        specialist = self.specialist_router.route(todo) if self.specialist_router else None
        if specialist is not None and todo.assigned_tool and todo.assigned_tool not in set(specialist.allowed_tools):
            error = build_error(
                "PermissionDeniedError",
                f"Todo assigns tool {todo.assigned_tool} to specialist {specialist.name}, but the tool is outside the specialist allowed_tools.",
                recoverable=False,
                source="llm_runtime.execute_todo_with_react",
                suggested_action="Repair the LLM plan so each specialist only receives tools in its scoped tool list.",
                details={"todo_id": todo.id, "specialist": specialist.name, "assigned_tool": todo.assigned_tool},
            ).to_dict()
            emit_llm_event(
                self.context,
                "LLMSpecialistMismatchRejected",
                {
                    "run_id": state.run_id,
                    "todo_id": todo.id,
                    "specialist": specialist.name,
                    "assigned_tool": todo.assigned_tool,
                },
            )
            state.errors.append(error)
            self.todo_manager.mark_failed(todo.id, error)
            observation = {"status": "failed", "action": {"tool": todo.assigned_tool}, "observation": {"error": error}}
            self._write_short_term_for_todo(state, todo, observation)
            return observation
        if specialist is not None and self._should_auto_delegate_specialist(todo, specialist):
            emit_llm_event(
                self.context,
                "LLMReActAutoDelegated",
                {
                    "run_id": state.run_id,
                    "todo_id": todo.id,
                    "specialist": specialist.name,
                    "assigned_tool": todo.assigned_tool,
                },
            )
            observation = self._execute_todo_with_specialist(state, todo, specialist)
            todo.react_steps.append(
                {
                    "reason_summary": "Planner already assigned a scoped specialist; deterministic delegation avoids a no-op Main Agent LLM call.",
                    "action": {
                        "type": "delegate_to_specialist",
                        "tool_name": todo.assigned_tool,
                    },
                    "observation_summary": (
                        observation.get("observation", {}).get("summary")
                        or observation.get("observation", {}).get("status")
                        or observation.get("status")
                    ),
                    "decision": self._decision_from_observation(state, todo, observation),
                }
            )
            self._write_short_term_for_todo(state, todo, observation)
            return observation
        if specialist is None and todo.assigned_tool:
            emit_llm_event(
                self.context,
                "LLMReActAutoDirect",
                {
                    "run_id": state.run_id,
                    "todo_id": todo.id,
                    "assigned_tool": todo.assigned_tool,
                },
            )
            observation = self._execute_todo_actions(state, todo)
            todo.react_steps.append(
                {
                    "reason_summary": "The validated plan already assigned an atomic tool; execute it without a redundant Main Agent LLM decision.",
                    "action": {
                        "type": "direct_tool_only_when_no_specialist",
                        "tool_name": todo.assigned_tool,
                    },
                    "observation_summary": (
                        observation.get("observation", {}).get("summary")
                        or observation.get("observation", {}).get("status")
                        or observation.get("status")
                    ),
                    "decision": self._decision_from_observation(state, todo, observation),
                }
            )
            self._write_short_term_for_todo(state, todo, observation)
            return observation
        envelope = None
        if specialist is not None:
            envelope = self.context_builder.build_for_specialist(state=state, todo=todo, specialist_name=specialist.name)
            emit_llm_event(
                self.context,
                "ContextEnvelopeCreated",
                {
                    "run_id": state.run_id,
                    "todo_id": todo.id,
                    "specialist": specialist.name,
                    "max_context_tokens": envelope.max_context_tokens,
                },
            )
            allowed_actions = ["delegate_to_specialist", "request_replan", "mark_blocked", "mark_failed"]
            allowed_tools = []
            scoped_state = envelope.scoped_state
        else:
            allowed_actions = ["direct_tool_only_when_no_specialist", "request_replan", "mark_blocked", "mark_failed"]
            allowed_tools = [todo.assigned_tool] if todo.assigned_tool else []
            scoped_state = {"task": state.task, "selected_path": state.selected_path}

        try:
            decision = self.controller.react.decide(
                todo=todo.to_dict(),
                scoped_state=scoped_state,
                allowed_tools=allowed_tools,
                allowed_actions=allowed_actions,
                recent_observations=state.tool_results[-5:],
                client=self.llm_client,
            )
        except AgentRuntimeError as exc:
            state.errors.append(exc.error.to_dict())
            emit_llm_event(
                self.context,
                "LLMReActFailed",
                {
                    "run_id": state.run_id,
                    "todo_id": todo.id,
                    "error_type": exc.error.error_type,
                    "message": exc.error.message,
                },
            )
            self.todo_manager.mark_failed(todo.id, exc.error.to_dict())
            observation = {"status": "failed", "action": {}, "observation": {"error": exc.error.to_dict()}}
            self._write_short_term_for_todo(state, todo, observation)
            return observation
        guard = self.guard.validate_react_decision(decision, allowed_tools=allowed_tools, allowed_actions=allowed_actions)
        if guard["status"] != "valid":
            emit_llm_event(
                self.context,
                "LLMGuardRejected",
                {"run_id": state.run_id, "todo_id": todo.id, "errors": guard["errors"]},
            )
            error = build_error(
                "PermissionDeniedError",
                "LLM ReAct decision was rejected by guard: " + "; ".join(guard["errors"]),
                recoverable=False,
                source="llm_runtime.execute_todo_with_react",
                suggested_action="Repair the ReAct prompt or allowed_tools scope instead of executing an unapproved action.",
                details={"todo_id": todo.id, "decision": decision},
            ).to_dict()
            state.errors.append(error)
            self.todo_manager.mark_failed(todo.id, error)
            observation = {"status": "failed", "action": decision.get("action", {}), "observation": {"error": error}}
            self._write_short_term_for_todo(state, todo, observation)
            return observation

        action = decision.get("action", {}) or {}
        decision_name = decision.get("decision")
        if specialist is not None and decision_name == "delegate_to_specialist":
            observation = self._execute_todo_with_specialist(state, todo, specialist)
        elif decision_name == "direct_tool_only_when_no_specialist":
            selected_tool = action.get("tool_name") or action.get("tool") or todo.assigned_tool
            if selected_tool != todo.assigned_tool and selected_tool is not None:
                result = self._call_tool(state, selected_tool, action.get("arguments", todo.inputs or {}))
                if result.get("status") in {"success", "candidate_generated", "verified"}:
                    self.todo_manager.mark_completed(todo.id, result)
                    observation = {"status": "completed", "action": {"tool": selected_tool}, "observation": result}
                elif result.get("status") == "skipped":
                    self.todo_manager.mark_skipped(todo.id, result.get("error", {}).get("message", "Skipped by tool result."))
                    observation = {"status": "skipped", "action": {"tool": selected_tool}, "observation": result}
                else:
                    self.todo_manager.mark_failed(todo.id, result.get("error", {}))
                    observation = {"status": "failed", "action": {"tool": selected_tool}, "observation": result}
            else:
                observation = self._execute_todo_actions(state, todo)
        elif decision_name == "request_replan":
            reason = action.get("reason") or decision.get("reason_summary") or "Replan requested by LLM decision."
            self.todo_manager.mark_blocked(todo.id, reason)
            observation = {"status": "blocked", "action": {"type": "request_replan"}, "observation": {"summary": reason}}
        elif decision_name == "mark_blocked":
            reason = action.get("reason") or decision.get("reason_summary") or "Blocked by LLM decision."
            self.todo_manager.mark_blocked(todo.id, reason)
            observation = {"status": "blocked", "action": {"tool": None}, "observation": {"summary": reason}}
        elif decision_name == "mark_failed":
            reason = action.get("reason") or decision.get("reason_summary") or "Failed by LLM decision."
            self.todo_manager.mark_failed(todo.id, {"error_type": "LLMGenerationError", "message": reason})
            observation = {"status": "failed", "action": {"tool": None}, "observation": {"summary": reason}}
        else:
            error = build_error(
                "LLMGenerationError",
                f"Unsupported Main Agent action: {decision_name}",
                recoverable=False,
                source="llm_runtime.execute_todo_with_react",
                details={"allowed_actions": allowed_actions, "decision": decision},
            ).to_dict()
            state.errors.append(error)
            self.todo_manager.mark_failed(todo.id, error)
            observation = {"status": "failed", "action": action, "observation": {"error": error}}

        todo.react_steps.append(
            {
                "reason_summary": decision.get("reason_summary", ""),
                "action": {
                    "type": decision_name,
                    "tool_name": action.get("tool_name") or action.get("tool") or todo.assigned_tool,
                },
                "observation_summary": (
                    observation.get("observation", {}).get("summary")
                    or observation.get("observation", {}).get("status")
                    or observation.get("status")
                ),
                "decision": self._decision_from_observation(state, todo, observation),
            }
        )
        state.llm_decisions.append(
            {
                "phase": "react",
                "todo_id": todo.id,
                "reason_summary": decision.get("reason_summary"),
                "decision": decision.get("decision"),
            }
        )
        self._write_short_term_for_todo(state, todo, observation)
        return observation

    def _should_auto_delegate_specialist(self, todo, specialist) -> bool:
        """Avoid spending an external LLM call to rediscover an already-scoped delegation."""
        return specialist is not None and bool(todo.assigned_specialist)

    def reflect(self, state: AgentState, todo, observation: dict) -> AgentState:
        if observation.get("status") in {"completed", "skipped"} and not observation.get("error_type"):
            return super().reflect(state, todo, observation)
        try:
            reflection = self.controller.reflector.reflect(
                current_todo=todo.to_dict(),
                observation=observation,
                current_skill=state.selected_skill,
                state_summary={
                    "run_id": state.run_id,
                    "status": state.status,
                    "selected_path": state.selected_path,
                    "errors": state.errors[-5:],
                },
                client=self.llm_client,
            )
        except AgentRuntimeError as exc:
            state.errors.append(exc.error.to_dict())
            emit_llm_event(
                self.context,
                "LLMReflectFailed",
                {
                    "run_id": state.run_id,
                    "todo_id": todo.id,
                    "error_type": exc.error.error_type,
                    "message": exc.error.message,
                },
            )
            self.todo_manager.mark_failed(todo.id, exc.error.to_dict())
            state.status = "failed"
            state.todos = self.todo_manager.todo_list.items
            return state
        guard = self.guard.validate_reflection(reflection, state.selected_skill)
        if guard["status"] != "valid":
            emit_llm_event(
                self.context,
                "LLMGuardRejected",
                {"run_id": state.run_id, "todo_id": todo.id, "errors": guard["errors"]},
            )
            return super().reflect(state, todo, observation)
        state.llm_decisions.append(
            {
                "phase": "reflect",
                "todo_id": todo.id,
                "reason_summary": reflection.get("reason_summary"),
                "decision": reflection.get("decision"),
            }
        )
        for new_todo in reflection.get("new_todos", []):
            title = new_todo.get("title")
            if not title:
                continue
            validation = self._validate_reflection_todo(new_todo)
            if validation["status"] != "valid":
                emit_llm_event(
                    self.context,
                    "LLMReflectionTodoRejected",
                    {
                        "run_id": state.run_id,
                        "todo_id": todo.id,
                        "title": title,
                        "errors": validation["errors"],
                    },
                )
                # The guard has contained this proposal before execution. Keep it in
                # the decision audit, but do not misclassify it as an unresolved run error.
                state.llm_decisions.append(
                    {
                        "phase": "reflect_todo_guard",
                        "todo_id": todo.id,
                        "decision": "reject_invalid_todo",
                        "status": "contained",
                        "proposed_todo": {
                            "title": title,
                            "assigned_tool": new_todo.get("assigned_tool"),
                            "assigned_specialist": new_todo.get("assigned_specialist"),
                        },
                        "errors": validation["errors"],
                    }
                )
                continue
            self.todo_manager.append_item(
                title=title,
                description=new_todo.get("description", title),
                priority=int(new_todo.get("priority", todo.priority + 1)),
                assigned_tool=new_todo.get("assigned_tool"),
                assigned_specialist=new_todo.get("assigned_specialist"),
                dependencies=[todo.id],
                inputs=new_todo.get("inputs", {}),
            )
        state.memory_candidates.extend(reflection.get("memory_candidates", []))
        state.todos = self.todo_manager.todo_list.items
        return super().reflect(state, todo, observation)

    def _validate_reflection_todo(self, todo_spec: dict[str, Any]) -> dict[str, Any]:
        errors: list[str] = []
        tool_name = todo_spec.get("assigned_tool")
        specialist_name = todo_spec.get("assigned_specialist")
        tools = {spec.name for spec in self.agent.registry.list_tools()}
        specialist_specs = {item["name"]: item for item in self.specialist_router.list_specialists()}
        if tool_name and tool_name not in tools:
            errors.append(f"Unknown tool: {tool_name}")
        if specialist_name and specialist_name not in specialist_specs:
            errors.append(f"Unknown specialist: {specialist_name}")

        private_tool_owners: dict[str, list[str]] = {}
        for name, spec in specialist_specs.items():
            for allowed_tool in spec.get("allowed_tools", []):
                private_tool_owners.setdefault(allowed_tool, []).append(name)
        if tool_name in private_tool_owners and not specialist_name:
            errors.append(
                f"Specialist-private tool {tool_name} must be delegated to one of {private_tool_owners[tool_name]}."
            )
        if specialist_name and tool_name and specialist_name in specialist_specs:
            allowed_tools = set(specialist_specs[specialist_name].get("allowed_tools", []))
            if tool_name not in allowed_tools:
                errors.append(
                    f"Tool {tool_name} is outside allowed_tools for specialist {specialist_name}."
                )
        return {"status": "invalid" if errors else "valid", "errors": errors}
