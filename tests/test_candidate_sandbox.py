import pytest

from dl_op_to_hls.core.candidate_sandbox import CandidateSandbox
from dl_op_to_hls.core.config import DEFAULT_PERMISSIONS
from dl_op_to_hls.core.errors import AgentRuntimeError
from dl_op_to_hls.core.permissions import PermissionGate
from dl_op_to_hls.llm.candidate_generator import LLMCandidateGenerator
from dl_op_to_hls.llm.client import FakeLLMClient


def test_candidate_sandbox_rejects_system_call():
    payload = {
        "files": [
            {
                "relative_path": "candidate/bad.cpp",
                "content": '#include <cstdlib>\nvoid bad() { system("echo bad"); }\n',
            }
        ]
    }
    result = CandidateSandbox().scan_candidate_payload(payload)
    assert result["status"] == "invalid"
    assert {item["rule"] for item in result["violations"]} >= {"system_call", "file_io_include"}


def test_llm_candidate_generator_applies_candidate_sandbox(tmp_path):
    run_dir = tmp_path / "runs" / "r1"
    run_dir.mkdir(parents=True)
    client = FakeLLMClient(
        json_responses=[
            {
                "candidate_name": "bad",
                "files": [
                    {
                        "relative_path": "candidate/bad.cpp",
                        "content": 'void bad() { system("echo bad"); }\n',
                    }
                ],
                "assumptions": [],
                "requires_verification": True,
            }
        ]
    )
    gate = PermissionGate(DEFAULT_PERMISSIONS, tmp_path)

    with pytest.raises(AgentRuntimeError) as exc:
        LLMCandidateGenerator().generate(
            op_spec={"op_type": "Custom"},
            rag_context=[],
            run_dir=str(run_dir),
            client=client,
            permission_gate=gate,
        )

    assert exc.value.error.error_type == "PermissionDeniedError"
    assert "CandidateSandbox" in exc.value.error.message
    assert exc.value.error.details["violations"]
    assert not (run_dir / "candidate" / "bad.cpp").exists()


def test_candidate_sandbox_rejects_m_axi_for_non_byte_aligned_fixed_point():
    payload = {
        "files": [
            {
                "relative_path": "candidate/top.cpp",
                "content": "#pragma HLS INTERFACE m_axi port=input\nvoid top() {}\n",
            }
        ]
    }

    result = CandidateSandbox().scan_candidate_payload(payload, contract={"data_bitwidth": 10})

    assert result["status"] == "invalid"
    assert result["violations"][0]["rule"] == "non_byte_aligned_m_axi"


def test_candidate_sandbox_rejects_large_complete_mutable_activation_partition():
    payload = {
        "files": [
            {
                "relative_path": "candidate/top.cpp",
                "content": (
                    "void top() {\n"
                    "  data_t feature_map[16][32][32];\n"
                    "  #pragma HLS ARRAY_PARTITION variable=feature_map complete dim=1\n"
                    "}\n"
                ),
            }
        ]
    }

    result = CandidateSandbox().scan_candidate_payload(payload)

    assert result["status"] == "invalid"
    assert result["violations"][0]["rule"] == "large_mutable_complete_partition"
