from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import onnx
from onnx import numpy_helper

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from dl_op_to_hls.adapters.vivado_hls_adapter import VivadoHLSAdapter
from dl_op_to_hls.core.candidate_sandbox import CandidateSandbox
from dl_op_to_hls.core.errors import AgentRuntimeError
from dl_op_to_hls.llm.client import LLMClient
from dl_op_to_hls.tools.report_parser import parse_csynth_report_file


SCHEMA = {
    "title": "mnist_direct_hls_candidate",
    "type": "object",
    "required": [
        "candidate_name",
        "data_type",
        "weight_type",
        "accum_type",
        "function_body",
        "resource_strategy",
        "rationale",
    ],
    "properties": {
        "candidate_name": {"type": "string"},
        "data_type": {"type": "string"},
        "weight_type": {"type": "string"},
        "accum_type": {"type": "string"},
        "function_body": {"type": "string"},
        "resource_strategy": {"type": "array"},
        "rationale": {"type": "string"},
    },
}


SYSTEM_PROMPT = """You are a senior FPGA HLS engineer.
Return strict JSON only.
Design a resource-minimized Vivado HLS 2018.3 C++ implementation body for a fixed MNIST MLP:
784 inputs -> Dense64 -> ReLU -> Dense32 -> ReLU -> Dense10 logits.

The final code will already provide:
- #include "mnist_llm_candidate.h"
- typedefs data_t, weight_t, acc_t
- constants W1[64][784], B1[64], W2[32][64], B2[32], W3[10][32], B3[10]
- prototype: void mnist_llm_candidate(data_t input[784], data_t output[10])

Your function_body must contain exactly one complete definition:
void mnist_llm_candidate(data_t input[784], data_t output[10]) { ... }

Rules:
- Use only synthesizable C++ accepted by Vivado HLS 2018.3.
- No dynamic allocation, no STL containers, no file IO, no system calls.
- Prefer resource sharing over latency. Do not fully unroll dense loops.
- Use simple loops over the real weight arrays.
- Keep the top contract unchanged.
- The output logits must preserve argmax accuracy on MNIST samples.
"""


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_onnx_weights(model_path: Path) -> dict[str, np.ndarray]:
    model = onnx.load(str(model_path), load_external_data=True)
    weights = {initializer.name: numpy_helper.to_array(initializer).astype(np.float32) for initializer in model.graph.initializer}
    required = ["fc1.weight", "fc1.bias", "fc2.weight", "fc2.bias", "fc3.weight", "fc3.bias"]
    missing = [name for name in required if name not in weights]
    if missing:
        raise RuntimeError(f"Missing ONNX initializer(s): {missing}")
    return weights


def _load_samples(samples_path: Path, labels_path: Path) -> tuple[np.ndarray, list[int]]:
    rows: list[list[float]] = []
    for line in samples_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append([float(value) for value in line.split()])
    samples = np.asarray(rows, dtype=np.float32)
    labels = list(_read_json(labels_path)["labels"])
    if samples.shape[1] != 784:
        raise RuntimeError(f"Expected 784-wide MNIST rows, got {samples.shape}")
    return samples, labels


def _reference_predictions(weights: dict[str, np.ndarray], samples: np.ndarray) -> list[int]:
    x = samples
    y1 = np.maximum(0.0, x @ weights["fc1.weight"].T + weights["fc1.bias"])
    y2 = np.maximum(0.0, y1 @ weights["fc2.weight"].T + weights["fc2.bias"])
    logits = y2 @ weights["fc3.weight"].T + weights["fc3.bias"]
    return [int(np.argmax(row)) for row in logits]


def _format_scalar(value: float) -> str:
    if abs(value) < 1e-12:
        return "0"
    return f"{float(value):.8g}"


def _format_1d(values: np.ndarray, indent: str = "    ") -> str:
    chunks: list[str] = []
    for start in range(0, len(values), 8):
        row = ", ".join(_format_scalar(float(item)) for item in values[start : start + 8])
        chunks.append(f"{indent}{row}")
    return ",\n".join(chunks)


def _format_2d(values: np.ndarray, indent: str = "    ") -> str:
    rows: list[str] = []
    for row in values:
        rows.append(f"{indent}{{{', '.join(_format_scalar(float(item)) for item in row)}}}")
    return ",\n".join(rows)


