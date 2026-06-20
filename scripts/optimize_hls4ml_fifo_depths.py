from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from dl_op_to_hls.adapters.hls4ml_adapter import HLS4MLAdapter
from dl_op_to_hls.adapters.vivado_hls_adapter import VivadoHLSAdapter


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Profile and optimize hls4ml Vivado io_stream FIFO depths using real CSim/cosim occupancy."
    )
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--config-path", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--input-path", required=True)
    parser.add_argument("--labels-path")
    parser.add_argument("--samples", type=int, default=1)
    parser.add_argument("--profiling-depth", type=int, default=2048)
    parser.add_argument(
        "--max-depth-path",
        help="Reuse a max_depth.json emitted by a prior successful profiling run instead of rerunning RTL cosim.",
    )
    parser.add_argument("--vivado-bin", default="D:/Xilinx/Vivado/2018.3/bin")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if int(args.profiling_depth) <= 0:
        raise SystemExit("--profiling-depth must be positive")

    try:
        import onnx
        from hls4ml.model.optimizer import get_optimizer
    except Exception as exc:  # pragma: no cover - dependency boundary
        print(json.dumps({"status": "error", "message": f"FIFO optimization dependencies unavailable: {exc}"}))
        return 2

    adapter = HLS4MLAdapter(mock_mode=False)
    config_payload = adapter._parse_onnx_config(args.config_path)
    hls_config = dict(config_payload.get("hls_config") or {})
    # Agent configs keep IOType at payload level, while the layer-list writer
    # accepts it as an internal HLSConfig extension.
    io_type = config_payload.get("io_type") or config_payload.get("IOType")
    if io_type:
        hls_config["__io_type"] = io_type
    backend = adapter._resolve_backend(str(config_payload.get("backend", "Vivado")))
    if backend != "Vivado":
        print(json.dumps({"status": "error", "message": "FIFO profiling script currently supports the Vivado backend only."}))
        return 3

    output_dir = Path(args.output_dir)
    model = onnx.load(args.model_path)
    adapter_info = adapter._write_layer_list_hls_project(
        model=model,
        output_dir=output_dir,
        project_name=str(config_payload.get("project_name") or "myproject"),
        backend=backend,
        hls_config=hls_config,
        part=str(config_payload.get("part") or "xc7z020clg400-1"),
        clock_period=config_payload.get("clock_period") or 5,
        return_model_graph=True,
    )
    model_graph = adapter_info.pop("_model_graph")
    original_pragmas = {
        name: variable.pragma
        for name, variable in model_graph.output_vars.items()
        if variable.pragma is not None
    }
    reference = adapter._write_reference_data_for_args(
        args.model_path,
        output_dir,
        {
            "input_path": args.input_path,
            "labels_path": args.labels_path,
            "num_samples": int(args.samples),
        },
    )
    firmware_dir = output_dir / "firmware"
    source_sanitizer = VivadoHLSAdapter(mock_mode=False)
    sanitized_files = source_sanitizer._sanitize_hls4ml_sources_for_legacy_vivado(
        firmware_dir,
        firmware_dir / "myproject.cpp",
    )
    vivado_bin = Path(args.vivado_bin)
    if not vivado_bin.exists():
        print(json.dumps({"status": "error", "message": f"Vivado bin directory not found: {vivado_bin}"}))
        return 4
    os.environ["PATH"] = str(vivado_bin) + os.pathsep + os.environ.get("PATH", "")

    max_depth_path = Path(args.max_depth_path) if args.max_depth_path else output_dir / "max_depth.json"
    if args.max_depth_path:
        max_depths = json.loads(max_depth_path.read_text(encoding="utf-8"))
        for name, variable in model_graph.output_vars.items():
            if variable.pragma is None:
                continue
            matched = [entry for entry in max_depths if variable.name in str(entry.get("name", ""))]
            if matched:
                variable.pragma = (variable.pragma[0], int(matched[0]["max"]) + 1)
            elif name in original_pragmas:
                variable.pragma = original_pragmas[name]
        model_graph.write()
    else:
        optimizer = get_optimizer("vivado:fifo_depth_optimization")
        optimizer.configure(profiling_fifo_depth=int(args.profiling_depth))
        # hls4ml's profiler calls model.write() immediately before invoking the
        # legacy compiler. Preserve the sanitized 2018.3-compatible sources for
        # that build, then sanitize the optimized writer output once more below.
        original_write = model_graph.write
        model_graph.write = lambda: None
        try:
            model_graph.apply_flow("vivado:fifo_depth_optimization")
        finally:
            model_graph.write = original_write
        max_depths = json.loads(max_depth_path.read_text(encoding="utf-8"))
        for name, variable in model_graph.output_vars.items():
            if variable.pragma and int(variable.pragma[1]) == int(args.profiling_depth) and name in original_pragmas:
                variable.pragma = original_pragmas[name]
        model_graph.write()
    sanitized_files.extend(
        source_sanitizer._sanitize_hls4ml_sources_for_legacy_vivado(
            firmware_dir,
            firmware_dir / "myproject.cpp",
        )
    )
    depths_path = output_dir / "fifo_depths.json"
    depths_path.write_text(
        json.dumps(
            {
                "source_max_depth_path": str(max_depth_path),
                "depths": {
                    name: int(variable.pragma[1])
                    for name, variable in model_graph.output_vars.items()
                    if variable.pragma is not None
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "success",
                "output_dir": str(output_dir),
                "fifo_depths_path": str(depths_path),
                "reference_data": reference,
                "adapter_info": adapter_info,
                "sanitized_files": sanitized_files,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
