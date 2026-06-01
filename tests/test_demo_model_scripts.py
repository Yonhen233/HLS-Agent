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
    ("make_qkeras_mnist_cnn.py", "tensorflow"),
    ("make_tiny_residual_block_onnx.py", "torch"),
]


def _load_script_module(script_path: Path):
    spec = importlib.util.spec_from_file_location(f"script_{script_path.stem}", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_demo_model_scripts_exist():
    for filename, _ in SCRIPT_CASES:
        assert (SCRIPTS / filename).exists()


def test_demo_model_scripts_support_help():
    for filename, _ in SCRIPT_CASES:
        script = SCRIPTS / filename
        completed = subprocess.run([sys.executable, str(script), "--help"], capture_output=True, text=True, check=False)
        assert completed.returncode == 0
        assert "usage" in completed.stdout.lower()


def test_demo_model_scripts_graceful_skip_missing_deps(monkeypatch, tmp_path):
    for filename, missing_root in SCRIPT_CASES:
        script = SCRIPTS / filename
        module = _load_script_module(script)
        original_import = builtins.__import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == missing_root or name.startswith(f"{missing_root}."):
                raise ImportError(f"mock missing dependency: {missing_root}")
            return original_import(name, globals, locals, fromlist, level)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        output_path = tmp_path / "generated" / f"{script.stem}.out"
        rc = module.main(["--output", str(output_path)])
        assert rc == 0
        monkeypatch.setattr(builtins, "__import__", original_import)
