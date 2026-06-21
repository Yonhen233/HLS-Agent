from __future__ import annotations

import argparse
import json
from pathlib import Path

from dl_op_to_hls.tools.cifar_architecture_screen import (
    CifarArchitectureSpec,
    default_candidates,
    screen_many,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Screen CIFAR-10 CNN candidates before expensive HLS synthesis.")
    parser.add_argument("--output", default="runs/cifar10_architecture_screen.json")
    parser.add_argument("--margin", type=float, default=0.90, help="Resource screening utilization margin.")
    parser.add_argument(
        "--candidate",
        action="append",
        default=[],
        metavar="NAME:C1,C2,C3:S1,S2,S3",
        help="Optional custom candidate; stages must have one or two convolutions.",
    )
    return parser


def _parse_candidate(raw: str) -> CifarArchitectureSpec:
    try:
        name, channel_text, stage_text = raw.split(":")
        channels = tuple(int(value) for value in channel_text.split(","))
        convs = tuple(int(value) for value in stage_text.split(","))
    except ValueError as error:
        raise argparse.ArgumentTypeError("candidate must be NAME:C1,C2,C3:S1,S2,S3") from error
    return CifarArchitectureSpec(name=name, channels=channels, convs_per_stage=convs)


def main() -> int:
    args = build_parser().parse_args()
    candidates = [_parse_candidate(raw) for raw in args.candidate] if args.candidate else default_candidates()
    results = screen_many(candidates, conservative_margin=args.margin)
    payload = {
        "status": "success",
        "purpose": "Static pre-synthesis ranking only; real CSim and Vivado HLS remain mandatory.",
        "margin": args.margin,
        "results": [result.to_dict() for result in results],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    for result in results:
        print(
            f"{result.spec.name}: {result.decision}; "
            f"MACs={result.macs:,}; LUT~{result.estimated_resources['lut']}; "
            f"BRAM~{result.estimated_resources['bram']}"
        )
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
