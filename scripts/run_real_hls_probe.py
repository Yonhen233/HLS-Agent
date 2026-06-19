from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Allow this diagnostic script to run from a clean shell without requiring an
# editable package install or a caller-provided PYTHONPATH.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from dl_op_to_hls.adapters.hls4ml_adapter import HLS4MLAdapter
from dl_op_to_hls.adapters.vivado_hls_adapter import VivadoHLSAdapter


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one real hls4ml -> Vivado HLS conversion, CSim, and optional synthesis probe."
    )
    parser.add_argument("--name", required=True, help="Probe directory name under runs/.")
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--input-path")
    parser.add_argument("--labels-path")
    parser.add_argument("--samples", type=int, default=2)
    parser.add_argument("--precision", default="fixed<16,6>")
    parser.add_argument(
        "--accumulator-precision",
        help="Optional hls4ml Conv/Dense accumulator precision, for example fixed<32,14>.",
    )
    parser.add_argument("--reuse-factor", type=int, default=64)
    parser.add_argument("--strategy", default="Resource")
    parser.add_argument(
        "--pipeline-style",
        choices=["auto", "dataflow", "pipeline"],
        help="Optional hls4ml Model.PipelineStyle override for resource/scheduling experiments.",
    )
    parser.add_argument("--io-type", choices=["io_parallel", "io_stream"], default="io_stream")
    parser.add_argument("--clock-period", type=float, default=15.0)
    parser.add_argument(
        "--array-partition-maximum-size",
        type=int,
        help="Explicit Vivado HLS auto array-partition limit for legacy large stream buffers.",
    )
    parser.add_argument("--part", default="xc7z020clg400-1")
    parser.add_argument("--vivado-hls-path", default="D:/Xilinx/Vivado/2018.3/bin/vivado_hls.bat")
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument(
        "--stage",
        choices=["csim", "csynth"],
        default="csynth",
        help="Run only real C simulation, or the full CSim plus C synthesis flow.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    os.environ["DL_OP_TO_HLS_VIVADO_TIMEOUT_SECONDS"] = str(args.timeout_seconds)
    root = Path("runs") / args.name
    root.mkdir(parents=True, exist_ok=True)
    reference_data = {
        "input_path": args.input_path,
        "labels_path": args.labels_path,
        "num_samples": args.samples,
    }

    hls4ml = HLS4MLAdapter(mock_mode=False)
    config_args = {
        "model_path": args.model_path,
        "frontend": "onnx",
        "backend": "Vivado",
        "part": args.part,
        "clock_period": args.clock_period,
        "precision": args.precision,
        "reuse_factor": args.reuse_factor,
        "strategy": args.strategy,
        "io_type": args.io_type,
        "output_dir": str(root),
    }
    if args.accumulator_precision:
        config_args["accumulator_precision"] = args.accumulator_precision
    if args.pipeline_style:
        config_args["model_overrides"] = {"PipelineStyle": args.pipeline_style}
    config = hls4ml.generate_config(config_args)
    print(json.dumps({"config": config}, indent=2), flush=True)
    if config.get("status") != "success":
        return 2

    converted = hls4ml.convert(
        {
            "model_path": args.model_path,
            "frontend": "onnx",
            "config_path": config["config_path"],
            "output_dir": str(root / "hls_project"),
            "reference_data": reference_data,
        }
    )
    print(json.dumps({"converted": converted}, indent=2), flush=True)
    if converted.get("status") != "success":
        return 3

    vivado = VivadoHLSAdapter(mock_mode=False, vivado_hls_path=args.vivado_hls_path)
    create = vivado.create_project(
        {
            "hls_project_dir": converted["hls_project_dir"],
            "top_function": converted["top_function"],
            "part": args.part,
            "clock_period": args.clock_period,
            "array_partition_maximum_size": args.array_partition_maximum_size,
            "work_dir": str(root / "vivado_hls"),
        }
    )
    print(json.dumps({"create": create}, indent=2), flush=True)
    if create.get("status") != "success":
        return 4

    run_args = {
        "work_dir": create["work_dir"],
        "tcl_path": create["tcl_path"],
        "top_function": create["top_function"],
    }
    result = vivado.run_csim(run_args) if args.stage == "csim" else vivado.run_csynth(run_args)
    print(json.dumps({"result": result}, indent=2), flush=True)
    if args.stage == "csynth" and result.get("report_path"):
        report = vivado.parse_report({"report_path": result["report_path"]})
        print(json.dumps({"report": report}, indent=2), flush=True)
    return 0 if result.get("status") == "success" else 5


if __name__ == "__main__":
    raise SystemExit(main())
