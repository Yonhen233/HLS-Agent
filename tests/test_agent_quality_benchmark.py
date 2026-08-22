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
    _wilson_interval,
)


def test_wilson_interval_marks_tiny_samples_exploratory():
    tiny = _wilson_interval(1, 1)
    usable = _wilson_interval(18, 20)
    assert tiny["estimate"] == 1.0
    assert tiny["low"] < 0.5
    assert tiny["statistically_usable"] is False
    assert usable["statistically_usable"] is True


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


def test_rag_eval_reports_embedding_and_cross_encoder_usage():
    case = {"query": "semantic HLS retrieval", "top_k": 2, "relevant_source_ids": ["doc-b"]}
    results = [
        {
            "source_id": "doc-b",
            "text": "Relevant implementation evidence.",
            "retrieval": {
                "mode": "embedding_cross_encoder",
                "semantic_score": 0.72,
                "cross_encoder_score": 0.91,
                "pre_rerank_rank": 2,
                "final_rank": 1,
            },
        },
        {
            "source_id": "doc-a",
            "text": "Less relevant evidence.",
            "retrieval": {
                "mode": "embedding_cross_encoder",
                "semantic_score": 0.81,
                "cross_encoder_score": 0.08,
                "pre_rerank_rank": 1,
                "final_rank": 2,
            },
        },
    ]

    metrics = evaluate_rag_case(case, results)

    assert metrics["embedding_recall_usage_rate"] == 1.0
    assert metrics["cross_encoder_rerank_usage_rate"] == 1.0
    assert metrics["semantic_score_avg"] == 0.765
    assert metrics["cross_encoder_score_avg"] == 0.495
    assert metrics["rerank_mean_position_gain"] == 0.0


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


def test_collect_run_metrics_tracks_semantic_rag_runtime_modes(tmp_path):
    run_dir = tmp_path / "runs" / "semantic-rag"
    run_dir.mkdir(parents=True)
    (run_dir / "state.json").write_text(
        json.dumps({"run_id": "semantic-rag", "task": {}, "retrieved_memories": []}),
        encoding="utf-8",
    )
    (run_dir / "trace.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"event": "RagRetrieved", "retrieval_mode": "cross_encoder"}),
                json.dumps({"event": "RagRetrieved", "retrieval_mode": "lexical_fallback"}),
            ]
        ),
        encoding="utf-8",
    )

    metrics = collect_run_metrics(run_dir)

    assert metrics["rag_quality"]["retrieval_event_count"] == 2
    assert metrics["rag_quality"]["embedding_retrieval_count"] == 1
    assert metrics["rag_quality"]["cross_encoder_rerank_count"] == 1
    assert metrics["rag_quality"]["lexical_fallback_count"] == 1


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
            "benchmark_category": "operator_fallback",
            "agent_task_success": True,
            "report_status": "success",
            "llm_decision_count": 1,
            "llm_call_count": 1,
            "tool_call_count": 2,
            "specialist_event_count": 3,
            "toolchain_quality": {"applicable": True, "correct_for_selected_path": True},
            "trace_completeness": {"rate": 1.0},
            "repair_quality": {"failure_stage_count": 0, "repair_success": False},
            "unsupported_honesty": {"applicable": False, "honest": True},
            "cost": {"estimated_total_tokens": 120},
            "artifact_completeness": {"rate": 1.0},
            "rag_quality": {
                "contains_prior_experience_hint": False,
                "contains_matmul_for_resnet_boundary": False,
                "pollution_detected": False,
                "evidence_hit": True,
            },
            "semantic_quality": {"unsupported_status_correct": True, "unsupported_metric_suggestion_error": False},
            "synthesis": {"latency_max_cycles": 5},
        },
        {
            "run_id": "bad",
            "runtime_s": 20,
            "status": "success",
            "selected_path": "unsupported_path",
            "benchmark_category": "unsupported_recovery",
            "agent_task_success": True,
            "report_status": "missing",
            "llm_decision_count": 1,
            "llm_call_count": 0,
            "tool_call_count": 2,
            "specialist_event_count": 3,
            "toolchain_quality": {"applicable": True, "correct_for_selected_path": False},
            "trace_completeness": {"rate": 0.5},
            "repair_quality": {"failure_stage_count": 1, "repair_success": False},
            "unsupported_honesty": {"applicable": True, "honest": False},
            "cost": {"estimated_total_tokens": 80},
            "artifact_completeness": {"rate": 0.5},
            "rag_quality": {
                "contains_prior_experience_hint": True,
                "contains_matmul_for_resnet_boundary": False,
                "pollution_detected": True,
                "evidence_hit": False,
            },
            "semantic_quality": {"unsupported_status_correct": False, "unsupported_metric_suggestion_error": True},
            "synthesis": {"latency_max_cycles": None},
        },
    ]

    aggregate = aggregate_metrics(metrics)

    assert aggregate["runtime_s"]["median"] == 15.0
    assert aggregate["rag_pollution_rate"] == 0.5
    assert aggregate["artifact_completeness_avg"] == 0.75
    assert aggregate["vivado_metric_runs"] == ["ok"]
    assert aggregate["toolchain_selection_accuracy"] == 0.5
    assert aggregate["trace_completeness_avg"] == 0.75
    assert aggregate["task_success_rate_by_category"]["operator_fallback"] == 1.0


