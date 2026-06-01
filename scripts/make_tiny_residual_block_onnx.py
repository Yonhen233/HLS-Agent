from __future__ import annotations

import argparse
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a tiny residual block ONNX model for boundary demo usage.")
    parser.add_argument("--output", default="models/generated/tiny_residual_block.onnx", help="Output ONNX path.")
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

    class TinyResidual(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.conv1 = nn.Conv2d(8, 8, kernel_size=3, padding=1)
            self.bn1 = nn.BatchNorm2d(8)
            self.conv2 = nn.Conv2d(8, 8, kernel_size=3, padding=1)
            self.bn2 = nn.BatchNorm2d(8)
            self.act = nn.ReLU()

        def forward(self, x):
            skip = x
            x = self.act(self.bn1(self.conv1(x)))
            x = self.bn2(self.conv2(x))
            x = x + skip
            return self.act(x)

    model = TinyResidual().eval()
    sample = torch.randn(1, 8, 16, 16)
    try:
        torch.onnx.export(
            model,
            sample,
            str(output_path),
            export_params=True,
            input_names=["input_nchw"],
            output_names=["output_nchw"],
            opset_version=args.opset,
            dynamic_axes={"input_nchw": {0: "batch"}, "output_nchw": {0: "batch"}},
        )
    except Exception as exc:  # pragma: no cover - environment dependent
        print(f"[skip] ONNX export failed in this environment: {exc}")
        return 0
    print(f"[ok] wrote {output_path}")
    print("[note] This model is for boundary handling demos. hls4ml support is intentionally not guaranteed.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
