from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from ..core.errors import build_error, error_result
from ..tools.report_parser import parse_csynth_report_file
from .senior_agent_adapter import SeniorVivadoBridge


MOCK_REPORT = """== Utilization Estimates
Latency (cycles): min = 45, max = 45
Interval (cycles): min = 1, max = 1
BRAM_18K = 0
DSP48E = 32
FF = 2100
LUT = 3500
Timing (ns): Target = 5.00, Estimated = 4.30
"""

MOCK_REPORT_BY_TOP = {
    "dense_16x32": "dense_latency_csynth.rpt",
    "matmul_16x16_resource": "matmul_resource_csynth.rpt",
    "mnist_mlp_demo": "mnist_mlp_csynth.rpt",
    "mnist_tiny_cnn": "mnist_tiny_cnn_csynth.rpt",
    "mnist_qkeras_cnn": "qkeras_cnn_resource_csynth.rpt",
}


class VivadoHLSAdapter:
    def __init__(self, mock_mode: bool = True, vivado_hls_path: str | None = None):
        self.mock_mode = mock_mode
        self.vivado_hls_path = vivado_hls_path

    def _bridge(self, work_dir: str) -> SeniorVivadoBridge:
        return SeniorVivadoBridge(self.vivado_hls_path, work_dir)

    def _binary_available(self) -> bool:
        return bool(self.vivado_hls_path and Path(self.vivado_hls_path).exists()) or shutil.which("vivado_hls") is not None or shutil.which("vivado_hls.bat") is not None

    def create_project(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hls_project_dir = Path(arguments["hls_project_dir"])
        work_dir = Path(arguments["work_dir"])
        work_dir.mkdir(parents=True, exist_ok=True)
        bridge = self._bridge(str(work_dir))
        top_function = arguments.get("top_function")
        firmware_dir = hls_project_dir / "firmware"
        tb_data_dir = hls_project_dir / "tb_data"

        # hls4ml layout: use firmware/<top>.cpp as design and copy firmware contents
        # into work_dir root so relative includes like nnet_utils/* resolve in Vivado.
        if firmware_dir.exists() and firmware_dir.is_dir():
            for child in firmware_dir.iterdir():
                destination = work_dir / child.name
                if child.is_dir():
                    shutil.copytree(child, destination, dirs_exist_ok=True)
                else:
                    shutil.copy2(child, destination)
            if tb_data_dir.exists() and tb_data_dir.is_dir():
                shutil.copytree(tb_data_dir, work_dir / "tb_data", dirs_exist_ok=True)
            candidate_files: list[Path] = []
            if top_function:
                candidate_files.append(work_dir / f"{top_function}.cpp")
            candidate_files.extend(sorted(work_dir.glob("*.cpp")))
            copied_code = next((path for path in candidate_files if path.exists() and not path.name.endswith("_test.cpp")), None)
            if copied_code is None:
                return error_result(
                    build_error(
                        "VivadoSynthesisError",
                        "No firmware C++ design file found in hls4ml project.",
                        recoverable=True,
                        source="vivado.create_project",
                    )
                )
            if not top_function:
                detected_top = bridge.extract_top_function(copied_code.read_text(encoding="utf-8", errors="ignore"))
                top_function = detected_top or copied_code.stem
            tcl_path = bridge.create_project_tcl(
                project_dir=str(work_dir),
                project_name=Path(arguments.get("work_dir", work_dir)).name,
                top_function=top_function,
                code_file=str(copied_code),
                testbench_file=None,
                target_device=arguments.get("part", "xc7z020clg400-1"),
                clock_period=str(arguments.get("clock_period", 5)),
            )
            return {"status": "success", "tcl_path": str(tcl_path), "work_dir": str(work_dir), "top_function": top_function}

        files = bridge.discover_design_files(str(hls_project_dir))
        code_file = files["code_file"]
        if not code_file:
            return error_result(
                build_error(
                    "VivadoSynthesisError",
                    "No C++ design file found in hls_project_dir.",
                    recoverable=True,
                    source="vivado.create_project",
                )
            )
        copied_code = work_dir / Path(code_file).name
        shutil.copy2(code_file, copied_code)
        copied_tb = None
        if files["testbench_file"]:
            copied_tb = work_dir / Path(files["testbench_file"]).name
            shutil.copy2(files["testbench_file"], copied_tb)
        if files["header_file"]:
            shutil.copy2(files["header_file"], work_dir / Path(files["header_file"]).name)
        detected_top = bridge.extract_top_function(Path(code_file).read_text(encoding="utf-8", errors="ignore"))
        if not top_function:
            top_function = detected_top or hls_project_dir.name
        tcl_path = bridge.create_project_tcl(
            project_dir=str(work_dir),
            project_name=Path(arguments.get("work_dir", work_dir)).name,
            top_function=top_function,
            code_file=str(copied_code),
            testbench_file=str(copied_tb) if copied_tb else None,
            target_device=arguments.get("part", "xc7z020clg400-1"),
            clock_period=str(arguments.get("clock_period", 5)),
        )
        return {"status": "success", "tcl_path": str(tcl_path), "work_dir": str(work_dir), "top_function": top_function}

    def run_csim(self, arguments: dict[str, Any]) -> dict[str, Any]:
        work_dir = Path(arguments["work_dir"])
        log_path = work_dir / "csim.log"
        if self.mock_mode:
            log_path.write_text("INFO: [SIM] CSim done with 0 errors.\n", encoding="utf-8")
            return {"status": "success", "log_path": str(log_path)}
        if not self._binary_available():
            return error_result(
                build_error(
                    "VivadoNotFoundError",
                    "vivado_hls command not found.",
                    recoverable=True,
                    source="vivado.run_csim",
                    suggested_action="Keep generated HLS project and skip synthesis.",
                    details={"command": "vivado_hls"},
                ),
                status="skipped",
            )
        return error_result(
            build_error(
                "VivadoSynthesisError",
                "Real csim execution is not enabled in this lightweight adapter.",
                recoverable=True,
                source="vivado.run_csim",
            )
        )

    def run_csynth(self, arguments: dict[str, Any]) -> dict[str, Any]:
        work_dir = Path(arguments["work_dir"])
        top_function = arguments.get("top_function") or "myproject"
        log_path = work_dir / "csynth.log"
        report_path = work_dir / "solution1" / "syn" / "report" / f"{top_function}_csynth.rpt"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        if self.mock_mode:
            if top_function in {"tiny_residual_block", "resnet18_boundary_demo"}:
                return error_result(
                    build_error(
                        "UnsupportedOperatorError",
                        "Boundary demo selected: skip full synthesis and emit boundary/unsupported report.",
                        recoverable=True,
                        source="vivado.run_csynth",
                        suggested_action="Use tiny CNN or subgraph synthesis for MVP demos.",
                    ),
                    status="skipped",
                )
            log_path.write_text("INFO: [HLS] Starting synthesis...\nINFO: [HLS] Finished generating all RTL models.\n", encoding="utf-8")
            fixture_name = MOCK_REPORT_BY_TOP.get(top_function)
            if fixture_name:
                fixture_path = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "reports" / fixture_name
                if fixture_path.exists():
                    report_path.write_text(fixture_path.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
                else:
                    report_path.write_text(MOCK_REPORT, encoding="utf-8")
            else:
                report_path.write_text(MOCK_REPORT, encoding="utf-8")
            return {"status": "success", "log_path": str(log_path), "report_path": str(report_path)}
        if not self._binary_available():
            return error_result(
                build_error(
                    "VivadoNotFoundError",
                    "vivado_hls command not found.",
                    recoverable=True,
                    source="vivado.run_csynth",
                    suggested_action="Keep generated HLS project and skip synthesis.",
                    details={"command": "vivado_hls"},
                ),
                status="skipped",
            )
        tcl_path = arguments["tcl_path"]
        code_files = sorted(work_dir.glob("*.cpp"))
        code_file = next((path for path in code_files if path.name != "testbench.cpp"), None)
        if code_file is None:
            return error_result(
                build_error(
                    "VivadoSynthesisError",
                    "No design cpp file found for real synthesis run.",
                    recoverable=True,
                    source="vivado.run_csynth",
                )
            )
        testbench_file = work_dir / "testbench.cpp"
        bridge = self._bridge(str(work_dir))
        result = bridge.run_with_existing_tcl(
            tcl_file_path=tcl_path,
            design_dir=str(work_dir),
            code_text=code_file.read_text(encoding="utf-8", errors="ignore"),
            testbench_text=testbench_file.read_text(encoding="utf-8", errors="ignore") if testbench_file.exists() else None,
            project_name=top_function,
        )
        synthesis = result.get("synthesis", {})
        real_report = bridge.locate_report(result.get("project_dir") or work_dir, top_function=top_function)
        log_path = synthesis.get("log_path")
        log_errors: list[str] = []
        if log_path and Path(log_path).exists():
            log_text = Path(log_path).read_text(encoding="utf-8", errors="ignore")
            for line in log_text.splitlines():
                lowered = line.lower()
                if re.search(r"\berror\b", lowered) or "fatal error" in lowered or "c preprocessor failed" in lowered:
                    log_errors.append(line.strip())
            if synthesis.get("status") == "success" and log_errors:
                return error_result(
                    build_error(
                        "VivadoSynthesisError",
                        "Vivado HLS log contains synthesis errors.",
                        recoverable=True,
                        source="vivado.run_csynth",
                        suggested_action="Inspect csynth.log and fix missing headers/includes or top function mismatch.",
                        details={"log_path": log_path, "errors": log_errors[:20]},
                    )
                )
        return {
            "status": "success" if synthesis.get("status") == "success" else synthesis.get("status", "error"),
            "log_path": log_path,
            "report_path": real_report,
            "project_dir": result.get("project_dir"),
        }

    def parse_report(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return parse_csynth_report_file(arguments["report_path"])

    def parse_log(self, arguments: dict[str, Any]) -> dict[str, Any]:
        path = Path(arguments["log_path"])
        if not path.exists():
            return {"status": "success", "errors": ["Log file not found."], "warnings": [], "summary": "Log file not found."}
        text = path.read_text(encoding="utf-8", errors="ignore")
        errors = [line.strip() for line in text.splitlines() if "ERROR" in line.upper()]
        warnings = [line.strip() for line in text.splitlines() if "WARNING" in line.upper()]
        summary = "Synthesis completed with warnings." if warnings and not errors else "Synthesis completed successfully." if not errors else "Synthesis failed."
        return {"status": "success", "errors": errors, "warnings": warnings, "summary": summary}
