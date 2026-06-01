from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


SUPPORTED_ERROR_TYPES = {
    "InvalidTaskError",
    "UnsupportedOperatorError",
    "HLS4MLNotInstalledError",
    "HLS4MLConversionError",
    "VivadoNotFoundError",
    "VivadoSynthesisError",
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
    error_type: str
    message: str
    recoverable: bool
    source: str
    suggested_action: str | None = None
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AgentRuntimeError(RuntimeError):
    def __init__(self, error: AgentError):
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
    return {"status": status, "error": error.to_dict()}

