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


KNOWN_OPERATOR_SEMANTICS = {"Dense", "MatMul", "ReLU", "Add", "ScaleShift", "Conv2D"}


def candidate_generation_contract_errors(op_spec: dict[str, Any]) -> list[str]:
    """Reject candidates that cannot be checked against an independent oracle."""

    op_type = str(op_spec.get("op_type") or "").strip()
    contract = op_spec.get("candidate_contract") if isinstance(op_spec.get("candidate_contract"), dict) else {}
    errors: list[str] = []
    if op_type not in KNOWN_OPERATOR_SEMANTICS:
        if not str(contract.get("operation") or "").strip():
            errors.append(f"Unknown operator {op_type or '<missing>'} requires candidate_contract.operation")
        if not str(contract.get("signature") or "").strip():
            errors.append(f"Unknown operator {op_type or '<missing>'} requires candidate_contract.signature")
        testbench = contract.get("testbench") if isinstance(contract.get("testbench"), dict) else {}
        if not (testbench.get("expected_formula") or testbench.get("reference_output")):
            errors.append(
                f"Unknown operator {op_type or '<missing>'} requires an independent golden oracle in candidate_contract.testbench"
            )
    return errors


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
        contract_errors = self.validate_operator_contract(op_spec)
        if contract_errors:
            raise AgentRuntimeError(
                build_error(
                    "UnsupportedOperatorError",
                    "; ".join(contract_errors),
                    recoverable=False,
                    source="llm.generate_hls_candidate",
                    suggested_action="Use a static NHWC group=1 Conv2D contract or split the operator before generation.",
                    details={"contract_errors": contract_errors},
                )
            )
        hls_contract = self._hls_contract(op_spec)
        reuse_context = self._select_reuse_context(op_spec, rag_context)
        payload = {
            "op_spec": op_spec,
            "verified_reuse_context": reuse_context,
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
            "reuse_context": {
                "candidate_count": len(rag_context),
                "accepted_count": len(reuse_context),
                "policy": "same-operator verified evidence only",
                "sources": [item.get("source_id") or item.get("source_run_id") for item in reuse_context],
            },
        }

    @staticmethod
    def _hls_contract(op_spec: dict[str, Any]) -> dict[str, Any]:
        """Extract only static guard data; code generation still needs verification."""

        type_text = " ".join(
            str(op_spec.get(key, ""))
            for key in ("dtype", "precision", "input_dtype", "output_dtype")
        )
        match = re.search(r"(?:ap_)?fixed\s*<\s*(\d+)", type_text, flags=re.IGNORECASE)
        contract = {
            "data_bitwidth": int(match.group(1)) if match else None,
            "max_complete_partition_elements": int(op_spec.get("max_complete_partition_elements", 256)),
            "top_function": op_spec.get("top_function") or op_spec.get("name"),
            "operator": op_spec.get("op_type"),
            "input_shape": op_spec.get("input_shape"),
            "output_shape": op_spec.get("output_shape"),
        }
        if str(op_spec.get("op_type")) == "Conv2D":
            params = op_spec.get("operator_params") or op_spec.get("params") or {}
            contract["conv2d"] = {
                "layout": params.get("layout", "NHWC"),
                "kernel_size": params.get("kernel_size") or params.get("kernel"),
                "stride": params.get("stride", [1, 1]),
                "padding": params.get("padding", "valid"),
                "groups": params.get("groups", 1),
                "output_channels": params.get("output_channels") or params.get("out_channels"),
                "weights": params.get("weights"),
                "bias": params.get("bias"),
            }
        return contract

    @staticmethod
    def validate_operator_contract(op_spec: dict[str, Any]) -> list[str]:
        errors = candidate_generation_contract_errors(op_spec)
        if str(op_spec.get("op_type")) != "Conv2D":
            return errors
        params = op_spec.get("operator_params") or op_spec.get("params") or {}
        shape = op_spec.get("input_shape")
        if not isinstance(shape, list) or len(shape) != 3 or not all(isinstance(value, int) and value > 0 for value in shape):
            errors.append("Conv2D input_shape must be static [height, width, channels]")
        if str(params.get("layout", "NHWC")).upper() != "NHWC":
            errors.append("Conv2D LLM candidate currently requires NHWC layout")
        if int(params.get("groups", 1)) != 1:
            errors.append("Grouped/depthwise Conv2D is not supported")
        kernel = params.get("kernel_size") or params.get("kernel")
        if not isinstance(kernel, list) or len(kernel) != 2 or not all(isinstance(value, int) and value > 0 for value in kernel):
            errors.append("Conv2D kernel_size must contain two static positive integers")
        stride = params.get("stride", [1, 1])
        if not isinstance(stride, list) or len(stride) != 2 or not all(isinstance(value, int) and value > 0 for value in stride):
            errors.append("Conv2D stride must contain two static positive integers")
        if str(params.get("padding", "valid")).lower() not in {"valid", "same"}:
            errors.append("Conv2D padding must be valid or same")
        if not isinstance(params.get("weights"), list) or not isinstance(params.get("bias"), list):
            errors.append("Conv2D weights and bias must be explicit static arrays")
        return errors

    @staticmethod
    def _select_reuse_context(op_spec: dict[str, Any], rag_context: list[dict[str, Any]]) -> list[dict[str, Any]]:
        operator = str(op_spec.get("op_type") or "").lower()
        accepted: list[dict[str, Any]] = []
        seen_sources: set[str] = set()
        for item in rag_context:
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            kind = str(item.get("kind") or item.get("memory_type") or metadata.get("memory_type") or "").lower()
            verification = item.get("verification") if isinstance(item.get("verification"), dict) else metadata.get("verification")
            verified = kind in {"verified_implementation", "parameter_experience"} or (
                isinstance(verification, dict) and verification.get("passed") is True
            )
            text = json.dumps(item, ensure_ascii=False, default=str).lower()
            if verified and operator and operator in text:
                source_key = str(
                    item.get("source_run_id")
                    or metadata.get("source_run_id")
                    or item.get("source_id")
                    or metadata.get("source_id")
                    or text
                )
                if source_key in seen_sources:
                    continue
                seen_sources.add(source_key)
                accepted.append(item)
        accepted.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
        return accepted[:3]

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
