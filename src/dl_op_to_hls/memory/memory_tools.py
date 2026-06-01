from __future__ import annotations

from pathlib import Path

from ..core.errors import build_error, error_result


def _artifact_path(context, path: str, artifact_type: str) -> None:
    artifact_manager = context.get("artifact_manager")
    if artifact_manager and Path(path).exists():
        artifact_manager.register_file(path, artifact_type)


def write_short_term(arguments, context):
    manager = context["memory_manager"]
    try:
        result = manager.write_short_term(arguments["run_id"], arguments["key"], arguments["value"])
        _artifact_path(context, result["path"], "memory_short_term")
        return result
    except Exception as exc:  # pragma: no cover - defensive
        return error_result(build_error("DatabaseError", str(exc), recoverable=True, source="memory.write_short_term"))


def compress_run_context(arguments, context):
    manager = context["memory_manager"]
    try:
        result = manager.compress_run_context(arguments["run_id"])
        _artifact_path(context, result["path"], "memory_compressed")
        return result
    except Exception as exc:  # pragma: no cover
        return error_result(build_error("RagIndexError", str(exc), recoverable=True, source="memory.compress_run_context"))


def extract_memory_candidates(arguments, context):
    manager = context["memory_manager"]
    try:
        candidates = manager.extract_memory_candidates(arguments["run_id"])
        path = str(manager._memory_dir(arguments["run_id"]) / "memory_candidates.json")
        _artifact_path(context, path, "memory_candidates")
        return {"status": "success", "candidates": candidates, "path": path}
    except Exception as exc:  # pragma: no cover
        return error_result(build_error("DatabaseError", str(exc), recoverable=True, source="memory.extract_memory_candidates"))


def promote_to_long_term(arguments, context):
    manager = context["memory_manager"]
    try:
        result = manager.promote_to_long_term(arguments["run_id"], arguments["candidates"])
        _artifact_path(context, result["path"], "memory_promoted")
        return result
    except Exception as exc:  # pragma: no cover
        return error_result(build_error("DatabaseError", str(exc), recoverable=True, source="memory.promote_to_long_term"))


def retrieve_similar_experiences(arguments, context):
    manager = context["memory_manager"]
    try:
        return {"status": "success", "results": manager.retrieve_similar_experiences(arguments["query"], int(arguments.get("top_k", 5)))}
    except Exception as exc:  # pragma: no cover
        return error_result(build_error("DatabaseError", str(exc), recoverable=True, source="memory.retrieve_similar_experiences"))


def retrieve_failure_cases(arguments, context):
    manager = context["memory_manager"]
    try:
        return {"status": "success", "results": manager.retrieve_failure_cases(arguments["query"], int(arguments.get("top_k", 5)))}
    except Exception as exc:  # pragma: no cover
        return error_result(build_error("DatabaseError", str(exc), recoverable=True, source="memory.retrieve_failure_cases"))


def retrieve_optimization_rules(arguments, context):
    manager = context["memory_manager"]
    try:
        return {"status": "success", "results": manager.retrieve_optimization_rules(arguments["query"], int(arguments.get("top_k", 5)))}
    except Exception as exc:  # pragma: no cover
        return error_result(build_error("DatabaseError", str(exc), recoverable=True, source="memory.retrieve_optimization_rules"))


def save_skill(arguments, context):
    manager = context["memory_manager"]
    try:
        return manager.save_skill(arguments["name"], arguments["steps"], arguments.get("trigger_conditions", {}), arguments.get("success_criteria", {}))
    except Exception as exc:  # pragma: no cover
        return error_result(build_error("DatabaseError", str(exc), recoverable=True, source="memory.save_skill"))

