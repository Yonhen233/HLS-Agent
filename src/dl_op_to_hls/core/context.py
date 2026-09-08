"""core layer implementation for context.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class ContextCompressor:
    """Coordinate ContextCompressor within the context boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    def __init__(self, hooks=None, run_id: str | None = None):
        """Implement the internal __init__ helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            hooks: Value supplied by the caller and validated by the surrounding schema.
            run_id: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        self.hooks = hooks
        self.run_id = run_id

    def _emit(self, source_path: str, summary: dict[str, Any]) -> None:
        """Implement the internal _emit helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            source_path: Value supplied by the caller and validated by the surrounding schema.
            summary: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        if self.hooks:
            self.hooks.emit(
                "ContextCompressed",
                {"run_id": self.run_id, "source_path": source_path, "summary": summary.get("summary", "")},
            )

    def compress_vivado_log(self, log_path: str) -> dict[str, Any]:
        """Execute compress_vivado_log at the context boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            log_path: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        path = Path(log_path)
        if not path.exists():
            summary = {
                "source_path": str(path),
                "summary": "Vivado log file was not found.",
                "errors": ["Vivado log file was not found."],
                "warnings": [],
                "key_metrics": {},
            }
            self._emit(str(path), summary)
            return summary
        text = path.read_text(encoding="utf-8", errors="ignore")
        errors = [line.strip() for line in text.splitlines() if "ERROR" in line.upper()][:10]
        warnings = [line.strip() for line in text.splitlines() if "WARNING" in line.upper()][:10]
        if errors:
            headline = errors[0]
        elif warnings:
            headline = warnings[0]
        else:
            headline = "Vivado stage completed without explicit errors."
        summary = {
            "source_path": str(path),
            "summary": headline,
            "errors": errors,
            "warnings": warnings,
            "key_metrics": {},
        }
        self._emit(str(path), summary)
        return summary

    def compress_csynth_report(self, report_path: str) -> dict[str, Any]:
        """Execute compress_csynth_report at the context boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            report_path: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        path = Path(report_path)
        if not path.exists():
            summary = {
                "source_path": str(path),
                "summary": "Vivado HLS report not found.",
                "errors": ["Vivado HLS report not found."],
                "warnings": [],
                "key_metrics": {},
            }
            self._emit(str(path), summary)
            return summary
        text = path.read_text(encoding="utf-8", errors="ignore")
        metrics: dict[str, Any] = {}
        for label, key in (("Latency", "latency"), ("Interval", "interval"), ("DSP", "dsp"), ("LUT", "lut"), ("FF", "ff"), ("BRAM", "bram")):
            for line in text.splitlines():
                if label.lower() in line.lower():
                    metrics[key] = " ".join(line.split())[:200]
                    break
        summary = {
            "source_path": str(path),
            "summary": "Compressed csynth report metrics extracted.",
            "errors": [],
            "warnings": [],
            "key_metrics": metrics,
        }
        self._emit(str(path), summary)
        return summary

    def compress_tool_result(self, result: dict[str, Any]) -> dict[str, Any]:
        """Execute compress_tool_result at the context boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            result: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        compressed = {
            "status": result.get("status"),
            "keys": sorted(result.keys()),
        }
        error = result.get("error")
        if error:
            compressed["error"] = error
        self._emit(str(result.get("source_path", "tool_result")), {"summary": f"Compressed tool result: {compressed['status']}"})
        return compressed

