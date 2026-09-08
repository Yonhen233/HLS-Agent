from dl_op_to_hls.benchmarks.design_experience_benchmark import (
    _metrics,
    build_design_experience_cases,
)


def test_design_experience_dataset_uses_method_cards_and_has_200_cases():
    cards, cases = build_design_experience_cases()
    assert len(cards) == 20
    assert len(cases) == 200
    assert all(card["action"] and card["tradeoff"] and card["constraints"] for card in cards)
    assert all(case["annotation"] == "manual_method_label" for case in cases)


def test_design_experience_metrics_are_card_level_not_run_id_level():
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
    _, cases = build_design_experience_cases()
    assert {case["relevant_card_ids"][0] for case in cases}.__len__() == 20
    assert all("manual_method_label" in case["annotation"] for case in cases)
