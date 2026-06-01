from __future__ import annotations

import json
from pathlib import Path

from dl_op_to_hls.schemas.task_schema import load_task


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


def test_mnist_tiny_cnn_schema_valid():
    data = _validate_example("mnist_tiny_cnn.json")
    assert data["task_type"] == "model"
    assert data["frontend"] == "onnx"


def test_mnist_qkeras_schema_valid():
    data = _validate_example("mnist_qkeras_cnn.json")
    assert data["task_type"] == "model"
    assert data["frontend"] == "qkeras"


def test_tiny_residual_schema_valid():
    data = _validate_example("tiny_residual_block.json")
    assert data["task_type"] == "model"
    assert data["name"] == "tiny_residual_block"


def test_resnet_boundary_schema_valid():
    data = _validate_example("resnet18_boundary.json")
    assert data["task_type"] == "model"
    assert data["name"] == "resnet18_boundary_demo"
