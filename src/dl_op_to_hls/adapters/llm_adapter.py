from __future__ import annotations

from ..core.errors import AgentRuntimeError, build_error
from ..llm.client import LLMClient


class LLMAdapter:
    def __init__(self, llm_client: LLMClient | None = None):
        self.llm_client = llm_client or LLMClient()

    def generate_candidate(self, op_spec: dict, rag_context: list[dict], output_dir: str) -> dict:
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
