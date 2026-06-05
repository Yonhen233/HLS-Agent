from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

import sys

sys.path.insert(0, str(SRC))

from dl_op_to_hls.tools.report_parser import parse_csynth_report_file  # noqa: E402


DEFAULT_VIVADO = Path("D:/Xilinx/Vivado/2018.3/bin/vivado_hls.bat")
DEFAULT_VITIS = Path("D:/vitis25.2.1/2025.2.1/Vitis/bin/vitis-run.bat")
DEFAULT_VITIS_2022 = Path("D:/Vitis2022.2/Vitis_HLS/2022.2/bin/vitis_hls.bat")


@dataclass
class Variant:
    name: str
    dir_name: str
    source_work_dir: Path
    toolchain: str
    clock_period: float
    clock_uncertainty: str | None = None
    config_dataflow: list[str] = field(default_factory=list)
    stream_depth: int | None = None
    migrate_pragmas: bool = False
    notes: str = ""


def copy_design_work(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    excluded_names = {
        "vivado_hls",
        "solution1",
        ".autopilot",
        ".crashReporter",
        "csynth.log",
        "csynth_stage.tcl",
        "run_vivado_hls.tcl",
        "summary.json",
    }
    for child in source.iterdir():
        if child.name in excluded_names:
            continue
        target = destination / child.name
        if child.is_dir():
            shutil.copytree(child, target, ignore=shutil.ignore_patterns("vivado_hls", "solution1", ".autopilot"))
        else:
            shutil.copy2(child, target)


def migrate_legacy_pragmas(work_dir: Path) -> list[str]:
    changed: list[str] = []
    for path in work_dir.rglob("*.h"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        new_text = text.replace(
            "#pragma HLS RESOURCE variable=weights core=ROM_nP_BRAM",
            "#pragma HLS bind_storage variable=weights type=rom_np impl=bram",
        )
        # There is no one-to-one source pragma replacement for all hls4ml ALLOCATION
        # operation-limit pragmas because Vitis bind_op targets named variables.
        # Keep them in place so the experiment measures the storage migration only.
        if new_text != text:
            path.write_text(new_text, encoding="utf-8")
            changed.append(str(path))
    return changed


def write_tcl(variant: Variant, work_dir: Path, top_function: str) -> Path:
    lines = [
        "# Auto-generated fair toolchain experiment TCL",
        "open_project -reset vivado_hls",
        'add_files -cflags "-std=c++0x" myproject.cpp',
        f"set_top {top_function}",
        'open_solution -reset "solution1"',
        "set_part {xc7z020clg400-1}",
        f"create_clock -period {variant.clock_period:g} -name default",
    ]
    if variant.clock_uncertainty:
        lines.append(f"set_clock_uncertainty {variant.clock_uncertainty}")
    lines.extend(variant.config_dataflow)
    if variant.stream_depth is not None:
        for name in ["layer2_out", "layer3_out", "layer4_out", "layer5_out", "layer6_out", "layer7_out", "layer9_out", "layer10_out"]:
            lines.append(f"set_directive_stream -type fifo -depth {variant.stream_depth} {top_function} {name}")
    lines.extend(
        [
            'puts "Starting synthesis..."',
            "csynth_design",
            'puts "Synthesis completed"',
            "exit",
        ]
    )
    tcl_path = work_dir / "run_fair_hls.tcl"
    tcl_path.write_text("\n".join(lines) + "\n", encoding="ascii")
    return tcl_path


def run_tool(variant: Variant, work_dir: Path, tcl_path: Path, vivado: Path, vitis: Path, timeout: int) -> dict[str, Any]:
    log_path = work_dir / "csynth.log"
    if variant.toolchain == "vivado_hls":
        command = [str(vivado), "-f", tcl_path.name]
    elif variant.toolchain == "vitis_hls":
        if "vitis-run" in vitis.name.lower():
            command = [str(vitis), "--mode", "hls", "--tcl", "--input_file", tcl_path.name]
        else:
            command = [str(vitis), "-f", tcl_path.name]
    else:
        raise ValueError(f"Unknown toolchain: {variant.toolchain}")
    started = time.time()
    completed = subprocess.run(
        command,
        cwd=work_dir,
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=(os.name == "nt"),
    )
    combined = (completed.stdout or "") + ("\n=== STDERR ===\n" + (completed.stderr or "") if completed.stderr else "")
    log_path.write_text(combined, encoding="utf-8", errors="replace")
    return {
        "returncode": completed.returncode,
        "duration_seconds": round(time.time() - started, 3),
        "command": " ".join(command),
        "log_path": str(log_path),
    }


def locate_report(work_dir: Path, top_function: str) -> Path | None:
    candidates = list(work_dir.rglob(f"{top_function}_csynth.rpt"))
    if not candidates:
        candidates = list(work_dir.rglob("*_csynth.rpt"))
    return candidates[0] if candidates else None


def summarize_log(log_path: Path | None) -> dict[str, Any]:
    if not log_path or not log_path.exists():
        return {"warnings": 0, "errors": 0, "fifo_lines": 0, "dataflow_lines": 0, "interesting": []}
    text = log_path.read_text(encoding="utf-8", errors="ignore")
    interesting = []
    for line in text.splitlines():
        lowered = line.lower()
        if any(token in lowered for token in ["warning", "error", "fifo", "dataflow", "deprecated", "ignored", "uncertainty"]):
            interesting.append(line.strip())
    return {
        "warnings": sum(1 for line in text.splitlines() if "WARNING" in line.upper()),
        "errors": sum(1 for line in text.splitlines() if re.search(r"\bERROR\b", line.upper())),
        "fifo_lines": sum(1 for line in text.splitlines() if "FIFO" in line.upper()),
        "dataflow_lines": sum(1 for line in text.splitlines() if "DATAFLOW" in line.upper()),
        "interesting": interesting[:80],
    }


def run_variant(variant: Variant, output_root: Path, top_function: str, vivado: Path, vitis: Path, timeout: int, force: bool) -> dict[str, Any]:
    work_dir = output_root / variant.dir_name
    result_path = work_dir / "experiment_result.json"
    if not force and result_path.exists():
        return json.loads(result_path.read_text(encoding="utf-8"))

    report_path = locate_report(work_dir, top_function) if work_dir.exists() else None
    if force or not report_path:
        copy_design_work(variant.source_work_dir, work_dir)
        changed = migrate_legacy_pragmas(work_dir) if variant.migrate_pragmas else []
        tcl_path = write_tcl(variant, work_dir, top_function)
        try:
            run_result = run_tool(variant, work_dir, tcl_path, vivado, vitis, timeout)
        except subprocess.TimeoutExpired:
            log_path = work_dir / "csynth.log"
            log_path.write_text(f"ERROR: timeout after {timeout} seconds\n", encoding="utf-8")
            run_result = {"returncode": -1, "duration_seconds": timeout, "command": "", "log_path": str(log_path)}
        report_path = locate_report(work_dir, top_function)
    else:
        changed = []
        run_result = {"returncode": 0, "duration_seconds": 0, "command": "cached", "log_path": str(work_dir / "csynth.log")}

    metrics = parse_csynth_report_file(str(report_path)) if report_path else {"status": "report_missing"}
    log_summary = summarize_log(Path(run_result["log_path"]) if run_result.get("log_path") else None)
    result = {
        "name": variant.name,
        "dir_name": variant.dir_name,
        "toolchain": variant.toolchain,
        "source_work_dir": str(variant.source_work_dir),
        "work_dir": str(work_dir),
        "clock_period": variant.clock_period,
        "clock_uncertainty": variant.clock_uncertainty,
        "config_dataflow": variant.config_dataflow,
        "stream_depth": variant.stream_depth,
        "migrate_pragmas": variant.migrate_pragmas,
        "changed_files": changed,
        "notes": variant.notes,
        "run": run_result,
        "report_path": str(report_path) if report_path else None,
        "metrics": metrics,
        "log_summary": log_summary,
    }
    result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def _resource_score(metrics: dict[str, Any]) -> int | None:
    resources = metrics.get("resources")
    if not resources:
        return None
    values = {
        key: int(resources.get(key) or 0)
        for key in ("bram", "dsp", "ff", "lut")
    }
    # A simple scalar score for ranking only. Keep raw resources in the summary
    # because BRAM/DSP/LUT/FF trade-offs are objective dependent.
    return values["ff"] + values["lut"] + values["bram"] * 1000 + values["dsp"] * 1000


def summarize_best_by_objective(results: list[dict[str, Any]]) -> dict[str, Any]:
    successful = [item for item in results if item.get("metrics", {}).get("status") == "success"]

    def latency_key(item: dict[str, Any]) -> tuple[int, str]:
        latency = item.get("metrics", {}).get("latency") or {}
        return int(latency.get("max_cycles") or 10**12), item["name"]

    def resource_key(item: dict[str, Any]) -> tuple[int, str]:
        score = _resource_score(item.get("metrics", {}))
        return int(score if score is not None else 10**12), item["name"]

    def pack(item: dict[str, Any] | None) -> dict[str, Any] | None:
        if not item:
            return None
        metrics = item.get("metrics", {})
        return {
            "name": item["name"],
            "toolchain": item["toolchain"],
            "latency": metrics.get("latency"),
            "resources": metrics.get("resources"),
            "timing": metrics.get("timing"),
            "resource_score": _resource_score(metrics),
            "notes": item.get("notes", ""),
        }

    vitis_successful = [item for item in successful if item.get("toolchain") == "vitis_hls"]
    return {
        "overall_lowest_latency": pack(min(successful, key=latency_key) if successful else None),
        "overall_lowest_resource_score": pack(min(successful, key=resource_key) if successful else None),
        "vitis_lowest_latency": pack(min(vitis_successful, key=latency_key) if vitis_successful else None),
        "vitis_lowest_resource_score": pack(min(vitis_successful, key=resource_key) if vitis_successful else None),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", default="runs/vfe_qonnx_0605")
    parser.add_argument("--vivado-backend-work", default="runs/mnist_qonnx_cnn_bc625576_02/vivado_hls")
    parser.add_argument("--vitis-backend-work", default="runs/mnist_qonnx_cnn_bc625576_06/vivado_hls")
    parser.add_argument("--vivado-hls", default=str(DEFAULT_VIVADO))
    parser.add_argument("--vitis-run", default=str(DEFAULT_VITIS if DEFAULT_VITIS.exists() else DEFAULT_VITIS_2022))
    parser.add_argument("--clock-period", type=float, default=10.0)
    parser.add_argument("--top-function", default="myproject")
    parser.add_argument("--timeout", type=int, default=1200)
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--include",
        nargs="*",
        default=None,
        help="Optional variant names or short directory names to run. Omit to run all variants.",
    )
    args = parser.parse_args()

    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    vivado_backend_work = Path(args.vivado_backend_work)
    vitis_backend_work = Path(args.vitis_backend_work)
    variants = [
        Variant(
            name="g1_vivado_backend_same_source_vivado_tool_u1p25",
            dir_name="g1_vivado_vivado",
            source_work_dir=vivado_backend_work,
            toolchain="vivado_hls",
            clock_period=args.clock_period,
            clock_uncertainty="1.25",
            notes="Same sanitized Vivado-backend HLS source, compiled by Vivado HLS with explicit 1.25ns uncertainty.",
        ),
        Variant(
            name="g1_vivado_backend_same_source_vitis_tool_u1p25",
            dir_name="g1_vivado_vitis",
            source_work_dir=vivado_backend_work,
            toolchain="vitis_hls",
            clock_period=args.clock_period,
            clock_uncertainty="1.25",
            notes="Same sanitized Vivado-backend HLS source, compiled by Vitis HLS with explicit 1.25ns uncertainty.",
        ),
        Variant(
            name="g2_vitis_backend_vitis_tool_u1p25",
            dir_name="g2_vitis_base",
            source_work_dir=vitis_backend_work,
            toolchain="vitis_hls",
            clock_period=args.clock_period,
            clock_uncertainty="1.25",
            notes="Vitis-backend source with only clock uncertainty normalized to Vivado default.",
        ),
        Variant(
            name="g2_vitis_backend_vitis_tool_u1p25_fifo_sizing_off",
            dir_name="g2_vitis_fifo2",
            source_work_dir=vitis_backend_work,
            toolchain="vitis_hls",
            clock_period=args.clock_period,
            clock_uncertainty="1.25",
            config_dataflow=["config_dataflow -disable_fifo_sizing_opt -fifo_depth 2 -start_fifo_depth 2 -scalar_fifo_depth 2 -task_level_fifo_depth 2"],
            notes="Vitis backend with normalized uncertainty and disabled FIFO sizing optimization.",
        ),
        Variant(
            name="g3_vitis_backend_vitis_tool_u1p25_bind_storage",
            dir_name="g3_vitis_bind",
            source_work_dir=vitis_backend_work,
            toolchain="vitis_hls",
            clock_period=args.clock_period,
            clock_uncertainty="1.25",
            migrate_pragmas=True,
            notes="Partial pragma migration: RESOURCE weight storage pragmas converted to bind_storage.",
        ),
        Variant(
            name="g4_vitis_backend_vitis_tool_tuned_combo",
            dir_name="g4_vitis_tuned",
            source_work_dir=vitis_backend_work,
            toolchain="vitis_hls",
            clock_period=args.clock_period,
            clock_uncertainty="1.25",
            config_dataflow=["config_dataflow -disable_fifo_sizing_opt -fifo_depth 2 -start_fifo_depth 2 -scalar_fifo_depth 2 -task_level_fifo_depth 2"],
            stream_depth=2,
            migrate_pragmas=True,
            notes="Vitis tuned combo: normalized uncertainty, FIFO sizing off, explicit stream depths, and bind_storage migration.",
        ),
    ]
    if args.include:
        requested = set(args.include)
        variants = [
            variant
            for variant in variants
            if variant.name in requested or variant.dir_name in requested
        ]
        if not variants:
            raise SystemExit(f"No variants matched --include {sorted(requested)}")
    results = []
    for variant in variants:
        print(f"Running {variant.name} ...", flush=True)
        result = run_variant(
            variant=variant,
            output_root=output_root,
            top_function=args.top_function,
            vivado=Path(args.vivado_hls),
            vitis=Path(args.vitis_run),
            timeout=args.timeout,
            force=args.force,
        )
        results.append(result)
        metrics = result.get("metrics", {})
        print(
            json.dumps(
                {
                    "name": result["name"],
                    "status": metrics.get("status"),
                    "latency": metrics.get("latency"),
                    "resources": metrics.get("resources"),
                    "timing": metrics.get("timing"),
                    "returncode": result["run"].get("returncode"),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    summary = {
        "output_root": str(output_root),
        "best_by_objective": summarize_best_by_objective(results),
        "variants": results,
    }
    (output_root / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
