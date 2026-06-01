from __future__ import annotations

from pathlib import Path
from typing import Any


class ContextCompressor:
    def __init__(self, hooks=None, run_id: str | None = None):
        self.hooks = hooks
        self.run_id = run_id

    def _emit(self, source_path: str, summary: dict[str, Any]) -> None:
        if self.hooks:
            self.hooks.emit(
                "ContextCompressed",
                {"run_id": self.run_id, "source_path": source_path, "summary": summary.get("summary", "")},
            )

    def compress_vivado_log(self, log_path: str) -> dict[str, Any]:
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
        compressed = {
            "status": result.get("status"),
            "keys": sorted(result.keys()),
        }
        error = result.get("error")
        if error:
            compressed["error"] = error
        self._emit(str(result.get("source_path", "tool_result")), {"summary": f"Compressed tool result: {compressed['status']}"})
        return compressed

