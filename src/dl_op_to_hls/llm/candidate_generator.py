from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from ..core.errors import AgentRuntimeError, build_error
from ..core.candidate_sandbox import CandidateSandbox
from . import prompts
from .guards import LLMGuard
from .schemas import CANDIDATE_GENERATION_SCHEMA
from .trace import emit_llm_event


class LLMCandidateGenerator:
    def __init__(self, guard: LLMGuard | None = None):
        self.guard = guard or LLMGuard()
        self.sandbox = CandidateSandbox()

    def generate(
        self,
        *,
        op_spec: dict[str, Any],
        rag_context: list[dict[str, Any]],
        run_dir: str,
        client,
        permission_gate,
    ) -> dict[str, Any]:
        hls_contract = self._hls_contract(op_spec)
        payload = {
            "op_spec": op_spec,
            "rag_context": rag_context[:5],
            "hls_contract": hls_contract,
            "constraints": [
                "Write files only under candidate/ relative path",
                "requires_verification must be true",
                "Do not mark candidate as verified",
            ],
        }
        result = client.complete_json(
            system_prompt=prompts.resolve_prompt(client.context, "candidate_generator"),
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
        sandbox_result = self.sandbox.scan_candidate_payload(result, contract=hls_contract)
        if sandbox_result["status"] != "valid":
            debug_artifact = self._write_rejected_candidate_artifact(result, sandbox_result, client)
            raise AgentRuntimeError(
                build_error(
                    "PermissionDeniedError",
                    "CandidateSandbox rejected generated HLS code.",
                    recoverable=False,
                    source="llm.generate_hls_candidate",
                    details={
                        "violations": sandbox_result["violations"],
                        "llm_debug_artifact": debug_artifact,
                    },
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
            "sandbox_scan": sandbox_result,
        }

    @staticmethod
    def _hls_contract(op_spec: dict[str, Any]) -> dict[str, Any]:
        """Extract only static guard data; code generation still needs verification."""

        type_text = " ".join(
            str(op_spec.get(key, ""))
            for key in ("dtype", "precision", "input_dtype", "output_dtype")
        )
        match = re.search(r"(?:ap_)?fixed\s*<\s*(\d+)", type_text, flags=re.IGNORECASE)
        return {
            "data_bitwidth": int(match.group(1)) if match else None,
            "max_complete_partition_elements": int(op_spec.get("max_complete_partition_elements", 256)),
        }

    def _write_rejected_candidate_artifact(self, candidate: dict[str, Any], sandbox_result: dict[str, Any], client) -> str | None:
        artifact_manager = getattr(client, "context", {}).get("artifact_manager")
        if artifact_manager is None:
            return None
        files = []
        for item in candidate.get("files", []):
            content = str(item.get("content", ""))
            files.append(
                {
                    "relative_path": item.get("relative_path"),
                    "role": item.get("role"),
                    "content": content,
                }
            )
        payload = {
            "candidate_name": candidate.get("candidate_name"),
            "requires_verification": candidate.get("requires_verification"),
            "assumptions": candidate.get("assumptions", []),
            "sandbox_scan": sandbox_result,
            "files": files,
        }
        try:
            return str(
                artifact_manager.write_json(
                    f"llm_debug/rejected_candidate_{int(time.time() * 1000)}.json",
                    payload,
                    "llm_debug",
                )
            )
        except Exception:
            return None
