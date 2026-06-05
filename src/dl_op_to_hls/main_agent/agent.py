from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..adapters.hls4ml_adapter import HLS4MLAdapter
from ..adapters.llm_adapter import LLMAdapter
from ..adapters.vivado_hls_adapter import VivadoHLSAdapter
from ..core.artifacts import ArtifactManager
from ..core.config import AppConfig
from ..core.hooks import ConsoleHook, DbHook, HookManager
from ..core.permissions import PermissionGate
from ..core.tool_registry import ToolRegistry, ToolSpec
from ..core.trace import TraceHook, TraceWriter, stable_hash
from ..db.database import Database
from ..db.repositories import MetadataRepository
from ..memory.memory_manager import MemoryManager
from ..memory.memory_tools import (
    compress_run_context,
    extract_memory_candidates,
    promote_to_long_term,
    retrieve_failure_cases,
    retrieve_optimization_rules,
    retrieve_similar_experiences,
    save_skill,
    write_short_term,
)
from ..mcp_servers.hls4ml_server import register_hls4ml_tools
from ..mcp_servers.vivado_hls_server import register_vivado_tools
from ..llm.candidate_generator import LLMCandidateGenerator as RuntimeCandidateGenerator
from ..llm.client import LLMClient
from ..rag.memory import RagMemory
from ..schemas.task_schema import load_task
from ..schemas.tool_schema import simple_schema
from ..skills.registry import SkillRegistry
from ..skills.extractor import LegacyWorkflowExtractor
from ..specialists.router import build_default_router
from ..tools.fallback_template import generate_operator_hls, generate_testbench
from ..tools.graph_rewrite import rewrite_graph
from ..tools.llm_candidate import LLMCandidateGenerator, generate_candidate
from ..tools.suggest_optimization import suggest_optimization
from ..tools.summarize import write_summary
from ..tools.verify_candidate import verify_candidate


