"""adapters layer implementation for llm_adapter.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

from ..core.errors import AgentRuntimeError, build_error
from ..llm.client import LLMClient


class LLMAdapter:
    """Coordinate LLMAdapter within the llm_adapter boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    def __init__(self, llm_client: LLMClient | None = None):
        """Implement the internal __init__ helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            llm_client: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        self.llm_client = llm_client or LLMClient()

    def generate_candidate(self, op_spec: dict, rag_context: list[dict], output_dir: str) -> dict:
        """Execute generate_candidate at the llm_adapter boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            op_spec: Value supplied by the caller and validated by the surrounding schema.
            rag_context: Value supplied by the caller and validated by the surrounding schema.
            output_dir: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        if not self.llm_client.is_enabled():
            raise AgentRuntimeError(
                build_error(
                    "LLMGenerationError",
                    "LLM is not enabled or API key is missing.",
                    recoverable=True,
                    source="llm_adapter.generate_candidate",
                    suggested_action="Set DL_OP_TO_HLS_LLM_ENABLED=1 and provide DL_OP_TO_HLS_LLM_API_KEY.",
                )
            )
        raise AgentRuntimeError(
            build_error(
                "LLMGenerationError",
                "Use llm.candidate_generator.LLMCandidateGenerator for candidate generation.",
                recoverable=True,
                source="llm_adapter.generate_candidate",
            )
        )
