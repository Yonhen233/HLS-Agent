from __future__ import annotations

from pathlib import Path


class AgentExecutor:
    def __init__(self, registry, context):
        self.registry = registry
        self.context = context

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
            "context_usage": result.context_usage,
        }
        todo.specialist_result = compressed
        todo.outputs = {
            "status": result.status,
            "summary": result.summary,
            "specialist": result.specialist_name,
            "context_usage": result.context_usage,
        }
        state.tool_results.append({"specialist": result.specialist_name, "result": compressed})
        state.errors.extend(result.errors)
        state.memory_candidates.extend(result.memory_candidates)
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
