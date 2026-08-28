from __future__ import annotations

import json
from pathlib import Path

import pytest

from dl_op_to_hls.schemas.task_schema import load_task
from dl_op_to_hls.tools.graph_rewrite import rewrite_graph
from dl_op_to_hls.core.errors import AgentRuntimeError
from dl_op_to_hls.schemas.operator_schema import normalize_operator_task


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


def _validate_example(filename: str) -> dict:
    payload = json.loads((EXAMPLES / filename).read_text(encoding="utf-8"))
    validated = load_task(payload)
    assert validated["task_type"] in {"operator", "model", "hls_project"}
    assert "name" in validated
    assert isinstance(validated.get("demo"), dict)
    return validated


def test_dense_operator_schema_valid():
    data = _validate_example("dense_operator.json")
    assert data["task_type"] == "operator"
    assert data["op_type"] == "Dense"


def test_matmul_resource_schema_valid():
    data = _validate_example("matmul_resource.json")
    assert data["task_type"] == "operator"
    assert data["op_type"] == "MatMul"


def test_mnist_mlp_schema_valid():
    data = _validate_example("mnist_mlp_hls4ml.json")
    assert data["task_type"] == "model"
    assert data["frontend"] == "onnx"


def test_mnist_recognition_mlp_schema_valid():
    data = _validate_example("mnist_recognition_mlp.json")
    assert data["task_type"] == "model"
    assert data["frontend"] == "onnx"
    assert data["demo"]["expected_path"] == "hls4ml"
    assert data["reference_data"]["classification_min_accuracy"] >= 0.9


def test_mnist_tiny_cnn_schema_valid():
    data = _validate_example("mnist_tiny_cnn.json")
    assert data["task_type"] == "model"
    assert data["frontend"] == "onnx"


def test_mnist_qkeras_schema_valid():
    data = _validate_example("mnist_qkeras_cnn.json")
    assert data["task_type"] == "model"
    assert data["frontend"] == "qkeras"


def test_mnist_qonnx_schema_valid():
    data = _validate_example("mnist_qonnx_cnn.json")
    assert data["task_type"] == "model"
    assert data["frontend"] == "qonnx"


def test_tiny_residual_schema_valid():
    data = _validate_example("tiny_residual_block.json")
    assert data["task_type"] == "model"
    assert data["name"] == "tiny_residual_block"


def test_resnet_boundary_schema_valid():
    data = _validate_example("resnet18_boundary.json")
    assert data["task_type"] == "model"
    assert data["name"] == "resnet18_boundary_demo"


def test_scale_shift_llm_candidate_schema_valid():
    data = _validate_example("scale_shift_llm_candidate.json")
    assert data["task_type"] == "operator"
    assert data["op_type"] == "ScaleShift"
    assert data["demo"]["expected_path"] == "llm_candidate_path"
    assert data["max_repair_attempts"] == 6
    assert data["candidate_contract"]["top_function"] == data["top_function"]


@pytest.mark.parametrize(
    ("filename", "op_type"),
    [
        ("dense_llm_candidate.json", "Dense"),
        ("matmul_llm_candidate.json", "MatMul"),
        ("relu_llm_candidate.json", "ReLU"),
        ("add_llm_candidate.json", "Add"),
    ],
)
def test_fallback_operator_llm_candidate_schema_valid(filename, op_type):
    data = _validate_example(filename)
    assert data["task_type"] == "operator"
    assert data["op_type"] == op_type
    assert data["llm_candidate"]["required"] is True
    assert data["demo"]["expected_path"] == "llm_candidate_path"
    assert data["candidate_contract"]["top_function"] == data["top_function"]


def test_graph_rewrite_suggests_gemm_decomposition():
    result = rewrite_graph({"task": {"task_type": "operator", "op_type": "Gemm"}}, {})
    assert result["status"] == "rewrite_suggested"
    assert "Gemm -> MatMul + Add" in result["rewrites"]


def test_operator_schema_rejects_dynamic_shape():
    with __import__("pytest").raises(AgentRuntimeError) as exc:
        normalize_operator_task(
            {"task_type": "operator", "op_type": "ReLU", "input_shape": ["N"], "output_shape": [16]}
        )
    assert exc.value.error.error_type == "UnsupportedOperatorError"


def test_operator_schema_rejects_invalid_fixed_point_dtype():
    with __import__("pytest").raises(AgentRuntimeError) as exc:
        normalize_operator_task(
            {"task_type": "operator", "op_type": "Add", "input_shape": [16], "output_shape": [16], "dtype": "float32"}
        )
    assert exc.value.error.error_type == "InvalidTaskError"


def test_operator_schema_rejects_inconsistent_matmul_shapes():
    with __import__("pytest").raises(AgentRuntimeError) as exc:
        normalize_operator_task(
            {
                "task_type": "operator",
                "op_type": "MatMul",
                "input_shape": [4, 8],
                "weight_shape": [7, 2],
                "output_shape": [4, 2],
                "dtype": "ap_fixed<12,4>",
            }
        )
    assert exc.value.error.error_type == "InvalidTaskError"


def test_graph_rewrite_suggests_static_shape_elimination():
    result = rewrite_graph({"task": {"task_type": "operator", "op_type": "Flatten"}}, {})
    assert result["status"] == "rewrite_suggested"
    assert result["implemented"] is False


def test_graph_rewrite_rewrites_onnx_gemm_to_matmul_add(tmp_path):
    onnx = pytest.importorskip("onnx")
    numpy = pytest.importorskip("numpy")
    from onnx import TensorProto, helper, numpy_helper

    model_path = tmp_path / "gemm.onnx"
    x = helper.make_tensor_value_info("x", TensorProto.FLOAT, [1, 16])
    y = helper.make_tensor_value_info("y", TensorProto.FLOAT, [1, 32])
    weights = numpy_helper.from_array(numpy.ones((32, 16), dtype=numpy.float32), name="w")
    bias = numpy_helper.from_array(numpy.zeros((32,), dtype=numpy.float32), name="b")
    gemm = helper.make_node("Gemm", inputs=["x", "w", "b"], outputs=["y"], name="dense_gemm", transB=1)
    graph = helper.make_graph([gemm], "gemm_graph", [x], [y], initializer=[weights, bias])
    model = helper.make_model(graph)
    onnx.save(model, str(model_path))

    result = rewrite_graph(
        {"task": {"task_type": "model", "model_path": str(model_path), "frontend": "onnx"}},
        {"run_dir": tmp_path / "run"},
    )

    assert result["status"] == "success"
    assert result["implemented"] is True
    rewritten = onnx.load(result["rewritten_model_path"])
    ops = {node.op_type for node in rewritten.graph.node}
    assert "Gemm" not in ops
    assert {"MatMul", "Add"} <= ops
