from __future__ import annotations

from .candidate_generator import LLMCandidateGenerator
from .finalizer import LLMFinalizer
from .planner import LLMTodoPlanner
from .react import LLMReActDecider
from .reflector import LLMReflectionEngine
from .task_interpreter import LLMTaskInterpreter


class LLMController:
    def __init__(self):
        self.task_interpreter = LLMTaskInterpreter()
        self.planner = LLMTodoPlanner()
        self.react = LLMReActDecider()
        self.reflector = LLMReflectionEngine()
        self.finalizer = LLMFinalizer()
        self.candidate_generator = LLMCandidateGenerator()
