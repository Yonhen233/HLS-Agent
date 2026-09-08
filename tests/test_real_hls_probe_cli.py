"""Test contracts and regression checks for test_real_hls_probe_cli.py.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _probe_script_module():
    """Verify the _probe_script_module contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "run_real_hls_probe.py"
    spec = importlib.util.spec_from_file_location("real_hls_probe_script", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_real_hls_probe_parser_reuses_existing_project_without_conversion():
    """Verify the test_real_hls_probe_parser_reuses_existing_project_without_conversion contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
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
