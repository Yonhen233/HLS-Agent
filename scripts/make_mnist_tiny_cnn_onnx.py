from __future__ import annotations

import argparse
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a tiny MNIST CNN ONNX model for demo usage.")
    parser.add_argument("--output", default="models/generated/mnist_tiny_cnn.onnx", help="Output ONNX path.")
    parser.add_argument("--opset", type=int, default=18, help="ONNX opset version.")
    return parser


def main(argv: list[str] | None = None) -> int:
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

    class TinyMNISTCNN(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.conv1 = nn.Conv2d(1, 4, kernel_size=3)
            self.conv2 = nn.Conv2d(4, 8, kernel_size=3)
            self.pool = nn.MaxPool2d(2)
            self.act = nn.ReLU()
            self.fc1 = nn.Linear(8 * 5 * 5, 16)
            self.fc2 = nn.Linear(16, 10)

        def forward(self, x):
            x = self.pool(self.act(self.conv1(x)))
            x = self.pool(self.act(self.conv2(x)))
            x = x.flatten(1)
            x = self.act(self.fc1(x))
            return self.fc2(x)

    model = TinyMNISTCNN().eval()
    sample = torch.randn(1, 1, 28, 28)
    try:
        torch.onnx.export(
            model,
            sample,
            str(output_path),
            export_params=True,
            input_names=["input_nchw"],
            output_names=["logits"],
            opset_version=args.opset,
            dynamic_axes={"input_nchw": {0: "batch"}, "logits": {0: "batch"}},
        )
    except Exception as exc:  # pragma: no cover - environment dependent
        print(f"[skip] ONNX export failed in this environment: {exc}")
        return 0
    print(f"[ok] wrote {output_path}")
    print("[note] Model is exported in PyTorch default NCHW. Layout cleanup/conversion may be needed for some hls4ml flows.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
