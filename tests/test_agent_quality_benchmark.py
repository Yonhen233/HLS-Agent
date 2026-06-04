import json
from pathlib import Path

from dl_op_to_hls.benchmarks.agent_quality_benchmark import (
    aggregate_metrics,
    collect_run_metrics,
    compare_runs,
    evaluate_rag_case,
    evaluate_suite_case,
    evaluate_suite_results,
    load_suite_cases,
)


def test_rag_eval_computes_standard_source_metrics():
    case = {"query": "Dense reuse", "top_k": 3, "relevant_source_ids": ["dense_doc"]}
    results = [
        {"source_id": "matmul_doc", "text": "MatMul reuse"},
        {"source_id": "dense_doc", "text": "Dense reuse factor"},
        {"source_id": "other_doc", "text": "Other"},
    ]

    metrics = evaluate_rag_case(case, results)

    assert metrics["precision_at_k"] == 0.3333
    assert metrics["recall_at_k"] == 1.0
    assert metrics["hit_at_k"] == 1.0
    assert metrics["mrr"] == 0.5
    assert metrics["ndcg_at_k"] > 0


def test_rag_eval_computes_term_coverage_and_pollution():
    case = {
        "query": "ResNet18 boundary unsupported",
        "top_k": 2,
        "relevant_terms": ["resnet18", "boundary", "unsupported"],
        "required_terms": ["resnet18", "boundary"],
        "irrelevant_terms": ["matmul"],
    }
    results = [
        {"source_id": "resnet", "text": "ResNet18 boundary unsupported report"},
        {"source_id": "bad", "text": "MatMul reuse factor"},
    ]

    metrics = evaluate_rag_case(case, results)

    assert metrics["relevant_term_coverage_at_k"] == 1.0
    assert metrics["pollution_at_k"] == 0.5
    assert metrics["precision_at_k"] == 0.5


def test_rag_eval_pollution_uses_retrieved_text_not_source_id():
    case = {
        "query": "VivadoNotFoundError recoverable skipped synthesis",
        "top_k": 2,
        "relevant_source_ids": ["vivado_failure_playbook.md"],
        "irrelevant_terms": ["resnet18"],
    }
    results = [
        {
            "source_id": "skill:1:vivado_synthesis_skill",
            "text": "VivadoNotFoundError is recoverable and synthesis can be skipped.",
            "metadata": {"run_id": "resnet18_boundary_demo"},
        },
        {"source_id": "docs/vivado_failure_playbook.md", "text": "VivadoNotFoundError playbook."},
    ]

    metrics = evaluate_rag_case(case, results)

    assert metrics["pollution_at_k"] == 0.0


def test_collect_run_metrics_flags_unsupported_semantic_errors(tmp_path):
    run_dir = tmp_path / "runs" / "resnet_run"
    run_dir.mkdir(parents=True)
    state = {
        "run_id": "resnet_run",
        "task": {"name": "resnet18_boundary_demo", "task_type": "model"},
        "status": "success",
        "selected_path": "unsupported_path",
        "report": {"status": "missing"},
        "suggestions": ["Increase reuse_factor to reduce DSP."],
        "retrieved_memories": [{"text": "MatMul resource hint"}],
    }
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    (run_dir / "trace.jsonl").write_text("", encoding="utf-8")

    metrics = collect_run_metrics(run_dir)

    assert metrics["rag_quality"]["contains_matmul_for_resnet_boundary"] is True
    assert metrics["semantic_quality"]["unsupported_status_correct"] is False
    assert metrics["semantic_quality"]["unsupported_metric_suggestion_error"] is True


def test_compare_runs_quantifies_fix_delta(tmp_path):
    before = {
        "run_id": "before",
        "runtime_s": 184.0,
        "status": "success",
        "selected_path": "unsupported_path",
        "rag_quality": {"contains_prior_experience_hint": False, "contains_matmul_for_resnet_boundary": True},
        "semantic_quality": {"unsupported_status_correct": False, "unsupported_metric_suggestion_error": True},
        "llm_decision_count": 5,
        "tool_call_count": 10,
    }
    after = {
        "run_id": "after",
        "runtime_s": 74.0,
        "status": "partial_success",
        "selected_path": "unsupported_path",
        "rag_quality": {"contains_prior_experience_hint": False, "contains_matmul_for_resnet_boundary": False},
        "semantic_quality": {"unsupported_status_correct": True, "unsupported_metric_suggestion_error": False},
        "llm_decision_count": 5,
        "tool_call_count": 8,
    }

    comparison = compare_runs(before, after)

    assert comparison["runtime_delta_pct"] == -59.78
    assert comparison["rag_pollution_removed"] is True
    assert comparison["unsupported_status_fixed"] is True
    assert comparison["unsupported_metric_suggestions_fixed"] is True


