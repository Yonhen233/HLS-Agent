from __future__ import annotations

import argparse
import json
import os
import re
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


SYSTEM_PROMPT_BASE = """You are a senior FPGA HLS engineer.
Return strict JSON only.
Design a Vivado HLS 2018.3 C++ implementation body for a fixed MNIST MLP:
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
- Use simple loops over the real weight arrays.
- Weight indexing is output-major: W1[out64][in784], W2[out32][in64], W3[out10][in32].
- Use acc_t for accumulators. accum_t is available as an alias, but acc_t is preferred.
- Keep the top contract unchanged.
- The output logits must preserve argmax accuracy on MNIST samples.
"""


OBJECTIVE_RULES = {
    "resource": [
        "Primary goal: minimize BRAM/DSP/FF/LUT.",
        "Prefer resource sharing over latency.",
        "Do not fully unroll dense loops.",
        "Serial or lightly parallel loops are acceptable.",
    ],
    "balanced": [
        "Primary goal: improve latency/interval versus the serial resource candidate while keeping resource_score <= 12000.",
        "Use the verified safe numeric starting point unless you justify a wider type: data_t=ap_fixed<16,4,AP_RND,AP_SAT>, weight_t=ap_fixed<8,4,AP_RND,AP_SAT>, acc_t=ap_fixed<20,16,AP_RND>.",
        "Do not use unsafe tiny types such as ap_fixed<8,1> or ap_fixed<8,2>; previous attempts with those types failed golden accuracy.",
        "Do not omit AP_SAT on data_t; default AP_WRAP can break classification accuracy.",
        "Use moderate parallelism such as output-neuron blocking, partial sums, small unroll factors 2-8, and local array partitioning.",
        "Current verified balanced best is latency/II=6776 with resource_score=7949; improve latency/II without raising score much beyond 12000.",
        "Do not fully partition the large W1/W2/W3 constant matrices.",
        "Avoid complete partitioning of large hidden activation arrays unless the resource estimate is still below baseline.",
        "Do not apply ARRAY_PARTITION complete to W1/W2/W3; use local partial-sum arrays instead.",
        "Avoid exploding LUT/FF; a moderate DSP budget is acceptable if II/latency improves materially.",
    ],
    "throughput": [
        "Primary goal: minimize latency and top interval / II.",
        "Use numerically safe types first: data_t at least ap_fixed<16,4>, weight_t at least ap_fixed<8,4>, acc_t at least 20 total bits with 16 integer bits.",
        "Do not use unsafe tiny types such as ap_fixed<8,1> or ap_fixed<8,2>; previous attempts with those types failed golden accuracy.",
        "Do not omit AP_SAT on data_t; default AP_WRAP can break classification accuracy.",
        "Use HLS pragmas, local partial sums, unroll factors, and partitioned local arrays where useful.",
        "It is acceptable to use more DSP/LUT/FF than the resource candidate if throughput improves.",
        "A known verified high-resource parallel candidate used W1 dim=2 cyclic factor=16 and W2/W3 dim=2 cyclic factor=4 and reached latency/II=857; try to match or improve that.",
        "A later candidate reached latency/II=465 but LUT=68311, which exceeds xc7z020 LUT capacity=53200. Improve throughput while staying within device capacity.",
        "Do not completely partition the 784-element input array; a previous complete input partition was fast but exceeded LUT capacity. Prefer cyclic input partition with factor 8-16 or local block buffering.",
        "Avoid DATAFLOW with STREAM pragmas on ordinary arrays unless you use real hls::stream producer/consumer structure; a previous array-stream dataflow candidate synthesized to II=25282.",
        "Do not fully partition the large W1/W2/W3 constant matrices unless the code remains realistic for Vivado HLS 2018.3.",
        "Prefer local partial-sum arrays over full W1/W2/W3 partitioning.",
    ],
}


def _system_prompt(objective: str) -> str:
    rules = "\n".join(f"- {rule}" for rule in OBJECTIVE_RULES.get(objective, OBJECTIVE_RULES["resource"]))
    return f"{SYSTEM_PROMPT_BASE}\nObjective-specific rules:\n{rules}\n"


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