def test_collect_run_metrics_tracks_llm_candidate_harness(tmp_path):
    run_dir = tmp_path / "runs" / "llm_candidate_eval"
    run_dir.mkdir(parents=True)
    state = {
        "run_id": "llm_candidate_eval",
        "task": {"name": "scale_shift_llm", "task_type": "operator"},
        "status": "success",
        "selected_path": "llm_candidate_path",
        "selected_skill": "llm_candidate_verification_flow",
        "skill_usage_mode": "full",
        "report": {
            "status": "success",
            "latency": {"max_cycles": 45},
            "resources": {"dsp": 32, "lut": 3500},
        },
        "todos": [
            {
                "status": "completed",
                "assigned_tool": "llm.generate_candidate",
                "inputs": {},
            },
            {
                "status": "completed",
                "assigned_tool": "verify_candidate.run",
                "specialist_result": {"specialist_name": "VerificationSpecialist"},
            },
            {
                "status": "completed",
                "assigned_tool": "vivado.run_csynth",
                "specialist_result": {"specialist_name": "VivadoSpecialist"},
            },
        ],
        "errors": [],
    }
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    (run_dir / "trace.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"event": "LLMCallStarted"}),
                json.dumps({"event": "LLMCallFinished"}),
                json.dumps({"event": "LLMPlanGenerated"}),
                json.dumps({"event": "LLMPlanAccepted"}),
                json.dumps({"event": "LLMReActDecision"}),
                json.dumps({"event": "LLMCandidateGenerated"}),
                json.dumps({"event": "PreToolUse", "tool": "llm.generate_candidate"}),
                json.dumps({"event": "PreToolUse", "tool": "verify_candidate.run"}),
                json.dumps({"event": "PreToolUse", "tool": "vivado.run_csynth"}),
                json.dumps({"event": "PreToolUse", "tool": "vivado.parse_report"}),
            ]
        ),
        encoding="utf-8",
    )

    metrics = collect_run_metrics(run_dir)

    assert metrics["toolchain_quality"]["correct_for_selected_path"] is True
    assert metrics["llm_harness"]["plan_accepted"] is True
    assert metrics["llm_harness"]["candidate_generation_event_count"] == 1
    aggregate = aggregate_metrics([metrics])
    assert aggregate["selected_path_valid_rate"] == 1.0
    assert aggregate["llm_harness"]["candidate_generation_event_count_total"] == 1


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


