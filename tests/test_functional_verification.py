import json

import pytest

from dl_op_to_hls.tools.fallback_template import render_fallback_operator
from dl_op_to_hls.tools.functional_verification import parse_csim_verification, write_onnx_reference_data
from dl_op_to_hls.tools.parameter_advisor import recommend_parameters


def _operator_task(op_type: str) -> dict:
    return {
        "task_type": "operator",
        "op_type": op_type,
        "name": f"{op_type.lower()}_golden",
        "input_shape": [4, 4] if op_type == "MatMul" else [4],
        "output_shape": [4, 4] if op_type == "MatMul" else [4],
        "dtype": "ap_fixed<16,6>",
        "target": {"backend": "VivadoHLS", "part": "xc7z020clg400-1", "clock_period": 5},
        "optimization": {"objective": "latency", "reuse_factor": 1, "pipeline_ii": 1},
    }


@pytest.mark.parametrize("op_type", ["Dense", "MatMul", "ReLU", "Add"])
def test_fallback_generates_golden_testbench_and_reference(tmp_path, op_type):
    result = render_fallback_operator(_operator_task(op_type), str(tmp_path))
    testbench = (tmp_path / "testbench.cpp").read_text(encoding="utf-8")
    reference = json.loads((tmp_path / "reference.json").read_text(encoding="utf-8"))
    assert result["status"] == "success"
    assert "GOLDEN_CHECK_PASSED" in testbench
    assert "GOLDEN_CHECK_FAILED" in testbench
    assert reference["status"] == "success"


def test_parse_csim_verification_from_golden_log(tmp_path):
    log = tmp_path / "csynth.log"
    log.write_text("Starting C simulation...\nGOLDEN_CHECK_PASSED\nC simulation completed\n", encoding="utf-8")
    result = parse_csim_verification(log, work_dir=tmp_path)
    assert result["status"] == "csim_passed"
    assert result["passed"] is True


def test_parse_csim_verification_compares_hls4ml_outputs(tmp_path):
    tb_data = tmp_path / "tb_data"
    tb_data.mkdir()
    (tb_data / "tb_output_predictions.dat").write_text("1.0 2.0\n", encoding="utf-8")
    (tb_data / "csim_results.log").write_text("1.1 1.9\n", encoding="utf-8")
    log = tmp_path / "csynth.log"
    log.write_text("C simulation completed\n", encoding="utf-8")
    result = parse_csim_verification(log, work_dir=tmp_path, tolerance=0.25)
    assert result["status"] == "csim_passed"
    assert result["comparison"]["max_abs_error"] == pytest.approx(0.1)


def test_parse_csim_verification_accepts_classification_pass_with_numeric_drift(tmp_path):
    tb_data = tmp_path / "tb_data"
    tb_data.mkdir()
    (tb_data / "tb_output_predictions.dat").write_text("1 9 0\n8 1 0\n", encoding="utf-8")
    (tb_data / "csim_results.log").write_text("0 100 0\n80 0 0\n", encoding="utf-8")
    labels = tmp_path / "labels.json"
    labels.write_text(json.dumps({"labels": [1, 0]}), encoding="utf-8")
    (tb_data / "reference_manifest.json").write_text(
        json.dumps({"labels_path": str(labels), "classification_min_accuracy": 1.0, "argmax_match_min": 1.0}),
        encoding="utf-8",
    )
    log = tmp_path / "csynth.log"
    log.write_text("C simulation completed\n", encoding="utf-8")
    result = parse_csim_verification(log, work_dir=tmp_path, tolerance=0.25)
    assert result["status"] == "csim_passed"
    assert result["comparison"]["numeric_passed"] is False
    assert result["comparison"]["recognition_passed"] is True
    assert result["classification"]["hls_accuracy"] == 1.0


def test_parse_csim_verification_finds_vivado_csim_build_output(tmp_path):
    tb_data = tmp_path / "tb_data"
    build_tb_data = tmp_path / "vivado_hls" / "solution1" / "csim" / "build" / "tb_data"
    tb_data.mkdir()
    build_tb_data.mkdir(parents=True)
    (tb_data / "tb_output_predictions.dat").write_text("1.0 2.0\n", encoding="utf-8")
    (build_tb_data / "csim_results.log").write_text("1.05 1.95\n", encoding="utf-8")
    log = tmp_path / "csynth.log"
    log.write_text("INFO: [SIM 211-1] CSim done with 0 errors.\n", encoding="utf-8")
    result = parse_csim_verification(log, work_dir=tmp_path, tolerance=0.25)
    assert result["mode"] == "hls4ml_reference_compare"
    assert result["status"] == "csim_passed"
    assert result["output_path"].endswith("csim_results.log")


