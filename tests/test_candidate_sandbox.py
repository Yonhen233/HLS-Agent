"""Test contracts and regression checks for test_candidate_sandbox.py.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

import pytest

from dl_op_to_hls.core.candidate_sandbox import CandidateSandbox
from dl_op_to_hls.core.config import DEFAULT_PERMISSIONS
from dl_op_to_hls.core.errors import AgentRuntimeError
from dl_op_to_hls.core.permissions import PermissionGate
from dl_op_to_hls.llm.candidate_generator import LLMCandidateGenerator
from dl_op_to_hls.llm.client import FakeLLMClient
from dl_op_to_hls.tools.llm_candidate import LLMCandidateGenerator as ToolCandidateGenerator


def test_candidate_sandbox_rejects_system_call():
    """Verify the test_candidate_sandbox_rejects_system_call contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
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
    """Verify the test_llm_candidate_generator_applies_candidate_sandbox contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
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
            # Use a known operator so this test reaches the sandbox layer;
            # unknown semantics are rejected earlier by the capability gate.
            op_spec={"op_type": "ReLU", "name": "relu_sandbox_probe", "input_shape": [1], "output_shape": [1]},
            rag_context=[],
            run_dir=str(run_dir),
            client=client,
            permission_gate=gate,
        )

    assert exc.value.error.error_type == "PermissionDeniedError"
    assert "CandidateSandbox" in exc.value.error.message
    assert exc.value.error.details["violations"]
    assert not (run_dir / "candidate" / "bad.cpp").exists()


def test_candidate_tool_uses_run_scoped_llm_client(tmp_path):
    """Verify the test_candidate_tool_uses_run_scoped_llm_client contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    class RecordingClient:
        """Coordinate RecordingClient within the test_candidate_sandbox boundary.

        The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
        """
        def __init__(self):
            """Verify the __init__ contract.

            The test should fail on a real contract regression rather than hide an unsupported path.

            Returns:
                The structured value promised by the function signature.
            """
            self.context = None

        def set_context(self, context):
            """Verify the set_context contract.

            The test should fail on a real contract regression rather than hide an unsupported path.

            Args:
                context: Value supplied by the caller and validated by the surrounding schema.

            Returns:
                The structured value promised by the function signature.
            """
            self.context = context

    class RecordingEngine:
        """Coordinate RecordingEngine within the test_candidate_sandbox boundary.

        The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
        """
        def __init__(self):
            """Verify the __init__ contract.

            The test should fail on a real contract regression rather than hide an unsupported path.

            Returns:
                The structured value promised by the function signature.
            """
            self.client = None

        def generate(self, **kwargs):
            """Verify the generate contract.

            The test should fail on a real contract regression rather than hide an unsupported path.

            Returns:
                The structured value promised by the function signature.
            """
            self.client = kwargs["client"]
            return {"status": "candidate_generated", "files": [], "requires_verification": True}

    owned_client = RecordingClient()
    run_client = RecordingClient()
    engine = RecordingEngine()
    generator = ToolCandidateGenerator(engine=engine, llm_client=owned_client)
    context = {"llm_client": run_client, "permission_gate": object()}

    result = generator.generate(
        {"op_type": "ReLU"},
        [],
        str(tmp_path / "runs" / "r1" / "candidate"),
        context=context,
    )

    assert result["status"] == "candidate_generated"
    assert engine.client is run_client
    assert run_client.context is context
    assert owned_client.context is None


def test_candidate_sandbox_rejects_m_axi_for_non_byte_aligned_fixed_point():
    """Verify the test_candidate_sandbox_rejects_m_axi_for_non_byte_aligned_fixed_point contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
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


def test_candidate_sandbox_rejects_dynamic_memory():
    """Verify the test_candidate_sandbox_rejects_dynamic_memory contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    payload = {
        "files": [
            {
                "relative_path": "candidate/top.cpp",
                "content": "void top(int n) { float* buffer = new float[n]; delete[] buffer; }\n",
            }
        ]
    }
    result = CandidateSandbox().scan_candidate_payload(payload)
    assert result["status"] == "invalid"
    assert any(item["rule"] == "dynamic_memory" for item in result["violations"])


def test_candidate_sandbox_rejects_large_complete_mutable_activation_partition():
    """Verify the test_candidate_sandbox_rejects_large_complete_mutable_activation_partition contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
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
