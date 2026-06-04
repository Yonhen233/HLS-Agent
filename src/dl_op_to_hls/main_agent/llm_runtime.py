from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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
    def __init__(self, agent, llm_client: LLMClient | None = None):
        super().__init__(agent)
        self.llm_client = llm_client or LLMClient()
        self.controller = LLMController()
        self.guard = LLMGuard()
        self.skill_registry = SkillRegistry(agent.config.workspace_root / "skills")
        self.skill_policy = SkillPolicy()
        self.skill_prompt_builder = SkillPromptContextBuilder()
        self.skill_expander = SkillExpander()
        self.selected_skill = None

    def run(self, input_data: str | dict[str, Any]) -> AgentState:
        state = self.initialize(input_data)
        self.llm_client.set_context(self.context)
        hooks = self.context["hooks"]
        hooks.emit("RunStarted", {"run_id": state.run_id, "message": f"Starting LLM-first run for {state.task.get('name')}"})
        try:
            if not self.llm_client.is_enabled():
                raise AgentRuntimeError(
                    build_error(
                        "LLMGenerationError",
                        "LLM is not enabled or API key is missing.",
                        recoverable=True,
                        source="llm_runtime.run",
                        suggested_action="Set DL_OP_TO_HLS_LLM_ENABLED=1 and DL_OP_TO_HLS_LLM_API_KEY.",
                    )
                )
            state = self.retrieve_initial_memory(state)
            state = self.build_skill_context(state)
            state = self.plan_todos(state)
            state = self.execute_todos(state)
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
            reflect_on_errors(state)
            update_status_from_todos(state)
            trace_path = self.context["run_dir"] / "trace.jsonl"
            if trace_path.exists():
                self.context["artifact_manager"].register_file(trace_path, "trace")
                state.artifacts["trace"] = str(trace_path)
            state_path = self.context["artifact_manager"].write_json("state.json", state.to_dict(), "state")
            state.artifacts["state"] = str(state_path)
            Path(state_path).write_text(json.dumps(state.to_dict(), indent=2, ensure_ascii=False, default=str), encoding="utf-8")
            hooks.emit("RunFinished", {"run_id": state.run_id, "status": state.status})
        return state

    def initialize(self, input_data: str | dict[str, Any]) -> AgentState:
        task = self._interpret_or_load_task(input_data)
        run_id = self.agent.make_run_id(task)
        self.context = self.agent.create_run_context(run_id)
        self.llm_client.set_context(self.context)
        self.executor = self.executor or self._build_executor()
        self.todo_manager = self.todo_manager or self._build_todo_manager()
        self.compressor = self.compressor or self._build_compressor(run_id)
        self.specialist_router = self.specialist_router or self._build_router()

        state = AgentState(run_id=run_id, task=task, objective=task.get("objective"))
        state.artifacts["run_dir"] = str(self.context["run_dir"])
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
            guard = self.guard.validate_todo_plan(plan, self.agent.registry, self.specialist_router, self.skill_registry)
            selected_skill = None
            if plan.get("selected_skill"):
                try:
                    selected_skill = self.skill_registry.get(plan["selected_skill"])
                except KeyError:
                    pass
            skill_policy_result = self.skill_policy.validate_llm_plan_against_skill(plan, selected_skill)
            errors = guard["errors"] + skill_policy_result["errors"]
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
                state.llm_decisions.append(
                    {
                        "phase": "plan",
                        "reason_summary": plan.get("reason_summary"),
                        "selected_skill": state.selected_skill,
                    }
                )
                self.selected_skill = selected_skill
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
            item.inputs = spec.get("inputs", item.inputs)
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
        state.artifacts["todos"] = str(self.context["run_dir"] / "todos.json")

    def _normalize_llm_plan_dependencies(self, todo_list, task: dict[str, Any]) -> None:
        """Repair missing edges in LLM plans without changing the selected skill semantics."""

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

        validate = first_by_tool("task.validate_schema")
        inspect = first_by_tool("hls4ml.inspect_model")
        support = first_by_tool("hls4ml.check_support", "hls4ml.check_hls4ml_support")
        graph = first_by_tool("graph_rewrite.rewrite")
        fallback = first_by_tool("fallback.generate_operator_hls")
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
        require(config, support)
        require(convert, config)
        require(prepare_existing, validate)

        implementation_source = convert or fallback or prepare_existing
        require(vivado_create, implementation_source)
        require(vivado_synth, vivado_create or implementation_source)
        require(parse, vivado_synth)
        require(unsupported, graph or support)

        terminal = unsupported or parse or vivado_synth or implementation_source
        require(suggest, terminal)
        require(summary, suggest or terminal)
        require(memory, summary or suggest or terminal)

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
                state.errors.append(
                    build_error(
                        "PermissionDeniedError",
                        "LLM reflection proposed an invalid todo: " + "; ".join(validation["errors"]),
                        recoverable=True,
                        source="llm_runtime.reflect",
                        suggested_action="Keep planner/reflection prompts aligned with ToolRegistry and Specialist allowlists.",
                        details={
                            "title": title,
                            "assigned_tool": new_todo.get("assigned_tool"),
                            "assigned_specialist": new_todo.get("assigned_specialist"),
                        },
                    ).to_dict()
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
