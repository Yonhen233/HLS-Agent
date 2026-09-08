"""adapters layer implementation for senior_agent_adapter.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from .legacy_vivado_env import HLSVerificationEnv


class SeniorVivadoBridge:
    """Coordinate SeniorVivadoBridge within the senior_agent_adapter boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    def __init__(self, vivado_hls_path: str | None, work_dir: str):
        """Implement the internal __init__ helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            vivado_hls_path: Value supplied by the caller and validated by the surrounding schema.
            work_dir: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        self.vivado_hls_path = vivado_hls_path or ""
        self.work_dir = work_dir

    def vivado_available(self) -> bool:
        """Execute vivado_available at the senior_agent_adapter boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Returns:
            The structured value promised by the function signature.
        """
        if self.vivado_hls_path and Path(self.vivado_hls_path).exists():
            return True
        return shutil.which("vivado_hls") is not None or shutil.which("vivado_hls.bat") is not None

    def make_env(self) -> HLSVerificationEnv:
        """Execute make_env at the senior_agent_adapter boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Returns:
            The structured value promised by the function signature.
        """
        path = self.vivado_hls_path
        if not path:
            resolved = shutil.which("vivado_hls") or shutil.which("vivado_hls.bat") or ""
            path = resolved
        return HLSVerificationEnv(path, self.work_dir)

    def discover_design_files(self, hls_project_dir: str) -> dict[str, str | None]:
        """Execute discover_design_files at the senior_agent_adapter boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            hls_project_dir: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
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
        """Execute extract_top_function at the senior_agent_adapter boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            code_text: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
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
        """Execute create_project_tcl at the senior_agent_adapter boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            project_dir: Value supplied by the caller and validated by the surrounding schema.
            project_name: Value supplied by the caller and validated by the surrounding schema.
            top_function: Value supplied by the caller and validated by the surrounding schema.
            code_file: Value supplied by the caller and validated by the surrounding schema.
            testbench_file: Value supplied by the caller and validated by the surrounding schema.
            target_device: Value supplied by the caller and validated by the surrounding schema.
            clock_period: Value supplied by the caller and validated by the surrounding schema.
            array_partition_maximum_size: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
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
        """Execute run_with_existing_tcl at the senior_agent_adapter boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            tcl_file_path: Value supplied by the caller and validated by the surrounding schema.
            design_dir: Value supplied by the caller and validated by the surrounding schema.
            code_text: Value supplied by the caller and validated by the surrounding schema.
            testbench_text: Value supplied by the caller and validated by the surrounding schema.
            project_name: Value supplied by the caller and validated by the surrounding schema.
            log_filename: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
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
        """Execute locate_report at the senior_agent_adapter boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            project_dir: Value supplied by the caller and validated by the surrounding schema.
            top_function: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        root = Path(project_dir)
        candidates = list(root.rglob("*_csynth.rpt"))
        if not candidates:
            candidates = list(root.rglob("csynth.rpt"))
        if top_function:
            for candidate in candidates:
                if top_function in candidate.name:
                    return str(candidate)
        return str(candidates[0]) if candidates else None
