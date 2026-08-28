from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DECLARED_SUPPORT: dict[str, dict[str, Any]] = {
    "Dense": {
        "deterministic_template": True,
        "llm_candidate": True,
        "onnx_patterns": ["Gemm", "MatMul+Add"],
        "known_limitations": ["static dimensions", "static weights for model conversion"],
    },
    "MatMul": {
        "deterministic_template": True,
        "llm_candidate": True,
        "onnx_patterns": ["static MatMul"],
        "known_limitations": ["static dimensions", "dynamic right-hand input is operator-task only"],
    },
    "ReLU": {
        "deterministic_template": True,
        "llm_candidate": True,
        "onnx_patterns": ["Relu"],
        "known_limitations": ["static tensor length in operator task"],
    },
    "Add": {
        "deterministic_template": True,
        "llm_candidate": True,
        "onnx_patterns": ["bias Add only"],
        "known_limitations": ["residual/branched elementwise Add is unsupported by the restricted graph adapter"],
    },
    "ScaleShift": {
        "deterministic_template": False,
        "llm_candidate": True,
        "onnx_patterns": [],
        "known_limitations": ["LLM candidate must pass sandbox, golden CSim, and CSynth"],
    },
    "Conv2D": {
        "deterministic_template": False,
        "llm_candidate": True,
        "onnx_patterns": ["Conv", "Conv+BatchNorm fold", "Conv+Activation"],
        "known_limitations": ["static NHWC", "group=1", "no depthwise/grouped convolution", "static kernel/stride/padding/weights/bias"],
    },
}


def build_support_matrix(functional_cases: list[dict[str, Any]], runs_root: str | Path) -> dict[str, Any]:
    by_operator: dict[str, list[dict[str, Any]]] = {}
    for case in functional_cases:
        by_operator.setdefault(str(case["operator"]), []).append(case)
    evidence = _audit_runs(Path(runs_root))
    operators: list[dict[str, Any]] = []
    for operator, declaration in DECLARED_SUPPORT.items():
        cases = by_operator.get(operator, [])
        operator_evidence = evidence.get(operator, {})
        operators.append(
            {
                "operator": operator,
                **declaration,
                "primary_generation_path": "llm_candidate",
                "tested_shapes": _unique([case["shape"] for case in cases]),
                "tested_dtypes": sorted({str(case["dtype"]) for case in cases}),
                "functional_case_count": len(cases),
                "real_csim_count": int(operator_evidence.get("real_csim", 0)),
                "real_csynth_count": int(operator_evidence.get("real_csynth", 0)),
                "mock_case_count": int(operator_evidence.get("mock", 0)),
                "fixture_case_count": int(operator_evidence.get("fixture", 0)),
                "evidence_runs": operator_evidence.get("runs", []),
                "support_status": "functional_reference_ready" if cases else "declared_unverified",
            }
        )
    return {
        "schema_version": "1.0",
        "generation_policy": "llm_candidate_first",
        "real_evidence_policy": "Only explicit current-run real_csim/real_csynth receipts are counted.",
        "operators": operators,
    }


def render_support_matrix_markdown(matrix: dict[str, Any]) -> str:
    lines = [
        "# Operator Support Matrix",
        "",
        "主生成策略为 LLM Candidate。确定性模板仅作为公平对照和已验证实现复用来源，不是默认降级路径。",
        "",
        "| Operator | LLM | Template | Functional cases | Real CSim | Real CSynth | Mock | Status |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for item in matrix["operators"]:
        lines.append(
            f"| {item['operator']} | {'yes' if item['llm_candidate'] else 'no'} | "
            f"{'yes' if item['deterministic_template'] else 'no'} | {item['functional_case_count']} | "
            f"{item['real_csim_count']} | {item['real_csynth_count']} | {item['mock_case_count']} | {item['support_status']} |"
        )
    lines.extend(
        [
            "",
            "## 口径",
            "",
            "- `functional_case_count` 表示独立 Python 数学/位精确 Golden Case，不表示 HLS 已验证。",
            "- `real_csim_count` 与 `real_csynth_count` 只接受当前 Run 内、有哈希且明确标记为真实工具的证据。",
            "- Mock、Fixture 和历史未迁移 Run 单独统计，不参与真实成功率。",
        ]
    )
    return "\n".join(lines) + "\n"


def _audit_runs(runs_root: Path) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    if not runs_root.exists():
        return summary
    for run_dir in runs_root.iterdir():
        if not run_dir.is_dir():
            continue
        state = _read_json(run_dir / "state.json")
        if not state:
            continue
        task = state.get("task") or {}
        operator = str(task.get("op_type") or "")
        if operator not in DECLARED_SUPPORT:
            continue
        receipts = _read_json(run_dir / "tool_evidence.json")
        if isinstance(receipts, dict):
            receipts = receipts.get("receipts", [])
        if not isinstance(receipts, list):
            receipts = []
        classes_in_run: set[str] = set()
        accepted: list[dict[str, Any]] = []
        for receipt in receipts:
            if not isinstance(receipt, dict) or not receipt.get("valid"):
                continue
            evidence_class = str(receipt.get("evidence_class") or ("mock" if receipt.get("mock_evidence") else "unit"))
            classes_in_run.add(evidence_class)
            if evidence_class in {"real_csim", "real_csynth", "mock", "fixture"}:
                accepted.append(
                    {
                        "run_id": run_dir.name,
                        "evidence_class": evidence_class,
                        "tool": receipt.get("tool_name"),
                        "receipt_id": receipt.get("receipt_id"),
                    }
                )
            if _receipt_has_real_golden_csim(receipt):
                classes_in_run.add("real_csim")
                accepted.append(
                    {
                        "run_id": run_dir.name,
                        "evidence_class": "real_csim",
                        "tool": receipt.get("tool_name"),
                        "receipt_id": receipt.get("receipt_id"),
                        "derived_from_check": "golden_csim_passed",
                    }
                )
        target = summary.setdefault(operator, {"runs": []})
        for key in classes_in_run:
            target[key] = int(target.get(key, 0)) + 1
        target["runs"].extend(accepted)
    return summary


def _receipt_has_real_golden_csim(receipt: dict[str, Any]) -> bool:
    if receipt.get("mock_evidence") or receipt.get("status") not in {"success", "verified", "csim_passed"}:
        return False
    if str(receipt.get("evidence_class")) not in {"real_csim", "real_csynth"}:
        return False
    return any(
        isinstance(check, dict)
        and check.get("name") == "golden_csim_passed"
        and check.get("passed") is True
        for check in receipt.get("checks", [])
    )


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _unique(values: list[Any]) -> list[Any]:
    seen: set[str] = set()
    output: list[Any] = []
    for value in values:
        key = json.dumps(value, sort_keys=True)
        if key not in seen:
            seen.add(key)
            output.append(value)
    return output
