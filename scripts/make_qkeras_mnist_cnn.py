"""Experiment, training, export, or real-tool entry point for make_qkeras_mnist_cnn.py.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

import argparse
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    """Execute build_parser at the make_qkeras_mnist_cnn boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Returns:
        The structured value promised by the function signature.
    """
    parser = argparse.ArgumentParser(description="Generate a tiny QKeras MNIST CNN model for demo usage.")
    parser.add_argument("--output", default="models/generated/mnist_qkeras_cnn.h5", help="Output .h5 path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Execute main at the make_qkeras_mnist_cnn boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Args:
        argv: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        from tensorflow import keras
        from tensorflow.keras import layers
    except Exception as exc:  # pragma: no cover - environment dependent
        print(f"[skip] tensorflow is unavailable: {exc}")
        return 0
    try:
        from qkeras import QActivation, QConv2D, QDense
    except Exception as exc:  # pragma: no cover - environment dependent
        print(f"[skip] qkeras is unavailable: {exc}")
        return 0

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    inputs = keras.Input(shape=(28, 28, 1), name="input")
    x = QConv2D(4, (3, 3), padding="valid", name="qconv1")(inputs)
    x = QActivation("quantized_relu(4)", name="qrelu1")(x)
    x = layers.MaxPool2D((2, 2), name="pool1")(x)
    x = QConv2D(8, (3, 3), padding="valid", name="qconv2")(x)
    x = QActivation("quantized_relu(4)", name="qrelu2")(x)
    x = layers.Flatten(name="flatten")(x)
    x = QDense(16, name="qdense1")(x)
    x = QActivation("quantized_relu(4)", name="qrelu3")(x)
    outputs = QDense(10, name="qdense2")(x)
    model = keras.Model(inputs=inputs, outputs=outputs, name="mnist_qkeras_cnn_demo")
    model.save(output_path, include_optimizer=False)
    print(f"[ok] wrote {output_path}")
    print("[note] This is a structure-only quantized demo model for toolchain validation, not an accuracy benchmark.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