class MainAgent:
    def __init__(self, workspace_root: str | Path | None = None, *, console: bool = True):
        self.config = AppConfig.load(workspace_root)
        self.config.ensure_directories()
        self.permission_gate = PermissionGate(self.config.load_permissions(), self.config.workspace_root)
        schema_path = Path(__file__).resolve().parents[1] / "db" / "schema.sql"
        self.database = Database(self.config.db_path, schema_path)
        self.repository = MetadataRepository(self.database)
        self.rag_memory = RagMemory(self.repository, self.config.workspace_root)
        self.memory_manager = MemoryManager(self.repository, self.rag_memory, self.config.workspace_root)
        self.registry = ToolRegistry()
        self.console = console
        self.llm_client = LLMClient()
        self.hls4ml_adapter = HLS4MLAdapter(
            mock_mode=self.config.mock_hls4ml,
            backend_override=self.config.hls4ml_backend,
        )
        self.vivado_adapter = VivadoHLSAdapter(
            mock_mode=self.config.mock_vivado,
            hls_toolchain=self.config.hls_toolchain,
            vivado_hls_path=self.config.vivado_hls_path,
            vitis_hls_path=self.config.vitis_hls_path,
        )
        self.skill_registry = SkillRegistry(self.config.workspace_root / "skills")
        self.skill_registry.load_all()
        self.legacy_extractor = LegacyWorkflowExtractor(self.config.workspace_root)
        self.llm_generator = LLMCandidateGenerator(
            LLMAdapter(self.llm_client),
            engine=RuntimeCandidateGenerator(),
            llm_client=self.llm_client,
        )
        self._register_tools()
        self._ensure_legacy_workflow_map()

    def _register_tools(self) -> None:
        register_hls4ml_tools(self.registry, self.hls4ml_adapter)
        register_vivado_tools(self.registry, self.vivado_adapter)
        self.registry.register(
            ToolSpec(
                name="task.validate_schema",
                description="Validate and echo the normalized task schema.",
                input_schema=simple_schema({"task": {"type": "object"}}, ["task"]),
                output_schema=simple_schema({"status": {"type": "string"}}),
                permission_level="read",
                tags=["task"],
                handler=lambda arguments, context: {"status": "success", "task": load_task(arguments["task"])},
            )
        )
        self.registry.register(
            ToolSpec(
                name="task.prepare_existing_project",
                description="Prepare an existing HLS project path.",
                input_schema=simple_schema({"task": {"type": "object"}}, ["task"]),
                output_schema=simple_schema({"status": {"type": "string"}}),
                permission_level="read",
                tags=["task"],
                handler=lambda arguments, context: {"status": "success", "task": arguments["task"]},
            )
        )
        self.registry.register(
            ToolSpec(
                name="report.write_unsupported",
                description="Write an actionable unsupported report artifact.",
                input_schema=simple_schema({"reason": {"type": "string"}}, ["reason"]),
                output_schema=simple_schema({"status": {"type": "string"}}),
                permission_level="write",
                tags=["report"],
                handler=self._write_unsupported_report_tool,
            )
        )
        self.registry.register(
            ToolSpec(
                name="graph_rewrite.rewrite",
                description="Suggest simple graph rewrites for unsupported ops.",
                input_schema=simple_schema({"task": {"type": "object"}}, ["task"]),
                output_schema=simple_schema({"status": {"type": "string"}}),
                permission_level="read",
                tags=["rewrite"],
                handler=rewrite_graph,
            )
        )
        self.registry.register(
            ToolSpec(
                name="fallback.generate_operator_hls",
                description="Generate a fallback HLS implementation for a supported operator template.",
                input_schema=simple_schema({"task": {"type": "object"}, "output_dir": {"type": "string"}}, ["task", "output_dir"]),
                output_schema=simple_schema({"status": {"type": "string"}}),
                permission_level="write",
                tags=["fallback"],
                handler=generate_operator_hls,
            )
        )
        self.registry.register(
            ToolSpec(
                name="fallback.generate_testbench",
                description="Generate a simple fallback testbench.",
                input_schema=simple_schema({"task": {"type": "object"}, "output_dir": {"type": "string"}}, ["task", "output_dir"]),
                output_schema=simple_schema({"status": {"type": "string"}}),
                permission_level="write",
                tags=["fallback"],
                handler=generate_testbench,
            )
        )
        self.registry.register(
            ToolSpec(
                name="llm.generate_candidate",
                description="Generate an LLM candidate implementation in mock mode.",
                input_schema=simple_schema({"op_spec": {"type": "object"}, "output_dir": {"type": "string"}}, ["op_spec", "output_dir"]),
                output_schema=simple_schema({"status": {"type": "string"}}),
                permission_level="write",
                tags=["llm"],
                handler=generate_candidate,
            )
        )
        self.registry.register(
            ToolSpec(
                name="verify_candidate.run",
                description="Verify an LLM-generated candidate. Mock verification is only used when mock mode is explicitly active.",
                input_schema=simple_schema({"candidate_dir": {"type": "string"}, "report_dir": {"type": "string"}}, ["candidate_dir", "report_dir"]),
                output_schema=simple_schema({"status": {"type": "string"}}),
                permission_level="write",
                tags=["verify"],
                handler=verify_candidate,
            )
        )
        self.registry.register(
            ToolSpec(
                name="memory.write_short_term",
                description="Write short-term memory for the current run.",
                input_schema=simple_schema({"run_id": {"type": "string"}, "key": {"type": "string"}, "value": {"type": "object"}}, ["run_id", "key", "value"]),
                output_schema=simple_schema({"status": {"type": "string"}}),
                permission_level="write",
                tags=["memory"],
                handler=write_short_term,
            )
        )
        self.registry.register(
            ToolSpec(
                name="memory.compress_run_context",
                description="Compress short-term run context into a durable summary.",
                input_schema=simple_schema({"run_id": {"type": "string"}}, ["run_id"]),
                output_schema=simple_schema({"status": {"type": "string"}}),
                permission_level="write",
                tags=["memory"],
                handler=compress_run_context,
            )
        )
        self.registry.register(
            ToolSpec(
                name="memory.extract_memory_candidates",
                description="Extract promotable memory candidates from a finished run.",
                input_schema=simple_schema({"run_id": {"type": "string"}}, ["run_id"]),
                output_schema=simple_schema({"status": {"type": "string"}}),
                permission_level="write",
                tags=["memory"],
                handler=extract_memory_candidates,
            )
        )
        self.registry.register(
            ToolSpec(
                name="memory.promote_to_long_term",
                description="Promote selected memory candidates into long-term stores.",
                input_schema=simple_schema({"run_id": {"type": "string"}, "candidates": {"type": "array"}}, ["run_id", "candidates"]),
                output_schema=simple_schema({"status": {"type": "string"}}),
                permission_level="write",
                tags=["memory"],
                handler=promote_to_long_term,
            )
        )
        self.registry.register(
            ToolSpec(
                name="memory.retrieve_similar_experiences",
                description="Retrieve similar episodic or implementation memories.",
                input_schema=simple_schema({"query": {"type": "string"}}, ["query"]),
                output_schema=simple_schema({"status": {"type": "string"}}),
                permission_level="read",
                tags=["memory"],
                handler=retrieve_similar_experiences,
            )
        )
        self.registry.register(
            ToolSpec(
                name="memory.retrieve_failure_cases",
                description="Retrieve related historical failure cases.",
                input_schema=simple_schema({"query": {"type": "string"}}, ["query"]),
                output_schema=simple_schema({"status": {"type": "string"}}),
                permission_level="read",
                tags=["memory"],
                handler=retrieve_failure_cases,
            )
        )
        self.registry.register(
            ToolSpec(
                name="memory.retrieve_optimization_rules",
                description="Retrieve learned optimization rules and semantic memories.",
                input_schema=simple_schema({"query": {"type": "string"}}, ["query"]),
                output_schema=simple_schema({"status": {"type": "string"}}),
                permission_level="read",
                tags=["memory"],
                handler=retrieve_optimization_rules,
            )
        )
        self.registry.register(
            ToolSpec(
                name="memory.save_skill",
                description="Store a reusable procedural skill or playbook.",
                input_schema=simple_schema({"name": {"type": "string"}, "steps": {"type": "array"}}, ["name", "steps"]),
                output_schema=simple_schema({"status": {"type": "string"}}),
                permission_level="write",
                tags=["memory", "skill"],
                handler=save_skill,
            )
        )
        self.registry.register(
            ToolSpec(
                name="rag.retrieve_experience",
                description="Retrieve prior RAG chunks related to the current task.",
                input_schema=simple_schema({"query": {"type": "string"}}, ["query"]),
                output_schema=simple_schema({"results": {"type": "array"}}),
                permission_level="read",
                tags=["rag"],
                handler=self._rag_retrieve,
            )
        )
        self.registry.register(
            ToolSpec(
                name="rag.index_artifact",
                description="Index run artifacts into lightweight RAG memory.",
                input_schema=simple_schema({"run_id": {"type": "string"}, "artifact_paths": {"type": "array"}}, ["run_id", "artifact_paths"]),
                output_schema=simple_schema({"status": {"type": "string"}}),
                permission_level="write",
                tags=["rag"],
                handler=self._rag_index,
            )
        )
        self.registry.register(
            ToolSpec(
                name="db.save_experiment",
                description="Save experiment metadata into SQLite.",
                input_schema=simple_schema({"run_id": {"type": "string"}}, ["run_id"]),
                output_schema=simple_schema({"status": {"type": "string"}}),
                permission_level="write",
                tags=["db"],
                handler=lambda arguments, context: self._db_call("save_experiment", arguments, context),
            )
        )
        self.registry.register(
            ToolSpec(
                name="db.save_operator",
                description="Save operator metadata into SQLite.",
                input_schema=simple_schema({"op_type": {"type": "string"}}, ["op_type"]),
                output_schema=simple_schema({"status": {"type": "string"}}),
                permission_level="write",
                tags=["db"],
                handler=lambda arguments, context: self._db_call("save_operator", arguments, context),
            )
        )
        self.registry.register(
            ToolSpec(
                name="db.save_implementation",
                description="Save implementation metadata into SQLite.",
                input_schema=simple_schema({"run_id": {"type": "string"}}, ["run_id"]),
                output_schema=simple_schema({"status": {"type": "string"}}),
                permission_level="write",
                tags=["db"],
                handler=lambda arguments, context: self._db_call("save_implementation", arguments, context),
            )
        )
        self.registry.register(
            ToolSpec(
                name="db.save_synthesis_run",
                description="Save synthesis report metadata into SQLite.",
                input_schema=simple_schema({"run_id": {"type": "string"}}, ["run_id"]),
                output_schema=simple_schema({"status": {"type": "string"}}),
                permission_level="write",
                tags=["db"],
                handler=lambda arguments, context: self._db_call("save_synthesis_run", arguments, context),
            )
        )
        self.registry.register(
            ToolSpec(
                name="db.save_failure",
                description="Save failure metadata into SQLite.",
                input_schema=simple_schema({"run_id": {"type": "string"}}, ["run_id"]),
                output_schema=simple_schema({"status": {"type": "string"}}),
                permission_level="write",
                tags=["db"],
                handler=lambda arguments, context: self._db_call("save_failure", arguments, context),
            )
        )
        self.registry.register(
            ToolSpec(
                name="summary.write_summary",
                description="Write a run summary markdown artifact.",
                input_schema=simple_schema({"state": {"type": "object"}}, ["state"]),
                output_schema=simple_schema({"status": {"type": "string"}}),
                permission_level="write",
                tags=["summary"],
                handler=write_summary,
            )
        )
        self.registry.register(
            ToolSpec(
                name="suggestion.suggest_optimization",
                description="Generate optimization suggestions from the current report and RAG context.",
                input_schema=simple_schema({"state": {"type": "object"}, "report": {"type": "object"}}, ["state", "report"]),
                output_schema=simple_schema({"status": {"type": "string"}}),
                permission_level="write",
                tags=["suggestion"],
                handler=suggest_optimization,
            )
        )
        self._register_tool_aliases()

    def _register_tool_aliases(self) -> None:
        alias_map = {
            "hls4ml.check_hls4ml_support": "hls4ml.check_support",
            "hls4ml.generate_hls4ml_config": "hls4ml.generate_config",
            "hls4ml.convert_with_hls4ml": "hls4ml.convert",
            "hls4ml.run_hls4ml_csim": "hls4ml.run_csim",
            "vivado.create_vivado_project": "vivado.create_project",
            "vivado.parse_csynth_report": "vivado.parse_report",
            "vivado.parse_vivado_log": "vivado.parse_log",
            "verify.generate_testbench": "fallback.generate_testbench",
            "verify.run_csim": "verify_candidate.run",
            "llm.generate_hls_candidate": "llm.generate_candidate",
            "suggestion.generate": "suggestion.suggest_optimization",
        }
        for alias_name, target_name in alias_map.items():
            target = self.registry.get(target_name)
            self.registry.register(
                ToolSpec(
                    name=alias_name,
                    description=f"Alias of {target_name}",
                    input_schema=target.input_schema,
                    output_schema=target.output_schema,
                    permission_level=target.permission_level,
                    handler=target.handler,
                    server=target.server,
                    tags=(target.tags or []) + ["alias"],
                )
            )

    def _rag_retrieve(self, arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        results = self.rag_memory.retrieve(arguments["query"], top_k=int(arguments.get("top_k", 5)))
        hooks = context.get("hooks")
        if hooks:
            hooks.emit("RagRetrieved", {"run_id": context.get("run_id"), "query": arguments["query"], "count": len(results)})
        return {"status": "success", "results": results}

    def _ensure_legacy_workflow_map(self) -> None:
        path = self.config.docs_root / "legacy_workflow_map.md"
        if path.exists():
            return
        self.legacy_extractor.write_legacy_workflow_map(path)

    def _rag_index(self, arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        return self.rag_memory.index_run(arguments["run_id"], arguments["artifact_paths"])

    def _write_unsupported_report_tool(self, arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        artifact_manager = context["artifact_manager"]
        reason = arguments["reason"]
        content = (
            "# Unsupported / Not Recommended Report\n\n"
            "## Reason\n"
            f"{reason}\n\n"
            "## Main Risks\n"
            "- Large CNN resource demand.\n"
            "- Long Vivado HLS synthesis time.\n"
            "- Residual graph complexity and layout conversion risks.\n"
            "- Difficult timing closure in MVP scope.\n\n"
            "## Recommended Alternative\n"
            "1. Use tiny_residual_block demo.\n"
            "2. Use mnist_tiny_cnn demo.\n"
            "3. Use QKeras quantization for resource-oriented experiments.\n"
            "4. Synthesize one subgraph at a time.\n"
            "5. Reduce input size before full-model attempts.\n"
        )
        path = artifact_manager.write_text("unsupported_report.md", content, "unsupported_report")
        return {"status": "success", "path": str(path), "summary": reason}

    def _db_call(self, method_name: str, arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        method = getattr(self.repository, method_name)
        result = method(arguments)
        hooks = context.get("hooks")
        if hooks:
            hooks.emit("DbRecordCreated", {"run_id": context.get("run_id"), "record_type": method_name})
        if isinstance(result, int):
            return {"status": "success", "id": result}
        return result

    def make_run_id(self, task: dict[str, Any]) -> str:
        name = str(task.get("name") or task.get("op_type") or task.get("task_type") or "run")
        safe = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name).strip("_").lower() or "run"
        base = f"{safe}_{stable_hash(task)[:8]}"
        candidate = base
        counter = 1
        while (self.config.runs_root / candidate).exists():
            counter += 1
            candidate = f"{base}_{counter:02d}"
        return candidate

    def create_run_context(self, run_id: str) -> dict[str, Any]:
        run_dir = self.config.runs_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        trace_writer = TraceWriter(run_dir / "trace.jsonl", run_id)
        hooks = HookManager()
        hooks.register("*", TraceHook(trace_writer))
        if self.console:
            hooks.register("RunStarted", ConsoleHook())
            hooks.register("PreToolUse", ConsoleHook())
            hooks.register("PostToolUse", ConsoleHook())
            hooks.register("ToolFailed", ConsoleHook())
            hooks.register("RunFinished", ConsoleHook())

        def tool_call_db_hook(payload: dict[str, Any]) -> None:
            event = payload.get("event")
            if event not in {"PostToolUse", "ToolFailed"}:
                return
            self.repository.save_tool_call(
                {
                    "run_id": run_id,
                    "tool_name": payload.get("tool", "unknown"),
                    "server": None,
                    "status": payload.get("status", "error" if event == "ToolFailed" else "success"),
                    "input_hash": payload.get("args_hash"),
                    "output_hash": payload.get("output_hash"),
                    "duration_ms": payload.get("duration_ms"),
                    "error_type": payload.get("error_type"),
                }
            )

        hooks.register("*", DbHook(tool_call_db_hook))
        artifact_manager = ArtifactManager(run_id=run_id, run_dir=run_dir, permission_gate=self.permission_gate, hooks=hooks)
        return {
            "run_id": run_id,
            "run_dir": run_dir,
            "hooks": hooks,
            "artifact_manager": artifact_manager,
            "permission_gate": self.permission_gate,
            "repository": self.repository,
            "rag_memory": self.rag_memory,
            "memory_manager": self.memory_manager,
            "llm_candidate_generator": self.llm_generator,
            "llm_client": self.llm_client,
            "hls4ml_adapter": self.hls4ml_adapter,
            "vivado_adapter": self.vivado_adapter,
            "runtime_mode": self.config.runtime_mode,
            "llm_fallback_policy": self.config.llm_fallback_policy,
            "optimization_fallback_mode": self.config.optimization_fallback_mode,
            "specialist_llm_decider_enabled": self.config.specialist_llm_decider_enabled,
            "config": self.config,
        }

    def list_runs(self) -> list[dict[str, Any]]:
        return self.repository.list_runs()

    def list_memories(self) -> list[dict[str, Any]]:
        return self.repository.list_memory_items(status=None)

    def get_memory(self, memory_id: int) -> dict[str, Any] | None:
        return self.repository.get_memory_item(memory_id)

    def search_memories(self, query: str) -> list[dict[str, Any]]:
        return (
            self.memory_manager.retrieve_similar_experiences(query, top_k=10)
            + self.memory_manager.retrieve_failure_cases(query, top_k=10)
            + self.memory_manager.retrieve_optimization_rules(query, top_k=10)
        )

    def promote_run_memories(self, run_id_or_path: str) -> dict[str, Any]:
        run_id = Path(run_id_or_path).name if Path(run_id_or_path).exists() else run_id_or_path
        candidates = self.memory_manager.extract_memory_candidates(run_id)
        return self.memory_manager.promote_to_long_term(run_id, candidates)

    def list_skills(self) -> list[dict[str, Any]]:
        self.skill_registry.load_all()
        return [
            {
                "name": skill.name,
                "description": skill.description,
                "intent": skill.intent,
                "trigger": skill.trigger,
                "tags": skill.tags,
            }
            for skill in self.skill_registry.list_skills()
        ]

    def get_skill(self, skill_name: str) -> dict[str, Any] | None:
        self.skill_registry.load_all()
        try:
            skill = self.skill_registry.get(skill_name)
        except KeyError:
            return None
        return {
            "name": skill.name,
            "description": skill.description,
            "intent": skill.intent,
            "trigger": skill.trigger,
            "preconditions": skill.preconditions,
            "recommended_todos": skill.recommended_todos,
            "allowed_tools": skill.allowed_tools,
            "allowed_specialists": skill.allowed_specialists,
            "required_artifacts": skill.required_artifacts,
            "failure_policy": skill.failure_policy,
            "verification_policy": skill.verification_policy,
            "memory_policy": skill.memory_policy,
            "tags": skill.tags,
            "source": skill.source,
        }

    def list_procedural_skills(self) -> list[dict[str, Any]]:
        return self.repository.list_skills()

    def get_procedural_skill(self, skill_id: int) -> dict[str, Any] | None:
        return self.repository.get_skill(skill_id)

    def list_specialists(self) -> list[dict[str, Any]]:
        return build_default_router().list_specialists()

    def get_specialist(self, name: str) -> dict[str, Any] | None:
        normalized = name.lower()
        for item in self.list_specialists():
            if item["name"].lower() == normalized:
                return item
        return None

    def read_specialist_trace(self, run_id_or_path: str, specialist_name: str) -> str:
        normalized_name = specialist_name.replace("HLS4ML", "Hls4ml")
        snake = "".join([f"_{ch.lower()}" if ch.isupper() and idx else ch.lower() for idx, ch in enumerate(normalized_name)])
        candidate = Path(run_id_or_path)
        run_dir = candidate if candidate.exists() else self.config.runs_root / run_id_or_path
        trace_path = run_dir / "specialists" / snake / "trace.jsonl"
        if trace_path.exists():
            return trace_path.read_text(encoding="utf-8")
        summary_path = run_dir / "specialists" / snake / "summary.json"
        return summary_path.read_text(encoding="utf-8")

    def read_run_file(self, run_id_or_path: str, name: str) -> str:
        candidate = Path(run_id_or_path)
        if candidate.exists():
            path = candidate if candidate.is_file() else candidate / name
        else:
            path = self.config.runs_root / run_id_or_path / name
        return path.read_text(encoding="utf-8")

    def read_run_json(self, run_id_or_path: str, name: str) -> dict[str, Any]:
        return json.loads(self.read_run_file(run_id_or_path, name))
