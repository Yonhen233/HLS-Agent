import json
from pathlib import Path

from dl_op_to_hls.benchmarks.operator_benchmark import audit_llm_pass3, run_operator_benchmark, wilson_rate
from dl_op_to_hls.benchmarks.operator_bad_cases import run_operator_bad_cases
from dl_op_to_hls.benchmarks.operator_onnx_cases import run_operator_onnx_cases
from dl_op_to_hls.benchmarks.operator_fair_comparison import analyze_template_vs_llm
from dl_op_to_hls.benchmarks.operator_support import build_support_matrix
from dl_op_to_hls.benchmarks.operator_suite_specs import all_suite_payloads


def test_wilson_rate_does_not_describe_one_of_one_as_stable():
    metric = wilson_rate(1, 1)
    assert metric["rate"] == 1.0
    assert metric["statistically_usable"] is False
    assert metric["status"] == "insufficient_data"


def test_operator_suite_manifests_have_required_sample_sizes():
    suites = all_suite_payloads()
    assert len(suites["operator_real_csim_suite.json"]["cases"]) == 18
    assert len(suites["operator_real_csynth_suite.json"]["cases"]) == 10
    assert len(suites["operator_llm_candidate_suite.json"]["cases"]) == 15
    assert len(suites["operator_bad_case_suite.json"]["cases"]) == 20


def test_operator_bad_case_suite_executes_all_production_guards(tmp_path):
    report = run_operator_bad_cases(tmp_path, "benchmarks/operator_bad_case_results.json")
    assert report["case_count"] == 20
    assert report["passed_count"] == 20
    assert report["false_success_rate"] == 0.0
    assert report["stale_artifact_acceptance"] == 0
    assert report["unsafe_candidate_acceptance"] == 0
    assert report["unsupported_fake_metric_rate"] == 0


def test_operator_onnx_suite_executes_real_positive_and_negative_graphs(tmp_path):
    source = Path(__file__).resolve().parents[1] / "benchmarks" / "operator_onnx_graph_suite.json"
    benchmark_dir = tmp_path / "benchmarks"
    benchmark_dir.mkdir()
    (benchmark_dir / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    report = run_operator_onnx_cases(tmp_path, "benchmarks/operator_onnx_graph_results.json")

    assert report["case_count"] == 26
    assert report["passed_count"] == 26
    assert report["positive_acceptance"] == 1.0
    assert report["negative_rejection"] == 1.0


def test_template_vs_llm_comparison_requires_same_contract_and_real_golden_evidence(tmp_path):
    runs = tmp_path / "runs"
    contract_task = {
        "op_type": "Dense", "input_shape": [16], "output_shape": [32], "dtype": "ap_fixed<16,6>",
        "target": {"part": "xc7z020clg400-1", "clock_period": 8},
        "optimization": {"objective": "latency", "reuse_factor": 1, "pipeline_ii": 1},
    }
    for run_id, path, latency in (("template_run", "fallback_template_path", 40), ("llm_run", "llm_candidate_path", 32)):
        run = runs / run_id
        run.mkdir(parents=True)
        (run / "state.json").write_text(
            json.dumps(
                {
                    "status": "success", "selected_path": path, "task": contract_task,
                        "verification": {"passed": True},
                        "report": {
                            "status": "success",
                            "latency": {"max_cycles": latency}, "interval": {"max_ii": 1},
                        "resources": {"dsp": 2, "bram": 0, "lut": 100, "ff": 80},
                        "timing": {"estimated_ns": 7.0, "met": True},
                    },
                }
            ),
            encoding="utf-8",
        )
        (run / "completion_gate.json").write_text(json.dumps({"production_ready": True}), encoding="utf-8")
        (run / "tool_evidence.json").write_text(
            json.dumps(
                {"receipts": [{"valid": True, "mock_evidence": False, "evidence_class": "real_csynth", "checks": [{"name": "golden_csim_passed", "passed": True}]}]}
            ),
            encoding="utf-8",
        )
        testbench_dir = run / ("candidate" if path == "llm_candidate_path" else "generated")
        testbench_dir.mkdir()
        (testbench_dir / "testbench.cpp").write_text(
            "(i % 5) - 2; o % 2; ((o + i) % 3) - 1; 0.001;",
            encoding="utf-8",
        )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"cases": [{"case_id": "dense", "operator": "Dense", "objective": "latency", "template_run_id": "template_run", "llm_run_id": "llm_run"}]}),
        encoding="utf-8",
    )

    report = analyze_template_vs_llm(tmp_path, manifest, "result.json")

    assert report["complete"] is True
    assert report["results"][0]["valid_fair_pair"] is True
    assert report["results"][0]["llm_minus_template"]["latency_cycles"] == -8


