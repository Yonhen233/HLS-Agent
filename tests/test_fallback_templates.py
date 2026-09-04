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
    result = verify_candidate({"candidate_dir": str(candidate_dir), "report_dir": str(run_dir / "reports"), "mode": "mock"}, {"artifact_manager": manager})
    assert result["status"] == "verified"
    assert result["mode"] == "mock"


def test_verify_candidate_mock_failure(tmp_path):
    result = verify_candidate({"candidate_dir": str(tmp_path / "candidate"), "report_dir": str(tmp_path / "reports"), "force_fail": True}, {})
    assert result["status"] == "failed"


def test_verify_candidate_real_mode_requires_testbench(tmp_path, monkeypatch):
    monkeypatch.setenv("DL_OP_TO_HLS_MOCK_VIVADO", "0")
    candidate_dir = tmp_path / "candidate"
    candidate_dir.mkdir()
    (candidate_dir / "candidate.cpp").write_text("void candidate(float x[1], float y[1]) { y[0] = x[0]; }\n", encoding="utf-8")
    result = verify_candidate(
        {"candidate_dir": str(candidate_dir), "report_dir": str(tmp_path / "runs" / "r1" / "reports"), "mode": "real"},
        {},
    )
    assert result["status"] == "failed"
    assert result["error"]["error_type"] == "VerificationFailedError"
    assert "testbench" in result["error"]["message"]


def test_verify_candidate_real_mode_rejects_missing_contract_file_before_vivado(tmp_path, monkeypatch):
    monkeypatch.setenv("DL_OP_TO_HLS_MOCK_VIVADO", "0")
    candidate_dir = tmp_path / "candidate"
    candidate_dir.mkdir()
    (candidate_dir / "top.cpp").write_text("void top() {}\n", encoding="utf-8")
    result = verify_candidate(
        {
            "candidate_dir": str(candidate_dir),
            "report_dir": str(tmp_path / "reports"),
            "mode": "real",
            "candidate_contract": {"required_files": ["candidate/top.h", "candidate/top.cpp"]},
        },
        {},
    )
    assert result["status"] == "failed"
    assert result["error"]["details"]["missing_files"] == ["candidate/top.h"]


def test_verify_candidate_real_mode_rejects_signature_mismatch_before_vivado(tmp_path, monkeypatch):
    monkeypatch.setenv("DL_OP_TO_HLS_MOCK_VIVADO", "0")
    candidate_dir = tmp_path / "candidate"
    candidate_dir.mkdir()
    (candidate_dir / "top.h").write_text("void wrong_top();\n", encoding="utf-8")
    (candidate_dir / "top.cpp").write_text("void wrong_top() {}\n", encoding="utf-8")
    (candidate_dir / "testbench.cpp").write_text("int main() { return 0; }\n", encoding="utf-8")
    result = verify_candidate(
        {
            "candidate_dir": str(candidate_dir),
            "report_dir": str(tmp_path / "reports"),
            "mode": "real",
            "candidate_contract": {
                "required_files": ["candidate/top.h", "candidate/top.cpp", "candidate/testbench.cpp"],
                "signature": "void expected_top(data_t input[4], data_t output[4])",
            },
        },
        {},
    )
    assert result["status"] == "failed"
    assert result["error"]["details"]["expected_top_function"] == "expected_top"


def test_verify_candidate_real_mode_records_composite_tool_phases(tmp_path, monkeypatch):
    monkeypatch.setenv("DL_OP_TO_HLS_MOCK_VIVADO", "0")
    candidate_dir = tmp_path / "candidate"
    candidate_dir.mkdir()
    (candidate_dir / "top.cpp").write_text("void top() {}\n", encoding="utf-8")
    (candidate_dir / "testbench.cpp").write_text("int main() { return 0; }\n", encoding="utf-8")
    report_path = tmp_path / "top_csynth.rpt"
    report_path.write_text("real report evidence\n", encoding="utf-8")

    class FakeVivadoAdapter:
        mock_mode = False

        def create_project(self, arguments):
            del arguments
            return {
                "status": "success",
                "work_dir": str(tmp_path / "vivado"),
                "tcl_path": str(tmp_path / "run_hls.tcl"),
                "top_function": "top",
            }

        def run_csynth(self, arguments):
            del arguments
            return {
                "status": "success",
                "log_path": str(tmp_path / "csynth.log"),
                "report_path": str(report_path),
                "verification": {
                    "status": "csim_passed",
                    "passed": True,
                    "log_path": str(tmp_path / "csim.log"),
                },
            }

        def parse_report(self, arguments):
            assert arguments["report_path"] == str(report_path)
            return {"status": "success", "latency": {"min_cycles": 1, "max_cycles": 1}}

    class RecordingHooks:
        def __init__(self):
            self.events = []

        def emit(self, event_name, payload):
            self.events.append({"event": event_name, **payload})

    hooks = RecordingHooks()
    result = verify_candidate(
        {
            "candidate_dir": str(candidate_dir),
            "report_dir": str(tmp_path / "reports"),
            "mode": "real",
            "top_function": "top",
        },
        {"run_id": "composite_trace", "vivado_adapter": FakeVivadoAdapter(), "hooks": hooks},
    )

    assert result["status"] == "verified"
    assert [item["capability"] for item in result["executed_subactions"]] == [
        "vivado.create_project",
        "vivado.run_csim",
        "vivado.run_csynth",
        "vivado.parse_report",
    ]
    observed = [item for item in hooks.events if item["event"] == "CompositeToolPhaseObserved"]
    assert [item["capability"] for item in observed] == [
        "vivado.create_project",
        "vivado.run_csim",
        "vivado.run_csynth",
        "vivado.parse_report",
    ]


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
    assert state.artifacts["unsupported_report"] == str(unsupported)
    manifest = __import__("json").loads((unsupported.parent / "artifacts.json").read_text(encoding="utf-8"))
    assert any(item["type"] == "unsupported_report" for item in manifest["artifacts"])