def _sanitize_ap_fixed_type(value: str, default: str) -> str:
    text = str(value or "").strip()
    if not text.startswith("ap_fixed<") or not text.endswith(">"):
        return default
    body = text[len("ap_fixed<") : -1]
    parts = [part.strip() for part in body.split(",")]
    if len(parts) < 2 or len(parts) > 4:
        return default
    try:
        width = int(parts[0])
        integer = int(parts[1])
    except ValueError:
        return default
    if width < 4 or width > 40 or integer < 1 or integer > width:
        return default
    extras: list[str] = []
    allowed_modes = {
        "AP_RND",
        "AP_RND_ZERO",
        "AP_RND_MIN_INF",
        "AP_RND_INF",
        "AP_RND_CONV",
        "AP_TRN",
        "AP_TRN_ZERO",
        "AP_SAT",
        "AP_SAT_ZERO",
        "AP_SAT_SYM",
        "AP_WRAP",
        "AP_WRAP_SM",
    }
    for extra in parts[2:]:
        if extra not in allowed_modes:
            return default
        extras.append(extra)
    rendered = [str(width), str(integer), *extras]
    return f"ap_fixed<{','.join(rendered)}>"


def _build_header(plan: dict[str, Any], weights: dict[str, np.ndarray]) -> str:
    data_type = _sanitize_ap_fixed_type(plan.get("data_type"), "ap_fixed<12,6>")
    weight_type = _sanitize_ap_fixed_type(plan.get("weight_type"), "ap_fixed<12,4>")
    accum_type = _sanitize_ap_fixed_type(plan.get("accum_type"), "ap_fixed<28,12>")
    plan["effective_types"] = {
        "data_type": data_type,
        "weight_type": weight_type,
        "accum_type": accum_type,
    }
    return f"""#ifndef MNIST_LLM_CANDIDATE_H
#define MNIST_LLM_CANDIDATE_H

#include "ap_fixed.h"

typedef {data_type} data_t;
typedef {weight_type} weight_t;
typedef {accum_type} acc_t;

static const weight_t W1[64][784] = {{
{_format_2d(weights["fc1.weight"])}
}};

static const weight_t B1[64] = {{
{_format_1d(weights["fc1.bias"])}
}};

static const weight_t W2[32][64] = {{
{_format_2d(weights["fc2.weight"])}
}};

static const weight_t B2[32] = {{
{_format_1d(weights["fc2.bias"])}
}};

static const weight_t W3[10][32] = {{
{_format_2d(weights["fc3.weight"])}
}};

static const weight_t B3[10] = {{
{_format_1d(weights["fc3.bias"])}
}};

void mnist_llm_candidate(data_t input[784], data_t output[10]);

#endif
"""


def _normalize_function_body(body: str) -> str:
    text = str(body or "").strip()
    text = text.replace("```cpp", "").replace("```c++", "").replace("```", "").strip()
    if "void mnist_llm_candidate" not in text:
        raise RuntimeError("LLM candidate does not define mnist_llm_candidate.")
    return text


def _build_cpp(plan: dict[str, Any]) -> str:
    body = _normalize_function_body(plan["function_body"])
    return f'#include "mnist_llm_candidate.h"\n\n{body}\n'


def _build_testbench(samples: np.ndarray, labels: list[int], required_correct: int) -> str:
    sample_rows = []
    for row in samples:
        sample_rows.append(f"    {{{', '.join(_format_scalar(float(item)) for item in row)}}}")
    return f"""#include "mnist_llm_candidate.h"
#include <cstdio>

static const float TEST_SAMPLES[{len(samples)}][784] = {{
{",\n".join(sample_rows)}
}};

static const int TEST_LABELS[{len(labels)}] = {{
    {", ".join(str(int(item)) for item in labels)}
}};

int main() {{
    int correct = 0;
    for (int n = 0; n < {len(samples)}; n++) {{
        data_t input[784];
        data_t output[10];
        for (int i = 0; i < 784; i++) {{
            input[i] = TEST_SAMPLES[n][i];
        }}
        mnist_llm_candidate(input, output);
        int pred = 0;
        data_t best = output[0];
        for (int k = 1; k < 10; k++) {{
            if (output[k] > best) {{
                best = output[k];
                pred = k;
            }}
        }}
        if (pred == TEST_LABELS[n]) {{
            correct++;
        }} else {{
            std::printf("MNIST_SAMPLE_MISMATCH n=%d pred=%d label=%d\\n", n, pred, TEST_LABELS[n]);
        }}
    }}
    std::printf("MNIST_LLM_CANDIDATE_ACCURACY %d/{len(samples)}\\n", correct);
    if (correct < {required_correct}) {{
        std::printf("GOLDEN_CHECK_FAILED accuracy=%d/{len(samples)} required={required_correct}\\n", correct);
        return 1;
    }}
    std::printf("GOLDEN_CHECK_PASSED accuracy=%d/{len(samples)} required={required_correct}\\n", correct);
    return 0;
}}
"""


