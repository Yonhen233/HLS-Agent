"""Test contracts and regression checks for test_historical_rag_benchmark.py.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

import json
from pathlib import Path

from dl_op_to_hls.benchmarks.historical_rag_benchmark import _timed_evaluation, build_historical_rag_cases


def _write_run(root: Path, run_id: str, family: str, objective: str, *, real: bool = True, verified: bool = True) -> Path:
    """Verify the _write_run contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        root: Value supplied by the caller and validated by the surrounding schema.
        run_id: Value supplied by the caller and validated by the surrounding schema.
        family: Value supplied by the caller and validated by the surrounding schema.
        objective: Value supplied by the caller and validated by the surrounding schema.
        real: Value supplied by the caller and validated by the surrounding schema.
        verified: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    run_dir = root / "runs" / run_id
    run_dir.mkdir(parents=True)
    advice = run_dir / "parameter_advice.json"
    advice.write_text(json.dumps({"recommendations": []}), encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "objective": objective,
                "task": {"task_type": "operator", "op_type": family, "input_shape": [16], "output_shape": [32]},
                "pipeline_status": {"functional_verified": verified, "synthesis_success": True},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "tool_evidence.json").write_text(
        json.dumps(
            {
                "receipts": [
                    {
                        "evidence_class": "real_csynth" if real else "unit",
                        "valid": True,
                        "mock_evidence": not real,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return advice


def test_historical_rag_cases_are_evidence_gated_and_leave_one_out(tmp_path: Path) -> None:
    """Verify the test_historical_rag_cases_are_evidence_gated_and_leave_one_out contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    first = _write_run(tmp_path, "dense_a", "Dense", "resource")
    second = _write_run(tmp_path, "dense_b", "Dense", "resource")
    mock = _write_run(tmp_path, "dense_mock", "Dense", "resource", real=False)
    _write_run(tmp_path, "matmul_single", "MatMul", "resource")
    unverified = _write_run(tmp_path, "dense_unverified", "Dense", "resource", verified=False)

    result = build_historical_rag_cases(
        tmp_path,
        [str(first.resolve()), str(second.resolve()), str(mock.resolve()), str(unverified.resolve())],
    )

    assert result["eligible_run_count"] == 2
    assert len(result["cases"]) == 2
    assert result["excluded"]["no_real_csynth_receipt"] == 1
    assert result["excluded"]["not_functionally_verified"] == 1
    for case in result["cases"]:
        assert case["anchor_source_id"] not in case["relevant_source_ids"]
        assert len(case["relevant_source_ids"]) == 1
        assert case["anchor_run_id"] not in case["relevant_run_ids"]
        assert len(case["relevant_run_ids"]) == 1


def test_historical_evaluation_excludes_anchor_and_deduplicates_sources() -> None:
    """Verify the test_historical_evaluation_excludes_anchor_and_deduplicates_sources contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    cases = [
        {
            "case_id": "history:a",
            "query": "Dense resource",
            "domain": "parameter",
            "top_k": 2,
            "anchor_source_id": "run:a",
            "anchor_run_id": "a",
            "relevant_source_ids": ["run:b"],
            "relevant_run_ids": ["b"],
            "task_family": "Dense",
            "objective": "resource",
        }
    ]

    metrics = _timed_evaluation(
        cases,
        lambda query, top_k, domain, metadata_filter: [
            {"source_id": "run:a", "text": "anchor", "metadata": {"run_id": "a"}},
            {"source_id": "run:b:advice", "text": "peer chunk one", "metadata": {"run_id": "b"}},
            {"source_id": "memory:peer-b", "text": "peer chunk two", "metadata": {"run_id": "b"}},
            {"source_id": "run:c", "text": "other", "metadata": {"run_id": "c"}},
        ],
    )

    case = metrics["cases"][0]
    assert case["top_source_ids"] == ["run:b:advice", "run:c"]
    assert case["hit_at_k"] == 1.0
    assert case["case_id"] == "history:a"
