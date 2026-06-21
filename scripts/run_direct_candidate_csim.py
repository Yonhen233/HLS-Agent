"""Run only real Vivado HLS CSim for a standalone candidate project.

Used as a cheap functional gate before letting an LLM candidate consume a long
csynth run.  The candidate directory must already contain its testbench and
golden reference data.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from dl_op_to_hls.adapters.vivado_hls_adapter import VivadoHLSAdapter


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run real CSim for a standalone HLS candidate.")
    parser.add_argument("--candidate-dir", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--top-function", required=True)
    parser.add_argument("--part", default="xc7z020clg400-1")
    parser.add_argument("--clock-period", type=float, default=15.0)
    parser.add_argument("--vivado-hls-path", default="D:/Xilinx/Vivado/2018.3/bin/vivado_hls.bat")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    os.environ["DL_OP_TO_HLS_VIVADO_TIMEOUT_SECONDS"] = str(args.timeout_seconds)
    adapter = VivadoHLSAdapter(mock_mode=False, vivado_hls_path=args.vivado_hls_path)
    create = adapter.create_project(
        {
            "hls_project_dir": str(Path(args.candidate_dir)),
            "top_function": args.top_function,
            "part": args.part,
            "clock_period": args.clock_period,
            "work_dir": str(Path(args.run_dir)),
        }
    )
    print(json.dumps({"create": create}, indent=2), flush=True)
    if create.get("status") != "success":
        return 2
    result = adapter.run_csim(
        {
            "work_dir": create["work_dir"],
            "tcl_path": create["tcl_path"],
            "top_function": args.top_function,
        }
    )
    print(json.dumps({"result": result}, indent=2), flush=True)
    return 0 if result.get("status") == "success" else 3


if __name__ == "__main__":
    raise SystemExit(main())