def _prompt_for_plan(
    *,
    baseline: dict[str, Any],
    previous_results: list[dict[str, Any]],
    attempt: int,
) -> str:
    prompt = {
        "goal": "Generate a direct HLS candidate that minimizes LUT/DSP/FF/BRAM while keeping MNIST accuracy >= baseline.",
        "attempt": attempt,
        "model": {
            "topology": "784 -> Dense64 -> ReLU -> Dense32 -> ReLU -> Dense10",
            "input_range": "[0, 1]",
            "weights_available_as_constants": ["W1", "B1", "W2", "B2", "W3", "B3"],
        },
        "baseline_to_beat": baseline,
        "previous_attempt_results": previous_results[-3:],
        "required_output": {
            "candidate_name": "short identifier",
            "data_type": "ap_fixed<W,I>",
            "weight_type": "ap_fixed<W,I>",
            "accum_type": "ap_fixed<W,I>",
            "function_body": "complete top function definition only",
            "resource_strategy": ["short bullets"],
            "rationale": "why this should reduce resources",
        },
        "hard_constraints": [
            "Do not use unsupported includes or host APIs.",
            "Do not fully unroll dense loops.",
            "Do not change the top function signature.",
            "Use constants W1/B1/W2/B2/W3/B3 exactly as declared.",
            "Return JSON only.",
        ],
    }
    return json.dumps(prompt, ensure_ascii=False, indent=2)


def _write_plan_artifacts(candidate_dir: Path, plan: dict[str, Any], weights: dict[str, np.ndarray], samples: np.ndarray, labels: list[int], required_correct: int) -> None:
    candidate_dir.mkdir(parents=True, exist_ok=True)
    (candidate_dir / "mnist_llm_candidate.h").write_text(_build_header(plan, weights), encoding="utf-8")
    (candidate_dir / "mnist_llm_candidate.cpp").write_text(_build_cpp(plan), encoding="utf-8")
    (candidate_dir / "testbench.cpp").write_text(_build_testbench(samples, labels, required_correct), encoding="utf-8")
    (candidate_dir / "candidate_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")


def _scan_candidate(candidate_dir: Path) -> dict[str, Any]:
    sandbox = CandidateSandbox()
    violations = []
    for path in sorted(candidate_dir.glob("*")):
        if path.suffix.lower() in {".cpp", ".h", ".hpp"}:
            violations.extend(sandbox.scan_text(path.read_text(encoding="utf-8", errors="ignore"), path.name))
    return {"status": "invalid" if violations else "valid", "violations": violations}


def _verify_with_vivado(candidate_dir: Path, run_dir: Path, part: str, clock_period: float, vivado_hls_path: str | None) -> dict[str, Any]:
    adapter = VivadoHLSAdapter(mock_mode=False, vivado_hls_path=vivado_hls_path)
    work_dir = run_dir / "vivado_hls"
    create = adapter.create_project(
        {
            "hls_project_dir": str(candidate_dir),
            "work_dir": str(work_dir),
            "top_function": "mnist_llm_candidate",
            "part": part,
            "clock_period": clock_period,
        }
    )
    if create.get("status") != "success":
        return {"status": "failed", "stage": "create_project", "create_project": create}
    synth = adapter.run_csynth(
        {
            "work_dir": create["work_dir"],
            "tcl_path": create["tcl_path"],
            "top_function": "mnist_llm_candidate",
        }
    )
    result: dict[str, Any] = {"status": synth.get("status"), "stage": "run_csynth", "create_project": create, "synthesis": synth}
    report_path = synth.get("report_path")
    if report_path:
        parsed = parse_csynth_report_file(report_path)
        result["report"] = parsed
    return result


