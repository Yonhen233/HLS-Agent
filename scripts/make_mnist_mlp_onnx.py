"""Experiment, training, export, or real-tool entry point for make_mnist_mlp_onnx.py.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    """Execute build_parser at the make_mnist_mlp_onnx boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Returns:
        The structured value promised by the function signature.
    """
    parser = argparse.ArgumentParser(description="Generate a tiny MNIST MLP ONNX model for demo usage.")
    parser.add_argument("--output", default="models/generated/mnist_mlp.onnx", help="Output ONNX path.")
    parser.add_argument("--opset", type=int, default=18, help="ONNX opset version.")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Execute main at the make_mnist_mlp_onnx boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Args:
        argv: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        import torch
        import torch.nn as nn
    except Exception as exc:  # pragma: no cover - environment dependent
        print(f"[skip] torch is unavailable: {exc}")
        return 0

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    class MnistMLP(nn.Module):
        """Coordinate MnistMLP within the make_mnist_mlp_onnx boundary.

        The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
        """
        def __init__(self) -> None:
            """Implement the internal __init__ helper.

            Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

            Returns:
                The structured value promised by the function signature.
            """
            super().__init__()
            self.fc1 = nn.Linear(784, 64)
            self.fc2 = nn.Linear(64, 32)
            self.fc3 = nn.Linear(32, 10)
            self.act = nn.ReLU()

        def forward(self, x):
            """Execute forward at the make_mnist_mlp_onnx boundary.

            This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

            Args:
                x: Value supplied by the caller and validated by the surrounding schema.

            Returns:
                The structured value promised by the function signature.
            """
            x = self.act(self.fc1(x))
            x = self.act(self.fc2(x))
            return self.fc3(x)

    model = MnistMLP().eval()
    sample = torch.randn(1, 784)
    try:
        torch.onnx.export(
            model,
            sample,
            str(output_path),
            export_params=True,
            input_names=["model_input"],
            output_names=["logits"],
            opset_version=args.opset,
        )
    except Exception as exc:  # pragma: no cover - environment dependent
        print(f"[skip] ONNX export failed in this environment: {exc}")
        return 0
    print(f"[ok] wrote {output_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
