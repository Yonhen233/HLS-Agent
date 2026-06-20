from __future__ import annotations

import importlib.util
from pathlib import Path


def _fifo_script_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "optimize_hls4ml_fifo_depths.py"
    spec = importlib.util.spec_from_file_location("fifo_optimization_script", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fifo_optimizer_parser_accepts_reusable_profile_artifact():
    parser = _fifo_script_module().build_parser()

    args = parser.parse_args(
        [
            "--model-path",
            "models/model.onnx",
            "--config-path",
            "runs/config.yml",
            "--output-dir",
            "runs/fifo_optimized",
            "--input-path",
            "models/reference_inputs.npy",
            "--max-depth-path",
            "runs/profile/max_depth.json",
        ]
    )

    assert args.max_depth_path == "runs/profile/max_depth.json"
    assert args.profiling_depth == 2048
