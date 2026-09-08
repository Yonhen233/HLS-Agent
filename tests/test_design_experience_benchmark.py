"""Test contracts and regression checks for test_design_experience_benchmark.py.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from dl_op_to_hls.benchmarks.design_experience_benchmark import (
    _metrics,
    build_design_experience_cases,
)


def test_design_experience_dataset_uses_method_cards_and_has_200_cases():
    """Verify the test_design_experience_dataset_uses_method_cards_and_has_200_cases contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    cards, cases = build_design_experience_cases()
    assert len(cards) == 20
    assert len(cases) == 200
    assert all(card["action"] and card["tradeoff"] and card["constraints"] for card in cards)
    assert all(case["annotation"] == "manual_method_label" for case in cases)


def test_design_experience_metrics_are_card_level_not_run_id_level():
    """Verify the test_design_experience_metrics_are_card_level_not_run_id_level contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    rows = [
        {
            "relevant_card_ids": ["dense_resource"],
            "returned_card_ids": ["dense_latency", "dense_resource", "matmul_resource"],
            "hard_negative_card_ids": ["dense_latency"],
        }
    ]
    metrics = _metrics(rows, 3)
    assert metrics["recall_at_k"] == 1.0
    assert metrics["precision_at_k"] == 1 / 3
    assert metrics["hard_negative_pollution"] == 1 / 3


def test_design_experience_labels_are_not_keyword_only():
    """Verify the test_design_experience_labels_are_not_keyword_only contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    _, cases = build_design_experience_cases()
    assert {case["relevant_card_ids"][0] for case in cases}.__len__() == 20
    assert all("manual_method_label" in case["annotation"] for case in cases)