def _score(report: dict[str, Any]) -> int:
    resources = report.get("resources") or {}
    return int(resources.get("lut") or 0) + int(resources.get("ff") or 0) + 200 * int(resources.get("dsp") or 0) + 100 * int(resources.get("bram") or 0)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate and verify direct LLM HLS candidates for the MNIST MLP.")
    parser.add_argument("--model", default="models/mnist_recognition/mnist_mlp_trained.onnx")
    parser.add_argument("--samples", default="models/mnist_recognition/mnist_test_inputs_20.dat")
    parser.add_argument("--labels", default="models/mnist_recognition/mnist_test_labels_20.json")
    parser.add_argument("--output-root", default="runs/llm_mnist_hls_candidate")
    parser.add_argument("--attempts", type=int, default=4)
    parser.add_argument("--required-correct", type=int, default=19)
    parser.add_argument("--clock-period", type=float, default=15.0)
    parser.add_argument("--part", default="xc7z020clg400-1")
    parser.add_argument("--vivado-hls-path", default=os.environ.get("DL_OP_TO_HLS_VIVADO_HLS_PATH") or r"D:\Xilinx\Vivado\2018.3\bin\vivado_hls.bat")
    parser.add_argument("--continue-run", action="store_true", help="Load existing summary/attempts and append more LLM repair attempts.")
    args = parser.parse_args()

    output_root = (REPO_ROOT / args.output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    weights = _load_onnx_weights((REPO_ROOT / args.model).resolve())
    samples, labels = _load_samples((REPO_ROOT / args.samples).resolve(), (REPO_ROOT / args.labels).resolve())
    reference_predictions = _reference_predictions(weights, samples)

    baseline = {
        "path": "hls4ml resource-priority best known",
        "accuracy": "19/20",
        "argmax_match": "20/20 against Python reference",
        "latency_cycles": 2135,
        "resources": {"bram": 47, "dsp": 64, "ff": 5999, "lut": 17899},
        "resource_score": 41398,
    }
    summary_path = output_root / "summary.json"
    previous_results: list[dict[str, Any]] = []
    if args.continue_run and summary_path.exists():
        existing_summary = json.loads(summary_path.read_text(encoding="utf-8"))
        previous_results = list(existing_summary.get("attempts") or [])
    client = LLMClient()
    best: dict[str, Any] | None = None
    for previous in previous_results:
        report = ((previous.get("verification") or {}).get("report") or {})
        verification = (((previous.get("verification") or {}).get("synthesis") or {}).get("verification") or {})
        if previous.get("status") == "success" and report.get("status") == "success" and verification.get("passed") is True:
            previous.setdefault("resource_score", _score(report))
            if best is None or previous["resource_score"] < best.get("resource_score", 10**12):
                best = previous

    last_attempt = max([int(item.get("attempt") or 0) for item in previous_results] or [0])
    for attempt in range(last_attempt + 1, last_attempt + max(1, args.attempts) + 1):
        new_best_this_attempt = False
        attempt_dir = output_root / f"attempt_{attempt:02d}"
        candidate_dir = attempt_dir / "candidate"
        prompt = _prompt_for_plan(baseline=baseline, previous_results=previous_results, attempt=attempt)
        try:
            plan = client.complete_json(SYSTEM_PROMPT, prompt, SCHEMA, temperature=0.15)
        except AgentRuntimeError as exc:
            failure = {"attempt": attempt, "status": "llm_failed", "error": exc.error.to_dict() if hasattr(exc, "error") else str(exc)}
            previous_results.append(failure)
            (attempt_dir / "attempt_result.json").parent.mkdir(parents=True, exist_ok=True)
            (attempt_dir / "attempt_result.json").write_text(json.dumps(failure, ensure_ascii=False, indent=2), encoding="utf-8")
            continue

        try:
            _write_plan_artifacts(candidate_dir, plan, weights, samples, labels, args.required_correct)
            scan = _scan_candidate(candidate_dir)
            if scan["status"] != "valid":
                result = {"attempt": attempt, "status": "sandbox_failed", "plan": plan, "sandbox": scan}
            else:
                verification = _verify_with_vivado(candidate_dir, attempt_dir, args.part, args.clock_period, args.vivado_hls_path)
                result = {"attempt": attempt, "status": verification.get("status"), "plan": plan, "sandbox": scan, "verification": verification}
                report = verification.get("report") or {}
                csim = (verification.get("synthesis") or {}).get("verification") or {}
                if verification.get("status") == "success" and report.get("status") == "success" and csim.get("passed") is True:
                    result["resource_score"] = _score(report)
                    if best is None or result["resource_score"] < best.get("resource_score", 10**12):
                        best = result
                        new_best_this_attempt = True
        except Exception as exc:
            result = {"attempt": attempt, "status": "exception", "plan": plan, "error": str(exc)}

        previous_results.append(result)
        (attempt_dir / "attempt_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

        if new_best_this_attempt and best and best.get("resource_score", 10**12) < baseline["resource_score"]:
            break

    summary = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "baseline": baseline,
        "reference_predictions": reference_predictions,
        "required_correct": args.required_correct,
        "attempts": previous_results,
        "best": best,
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"summary_path": str(summary_path), "best": best}, ensure_ascii=False, indent=2, default=str))
    return 0 if best else 1


if __name__ == "__main__":
    raise SystemExit(main())
