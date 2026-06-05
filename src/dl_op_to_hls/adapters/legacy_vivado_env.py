from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any


class HLSVerificationEnv:
    """Local copy of the minimal Vivado helper used by the new package.

    This intentionally lives inside ``src/dl_op_to_hls`` so the new project does
    not import root-level legacy scripts directly.
    """

    def __init__(self, vivado_hls_path: str, work_dir: str | None = None):
        raw_path = str(vivado_hls_path or "").strip()
        normalized = raw_path.replace("\\", "/").lower()
        is_direct_vivado_hls = normalized.endswith("/vivado_hls") or normalized.endswith("/vivado_hls.bat")
        if is_direct_vivado_hls:
            exe_path = Path(raw_path)
            if exe_path.parent.name.lower() == "bin":
                vivado_root = exe_path.parent.parent
            else:
                vivado_root = exe_path.parent
            self.vivado_hls_path = str(vivado_root)
            self.vivado_hls_exe = str(exe_path)
        else:
            self.vivado_hls_path = raw_path
            self.vivado_hls_exe = os.path.join(self.vivado_hls_path, "bin", "vivado_hls")
            if os.name == "nt":
                self.vivado_hls_exe += ".bat"

        self.work_dir = work_dir or os.path.join(os.getcwd(), "hls_work")
        os.makedirs(self.work_dir, exist_ok=True)

    def _sanitize_name(self, value: str | None, default: str = "hls", max_len: int = 24) -> str:
        text = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in str(value or default)).strip("_")
        return (text or default)[:max_len]

    def _build_stage_tcl(self, workspace: dict[str, Any], stage: str) -> str:
        first_open = not workspace.get("initialized")
        open_project_line = f"open_project {'-reset ' if first_open else ''}{workspace['project_name']}"
        lines = ["# Auto-generated stage-aware HLS TCL", open_project_line]
        if first_open:
            lines.append(f"add_files -cflags \"-std=c++0x\" {workspace['code_filename']}")
            if workspace.get("testbench_filename"):
                lines.append(f"add_files -tb -cflags \"-std=c++0x\" {workspace['testbench_filename']}")
            lines.append(f"set_top {workspace['top_function']}")
            lines.append('open_solution -reset "solution1"')
            lines.append(f"set_part {{{workspace['part']}}}")
            lines.append(f"create_clock -period {workspace['clock_period']} -name default")
        else:
            lines.append(f"set_top {workspace['top_function']}")
            lines.append('open_solution "solution1"')

        if stage == "csim":
            lines.extend(['puts "Starting C simulation..."', "csim_design", 'puts "C simulation completed"'])
        elif stage == "csynth":
            lines.extend(['puts "Starting synthesis..."', "csynth_design", 'puts "Synthesis completed"'])
        elif stage == "cosim":
            lines.extend(['puts "Starting co-simulation..."', "cosim_design", 'puts "Co-simulation completed"'])
        else:  # pragma: no cover - defensive branch
            raise ValueError(f"Unsupported stage: {stage}")

        lines.append("exit")
        tcl_path = os.path.join(workspace["project_dir"], f"{stage}_stage.tcl")
        Path(tcl_path).write_text("\n".join(lines), encoding="utf-8")
        return tcl_path

    def create_project_tcl(
        self,
        project_dir: str,
        project_name: str,
        top_function: str,
        code_file: str,
        testbench_file: str | None = None,
        target_device: str = "xc7z020clg484-1",
        clock_period: str = "10",
        enable_instrumentation: bool = False,
    ) -> str:
        del enable_instrumentation
        workspace = {
            "project_dir": project_dir,
            "project_name": self._sanitize_name(project_name),
            "top_function": top_function,
            "part": target_device,
            "clock_period": clock_period,
            "code_filename": os.path.basename(code_file),
            "testbench_filename": os.path.basename(testbench_file) if testbench_file else None,
            "initialized": False,
        }
        tcl_path = os.path.join(project_dir, f"run_{workspace['project_name']}.tcl")
        stages = ["csim", "csynth"] if testbench_file else ["csynth"]
        lines = ["# Legacy full-flow HLS TCL"]
        for stage in stages:
            stage_tcl = self._build_stage_tcl(workspace, stage)
            stage_lines = [line for line in Path(stage_tcl).read_text(encoding="utf-8").splitlines() if line != "exit"]
            lines.extend(line for line in stage_lines if not line.startswith("# Auto-generated"))
            workspace["initialized"] = True
        lines.append("exit")
        Path(tcl_path).write_text("\n".join(lines), encoding="utf-8")
        return tcl_path

    def _resolve_executable(self) -> str | None:
        candidate = Path(self.vivado_hls_exe)
        if candidate.exists():
            return str(candidate)
        return shutil.which("vivado_hls") or shutil.which("vivado_hls.bat")

    def run_with_existing_tcl(
        self,
        tcl_file_path: str,
        design_dir: str,
        code: str,
        testbench: str | None = None,
        timeout_seconds: int | None = None,
        project_name: str | None = None,
    ) -> dict[str, Any]:
        del code, testbench, project_name
        executable = self._resolve_executable()
        if not executable:
            return {
                "project_dir": design_dir,
                "synthesis": {
                    "status": "error",
                    "errors": ["vivado_hls command not found"],
                    "warnings": [],
                    "log_path": None,
                    "project_dir": design_dir,
                },
            }
        cwd = Path(design_dir)
        log_path = cwd / "csynth.log"
        timeout = int(timeout_seconds or os.environ.get("DL_OP_TO_HLS_VIVADO_TIMEOUT_SECONDS", "600"))
        started = time.time()
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        process = subprocess.Popen(
            [executable, "-f", os.path.basename(tcl_file_path)],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=(os.name == "nt"),
            creationflags=creationflags,
        )
        timed_out = False
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:  # pragma: no cover - Windows is the primary Vivado HLS environment.
                process.kill()
            stdout, stderr = process.communicate(timeout=30)

        if timed_out:
            combined = f"ERROR: csynth timed out after {timeout} seconds"
            if stdout:
                combined += f"\n=== STDOUT BEFORE TIMEOUT ===\n{stdout}"
            if stderr:
                combined += f"\n=== STDERR BEFORE TIMEOUT ===\n{stderr}"
            log_path.write_text(combined, encoding="utf-8")
            return {
                "project_dir": str(cwd),
                "synthesis": {
                    "status": "timeout",
                    "passed": False,
                    "errors": [f"csynth timed out after {timeout} seconds"],
                    "warnings": [],
                    "log_path": str(log_path),
                    "project_dir": str(cwd),
                    "duration_seconds": round(time.time() - started, 3),
                },
            }

        combined = (stdout or "") + ("\n=== STDERR ===\n" + (stderr or "") if stderr else "")
        log_path.write_text(combined, encoding="utf-8")
        status = "success" if process.returncode == 0 else "error"
        return {
            "project_dir": str(cwd),
            "synthesis": {
                "status": status,
                "passed": process.returncode == 0,
                "errors": [] if process.returncode == 0 else [f"Vivado HLS exited with return code {process.returncode}"],
                "warnings": [],
                "log_path": str(log_path),
                "project_dir": str(cwd),
                "duration_seconds": round(time.time() - started, 3),
            },
        }
