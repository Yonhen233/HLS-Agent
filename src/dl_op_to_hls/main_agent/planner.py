from __future__ import annotations


def build_plan(task: dict) -> list[str]:
    task_type = task.get("task_type")
    if task_type == "model":
        return [
            "Validate task schema",
            "Inspect model structure",
            "Check hls4ml support",
            "Run Vivado HLS synthesis",
            "Parse synthesis report",
            "Generate optimization suggestions",
            "Write run summary",
            "Promote memories",
        ]
    if task_type == "operator":
        return [
            "Validate task schema",
            "Check hls4ml support",
            "Run Vivado HLS synthesis",
            "Parse synthesis report",
            "Generate optimization suggestions",
            "Write run summary",
            "Promote memories",
        ]
    return [
        "Validate task schema",
        "Prepare existing HLS project",
        "Run Vivado HLS synthesis",
        "Parse synthesis report",
        "Generate optimization suggestions",
        "Write run summary",
        "Promote memories",
    ]
