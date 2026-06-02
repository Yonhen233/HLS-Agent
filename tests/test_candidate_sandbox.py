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
    assert not (run_dir / "candidate" / "bad.cpp").exists()
