from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..core.errors import AgentRuntimeError, build_error
from . import prompts
from .guards import LLMGuard
from .schemas import CANDIDATE_GENERATION_SCHEMA
from .trace import emit_llm_event


class LLMCandidateGenerator:
    def __init__(self, guard: LLMGuard | None = None):
        self.guard = guard or LLMGuard()

    def generate(
        self,
        *,
        op_spec: dict[str, Any],
        rag_context: list[dict[str, Any]],
        run_dir: str,
        client,
        permission_gate,
    ) -> dict[str, Any]:
        payload = {
            "op_spec": op_spec,
            "rag_context": rag_context[:5],
            "constraints": [
                "Write files only under candidate/ relative path",
                "requires_verification must be true",
                "Do not mark candidate as verified",
            ],
        }
        result = client.complete_json(
            system_prompt=prompts.CANDIDATE_GENERATOR_SYSTEM_PROMPT,
            user_prompt=json.dumps(payload, ensure_ascii=False),
            schema=CANDIDATE_GENERATION_SCHEMA,
            temperature=0.2,
        )
        guard = self.guard.validate_candidate_files(result, run_dir)
        if guard["status"] != "valid":
            raise AgentRuntimeError(
                build_error(
                    "PermissionDeniedError",
                    "; ".join(guard["errors"]),
                    recoverable=False,
                    source="llm.generate_hls_candidate",
                )
            )
        target_root = Path(run_dir).resolve()
        files = result.get("files", [])
        written: list[str] = []
        for item in files:
            relative_path = item["relative_path"]
            content = item.get("content", "")
            output_path = (target_root / relative_path).resolve()
            decision = permission_gate.check_write_path(str(output_path))
            if decision["decision"] != "allow":
                raise AgentRuntimeError(
                    build_error(
                        "PermissionDeniedError",
                        decision["reason"],
                        recoverable=False,
                        source="llm.generate_hls_candidate",
                    )
                )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(content, encoding="utf-8")
            written.append(str(output_path))
        emit_llm_event(
            client.context,
            "LLMCandidateGenerated",
            {
                "run_id": client.context.get("run_id"),
                "candidate_name": result.get("candidate_name"),
                "file_count": len(written),
            },
        )
        return {
            "status": "candidate_generated",
            "source": "llm_generated",
            "files": written,
            "requires_verification": True,
            "candidate_name": result.get("candidate_name"),
            "assumptions": result.get("assumptions", []),
        }
