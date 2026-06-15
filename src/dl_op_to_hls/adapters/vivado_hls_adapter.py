from __future__ import annotations

import re
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from ..core.errors import build_error, error_result
from ..tools.functional_verification import parse_csim_verification
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
    "mnist_qonnx_cnn": "qkeras_cnn_resource_csynth.rpt",
    "mnist_qkeras_cnn": "qkeras_cnn_resource_csynth.rpt",
}


class VivadoHLSAdapter:
    def __init__(
        self,
        mock_mode: bool = True,
        vivado_hls_path: str | None = None,
        hls_toolchain: str = "vivado_hls",
        vitis_hls_path: str | None = None,
    ):
        self.mock_mode = mock_mode
        self.vivado_hls_path = vivado_hls_path
        self.hls_toolchain = self._normalize_toolchain(hls_toolchain)
        self.vitis_hls_path = vitis_hls_path

    def _bridge(self, work_dir: str) -> SeniorVivadoBridge:
        return SeniorVivadoBridge(self.vivado_hls_path, work_dir)

    def _normalize_toolchain(self, value: str | None) -> str:
        text = str(value or "vivado_hls").strip().lower().replace("-", "_")
        if text in {"vivado", "vivado_hls", "legacy_vivado"}:
            return "vivado_hls"
        if text in {"vitis", "vitis_hls", "vitis_run", "vitisrun", "modern_vitis"}:
            return "vitis_hls"
        return "vivado_hls"

    def _resolve_vitis_executable(self) -> str | None:
        candidates: list[Path] = []
        if self.vitis_hls_path:
            configured = Path(self.vitis_hls_path)
            if configured.is_file():
                candidates.append(configured)
            else:
                candidates.extend(
                    [
                        configured / "bin" / "vitis-run.bat",
                        configured / "bin" / "vitis_hls.bat",
                        configured / "Vitis" / "bin" / "vitis-run.bat",
                        configured / "Vitis_HLS" / "2022.2" / "bin" / "vitis_hls.bat",
                        configured / "2022.2" / "bin" / "vitis_hls.bat",
                        configured / "2025.2.1" / "Vitis" / "bin" / "vitis-run.bat",
                        configured / "2025.2" / "Vitis" / "bin" / "vitis-run.bat",
                    ]
                )
        candidates.extend(
            [
                Path("D:/Vitis2022.2/Vitis_HLS/2022.2/bin/vitis_hls.bat"),
                Path("D:/vitis25.2.1/2025.2.1/Vitis/bin/vitis-run.bat"),
                Path("D:/vitis25.2.1/2025.2/Vitis/bin/vitis-run.bat"),
            ]
        )
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)
        resolved = shutil.which("vitis-run") or shutil.which("vitis-run.bat")
        return resolved

    def _command_label(self) -> str:
        if self.hls_toolchain == "vitis_hls":
            executable = self._resolve_vitis_executable()
            return Path(executable).name if executable else "vitis_hls/vitis-run"
        return "vivado_hls"

    def _vitis_command(self, executable: str, tcl_path: str) -> list[str]:
        exe_name = Path(executable).name.lower()
        if "vitis-run" in exe_name:
            return [executable, "--mode", "hls", "--tcl", "--input_file", Path(tcl_path).name]
        return [executable, "-f", Path(tcl_path).name]

    def _binary_available(self) -> bool:
        if self.hls_toolchain == "vitis_hls":
            return self._resolve_vitis_executable() is not None
        return bool(self.vivado_hls_path and Path(self.vivado_hls_path).exists()) or shutil.which("vivado_hls") is not None or shutil.which("vivado_hls.bat") is not None

    def _run_vitis_with_existing_tcl(self, tcl_path: str, work_dir: Path, timeout_seconds: int | None = None) -> dict[str, Any]:
        executable = self._resolve_vitis_executable()
        log_path = work_dir / "csynth.log"
        if not executable:
            return {
                "project_dir": str(work_dir),
                "synthesis": {
                    "status": "error",
                    "errors": ["vitis-run command not found"],
                    "warnings": [],
                    "log_path": None,
                    "project_dir": str(work_dir),
                },
            }
        timeout = int(timeout_seconds or 900)
        started = time.time()
        command = self._vitis_command(executable, tcl_path)
        try:
            completed = subprocess.run(
                command,
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=(os.name == "nt"),
            )
            combined = (completed.stdout or "") + ("\n=== STDERR ===\n" + (completed.stderr or "") if completed.stderr else "")
            log_path.write_text(combined, encoding="utf-8")
            status = "success" if completed.returncode == 0 else "error"
            return {
                "project_dir": str(work_dir),
                "synthesis": {
                    "status": status,
                    "passed": completed.returncode == 0,
                    "errors": [] if completed.returncode == 0 else [f"Vitis HLS exited with return code {completed.returncode}"],
                    "warnings": [],
                    "log_path": str(log_path),
                    "project_dir": str(work_dir),
                    "duration_seconds": round(time.time() - started, 3),
                    "command": " ".join(command),
                    "toolchain": "vitis_hls",
                },
            }
        except subprocess.TimeoutExpired:
            log_path.write_text(f"ERROR: vitis-run csynth timed out after {timeout} seconds", encoding="utf-8")
            return {
                "project_dir": str(work_dir),
                "synthesis": {
                    "status": "timeout",
                    "passed": False,
                    "errors": [f"vitis-run csynth timed out after {timeout} seconds"],
                    "warnings": [],
                    "log_path": str(log_path),
                    "project_dir": str(work_dir),
                    "duration_seconds": round(time.time() - started, 3),
                    "toolchain": "vitis_hls",
                },
            }

    def _sanitize_hls4ml_sources_for_legacy_vivado(self, work_dir: Path, top_source: Path) -> list[str]:
        """Trim non-synthesis stdio includes that break Vivado HLS 2018.3 on Windows.

        hls4ml emits a few debug/CSim oriented includes in firmware files. Vivado HLS
        2018.3's bundled clang/libstdc++ can fail during preprocessing before
        __SYNTHESIS__ removes the debug code. Keep the generated project intact and
        only sanitize the copied Vivado work directory.
        """

        changed: list[str] = []

        def write_if_changed(path: Path, text: str, new_text: str) -> None:
            if new_text != text:
                path.write_text(new_text, encoding="utf-8")
                changed.append(str(path))

        if top_source.exists():
            text = top_source.read_text(encoding="utf-8", errors="ignore")
            new_text = re.sub(r"^\s*#include\s+<iostream>\s*\r?\n", "", text, flags=re.MULTILINE)
            new_text = re.sub(r"^\s*#include\s+<fstream>\s*\r?\n", "", new_text, flags=re.MULTILINE)
            write_if_changed(top_source, text, new_text)

        helpers = work_dir / "nnet_utils" / "nnet_helpers.h"
        if helpers.exists():
            text = helpers.read_text(encoding="utf-8", errors="ignore")
            old_block = (
                "#include \"hls_stream.h\"\n"
                "#include <algorithm>\n"
                "#include <fstream>\n"
                "#include <iostream>\n"
                "#include <map>\n"
                "#include <math.h>\n"
                "#include <stdio.h>\n"
                "#include <stdlib.h>\n"
                "#include <vector>"
            )
            new_block = (
                "#include \"hls_stream.h\"\n"
                "#ifndef __SYNTHESIS__\n"
                "#include <algorithm>\n"
                "#include <fstream>\n"
                "#include <iostream>\n"
                "#include <map>\n"
                "#include <vector>\n"
                "#endif\n"
                "#include <math.h>\n"
                "#include <stdio.h>\n"
                "#include <stdlib.h>"
            )
            new_text = text.replace(old_block, new_block)
            if new_text == text:
                short_block = "#include <algorithm>\n#include <fstream>\n#include <iostream>\n#include <map>\n#include <math.h>"
                short_new_block = (
                    "#ifndef __SYNTHESIS__\n"
                    "#include <algorithm>\n"
                    "#include <fstream>\n"
                    "#include <iostream>\n"
                    "#include <map>\n"
                    "#include <vector>\n"
                    "#endif\n"
                    "#include <math.h>"
                )
                new_text = text.replace(short_block, short_new_block)
            copy_data_anchor = "\n#endif\n\ntemplate <class src_T, class dst_T, size_t OFFSET, size_t SIZE> void copy_data"
            if copy_data_anchor in new_text and "#ifndef __SYNTHESIS__\ntemplate <class src_T, class dst_T, size_t OFFSET, size_t SIZE> void copy_data" not in new_text:
                new_text = new_text.replace(
                    copy_data_anchor,
                    "\n#endif\n\n#ifndef __SYNTHESIS__\ntemplate <class src_T, class dst_T, size_t OFFSET, size_t SIZE> void copy_data",
                    1,
                )
            read_file_anchor = "\ntemplate <class dataType, unsigned int nrows> int read_file_1D"
            if read_file_anchor in new_text and "#endif\n\ntemplate <class dataType, unsigned int nrows> int read_file_1D" not in new_text:
                new_text = new_text.replace(
                    read_file_anchor,
                    "\n#endif\n\ntemplate <class dataType, unsigned int nrows> int read_file_1D",
                    1,
                )
            debug_anchor = "\ntemplate <class data_T, int N_IN> void hls_stream_debug"
            if debug_anchor in new_text and "#ifndef __SYNTHESIS__\ntemplate <class data_T, int N_IN> void hls_stream_debug" not in new_text:
                new_text = new_text.replace(
                    debug_anchor,
                    "\n#ifndef __SYNTHESIS__\ntemplate <class data_T, int N_IN> void hls_stream_debug",
                    1,
                )
                new_text = new_text.replace("\n}\n\nconstexpr int ceillog2", "\n}\n#endif\n\nconstexpr int ceillog2", 1)
            write_if_changed(helpers, text, new_text)

        for relative in ["nnet_utils/nnet_mult.h", "nnet_utils/nnet_pooling.h"]:
            path = work_dir / relative
            if path.exists():
                text = path.read_text(encoding="utf-8", errors="ignore")
                new_text = re.sub(r"^\s*#include\s+<iostream>\s*\r?\n", "", text, flags=re.MULTILINE)
                write_if_changed(path, text, new_text)

        return changed

    def _copy_hls4ml_testbench(self, hls_project_dir: Path, work_dir: Path, top_function: str | None) -> Path | None:
        candidates: list[Path] = []
        if top_function:
            candidates.append(hls_project_dir / f"{top_function}_test.cpp")
        candidates.extend(sorted(hls_project_dir.glob("*_test.cpp")))
        candidates.extend(sorted(hls_project_dir.glob("testbench.cpp")))
        source = next((path for path in candidates if path.exists()), None)
        if source is None:
            return None
        text = source.read_text(encoding="utf-8", errors="ignore")
        # The copied firmware files live at work_dir root for synthesis include
        # compatibility, so the generated hls4ml testbench needs local includes.
        text = text.replace('#include "firmware/', '#include "')
        if "#include <string.h>" not in text and "#include <stdlib.h>" in text:
            text = text.replace("#include <stdlib.h>", "#include <stdlib.h>\n#include <string.h>", 1)
        destination = work_dir / "testbench.cpp"
        destination.write_text(text, encoding="utf-8")
        return destination

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
            copied_tb = self._copy_hls4ml_testbench(hls_project_dir, work_dir, top_function)
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
            sanitized_files = (
                self._sanitize_hls4ml_sources_for_legacy_vivado(work_dir, copied_code)
                if self.hls_toolchain == "vivado_hls"
                else []
            )
            tcl_path = bridge.create_project_tcl(
                project_dir=str(work_dir),
                project_name=Path(arguments.get("work_dir", work_dir)).name,
                top_function=top_function,
                code_file=str(copied_code),
                testbench_file=str(copied_tb) if copied_tb else None,
                target_device=arguments.get("part", "xc7z020clg400-1"),
                clock_period=str(arguments.get("clock_period", 5)),
            )
            return {
                "status": "success",
                "tcl_path": str(tcl_path),
                "work_dir": str(work_dir),
                "top_function": top_function,
                "testbench_path": str(copied_tb) if copied_tb else None,
                "sanitized_files": sanitized_files,
                "toolchain": self.hls_toolchain,
            }

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
        return {
            "status": "success",
            "tcl_path": str(tcl_path),
            "work_dir": str(work_dir),
            "top_function": top_function,
            "testbench_path": str(copied_tb) if copied_tb else None,
            "toolchain": self.hls_toolchain,
        }

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
                    f"{self._command_label()} command not found.",
                    recoverable=True,
                    source="vivado.run_csim",
                    suggested_action="Keep generated HLS project and skip synthesis.",
                    details={"command": self._command_label(), "toolchain": self.hls_toolchain},
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
            log_path.write_text(
                "INFO: [SIM] CSim done with 0 errors.\nGOLDEN_CHECK_PASSED\nINFO: [HLS] Starting synthesis...\nINFO: [HLS] Finished generating all RTL models.\n",
                encoding="utf-8",
            )
            fixture_name = MOCK_REPORT_BY_TOP.get(top_function)
            if fixture_name:
                fixture_path = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "reports" / fixture_name
                if fixture_path.exists():
                    report_path.write_text(fixture_path.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
                else:
                    report_path.write_text(MOCK_REPORT, encoding="utf-8")
            else:
                report_path.write_text(MOCK_REPORT, encoding="utf-8")
            verification = parse_csim_verification(log_path, work_dir=work_dir)
            return {"status": "success", "log_path": str(log_path), "report_path": str(report_path), "verification": verification}
        if not self._binary_available():
            return error_result(
                build_error(
                    "VivadoNotFoundError",
                    f"{self._command_label()} command not found.",
                    recoverable=True,
                    source="vivado.run_csynth",
                    suggested_action="Keep generated HLS project and skip synthesis.",
                    details={"command": self._command_label(), "toolchain": self.hls_toolchain},
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
        if self.hls_toolchain == "vitis_hls":
            result = self._run_vitis_with_existing_tcl(tcl_path=tcl_path, work_dir=work_dir)
        else:
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
            verification = parse_csim_verification(log_path, work_dir=work_dir)
            log_text = Path(log_path).read_text(encoding="utf-8", errors="ignore")
            for line in log_text.splitlines():
                lowered = line.lower()
                if re.search(r"\b0\s+error\(s\)", lowered):
                    continue
                if (
                    re.search(r"\berror\b", lowered)
                    or "fatal error" in lowered
                    or "c preprocessor failed" in lowered
                    or "compilation of the preprocessed source" in lowered
                    or "failed before report" in lowered
                ):
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
            "toolchain": self.hls_toolchain,
            "verification": parse_csim_verification(log_path, work_dir=work_dir) if log_path else {"status": "not_run", "passed": None, "mode": "none"},
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
