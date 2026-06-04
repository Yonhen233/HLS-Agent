from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture
def sample_csynth_report_path() -> Path:
    return ROOT / "tests" / "fixtures" / "sample_csynth.rpt"


@pytest.fixture
def sample_vivado_log_path() -> Path:
    return ROOT / "tests" / "fixtures" / "sample_vivado_log.txt"


@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    (tmp_path / "examples").mkdir(parents=True, exist_ok=True)
    (tmp_path / "models").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "runs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "skills").mkdir(parents=True, exist_ok=True)
    (tmp_path / "examples" / "hls_projects" / "dense").mkdir(parents=True, exist_ok=True)

    for filename in [
        "dense_operator.json",
        "matmul_resource.json",
        "matmul_operator.json",
        "relu_operator.json",
        "add_operator.json",
        "mlp_onnx_example.json",
        "mnist_mlp_hls4ml.json",
        "mnist_tiny_cnn.json",
        "mnist_qonnx_cnn.json",
        "mnist_qkeras_cnn.json",
        "tiny_residual_block.json",
        "resnet18_boundary.json",
        "existing_hls_project.json",
    ]:
        shutil.copy2(ROOT / "examples" / filename, tmp_path / "examples" / filename)
    for filename in ["existing_dense_project.h", "existing_dense_project.cpp", "testbench.cpp", "run_hls.tcl"]:
        shutil.copy2(ROOT / "examples" / "hls_projects" / "dense" / filename, tmp_path / "examples" / "hls_projects" / "dense" / filename)
    for skill_path in (ROOT / "skills").glob("*.yaml"):
        shutil.copy2(skill_path, tmp_path / "skills" / skill_path.name)
    shutil.copy2(ROOT / "models" / "mlp.onnx", tmp_path / "models" / "mlp.onnx")
    shutil.copy2(ROOT / "permissions.yaml", tmp_path / "permissions.yaml")
    return tmp_path


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