def test_parse_csim_verification_reports_assertion_failure(tmp_path):
    tb_data = tmp_path / "tb_data"
    build_tb_data = tmp_path / "vivado_hls" / "solution1" / "csim" / "build" / "tb_data"
    tb_data.mkdir()
    build_tb_data.mkdir(parents=True)
    (tb_data / "tb_output_predictions.dat").write_text("1.0 2.0\n", encoding="utf-8")
    (build_tb_data / "csim_results.log").write_text("", encoding="utf-8")
    log = tmp_path / "csynth.log"
    log.write_text("Processing input 0\nAssertion failed!\n@E Simulation failed\n", encoding="utf-8")
    result = parse_csim_verification(log, work_dir=tmp_path)
    assert result["status"] == "csim_failed"
    assert result["csim_executed"] is True
    assert result["reason"] == "C simulation log contains a failure marker."


def test_write_onnx_reference_data(tmp_path):
    pytest.importorskip("onnx")
    pytest.importorskip("onnxruntime")
    import onnx
    from onnx import TensorProto, helper

    input_tensor = helper.make_tensor_value_info("x", TensorProto.FLOAT, [1, 2])
    output_tensor = helper.make_tensor_value_info("y", TensorProto.FLOAT, [1, 2])
    node = helper.make_node("Identity", ["x"], ["y"])
    graph = helper.make_graph([node], "identity_graph", [input_tensor], [output_tensor])
    model = helper.make_model(graph, producer_name="dl-op-to-hls-test", opset_imports=[helper.make_operatorsetid("", 13)])
    model.ir_version = 10
    model_path = tmp_path / "identity.onnx"
    onnx.save(model, model_path)

    result = write_onnx_reference_data(model_path, tmp_path / "hls_project", num_samples=2)
    assert result["status"] == "success"
    assert (tmp_path / "hls_project" / "tb_data" / "tb_input_features.dat").exists()
    assert (tmp_path / "hls_project" / "tb_data" / "tb_output_predictions.dat").exists()


class _Repo:
    def list_memory_items(self, memory_types):
        del memory_types
        value = {
            "task": {
                "name": "mnist_mlp_demo",
                "task_type": "model",
                "hls4ml": {"precision": "fixed<8,3>", "reuse_factor": 512, "strategy": "Resource"},
                "target": {"clock_period": 10},
            },
            "verification": {"status": "csim_passed", "passed": True, "mode": "hls4ml_reference_compare"},
            "report": {"status": "success", "resources": {"lut": 123}},
        }
        return [
            {
                "id": 1,
                "source_run_id": "verified_run",
                "importance": 3,
                "value_json": json.dumps(value),
            }
        ]


def test_parameter_advisor_reads_verified_history():
    state = {
        "task": {
            "name": "mnist_mlp_demo",
            "task_type": "model",
            "hls4ml": {"precision": "fixed<16,6>", "reuse_factor": 64},
        }
    }
    result = recommend_parameters({"state": state}, {"repository": _Repo()})
    assert result["status"] == "success"
    assert result["mode"] == "verified_history"
    assert any(item["parameter"] == "reuse_factor" and item["recommended_value"] == 512 for item in result["recommendations"])


class _ExecutionOnlyRepo:
    def list_memory_items(self, memory_types):
        del memory_types
        value = {
            "task": {"name": "mnist_mlp_demo", "task_type": "model", "hls4ml": {"reuse_factor": 512}},
            "verification": {"status": "csim_passed", "passed": True, "mode": "vivado_csim"},
            "report": {"status": "success"},
        }
        return [{"id": 2, "source_run_id": "execution_only", "importance": 5, "value_json": json.dumps(value)}]


def test_parameter_advisor_ignores_execution_only_csim_history():
    state = {"task": {"name": "mnist_mlp_demo", "task_type": "model", "hls4ml": {"reuse_factor": 64}}}
    result = recommend_parameters({"state": state}, {"repository": _ExecutionOnlyRepo()})
    assert result["mode"] == "heuristic_bootstrap"
    assert result["source_count"] == 0


class _TimingFailedRepo:
    def list_memory_items(self, memory_types):
        del memory_types
        value = {
            "task": {"name": "matmul_16x16_resource", "task_type": "operator", "optimization": {"reuse_factor": 8}},
            "verification": {"status": "csim_passed", "passed": True, "mode": "golden_testbench"},
            "report": {"status": "success", "timing": {"met": False}},
        }
        return [{"id": 3, "source_run_id": "timing_failed", "importance": 5, "value_json": json.dumps(value)}]


