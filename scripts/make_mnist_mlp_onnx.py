from __future__ import annotations

import argparse
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a tiny MNIST MLP ONNX model for demo usage.")
    parser.add_argument("--output", default="models/generated/mnist_mlp.onnx", help="Output ONNX path.")
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

    class MnistMLP(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.fc1 = nn.Linear(784, 64)
            self.fc2 = nn.Linear(64, 32)
            self.fc3 = nn.Linear(32, 10)
            self.act = nn.ReLU()

        def forward(self, x):
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