def test_operator_benchmark_writes_machine_readable_release(tmp_path):
    (tmp_path / "runs").mkdir()
    (tmp_path / "docs").mkdir()
    report = run_operator_benchmark(tmp_path, "runs/benchmarks/operator_release.json")
    assert report["functional"]["rate"]["denominator"] >= 90
    assert report["release_gates"]["functional_cases_at_least_90"] is True
    assert report["interview_ready"] is False
    output = tmp_path / "runs" / "benchmarks" / "operator_release.json"
    assert json.loads(output.read_text(encoding="utf-8"))["generation_policy"] == "llm_candidate_first"
    assert (tmp_path / "benchmarks" / "operator_support_matrix.json").exists()
    assert (tmp_path / "benchmarks" / "operator_llm_candidate_results.json").exists()


def test_verified_receipt_counts_both_real_csim_and_real_csynth(tmp_path):
    run_dir = tmp_path / "runs" / "verified_conv"
    run_dir.mkdir(parents=True)
    (run_dir / "state.json").write_text(
        json.dumps({"task": {"task_type": "operator", "op_type": "Conv2D"}}),
        encoding="utf-8",
    )
    (run_dir / "tool_evidence.json").write_text(
        json.dumps(
            {
                "receipts": [
                    {
                        "receipt_id": "verified-1",
                        "tool_name": "verify_candidate.run",
                        "status": "verified",
                        "valid": True,
                        "mock_evidence": False,
                        "evidence_class": "real_csynth",
                        "checks": [{"name": "golden_csim_passed", "passed": True}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    matrix = build_support_matrix([], tmp_path / "runs")
    conv = next(item for item in matrix["operators"] if item["operator"] == "Conv2D")
    assert conv["real_csim_count"] == 1
    assert conv["real_csynth_count"] == 1


def test_llm_pass3_reports_failures_without_best_of_filtering(tmp_path):
    runs = tmp_path / "runs"
    for operator in ("Dense", "MatMul", "ReLU", "Add", "ScaleShift"):
        for repeat in range(1, 4):
            run = runs / f"{operator.lower()}_{repeat}"
            run.mkdir(parents=True)
            passed = not (operator == "Dense" and repeat == 2)
            state = {
                "run_id": run.name,
                "task": {"task_type": "operator", "op_type": operator},
                "selected_path": "llm_candidate_path",
                "status": "success" if passed else "partial_success",
                "verification": {"passed": True},
                "report": {"status": "success", "timing": {"met": True}},
                "errors": [] if passed else [{"error_type": "VerificationFailedError"}],
                "todos": [],
            }
            (run / "state.json").write_text(json.dumps(state), encoding="utf-8")
            (run / "completion_gate.json").write_text(
                json.dumps({"passed": passed, "production_ready": passed}), encoding="utf-8"
            )
            (run / "tool_evidence.json").write_text(
                json.dumps({"receipts": [{
                    "valid": True,
                    "mock_evidence": False,
                    "evidence_class": "real_csynth",
                    "checks": [{"name": "golden_csim_passed", "passed": True}],
                }]}),
                encoding="utf-8",
            )

    result = audit_llm_pass3(runs)

    assert result["complete"] is True
    assert result["rate"]["numerator"] == 14
    assert result["rate"]["denominator"] == 15
    assert result["by_operator"]["Dense"]["numerator"] == 2
