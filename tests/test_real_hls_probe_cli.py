from __future__ import annotations

import importlib.util
from pathlib import Path


def _probe_script_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "run_real_hls_probe.py"
    spec = importlib.util.spec_from_file_location("real_hls_probe_script", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_real_hls_probe_parser_reuses_existing_project_without_conversion():
    parser = _probe_script_module().build_parser()

    args = parser.parse_args(
        [
            "--name",
            "existing_project_probe",
            "--hls-project-dir",
            "runs/already_generated/hls_project",
            "--top-function",
            "custom_top",
            "--stage",
            "csynth",
        ]
    )

    assert args.hls_project_dir == "runs/already_generated/hls_project"
    assert args.top_function == "custom_top"
    assert args.stage == "csynth"
