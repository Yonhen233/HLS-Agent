"""Experiment, training, export, or real-tool entry point for make_mnist_qonnx_cnn.py.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    """Execute build_parser at the make_mnist_qonnx_cnn boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Returns:
        The structured value promised by the function signature.
    """
    parser = argparse.ArgumentParser(description="Generate a tiny Torch/QONNX-style quantized MNIST CNN ONNX model.")
    parser.add_argument("--output", default="models/generated/mnist_qonnx_cnn.onnx", help="Output ONNX path.")
    parser.add_argument("--opset", type=int, default=18, help="ONNX opset version.")
    parser.add_argument("--quant-step", type=float, default=1.0 / 32.0, help="Static weight quantization step.")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Execute main at the make_mnist_qonnx_cnn boundary.

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

    class QuantizedTinyMNISTCNN(nn.Module):
        """Coordinate QuantizedTinyMNISTCNN within the make_mnist_qonnx_cnn boundary.

        The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
        """
        def __init__(self) -> None:
            """Implement the internal __init__ helper.

            Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

            Returns:
                The structured value promised by the function signature.
            """
            super().__init__()
            self.conv1 = nn.Conv2d(1, 4, kernel_size=3)
            self.conv2 = nn.Conv2d(4, 8, kernel_size=3)
            self.pool = nn.MaxPool2d(2)
            self.act = nn.ReLU()
            self.fc1 = nn.Linear(8 * 2 * 2, 16)
            self.fc2 = nn.Linear(16, 10)

        def forward(self, x):
            """Execute forward at the make_mnist_qonnx_cnn boundary.

            This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

            Args:
                x: Value supplied by the caller and validated by the surrounding schema.

            Returns:
                The structured value promised by the function signature.
            """
            x = self.pool(self.act(self.conv1(x)))
            x = self.pool(self.act(self.conv2(x)))
            x = x.flatten(1)
            x = self.act(self.fc1(x))
            return self.fc2(x)

    model = QuantizedTinyMNISTCNN().eval()
    step = float(args.quant_step)
    with torch.no_grad():
        for parameter in model.parameters():
            parameter.copy_(torch.round(parameter / step) * step)

    sample = torch.randn(1, 1, 14, 14)
    try:
        torch.onnx.export(
            model,
            sample,
            str(output_path),
            export_params=True,
            input_names=["model_input_nchw"],
            output_names=["logits"],
            opset_version=args.opset,
        )
    except Exception as exc:  # pragma: no cover - environment dependent
        print(f"[skip] ONNX export failed in this environment: {exc}")
        return 0

    try:
        import onnx

        model_proto = onnx.load(str(output_path))
        props = {
            "demo_frontend": "qonnx",
            "source_framework": "torch",
            "quantization": f"static_weight_rounding_step_{step}",
            "note": "QONNX-style demo artifact for hls4ml agent toolchain validation, not an accuracy benchmark.",
        }
        del model_proto.metadata_props[:]
        for key, value in props.items():
            item = model_proto.metadata_props.add()
            item.key = key
            item.value = value
        onnx.save(model_proto, str(output_path))
    except Exception as exc:  # pragma: no cover - optional metadata
        print(f"[warn] wrote ONNX but could not attach metadata: {exc}")

    print(f"[ok] wrote {output_path}")
    print("[note] Weights are statically rounded to mimic a quantized Torch/QONNX path for FPGA toolchain validation.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
