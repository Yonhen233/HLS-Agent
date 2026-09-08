"""tools layer implementation for llm_candidate.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.errors import AgentRuntimeError, build_error, error_result
from ..llm.candidate_generator import LLMCandidateGenerator as RuntimeCandidateGenerator
from ..llm.client import LLMClient


class LLMCandidateGenerator:
    """Coordinate LLMCandidateGenerator within the llm_candidate boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    def __init__(self, adapter=None, engine: RuntimeCandidateGenerator | None = None, llm_client: LLMClient | None = None):
        """Implement the internal __init__ helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            adapter: Value supplied by the caller and validated by the surrounding schema.
            engine: Value supplied by the caller and validated by the surrounding schema.
            llm_client: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        self.adapter = adapter
        self.engine = engine
        self.llm_client = llm_client or LLMClient()

    def generate(self, op_spec: dict, rag_context: list[dict], output_dir: str, context: dict[str, Any] | None = None) -> dict:
        """Execute generate at the llm_candidate boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            op_spec: Value supplied by the caller and validated by the surrounding schema.
            rag_context: Value supplied by the caller and validated by the surrounding schema.
            output_dir: Value supplied by the caller and validated by the surrounding schema.
            context: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        if self.engine is not None and context is not None:
            try:
                run_path = Path(output_dir).resolve()
                run_dir = run_path.parent if run_path.name == "candidate" else run_path
                active_client = context.get("llm_client") or self.llm_client
                active_client.set_context(context)
                return self.engine.generate(
                    op_spec=op_spec,
                    rag_context=rag_context,
                    run_dir=str(run_dir),
                    client=active_client,
                    permission_gate=context["permission_gate"],
                )
            except AgentRuntimeError as exc:
                return error_result(exc.error, status="failed")
            except Exception as exc:
                return error_result(
                    build_error(
                        "LLMGenerationError",
                        str(exc),
                        recoverable=True,
                        source="llm_candidate.generate",
                    )
                )
        try:
            payload = self.adapter.generate_candidate(op_spec, rag_context, output_dir)
        except Exception as exc:
            return error_result(
                build_error(
                    "LLMGenerationError",
                    str(exc),
                    recoverable=True,
                    source="llm_candidate.generate",
                )
            )
        return {
            "status": "candidate_generated",
            "source": "llm_generated",
            "files": payload["files"],
            "requires_verification": True,
        }


def generate_candidate(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Execute generate_candidate at the llm_candidate boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Args:
        arguments: Value supplied by the caller and validated by the surrounding schema.
        context: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    generator = context["llm_candidate_generator"]
    result = generator.generate(arguments["op_spec"], arguments.get("rag_context", []), arguments["output_dir"], context=context)
    artifact_manager = context.get("artifact_manager")
    if artifact_manager and result.get("status") == "candidate_generated":
        for path in result["files"]:
            artifact_manager.register_file(path, "hls_cpp" if path.endswith(".cpp") else "hls_header")
    return result
