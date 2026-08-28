from __future__ import annotations

import json
from pathlib import Path

from dl_op_to_hls.benchmarks.agent_interview_benchmark import (
    _matches_expected_task,
    render_markdown,
    run_context_ablation,
    run_guard_ablation,
    run_rag_ablation,
    run_recovery_idempotency_probes,
)

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]


def test_open_task_expectation_matching() -> None:
    task = {"task_type": "operator", "op_type": "Dense", "objective": "latency"}
    case = {"expected_task_type": "operator", "expected_op_type": "Dense", "expected_objective": "latency"}
    assert _matches_expected_task(task, case)
    assert not _matches_expected_task({**task, "op_type": "MatMul"}, case)


def test_interview_rag_ablation_uses_fixed_scoped_corpus() -> None:
    report = run_rag_ablation(WORKSPACE_ROOT)
    assert report["corpus_size"] == 12
    assert report["query_count"] == 9
    assert report["no_memory"]["macro_hit_at_k"] == 0.0
    assert report["production_retriever"]["macro_mrr"] >= 0.8
    assert report["production_retriever"]["macro_pollution_at_k"] <= 0.1
    assert report["production_retriever"]["macro_pollution_at_k"] < report["naive_lexical"]["macro_pollution_at_k"]


def test_guard_ablation_blocks_known_unsafe_candidates() -> None:
    report = run_guard_ablation(WORKSPACE_ROOT)
    assert report["case_count"] >= 1
    assert report["guard_enabled"]["unsafe_candidate_acceptance_rate"] == 0.0
    assert report["schema_only_ablation"]["unsafe_candidate_acceptance_rate"] == 1.0


def test_context_ablation_measures_specialist_isolation(temp_workspace: Path) -> None:
    run_dir = temp_workspace / "context_run"
    run_dir.mkdir()
    state = {
        "run_id": "run",
        "padding": "x" * 5000,
        "todos": [
            {
                "specialist_result": {
                    "summary": "compressed",
                    "context_usage": {"raw_bytes_read": 1000, "summary_bytes_returned": 100},
                }
            }
        ],
    }
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    report = run_context_ablation([run_dir])
    assert report["specialist_result_count"] == 1
    assert report["main_agent_context_reduction_p50"] > 0.9
    assert report["raw_to_summary_reduction_p50"] == 0.9


def test_recovery_and_idempotency_probes_use_production_components() -> None:
    report = run_recovery_idempotency_probes(WORKSPACE_ROOT)
    assert report["evidence_class"] == "controlled_production_components"
    assert report["rate"]["rate"] == 1.0
    assert {item["name"] for item in report["probes"]} == {
        "queue_enqueue_dedup",
        "exactly_once_commit_replay",
        "checkpoint_round_trip",
        "idempotent_tool_cache",
        "bounded_idempotent_retry",
    }


def test_interview_markdown_records_evidence_and_limitations() -> None:
    report = {
        "generated_at": "2026-08-28T00:00:00Z",
        "interview_ready": False,
        "historical_real_run_metrics": {
            "run_count": 22,
            "task_success_rate": 0.9,
            "false_success_rate": 0.0,
            "toolchain_selection_accuracy": 0.86,
            "trace_completeness_avg": 1.0,
            "artifact_completeness_avg": 1.0,
            "runtime_s": {"p50": 10, "p95": 20},
            "tokens_per_success": 100,
        },
        "open_task_generalization": {"rate": {"rate": 0.8, "numerator": 8, "denominator": 10}, "llm_calls": 20, "total_tokens": 100},
        "ablations": {
            "rag": {
                "no_memory": {"macro_mrr": 0.0},
                "naive_lexical": {"macro_mrr": 0.5, "macro_ndcg_at_k": 0.5, "macro_pollution_at_k": 0.2},
                "production_retriever": {"macro_mrr": 0.9, "macro_ndcg_at_k": 0.9, "macro_pollution_at_k": 0.05},
            },
            "guard": {
                "schema_only_ablation": {"unsafe_candidate_acceptance_rate": 1.0},
                "guard_enabled": {"unsafe_candidate_acceptance_rate": 0.0},
            },
            "context_and_specialists": {"main_agent_context_reduction_p50": 0.97},
        },
        "recovery_and_idempotency": {"rate": {"rate": 1.0, "numerator": 5, "denominator": 5}},
        "release_gates": {"example_gate": False},
        "limitations": ["Small samples are not population proof."],
    }
    markdown = render_markdown(report)
    assert "Interview Ready" in markdown
    assert "Small samples are not population proof." in markdown
    assert "example_gate" in markdown
