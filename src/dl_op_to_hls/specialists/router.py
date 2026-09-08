"""specialists layer implementation for router.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

from .base import BaseSpecialist
from .codegen_specialist import CodegenSpecialist
from .hls4ml_specialist import HLS4MLSpecialist
from .memory_specialist import MemorySpecialist
from .optimization_specialist import OptimizationSpecialist
from .verification_specialist import VerificationSpecialist
from .vivado_specialist import VivadoSpecialist


class SpecialistRouter:
    """Coordinate SpecialistRouter within the router boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    def __init__(self, specialists: list[BaseSpecialist]):
        """Implement the internal __init__ helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            specialists: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        self.specialists = specialists

    def route(self, todo) -> BaseSpecialist | None:
        """Execute route at the router boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            todo: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        if todo.assigned_specialist:
            for specialist in self.specialists:
                if specialist.name == todo.assigned_specialist:
                    return specialist
        for specialist in self.specialists:
            if specialist.can_handle(todo):
                return specialist
        return None

    def list_specialists(self) -> list[dict]:
        """Execute list_specialists at the router boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Returns:
            The structured value promised by the function signature.
        """
        return [
            {
                "name": specialist.name,
                "description": specialist.description,
                "allowed_tools": list(specialist.allowed_tools),
            }
            for specialist in self.specialists
        ]


def build_default_router(runtime_context: dict | None = None) -> SpecialistRouter:
    """Execute build_default_router at the router boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Args:
        runtime_context: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    return SpecialistRouter(
        [
            CodegenSpecialist(runtime_context),
            HLS4MLSpecialist(runtime_context),
            VivadoSpecialist(runtime_context),
            VerificationSpecialist(runtime_context),
            OptimizationSpecialist(runtime_context),
            MemorySpecialist(runtime_context),
        ]
    )
