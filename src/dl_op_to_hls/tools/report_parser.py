from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..core.errors import build_error, error_result


RESOURCE_PATTERNS = {
    "bram": [r"BRAM(?:_18K)?\s*[:=]\s*(\d+)"],
    "dsp": [r"DSP(?:48E)?\s*[:=]\s*(\d+)"],
    "ff": [r"FF\s*[:=]\s*(\d+)"],
    "lut": [r"LUT\s*[:=]\s*(\d+)"],
}


def _extract_pair(text: str, label: str) -> tuple[int | None, int | None]:
    patterns = [
        rf"{label}\s*\(cycles\)\s*:\s*min\s*=\s*(\d+)\s*,\s*max\s*=\s*(\d+)",
        rf"{label}\s*:\s*min\s*=\s*(\d+)\s*,\s*max\s*=\s*(\d+)",
        rf"{label}.*?(\d+).*?(\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return int(match.group(1)), int(match.group(2))
    return None, None


def _extract_resource(text: str, name: str) -> int | None:
    for pattern in RESOURCE_PATTERNS.get(name, []):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def _extract_resources_from_total_row(text: str) -> dict[str, int | None]:
    total_row = re.search(
        r"\|\s*Total\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|",
        text,
        flags=re.IGNORECASE,
    )
    if not total_row:
        return {"bram": None, "dsp": None, "ff": None, "lut": None}
    return {
        "bram": int(total_row.group(1)),
        "dsp": int(total_row.group(2)),
        "ff": int(total_row.group(3)),
        "lut": int(total_row.group(4)),
    }


def parse_csynth_report_file(report_path: str) -> dict[str, Any]:
    path = Path(report_path)
    if not path.exists():
        return error_result(
            build_error(
                "ReportMissingError",
                "Vivado HLS report not found.",
                recoverable=True,
                source="vivado.parse_report",
            ),
            status="report_missing",
        )

    text = path.read_text(encoding="utf-8", errors="ignore")
    latency_min, latency_max = _extract_pair(text, "Latency")
    ii_min, ii_max = _extract_pair(text, "Interval")
    latency_table = re.search(
        r"\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*[A-Za-z_]+\s*\|",
        text,
        flags=re.IGNORECASE,
    )
    if latency_table:
        latency_min = latency_min if latency_min is not None else int(latency_table.group(1))
        latency_max = latency_max if latency_max is not None else int(latency_table.group(2))
        ii_min = ii_min if ii_min is not None else int(latency_table.group(3))
        ii_max = ii_max if ii_max is not None else int(latency_table.group(4))
    timing_match = re.search(
        r"Timing\s*\(ns\)\s*:\s*Target\s*=\s*([0-9.]+)\s*,\s*Estimated\s*=\s*([0-9.]+)",
        text,
        flags=re.IGNORECASE,
    )
    if not timing_match:
        timing_match = re.search(
            r"Target\s*=\s*([0-9.]+).*?Estimated\s*=\s*([0-9.]+)",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
    if not timing_match:
        timing_match = re.search(
            r"\|\s*ap_clk\s*\|\s*([0-9.]+)\s*(?:ns)?\s*\|\s*([0-9.]+)\s*(?:ns)?\s*\|",
            text,
            flags=re.IGNORECASE,
        )
    target_ns = float(timing_match.group(1)) if timing_match else None
    estimated_ns = float(timing_match.group(2)) if timing_match else None
    if all(value is None for value in (latency_min, latency_max, ii_min, ii_max, target_ns, estimated_ns)):
        return error_result(
            build_error(
                "ReportParseError",
                "Unable to parse Vivado HLS report metrics.",
                recoverable=True,
                source="vivado.parse_report",
                details={"report_path": str(path)},
            )
        )
    resources = {name: _extract_resource(text, name) for name in ("bram", "dsp", "ff", "lut")}
    if any(value is None for value in resources.values()):
        table_resources = _extract_resources_from_total_row(text)
        for key in resources:
            if resources[key] is None:
                resources[key] = table_resources[key]

    return {
        "status": "success",
        "latency": {"min_cycles": latency_min, "max_cycles": latency_max},
        "interval": {"min_ii": ii_min, "max_ii": ii_max},
        "resources": resources,
        "timing": {
            "target_ns": target_ns,
            "estimated_ns": estimated_ns,
            "met": (estimated_ns <= target_ns) if target_ns is not None and estimated_ns is not None else None,
        },
    }


def parse_csynth_report(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    del context
    return parse_csynth_report_file(arguments["report_path"])
