"""core layer implementation for errors.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


SUPPORTED_ERROR_TYPES = {
    "InvalidTaskError",
    "UnsupportedOperatorError",
    "HLS4MLNotInstalledError",
    "HLS4MLConversionError",
    "VivadoNotFoundError",
    "VivadoSynthesisError",
    "HostResourceExhaustedError",
    "ReportMissingError",
    "ReportParseError",
    "PermissionDeniedError",
    "TemplateRenderError",
    "RagIndexError",
    "DatabaseError",
    "LLMGenerationError",
    "VerificationFailedError",
}


@dataclass
class AgentError:
    """Coordinate AgentError within the errors boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    error_type: str
    message: str
    recoverable: bool
    source: str
    suggested_action: str | None = None
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Execute to_dict at the errors boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Returns:
            The structured value promised by the function signature.
        """
        return asdict(self)


class AgentRuntimeError(RuntimeError):
    """Coordinate AgentRuntimeError within the errors boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    def __init__(self, error: AgentError):
        """Implement the internal __init__ helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            error: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        super().__init__(error.message)
        self.error = error


def build_error(
    error_type: str,
    message: str,
    *,
    recoverable: bool,
    source: str,
    suggested_action: str | None = None,
    details: dict[str, Any] | None = None,
) -> AgentError:
    """Execute build_error at the errors boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Args:
        error_type: Value supplied by the caller and validated by the surrounding schema.
        message: Value supplied by the caller and validated by the surrounding schema.
        recoverable: Value supplied by the caller and validated by the surrounding schema.
        source: Value supplied by the caller and validated by the surrounding schema.
        suggested_action: Value supplied by the caller and validated by the surrounding schema.
        details: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    normalized_type = error_type if error_type in SUPPORTED_ERROR_TYPES else error_type
    return AgentError(
        error_type=normalized_type,
        message=message,
        recoverable=recoverable,
        source=source,
        suggested_action=suggested_action,
        details=details or {},
    )


def error_result(error: AgentError, status: str = "error") -> dict[str, Any]:
    """Execute error_result at the errors boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Args:
        error: Value supplied by the caller and validated by the surrounding schema.
        status: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    return {"status": status, "error": error.to_dict()}


def unresolved_errors(errors: list[Any] | None) -> list[Any]:
    """Execute unresolved_errors at the errors boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Args:
        errors: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    return [item for item in (errors or []) if not (isinstance(item, dict) and item.get("resolved") is True)]


def mark_errors_resolved(
    errors: list[Any],
    *,
    error_types: set[str],
    resolved_by_todo_id: str,
    resolution: str,
) -> list[dict[str, Any]]:
    """Execute mark_errors_resolved at the errors boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Args:
        errors: Value supplied by the caller and validated by the surrounding schema.
        error_types: Value supplied by the caller and validated by the surrounding schema.
        resolved_by_todo_id: Value supplied by the caller and validated by the surrounding schema.
        resolution: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    resolved: list[dict[str, Any]] = []
    resolved_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    for item in errors:
        if not isinstance(item, dict) or item.get("resolved") is True:
            continue
        if str(item.get("error_type") or "") not in error_types:
            continue
        if item.get("recoverable") is False:
            continue
        item["resolved"] = True
        item["resolved_at"] = resolved_at
        item["resolved_by_todo_id"] = resolved_by_todo_id
        item["resolution"] = resolution
        resolved.append(item)
    return resolved
