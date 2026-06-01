from __future__ import annotations


def empty_report(status: str = "missing") -> dict:
    return {
        "status": status,
        "latency": {"min_cycles": None, "max_cycles": None},
        "interval": {"min_ii": None, "max_ii": None},
        "resources": {"bram": None, "dsp": None, "ff": None, "lut": None},
        "timing": {"target_ns": None, "estimated_ns": None, "met": None},
    }