def test_parameter_advisor_ignores_timing_failed_history():
    state = {"task": {"name": "matmul_16x16_resource", "task_type": "operator", "optimization": {"reuse_factor": 8}}}
    result = recommend_parameters({"state": state}, {"repository": _TimingFailedRepo()})
    assert result["mode"] == "heuristic_bootstrap"
    assert result["source_count"] == 0


class _MismatchedFamilyRepo:
    def list_memory_items(self, memory_types):
        del memory_types
        value = {
            "task": {
                "name": "mnist_qonnx_cnn",
                "task_type": "model",
                "frontend": "qonnx",
                "hls4ml": {"precision": "fixed<8,3>", "reuse_factor": 32, "strategy": "Resource"},
                "target": {"clock_period": 10},
            },
            "verification": {"status": "csim_passed", "passed": True, "mode": "hls4ml_reference_compare"},
            "report": {"status": "success", "timing": {"met": True}},
        }
        return [{"id": 4, "source_run_id": "qonnx_cnn_verified", "importance": 5, "value_json": json.dumps(value)}]


def test_parameter_advisor_does_not_cross_model_family_from_cnn_to_mlp():
    state = {"task": {"name": "mnist_mlp_demo", "task_type": "model", "hls4ml": {"reuse_factor": 512}}}
    result = recommend_parameters({"state": state}, {"repository": _MismatchedFamilyRepo()})
    assert result["mode"] == "heuristic_bootstrap"
    assert result["source_count"] == 0
    assert all(item.get("source") != "verified_history" for item in result["recommendations"])


class _SampleFixtureRepo:
    def list_memory_items(self, memory_types):
        del memory_types
        value = {
            "task": {
                "name": "mnist_recognition_mlp_mock",
                "task_type": "model",
                "hls4ml": {"precision": "fixed<12,6>", "reuse_factor": 1024, "strategy": "Resource"},
                "target": {"clock_period": 10},
            },
            "verification": {"status": "csim_passed", "passed": True, "mode": "golden_testbench"},
            "report": {
                "status": "success",
                "latency": {"min_cycles": 45, "max_cycles": 45},
                "resources": {"bram": 0, "dsp": 32, "ff": 2100, "lut": 3500},
                "timing": {"estimated_ns": 4.3, "met": True},
            },
        }
        return [{"id": 5, "source_run_id": "mock_fixture", "importance": 5, "value_json": json.dumps(value)}]


def test_parameter_advisor_ignores_sample_fixture_history():
    state = {"task": {"name": "mnist_recognition_mlp", "task_type": "model", "hls4ml": {"reuse_factor": 1024}}}
    result = recommend_parameters({"state": state}, {"repository": _SampleFixtureRepo()})
    assert result["mode"] == "heuristic_bootstrap"
    assert result["source_count"] == 0


class _ResourceRankingRepo:
    def list_memory_items(self, memory_types):
        del memory_types

        def item(memory_id, run_id, clock, ff, lut):
            value = {
                "task": {
                    "name": "mnist_recognition_mlp",
                    "task_type": "model",
                    "hls4ml": {"precision": "fixed<12,6>", "reuse_factor": 1024, "strategy": "Resource"},
                    "target": {"clock_period": clock},
                    "objective": "resource",
                },
                "verification": {"status": "csim_passed", "passed": True, "mode": "hls4ml_reference_compare"},
                "report": {
                    "status": "success",
                    "latency": {"min_cycles": 2135, "max_cycles": 2139},
                    "resources": {"bram": 47, "dsp": 64, "ff": ff, "lut": lut},
                    "timing": {"estimated_ns": 8.0, "met": True},
                },
            }
            return {"id": memory_id, "source_run_id": run_id, "importance": 3, "value_json": json.dumps(value)}

        return [
            item(6, "ten_ns_verified", 10, 8548, 19720),
            item(7, "fifteen_ns_verified", 15, 5999, 17899),
        ]


def test_parameter_advisor_ranks_verified_history_by_resource_cost():
    state = {"task": {"name": "mnist_recognition_mlp", "task_type": "model", "objective": "resource", "hls4ml": {}}}
    result = recommend_parameters({"state": state}, {"repository": _ResourceRankingRepo()})
    assert result["mode"] == "verified_history"
    assert result["matched_history"][0]["source_run_id"] == "fifteen_ns_verified"
    assert any(item["parameter"] == "clock_period" and item["recommended_value"] == 15 for item in result["recommendations"])