def test_suite_expected_defaults_are_merged_and_case_values_override(tmp_path):
    suite_path = tmp_path / "suite.json"
    suite_path.write_text(
        json.dumps(
            {
                "expected_defaults": {"require_session": True, "max_llm_calls": 30},
                "cases": [
                    {
                        "id": "case_1",
                        "task": "task.json",
                        "expected": {"max_llm_calls": 5},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    case = load_suite_cases(suite_path)[0]

    assert case["expected"]["require_session"] is True
    assert case["expected"]["max_llm_calls"] == 5


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
                json.dumps({"event": "PreToolUse", "tool": "fallback.generate_operator_hls"}),
                json.dumps({"event": "PreToolUse", "tool": "vivado.run_csynth"}),
                json.dumps({"event": "PreToolUse", "tool": "vivado.parse_report"}),
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
            "toolchain_for_path": True,
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


def test_evaluate_suite_case_scores_llm_harness_contract(tmp_path):
    run_dir = tmp_path / "runs" / "llm_eval"
    run_dir.mkdir(parents=True)
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": "llm_eval",
                "session_id": "session_eval",
                "task": {"name": "scale_shift_llm", "task_type": "operator"},
                "status": "success",
                "selected_path": "llm_candidate_path",
                "selected_skill": "llm_candidate_verification_flow",
                "report": {"status": "success", "latency": {"max_cycles": 45}, "resources": {"dsp": 32}},
                "todos": [
                    {"status": "completed", "assigned_tool": "llm.generate_candidate", "inputs": {}},
                    {"status": "completed", "assigned_tool": "verify_candidate.run", "specialist_result": {"specialist_name": "VerificationSpecialist"}},
                ],
                "errors": [],
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "trace.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"event": "LLMCallStarted"}),
                json.dumps({"event": "LLMCallStarted"}),
                json.dumps({"event": "LLMPlanGenerated"}),
                json.dumps({"event": "LLMPlanAccepted"}),
                json.dumps({"event": "LLMCandidateGenerated"}),
                json.dumps({"event": "SessionCheckpointCreated"}),
                json.dumps({"event": "PreToolUse", "tool": "llm.generate_candidate", "args_hash": "1"}),
                json.dumps({"event": "PreToolUse", "tool": "verify_candidate.run", "args_hash": "2"}),
                json.dumps({"event": "PreToolUse", "tool": "vivado.run_csynth", "args_hash": "3"}),
                json.dumps({"event": "PreToolUse", "tool": "vivado.parse_report", "args_hash": "4"}),
            ]
        ),
        encoding="utf-8",
    )
    (run_dir / "agent_messages.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"message_type": "delegation_request", "correlation_id": "corr_1"}),
                json.dumps({"message_type": "delegation_result", "correlation_id": "corr_1"}),
            ]
        ),
        encoding="utf-8",
    )
    (run_dir / "run_budget.json").write_text(json.dumps({"total_tokens": 1800}), encoding="utf-8")
    case = {
        "id": "llm_case",
        "category": "llm_candidate_generation",
        "task": "examples/scale_shift_llm_candidate.json",
        "expected": {
            "allowed_statuses": ["success"],
            "selected_path": "llm_candidate_path",
            "selected_skill": "llm_candidate_verification_flow",
            "toolchain_for_path": True,
            "llm_plan_accepted": True,
            "min_llm_calls": 2,
            "min_llm_candidate_generations": 1,
            "max_llm_guard_rejections": 0,
            "require_session": True,
            "min_checkpoints": 1,
            "delegation_completion_min": 1.0,
            "max_duplicate_tool_call_rate": 0.0,
            "max_budget_exceeded": 0,
            "max_tool_schema_rejections": 0,
            "max_recorded_tokens": 2000,
            "max_tool_calls_run": 4,
        },
    }

    result = evaluate_suite_case(case, run_dir)

    assert result["passed"] is True


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
