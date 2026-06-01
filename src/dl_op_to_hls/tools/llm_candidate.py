from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.errors import build_error, error_result
from ..llm.candidate_generator import LLMCandidateGenerator as RuntimeCandidateGenerator
from ..llm.client import LLMClient


class LLMCandidateGenerator:
    def __init__(self, adapter=None, engine: RuntimeCandidateGenerator | None = None, llm_client: LLMClient | None = None):
        self.adapter = adapter
        self.engine = engine
        self.llm_client = llm_client or LLMClient()

    def generate(self, op_spec: dict, rag_context: list[dict], output_dir: str, context: dict[str, Any] | None = None) -> dict:
        if self.engine is not None and context is not None:
            try:
                run_path = Path(output_dir).resolve()
                run_dir = run_path.parent if run_path.name == "candidate" else run_path
                self.llm_client.set_context(context)
                return self.engine.generate(
                    op_spec=op_spec,
                    rag_context=rag_context,
                    run_dir=str(run_dir),
                    client=self.llm_client,
                    permission_gate=context["permission_gate"],
                )
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
    generator = context["llm_candidate_generator"]
    result = generator.generate(arguments["op_spec"], arguments.get("rag_context", []), arguments["output_dir"], context=context)
    artifact_manager = context.get("artifact_manager")
    if artifact_manager and result.get("status") == "candidate_generated":
        for path in result["files"]:
            artifact_manager.register_file(path, "hls_cpp" if path.endswith(".cpp") else "hls_header")
    return result
