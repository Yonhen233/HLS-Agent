from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from .legacy_vivado_env import HLSVerificationEnv


class SeniorVivadoBridge:
    def __init__(self, vivado_hls_path: str | None, work_dir: str):
        self.vivado_hls_path = vivado_hls_path or ""
        self.work_dir = work_dir

    def vivado_available(self) -> bool:
        if self.vivado_hls_path and Path(self.vivado_hls_path).exists():
            return True
        return shutil.which("vivado_hls") is not None or shutil.which("vivado_hls.bat") is not None

    def make_env(self) -> HLSVerificationEnv:
        path = self.vivado_hls_path
        if not path:
            resolved = shutil.which("vivado_hls") or shutil.which("vivado_hls.bat") or ""
            path = resolved
        return HLSVerificationEnv(path, self.work_dir)

    def discover_design_files(self, hls_project_dir: str) -> dict[str, str | None]:
        design_dir = Path(hls_project_dir)
        code_file = None
        testbench_file = None
        for candidate in sorted(design_dir.glob("*.cpp")):
            lowered = candidate.name.lower()
            if "testbench" in lowered or lowered.startswith("tb_"):
                testbench_file = testbench_file or str(candidate)
            elif code_file is None:
                code_file = str(candidate)
        header_file = None
        for candidate in sorted(design_dir.glob("*.h")):
            header_file = str(candidate)
            break
        tcl_file = None
        for candidate in sorted(design_dir.glob("*.tcl")):
            tcl_file = str(candidate)
            break
        return {"code_file": code_file, "testbench_file": testbench_file, "header_file": header_file, "tcl_file": tcl_file}

    def extract_top_function(self, code_text: str) -> str | None:
        patterns = [
            r"void\s+([A-Za-z_]\w*)\s*\(",
            r"int\s+([A-Za-z_]\w*)\s*\(",
            r"float\s+([A-Za-z_]\w*)\s*\(",
        ]
        for pattern in patterns:
            match = re.search(pattern, code_text)
            if match and match.group(1) != "main":
                return match.group(1)
        return None

    def create_project_tcl(
        self,
        project_dir: str,
        project_name: str,
        top_function: str,
        code_file: str,
        testbench_file: str | None,
        target_device: str,
        clock_period: str,
        array_partition_maximum_size: int | None = None,
    ) -> str:
        env = self.make_env()
        return env.create_project_tcl(
            project_dir=project_dir,
            project_name=project_name,
            top_function=top_function,
            code_file=code_file,
            testbench_file=testbench_file,
            target_device=target_device,
            clock_period=clock_period,
            array_partition_maximum_size=array_partition_maximum_size,
        )

    def run_with_existing_tcl(
        self,
        tcl_file_path: str,
        design_dir: str,
        code_text: str,
        testbench_text: str | None = None,
        project_name: str | None = None,
        log_filename: str = "csynth.log",
    ) -> dict[str, Any]:
        env = self.make_env()
        return env.run_with_existing_tcl(
            tcl_file_path=tcl_file_path,
            design_dir=design_dir,
            code=code_text,
            testbench=testbench_text,
            project_name=project_name,
            log_filename=log_filename,
        )

    def locate_report(self, project_dir: str, top_function: str | None = None) -> str | None:
        root = Path(project_dir)
        candidates = list(root.rglob("*_csynth.rpt"))
        if not candidates:
            candidates = list(root.rglob("csynth.rpt"))
        if top_function:
            for candidate in candidates:
                if top_function in candidate.name:
                    return str(candidate)
        return str(candidates[0]) if candidates else None