def test_aggregate_metrics_reports_common_rates():
    metrics = [
        {
            "run_id": "ok",
            "runtime_s": 10,
            "status": "success",
            "selected_path": "fallback_template_path",
            "report_status": "success",
            "llm_decision_count": 1,
            "tool_call_count": 2,
            "specialist_event_count": 3,
            "artifact_completeness": {"rate": 1.0},
            "rag_quality": {"contains_prior_experience_hint": False, "contains_matmul_for_resnet_boundary": False},
            "semantic_quality": {"unsupported_status_correct": True, "unsupported_metric_suggestion_error": False},
            "synthesis": {"latency_max_cycles": 5},
        },
        {
            "run_id": "bad",
            "runtime_s": 20,
            "status": "success",
            "selected_path": "unsupported_path",
            "report_status": "missing",
            "llm_decision_count": 1,
            "tool_call_count": 2,
            "specialist_event_count": 3,
            "artifact_completeness": {"rate": 0.5},
            "rag_quality": {"contains_prior_experience_hint": True, "contains_matmul_for_resnet_boundary": False},
            "semantic_quality": {"unsupported_status_correct": False, "unsupported_metric_suggestion_error": True},
            "synthesis": {"latency_max_cycles": None},
        },
    ]

    aggregate = aggregate_metrics(metrics)

    assert aggregate["runtime_s"]["median"] == 15.0
    assert aggregate["rag_pollution_rate"] == 0.5
    assert aggregate["artifact_completeness_avg"] == 0.75
    assert aggregate["vivado_metric_runs"] == ["ok"]


def test_default_agent_capability_suite_is_curated():
    cases = load_suite_cases(Path("benchmarks/agent_capability_suite.json"))

    assert len(cases) >= 10
    assert {case["category"] for case in cases} >= {
        "operator_fallback",
        "model_hls4ml",
        "unsupported_recovery",
        "toolchain_recovery",
    }
    assert any(case["id"] == "toolchain_vivado_missing_recovery" for case in cases)


def test_evaluate_suite_case_scores_expected_agent_contract(tmp_path):
    run_dir = tmp_path / "runs" / "dense_eval"
    (run_dir / "memory").mkdir(parents=True)
    for artifact in [
        "state.json",
        "todos.json",
        "trace.jsonl",
        "artifacts.json",
        "summary.md",
        "suggestions.md",
        "memory/short_term.json",
        "memory/compressed_context.json",
        "memory/memory_candidates.json",
        "memory/promoted_memories.json",
        "memory/retrieved_memories.json",
    ]:
        path = run_dir / artifact
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
    state = {
        "run_id": "dense_eval",
        "task": {"name": "dense_16x32", "task_type": "operator"},
        "status": "success",
        "selected_path": "fallback_template_path",
        "report": {
            "status": "success",
            "latency": {"max_cycles": 45},
            "resources": {"dsp": 32, "lut": 3500},
        },
        "todos": [
            {"status": "completed", "specialist_result": {"specialist_name": "VivadoSpecialist"}},
            {"status": "completed", "specialist_result": {"specialist_name": "MemorySpecialist"}},
        ],
        "errors": [],
        "promoted_memories": [{"id": 1}],
    }
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    (run_dir / "trace.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"event": "RunStarted"}),
                json.dumps({"event": "SpecialistSelected", "specialist": "VivadoSpecialist"}),
                json.dumps({"event": "SpecialistResultMerged", "specialist": "VivadoSpecialist"}),
                json.dumps({"event": "RunFinished"}),
            ]
        ),
        encoding="utf-8",
    )
    (run_dir / "artifacts.json").write_text(json.dumps({"artifacts": []}), encoding="utf-8")
    case = {
        "id": "dense_case",
        "category": "operator_fallback",
        "task": "examples/dense_operator.json",
        "expected": {
            "allowed_statuses": ["success"],
            "selected_path": "fallback_template_path",
            "report_status": "success",
            "artifact_completeness_min": 1.0,
            "required_trace_events": ["RunStarted", "SpecialistSelected", "SpecialistResultMerged", "RunFinished"],
            "required_specialists": ["VivadoSpecialist", "MemorySpecialist"],
            "forbidden_error_types": ["PermissionDeniedError"],
            "max_todo_failed": 0,
            "vivado_metrics_required": True,
            "min_promoted_memories": 1,
        },
    }

    result = evaluate_suite_case(case, run_dir)

    assert result["passed"] is True
    assert result["score"] == 1.0


def test_evaluate_suite_results_aggregates_category_scores(tmp_path):
    run_dir = tmp_path / "runs" / "bad"
    run_dir.mkdir(parents=True)
    (run_dir / "benchmark_case.json").write_text(json.dumps({"case_id": "bad_case", "iteration": 1}), encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": "bad",
                "task": {"name": "bad", "task_type": "operator"},
                "status": "failed",
                "selected_path": None,
                "report": {"status": "missing"},
                "todos": [{"status": "failed"}],
                "errors": [{"error_type": "PermissionDeniedError"}],
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "trace.jsonl").write_text("", encoding="utf-8")
    suite = [
        {
            "id": "bad_case",
            "category": "routing",
            "task": "x.json",
            "expected": {
                "allowed_statuses": ["success"],
                "selected_path": "fallback_template_path",
                "forbidden_error_types": ["PermissionDeniedError"],
            },
        }
    ]

    result = evaluate_suite_results([run_dir], suite)

    assert result["case_count"] == 1
    assert result["pass_rate"] == 0.0
    assert result["failed_cases"] == ["bad_case"]
    assert result["category_scores"]["routing"] < 1.0
