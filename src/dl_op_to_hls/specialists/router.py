from __future__ import annotations

from .base import BaseSpecialist
from .hls4ml_specialist import HLS4MLSpecialist
from .memory_specialist import MemorySpecialist
from .optimization_specialist import OptimizationSpecialist
from .verification_specialist import VerificationSpecialist
from .vivado_specialist import VivadoSpecialist


class SpecialistRouter:
    def __init__(self, specialists: list[BaseSpecialist]):
        self.specialists = specialists

    def route(self, todo) -> BaseSpecialist | None:
        if todo.assigned_specialist:
            for specialist in self.specialists:
                if specialist.name == todo.assigned_specialist:
                    return specialist
        for specialist in self.specialists:
            if specialist.can_handle(todo):
                return specialist
        return None

    def list_specialists(self) -> list[dict]:
        return [
            {
                "name": specialist.name,
                "description": specialist.description,
                "allowed_tools": list(specialist.allowed_tools),
            }
            for specialist in self.specialists
        ]


def build_default_router(runtime_context: dict | None = None) -> SpecialistRouter:
    return SpecialistRouter(
        [
            HLS4MLSpecialist(runtime_context),
            VivadoSpecialist(runtime_context),
            VerificationSpecialist(runtime_context),
            OptimizationSpecialist(runtime_context),
            MemorySpecialist(runtime_context),
        ]
    )
