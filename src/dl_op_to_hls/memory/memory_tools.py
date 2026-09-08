"""memory layer implementation for memory_tools.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

from pathlib import Path

from ..core.errors import build_error, error_result


def _artifact_path(context, path: str, artifact_type: str) -> None:
    """Implement the internal _artifact_path helper.

    Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

    Args:
        context: Value supplied by the caller and validated by the surrounding schema.
        path: Value supplied by the caller and validated by the surrounding schema.
        artifact_type: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    artifact_manager = context.get("artifact_manager")
    if artifact_manager and Path(path).exists():
        artifact_manager.register_file(path, artifact_type)


def _identity(context):
    """Implement the internal _identity helper.

    Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

    Args:
        context: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    return context.get("memory_identity") or None


def write_short_term(arguments, context):
    """Execute write_short_term at the memory_tools boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Args:
        arguments: Value supplied by the caller and validated by the surrounding schema.
        context: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    manager = context["memory_manager"]
    try:
        result = manager.write_short_term(arguments["run_id"], arguments["key"], arguments["value"], _identity(context))
        _artifact_path(context, result["path"], "memory_short_term")
        return result
    except Exception as exc:  # pragma: no cover - defensive
        return error_result(build_error("DatabaseError", str(exc), recoverable=True, source="memory.write_short_term"))


def compress_run_context(arguments, context):
    """Execute compress_run_context at the memory_tools boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Args:
        arguments: Value supplied by the caller and validated by the surrounding schema.
        context: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    manager = context["memory_manager"]
    try:
        result = manager.compress_run_context(arguments["run_id"])
        _artifact_path(context, result["path"], "memory_compressed")
        return result
    except Exception as exc:  # pragma: no cover
        return error_result(build_error("RagIndexError", str(exc), recoverable=True, source="memory.compress_run_context"))


def extract_memory_candidates(arguments, context):
    """Execute extract_memory_candidates at the memory_tools boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Args:
        arguments: Value supplied by the caller and validated by the surrounding schema.
        context: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    manager = context["memory_manager"]
    try:
        candidates = manager.extract_memory_candidates(arguments["run_id"])
        path = str(manager._memory_dir(arguments["run_id"]) / "memory_candidates.json")
        _artifact_path(context, path, "memory_candidates")
        return {"status": "success", "candidates": candidates, "path": path}
    except Exception as exc:  # pragma: no cover
        return error_result(build_error("DatabaseError", str(exc), recoverable=True, source="memory.extract_memory_candidates"))


def promote_to_long_term(arguments, context):
    """Execute promote_to_long_term at the memory_tools boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Args:
        arguments: Value supplied by the caller and validated by the surrounding schema.
        context: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    manager = context["memory_manager"]
    try:
        result = manager.promote_to_long_term(arguments["run_id"], arguments["candidates"], _identity(context))
        _artifact_path(context, result["path"], "memory_promoted")
        return result
    except Exception as exc:  # pragma: no cover
        return error_result(build_error("DatabaseError", str(exc), recoverable=True, source="memory.promote_to_long_term"))


def retrieve_similar_experiences(arguments, context):
    """Execute retrieve_similar_experiences at the memory_tools boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Args:
        arguments: Value supplied by the caller and validated by the surrounding schema.
        context: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    manager = context["memory_manager"]
    try:
        return {"status": "success", "results": manager.retrieve_similar_experiences(arguments["query"], int(arguments.get("top_k", 5)), _identity(context))}
    except Exception as exc:  # pragma: no cover
        return error_result(build_error("DatabaseError", str(exc), recoverable=True, source="memory.retrieve_similar_experiences"))


def retrieve_failure_cases(arguments, context):
    """Execute retrieve_failure_cases at the memory_tools boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Args:
        arguments: Value supplied by the caller and validated by the surrounding schema.
        context: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    manager = context["memory_manager"]
    try:
        return {"status": "success", "results": manager.retrieve_failure_cases(arguments["query"], int(arguments.get("top_k", 5)), _identity(context))}
    except Exception as exc:  # pragma: no cover
        return error_result(build_error("DatabaseError", str(exc), recoverable=True, source="memory.retrieve_failure_cases"))


def retrieve_optimization_rules(arguments, context):
    """Execute retrieve_optimization_rules at the memory_tools boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Args:
        arguments: Value supplied by the caller and validated by the surrounding schema.
        context: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    manager = context["memory_manager"]
    try:
        return {"status": "success", "results": manager.retrieve_optimization_rules(arguments["query"], int(arguments.get("top_k", 5)), _identity(context))}
    except Exception as exc:  # pragma: no cover
        return error_result(build_error("DatabaseError", str(exc), recoverable=True, source="memory.retrieve_optimization_rules"))


def retrieve_conversation(arguments, context):
    """Execute retrieve_conversation at the memory_tools boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Args:
        arguments: Value supplied by the caller and validated by the surrounding schema.
        context: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    manager = context["memory_manager"]
    try:
        identity = dict(_identity(context) or {})
        identity["namespace"] = "user"
        return {
            "status": "success",
            "results": manager.recall_conversation(arguments["query"], identity, int(arguments.get("top_k", 5))),
        }
    except Exception as exc:  # pragma: no cover
        return error_result(build_error("DatabaseError", str(exc), recoverable=True, source="memory.retrieve_conversation"))


def save_skill(arguments, context):
    """Execute save_skill at the memory_tools boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Args:
        arguments: Value supplied by the caller and validated by the surrounding schema.
        context: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    manager = context["memory_manager"]
    try:
        return manager.save_skill(arguments["name"], arguments["steps"], arguments.get("trigger_conditions", {}), arguments.get("success_criteria", {}))
    except Exception as exc:  # pragma: no cover
        return error_result(build_error("DatabaseError", str(exc), recoverable=True, source="memory.save_skill"))
