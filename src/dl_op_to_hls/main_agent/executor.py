from __future__ import annotations

from pathlib import Path

from ..core.context_modes import ContextModeConfig


class AgentExecutor:
    def __init__(self, registry, context):
        self.registry = registry
        self.context = context
        self.context_modes = ContextModeConfig.from_env()

    def call(self, tool_name: str, arguments: dict) -> dict:
        return self.registry.call(tool_name, arguments, self.context)

    def call_and_record(self, state, tool_name: str, arguments: dict) -> dict:
        result = self.call(tool_name, arguments)
        state.tool_results.append({"tool": tool_name, "result": result})
        return result

    def merge_specialist_result(self, state, todo, result):
        result_dict = result.to_dict()
        compressed = {
            "specialist_name": result.specialist_name,
            "todo_id": result.todo_id,
            "status": result.status,
            "summary": result.summary,
            "observations": result.observations,
            "metrics": result.metrics,
            "artifacts": result.artifacts,
            "errors": result.errors,
            "warnings": result.warnings,
            "suggested_todos": result.suggested_todos,
            "memory_candidates": result.memory_candidates,
            "verification": result.verification,
            "context_usage": result.context_usage,
        }
        delivered = compressed
        if self.context_modes.result_context_mode == "raw":
            delivered = {
                **result_dict,
                "raw_text_artifacts": self._read_text_artifacts(result.artifacts),
                "result_context_mode": "raw",
            }
        else:
            delivered = {**compressed, "result_context_mode": "compressed"}
        todo.specialist_result = delivered
        todo.outputs = {
            "status": result.status,
            "summary": result.summary,
            "specialist": result.specialist_name,
            "context_usage": result.context_usage,
            "verification": result.verification,
        }
        state.tool_results.append({"specialist": result.specialist_name, "result": delivered})
        state.errors.extend(result.errors)
        state.memory_candidates.extend(result.memory_candidates)
        if result.verification:
            state.verification = result.verification
        for artifact in result.artifacts:
            artifact_type = artifact.get("type")
            artifact_path = artifact.get("path")
            if artifact_type and artifact_path:
                state.artifacts[artifact_type] = artifact_path
                manager = self.context.get("artifact_manager")
                if manager and Path(artifact_path).is_file():
                    manager.register_file(artifact_path, artifact_type)
        if result.metrics:
            if result.metrics.get("status") == "success" and ("latency" in result.metrics or "resources" in result.metrics):
                state.report = result.metrics
            if "suggestions" in result.metrics:
                state.suggestions = result.metrics.get("suggestions", [])
            if "memory_candidates" in result.metrics:
                state.memory_candidates = result.metrics.get("memory_candidates", state.memory_candidates)
            if "promoted_memories" in result.metrics:
                state.promoted_memories = result.metrics.get("promoted_memories", state.promoted_memories)
        return state

    @staticmethod
    def _read_text_artifacts(artifacts: list[dict]) -> list[dict]:
        payloads: list[dict] = []
        text_suffixes = {".txt", ".log", ".rpt", ".json", ".jsonl", ".md", ".cpp", ".cc", ".c", ".h", ".hpp", ".tcl", ".yml", ".yaml"}
        seen: set[str] = set()
        for artifact in artifacts:
            raw_path = artifact.get("path")
            if not raw_path or raw_path in seen:
                continue
            seen.add(raw_path)
            path = Path(raw_path)
            if not path.is_file() or path.suffix.lower() not in text_suffixes:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            payloads.append(
                {
                    "type": artifact.get("type"),
                    "path": str(path),
                    "text": text,
                    "bytes": len(text.encode("utf-8")),
                }
            )
        return payloads