def _ap_fixed_parts(value: str) -> tuple[int, int] | None:
    text = _sanitize_ap_fixed_type(value, "")
    if not text:
        return None
    body = text[len("ap_fixed<") : -1]
    parts = [part.strip() for part in body.split(",")]
    return int(parts[0]), int(parts[1])


def _ap_fixed_tokens(value: str) -> set[str]:
    text = _sanitize_ap_fixed_type(value, "")
    if not text:
        return set()
    body = text[len("ap_fixed<") : -1]
    return {part.strip() for part in body.split(",")[2:]}


def _validate_plan_for_objective(plan: dict[str, Any], objective: str) -> dict[str, Any]:
    if objective == "resource":
        return {"status": "valid", "violations": []}
    checks = [
        ("data_type", 16, 4),
        ("weight_type", 8, 4),
        ("accum_type", 20, 16),
    ]
    violations: list[dict[str, Any]] = []
    for key, min_width, min_integer in checks:
        parts = _ap_fixed_parts(str(plan.get(key) or ""))
        if parts is None:
            violations.append({"field": key, "message": f"{key} must be a valid ap_fixed type."})
            continue
        width, integer = parts
        if width < min_width or integer < min_integer:
            violations.append(
                {
                    "field": key,
                    "message": f"{key}={plan.get(key)} is unsafe for {objective}; require width>={min_width}, integer>={min_integer}.",
                }
            )
    quantization_requirements = {
        "data_type": {"AP_RND", "AP_SAT"},
        "weight_type": {"AP_RND", "AP_SAT"},
        "accum_type": {"AP_RND"},
    }
    for key, required_tokens in quantization_requirements.items():
        tokens = _ap_fixed_tokens(str(plan.get(key) or ""))
        missing = sorted(required_tokens - tokens)
        if missing:
            violations.append(
                {
                    "field": key,
                    "message": f"{key}={plan.get(key)} is unsafe for {objective}; missing quantization/overflow mode(s): {', '.join(missing)}.",
                }
            )
    body = str(plan.get("function_body") or "")
    invalid_pragma_fragments = [
        "ARRAY_PARTITION variable=W1 type=cyclic",
        "ARRAY_PARTITION variable=W2 type=cyclic",
        "ARRAY_PARTITION variable=W3 type=cyclic",
        "ARRAY_PARTITION variable=W1 cyclic factor",
        "ARRAY_PARTITION variable=W2 cyclic factor",
        "ARRAY_PARTITION variable=W3 cyclic factor",
    ]
    for fragment in invalid_pragma_fragments:
        if fragment in body:
            violations.append(
                {
                    "field": "function_body",
                    "message": f"Vivado HLS 2018.3 rejected this ARRAY_PARTITION syntax before: {fragment}. Use 'variable=W1 dim=2 cyclic factor=N'.",
                }
            )
    if objective == "throughput" and "#pragma HLS STREAM" in body and "hls::stream" not in body:
        violations.append(
            {
                "field": "function_body",
                "message": "Throughput candidates must not use STREAM pragmas on ordinary arrays; previous array-stream dataflow code synthesized to poor II.",
            }
        )
    if objective == "throughput" and "ARRAY_PARTITION variable=input complete" in body:
        violations.append(
            {
                "field": "function_body",
                "message": "Throughput candidates must not completely partition the 784-element input array; previous complete input partition exceeded xc7z020 LUT capacity.",
            }
        )
    return {"status": "invalid" if violations else "valid", "violations": violations}


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
typedef acc_t accum_t;

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
    objective: str,
) -> str:
    goals = {
        "resource": "Generate a direct HLS candidate that minimizes LUT/DSP/FF/BRAM while keeping MNIST accuracy >= baseline.",
        "balanced": "Generate a balanced HLS candidate that improves latency/II versus the serial LLM resource candidate while retaining a substantial resource reduction versus hls4ml.",
        "throughput": "Generate a throughput-priority HLS candidate that improves latency and top interval/II as much as possible while preserving MNIST accuracy.",
    }
    def summarize_attempt(item: dict[str, Any]) -> dict[str, Any]:
        report = (item.get("verification") or {}).get("report") or {}
        synthesis = (item.get("verification") or {}).get("synthesis") or {}
        error = synthesis.get("error") or item.get("error")
        plan = item.get("plan") or {}
        return {
            "attempt": item.get("attempt"),
            "status": item.get("status"),
            "candidate_name": plan.get("candidate_name"),
            "effective_types": plan.get("effective_types"),
            "resource_score": item.get("resource_score"),
            "objective_score": item.get("objective_score"),
            "latency": report.get("latency"),
            "interval": report.get("interval"),
            "resources": report.get("resources"),
            "verification": synthesis.get("verification"),
            "error": error,
            "notes": [
                "If accuracy failed, do not repeat the same precision/indexing pattern.",
                "If compile failed due to a type name, use acc_t/accum_t consistently.",
            ],
        }

    prompt = {
        "goal": goals.get(objective, goals["resource"]),
        "objective": objective,
        "attempt": attempt,
        "model": {
            "topology": "784 -> Dense64 -> ReLU -> Dense32 -> ReLU -> Dense10",
            "input_range": "[0, 1]",
            "weights_available_as_constants": ["W1", "B1", "W2", "B2", "W3", "B3"],
        },
        "baseline_to_beat": baseline,
        "previous_attempt_results": [summarize_attempt(item) for item in previous_results[-5:]],
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
            "Do not change the top function signature.",
            "Use constants W1/B1/W2/B2/W3/B3 exactly as declared.",
            "Use W1[out][in], W2[out][in], and W3[out][in]. Never use W1[in][out].",
            "For balanced/throughput objectives, keep data_type integer bits >= 4, weight_type integer bits >= 4, and accum_type integer bits >= 16.",
            "For balanced/throughput objectives, data_type must include AP_RND and AP_SAT; weight_type should include AP_RND and AP_SAT; accum_type should include AP_RND.",
            "If you introduce partial-sum arrays, keep their sizes explicit and compatible with Vivado HLS 2018.3.",
            "Do not partition the full W1/W2/W3 matrices complete; prefer local partial arrays or limited unroll factors.",
            "Use Vivado HLS 2018.3 pragma syntax: '#pragma HLS ARRAY_PARTITION variable=W1 dim=2 cyclic factor=16'. Do not use 'type=cyclic'.",
            "For balanced objective, resource_score = LUT + FF + 200*DSP + 100*BRAM must stay <= 12000.",
            "For throughput objective, latency and interval should beat the hls4ml baseline latency=2135 and interval=1024, and resources must fit xc7z020 capacity: BRAM<=280, DSP<=220, FF<=106400, LUT<=53200.",
            "For throughput objective, do not use '#pragma HLS ARRAY_PARTITION variable=input complete'. Use cyclic factor 8-16 if you need parallel reads.",
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


def _merge_attempt_results_from_disk(output_root: Path, previous_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = list(previous_results)
    seen_attempts = {str(item.get("attempt")) for item in merged if item.get("attempt") is not None}
    for result_path in sorted(output_root.glob("attempt_*/attempt_result.json")):
        try:
            item = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        attempt = item.get("attempt")
        if attempt is None:
            continue
        attempt_key = str(attempt)
        if attempt_key not in seen_attempts:
            merged.append(item)
            seen_attempts.add(attempt_key)
    return sorted(merged, key=lambda item: _attempt_sort_key(item.get("attempt")))


def _attempt_sort_key(value: Any) -> tuple[int, str]:
    text = str(value or "")
    match = re.search(r"\d+", text)
    return (int(match.group(0)) if match else 0, text)


def _score(report: dict[str, Any]) -> int:
    resources = report.get("resources") or {}
    return int(resources.get("lut") or 0) + int(resources.get("ff") or 0) + 200 * int(resources.get("dsp") or 0) + 100 * int(resources.get("bram") or 0)


def _objective_score(report: dict[str, Any], objective: str, baseline: dict[str, Any]) -> float:
    resource_score = _score(report)
    latency = float((report.get("latency") or {}).get("max_cycles") or 10**12)
    interval = float((report.get("interval") or {}).get("max_ii") or latency)
    base_resource = float(baseline.get("resource_score") or 1)
    base_latency = float(baseline.get("latency_cycles") or 1)
    base_interval = float(baseline.get("interval_cycles") or base_latency)
    resource_ratio = resource_score / max(base_resource, 1.0)
    latency_ratio = latency / max(base_latency, 1.0)
    interval_ratio = interval / max(base_interval, 1.0)
    if objective == "throughput":
        infeasible_penalty = 1000.0 if not _resource_feasible(report, baseline) else 0.0
        return infeasible_penalty + 0.45 * latency_ratio + 0.45 * interval_ratio + 0.10 * resource_ratio
    if objective == "balanced":
        return 0.35 * latency_ratio + 0.35 * interval_ratio + 0.30 * resource_ratio
    return float(resource_score)


def _resource_feasible(report: dict[str, Any], baseline: dict[str, Any]) -> bool:
    if report.get("resource_feasible") is not None:
        return bool(report["resource_feasible"])
    resources = report.get("resources") or {}
    available = report.get("resource_available") or baseline.get("device_available") or {}
    return all(
        resources.get(key) is not None
        and available.get(key) is not None
        and int(resources[key]) <= int(available[key])
        for key in ("bram", "dsp", "ff", "lut")
    )


def _objective_met(report: dict[str, Any], objective: str, baseline: dict[str, Any]) -> bool:
    resource_score = _score(report)
    latency = float((report.get("latency") or {}).get("max_cycles") or 10**12)
    interval = float((report.get("interval") or {}).get("max_ii") or latency)
    if objective == "balanced":
        serial = baseline.get("known_resource_best_llm_candidate") or {}
        return (
            resource_score <= float(baseline.get("balanced_resource_budget") or baseline.get("resource_score") or 0)
            and latency < float(serial.get("latency_cycles") or 10**12)
            and interval < float(serial.get("interval_cycles") or 10**12)
            and _resource_feasible(report, baseline)
        )
    if objective == "throughput":
        return (
            latency < float(baseline.get("latency_cycles") or 0)
            and interval < float(baseline.get("interval_cycles") or 0)
            and _resource_feasible(report, baseline)
        )
    return resource_score < float(baseline.get("resource_score") or 0) and _resource_feasible(report, baseline)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate and verify direct LLM HLS candidates for the MNIST MLP.")
    parser.add_argument("--model", default="models/mnist_recognition/mnist_mlp_trained.onnx")
    parser.add_argument("--samples", default="models/mnist_recognition/mnist_test_inputs_20.dat")
    parser.add_argument("--labels", default="models/mnist_recognition/mnist_test_labels_20.json")
    parser.add_argument("--output-root", default=None)
    parser.add_argument("--objective", choices=["resource", "balanced", "throughput"], default="resource")
    parser.add_argument("--attempts", type=int, default=4)
    parser.add_argument("--required-correct", type=int, default=19)
    parser.add_argument("--clock-period", type=float, default=15.0)
    parser.add_argument("--part", default="xc7z020clg400-1")
    parser.add_argument("--vivado-hls-path", default=os.environ.get("DL_OP_TO_HLS_VIVADO_HLS_PATH") or r"D:\Xilinx\Vivado\2018.3\bin\vivado_hls.bat")
    parser.add_argument("--continue-run", action="store_true", help="Load existing summary/attempts and append more LLM repair attempts.")
    args = parser.parse_args()

    output_root_value = args.output_root or (
        "runs/llm_mnist_hls_candidate"
        if args.objective == "resource"
        else f"runs/llm_mnist_hls_candidate_{args.objective}"
    )
    output_root = (REPO_ROOT / output_root_value).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    weights = _load_onnx_weights((REPO_ROOT / args.model).resolve())
    samples, labels = _load_samples((REPO_ROOT / args.samples).resolve(), (REPO_ROOT / args.labels).resolve())
    reference_predictions = _reference_predictions(weights, samples)

    baseline = {
        "path": "hls4ml resource-priority best known",
        "accuracy": "19/20",
        "argmax_match": "20/20 against Python reference",
        "latency_cycles": 2135,
        "interval_cycles": 1024,
        "pipeline_type": "dataflow",
        "resources": {"bram": 47, "dsp": 64, "ff": 5999, "lut": 17899},
        "device_available": {"bram": 280, "dsp": 220, "ff": 106400, "lut": 53200},
        "resource_score": 41398,
        "balanced_resource_budget": 12000,
        "known_resource_best_llm_candidate": {
            "candidate": "mnist_narrow_accum_20",
            "latency_cycles": 157953,
            "interval_cycles": 157953,
            "pipeline_type": "none",
            "resources": {"bram": 18, "dsp": 0, "ff": 347, "lut": 899},
            "resource_score": 3046,
        },
        "known_parallel_llm_candidate": {
            "candidate": "balanced_UF16_inner_par",
            "latency_cycles": 857,
            "interval_cycles": 857,
            "pipeline_type": "none",
            "resources": {"bram": 0, "dsp": 0, "ff": 49485, "lut": 73605},
            "resource_score": 123090,
            "note": "Verified but high LUT/FF. Treat as throughput evidence, not balanced.",
        },
        "known_balanced_llm_candidate": {
            "candidate": "balanced_UF8_layerwise",
            "latency_cycles": 6776,
            "interval_cycles": 6776,
            "resources": {"bram": 24, "dsp": 0, "ff": 1391, "lut": 4158},
            "resource_score": 7949,
        },
        "known_throughput_infeasible_candidate": {
            "candidate": "throughput_pipe_II1",
            "latency_cycles": 465,
            "interval_cycles": 465,
            "resources": {"bram": 0, "dsp": 0, "ff": 38783, "lut": 68311},
            "resource_score": 107094,
            "reason": "LUT exceeds xc7z020 capacity 53200.",
        },
    }
    summary_path = output_root / "summary.json"
    previous_results: list[dict[str, Any]] = []
    if args.continue_run and summary_path.exists():
        existing_summary = json.loads(summary_path.read_text(encoding="utf-8"))
        previous_results = list(existing_summary.get("attempts") or [])
    if args.continue_run:
        previous_results = _merge_attempt_results_from_disk(output_root, previous_results)
    client = LLMClient()
    best: dict[str, Any] | None = None
    for previous in previous_results:
        report = ((previous.get("verification") or {}).get("report") or {})
        verification = (((previous.get("verification") or {}).get("synthesis") or {}).get("verification") or {})
        if previous.get("status") == "success" and report.get("status") == "success" and verification.get("passed") is True:
            previous["resource_score"] = _score(report)
            previous["objective_score"] = _objective_score(report, args.objective, baseline)
            previous["objective_met"] = _objective_met(report, args.objective, baseline)
            if previous["objective_met"] and (best is None or previous["objective_score"] < best.get("objective_score", 10**12)):
                best = previous

    last_attempt = max([int(item.get("attempt")) for item in previous_results if str(item.get("attempt") or "").isdigit()] or [0])
    for attempt in range(last_attempt + 1, last_attempt + max(0, args.attempts) + 1):
        new_best_this_attempt = False
        attempt_dir = output_root / f"attempt_{attempt:02d}"
        attempt_dir.mkdir(parents=True, exist_ok=True)
        candidate_dir = attempt_dir / "candidate"
        prompt = _prompt_for_plan(baseline=baseline, previous_results=previous_results, attempt=attempt, objective=args.objective)
        try:
            plan = client.complete_json(_system_prompt(args.objective), prompt, SCHEMA, temperature=0.15)
        except AgentRuntimeError as exc:
            failure = {"attempt": attempt, "status": "llm_failed", "error": exc.error.to_dict() if hasattr(exc, "error") else str(exc)}
            previous_results.append(failure)
            (attempt_dir / "attempt_result.json").write_text(json.dumps(failure, ensure_ascii=False, indent=2), encoding="utf-8")
            continue

        try:
            plan_guard = _validate_plan_for_objective(plan, args.objective)
            if plan_guard["status"] != "valid":
                result = {"attempt": attempt, "status": "guard_failed", "plan": plan, "plan_guard": plan_guard}
            else:
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
                        result["objective_score"] = _objective_score(report, args.objective, baseline)
                        result["objective_met"] = _objective_met(report, args.objective, baseline)
                        if result["objective_met"] and (best is None or result["objective_score"] < best.get("objective_score", 10**12)):
                            best = result
                            new_best_this_attempt = True
        except Exception as exc:
            result = {"attempt": attempt, "status": "exception", "plan": plan, "error": str(exc)}

        previous_results.append(result)
        (attempt_dir / "attempt_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

        if args.objective == "resource" and new_best_this_attempt and best and best.get("objective_met"):
            break

    summary = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "objective": args.objective,
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
