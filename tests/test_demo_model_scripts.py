"""Test contracts and regression checks for test_demo_model_scripts.py.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

import builtins
import importlib.util
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


SCRIPT_CASES = [
    ("make_mnist_mlp_onnx.py", "torch"),
    ("make_mnist_tiny_cnn_onnx.py", "torch"),
    ("make_mnist_qonnx_cnn.py", "torch"),
    ("make_qkeras_mnist_cnn.py", "tensorflow"),
    ("make_tiny_residual_block_onnx.py", "torch"),
]


def _load_script_module(script_path: Path):
    """Verify the _load_script_module contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        script_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    spec = importlib.util.spec_from_file_location(f"script_{script_path.stem}", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_demo_model_scripts_exist():
    """Verify the test_demo_model_scripts_exist contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    for filename, _ in SCRIPT_CASES:
        assert (SCRIPTS / filename).exists()


def test_demo_model_scripts_support_help():
    """Verify the test_demo_model_scripts_support_help contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    for filename, _ in SCRIPT_CASES:
        script = SCRIPTS / filename
        completed = subprocess.run([sys.executable, str(script), "--help"], capture_output=True, text=True, check=False)
        assert completed.returncode == 0
        assert "usage" in completed.stdout.lower()


def test_demo_model_scripts_graceful_skip_missing_deps(monkeypatch, tmp_path):
    """Verify the test_demo_model_scripts_graceful_skip_missing_deps contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        monkeypatch: Value supplied by the caller and validated by the surrounding schema.
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    for filename, missing_root in SCRIPT_CASES:
        script = SCRIPTS / filename
        module = _load_script_module(script)
        original_import = builtins.__import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            """Verify the fake_import contract.

            The test should fail on a real contract regression rather than hide an unsupported path.

            Args:
                name: Value supplied by the caller and validated by the surrounding schema.
                globals: Value supplied by the caller and validated by the surrounding schema.
                locals: Value supplied by the caller and validated by the surrounding schema.
                fromlist: Value supplied by the caller and validated by the surrounding schema.
                level: Value supplied by the caller and validated by the surrounding schema.

            Returns:
                The structured value promised by the function signature.
            """
            if name == missing_root or name.startswith(f"{missing_root}."):
                raise ImportError(f"mock missing dependency: {missing_root}")
            return original_import(name, globals, locals, fromlist, level)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        output_path = tmp_path / "generated" / f"{script.stem}.out"
        rc = module.main(["--output", str(output_path)])
        assert rc == 0
        monkeypatch.setattr(builtins, "__import__", original_import)
