from pathlib import Path

from dl_op_to_hls.adapters.llm_adapter import LLMAdapter
from dl_op_to_hls.core.artifacts import ArtifactManager
from dl_op_to_hls.core.config import DEFAULT_PERMISSIONS
from dl_op_to_hls.core.permissions import PermissionGate
from dl_op_to_hls.main_agent.agent import MainAgent
from dl_op_to_hls.main_agent.workflow import run_task
from dl_op_to_hls.tools.fallback_template import render_fallback_operator
from dl_op_to_hls.tools.llm_candidate import LLMCandidateGenerator
from dl_op_to_hls.tools.verify_candidate import verify_candidate


def _task(op_type: str) -> dict:
    return {
        "task_type": "operator",
        "op_type": op_type,
        "name": f"{op_type.lower()}_demo",
        "input_shape": [16],
        "output_shape": [16],
        "dtype": "ap_fixed<16,6>",
        "target": {"backend": "VivadoHLS", "part": "xc7z020clg400-1", "clock_period": 5},
        "optimization": {"objective": "latency", "reuse_factor": 1, "pipeline_ii": 1},
    }


def test_fallback_dense_generation(tmp_path):
    result = render_fallback_operator(_task("Dense") | {"output_shape": [32], "name": "dense_demo"}, str(tmp_path))
    assert result["status"] == "success"


def test_fallback_matmul_generation(tmp_path):
    result = render_fallback_operator(_task("MatMul") | {"input_shape": [4, 4], "output_shape": [4, 4]}, str(tmp_path))
    assert result["status"] == "success"


def test_fallback_relu_generation(tmp_path):
    result = render_fallback_operator(_task("ReLU"), str(tmp_path))
    assert result["status"] == "success"


def test_fallback_add_generation(tmp_path):
    result = render_fallback_operator(_task("Add"), str(tmp_path))
    assert result["status"] == "success"


def test_llm_candidate_interface_mock(tmp_path):
    generator = LLMCandidateGenerator(LLMAdapter())
    result = generator.generate(_task("Custom"), [], str(tmp_path))
    assert result["status"] == "error"
    assert "LLM is not enabled or API key is missing." in result["error"]["message"]


def test_verify_candidate_mock_success(tmp_path):
    run_dir = tmp_path / "runs" / "r1"
    run_dir.mkdir(parents=True, exist_ok=True)
    gate = PermissionGate(DEFAULT_PERMISSIONS, tmp_path)
    manager = ArtifactManager("r1", run_dir, gate)
    candidate_dir = tmp_path / "candidate"
    candidate_dir.mkdir()
    result = verify_candidate({"candidate_dir": str(candidate_dir), "report_dir": str(run_dir / "reports")}, {"artifact_manager": manager})
    assert result["status"] == "verified"


def test_verify_candidate_mock_failure(tmp_path):
    result = verify_candidate({"candidate_dir": str(tmp_path / "candidate"), "report_dir": str(tmp_path / "reports"), "force_fail": True}, {})
    assert result["status"] == "failed"


def test_unsupported_report_generated(temp_workspace):
    task = {
        "task_type": "operator",
        "op_type": "CustomUnsupported",
        "name": "custom_unsupported",
        "input_shape": [8],
        "output_shape": [8],
        "dtype": "ap_fixed<16,6>",
        "target": {"backend": "VivadoHLS", "part": "xc7z020clg400-1", "clock_period": 5},
        "optimization": {"objective": "latency", "reuse_factor": 1, "pipeline_ii": 1},
        "force_fail": True,
    }
    task_path = temp_workspace / "examples" / "unsupported.json"
    task_path.write_text(__import__("json").dumps(task), encoding="utf-8")
    state = run_task(str(task_path), agent=MainAgent(temp_workspace, console=False))
    unsupported = Path(temp_workspace / "runs" / state.run_id / "unsupported_report.md")
    assert unsupported.exists()
