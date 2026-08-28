import json

from dl_op_to_hls.benchmarks.operator_benchmark import audit_llm_pass3, run_operator_benchmark, wilson_rate
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
