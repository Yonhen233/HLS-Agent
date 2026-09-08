"""llm layer implementation for controller.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

from .candidate_generator import LLMCandidateGenerator
from .finalizer import LLMFinalizer
from .planner import LLMTodoPlanner
from .react import LLMReActDecider
from .reflector import LLMReflectionEngine
from .task_interpreter import LLMTaskInterpreter


class LLMController:
    """Coordinate LLMController within the controller boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    def __init__(self):
        """Implement the internal __init__ helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Returns:
            The structured value promised by the function signature.
        """
        self.task_interpreter = LLMTaskInterpreter()
        self.planner = LLMTodoPlanner()
        self.react = LLMReActDecider()
        self.reflector = LLMReflectionEngine()
        self.finalizer = LLMFinalizer()
        self.candidate_generator = LLMCandidateGenerator()
