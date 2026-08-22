from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any


def _sigmoid(value: float) -> float:
    value = max(-60.0, min(60.0, value))
    return 1.0 / (1.0 + math.exp(-value))


class HLSRerankerCalibrator:
    def __init__(self, semantic_engine):
        self.engine = semantic_engine

    def run(self, dataset_path: str | Path, *, max_pollution_rate: float = 0.05) -> dict[str, Any]:
        path = Path(dataset_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        cases = payload.get("cases") or []
        if not cases:
            raise ValueError("Hard-negative dataset contains no cases.")
        pairs: list[tuple[str, str]] = []
        labels: list[int] = []
        boundaries: list[tuple[int, int]] = []
        for case in cases:
            start = len(pairs)
            pairs.append((case["query"], case["positive"]))
            labels.append(1)
            for negative in case.get("hard_negatives", []):
                pairs.append((case["query"], negative))
                labels.append(0)
            boundaries.append((start, len(pairs)))
        raw = self.engine.reranker.predict(pairs, batch_size=self.engine.config.rerank_batch_size)
        scores = [_sigmoid(float(value)) for value in raw]
        threshold, threshold_metrics = self._select_threshold(scores, labels, max_pollution_rate)
        reciprocal_ranks = []
        pair_wins = 0
        pair_total = 0
        case_results = []
        for case, (start, end) in zip(cases, boundaries):
            case_scores = scores[start:end]
            ranking = sorted(range(len(case_scores)), key=lambda index: case_scores[index], reverse=True)
            positive_rank = ranking.index(0) + 1
            reciprocal_ranks.append(1.0 / positive_rank)
            pair_wins += sum(case_scores[0] > score for score in case_scores[1:])
            pair_total += max(0, len(case_scores) - 1)
            case_results.append({"id": case["id"], "positive_rank": positive_rank, "scores": case_scores})
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return {
            "status": "calibrated",
            "dataset": str(path),
            "dataset_hash": digest,
            "dataset_version": payload.get("version"),
            "reranker_model": self.engine.reranker.model_id,
            "case_count": len(cases),
            "pair_count": len(pairs),
            "threshold": threshold,
            "threshold_metrics": threshold_metrics,
            "pairwise_accuracy": round(pair_wins / max(pair_total, 1), 6),
            "mrr": round(sum(reciprocal_ranks) / len(reciprocal_ranks), 6),
            "top1_accuracy": round(sum(item == 1.0 for item in reciprocal_ranks) / len(reciprocal_ranks), 6),
            "cases": case_results,
        }

    @staticmethod
    def save(report: dict[str, Any], output_path: str | Path) -> Path:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        return target

    @staticmethod
    def export_training_triples(dataset_path: str | Path, output_path: str | Path) -> Path:
        payload = json.loads(Path(dataset_path).read_text(encoding="utf-8"))
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as handle:
            for case in payload.get("cases", []):
                for negative in case.get("hard_negatives", []):
                    handle.write(json.dumps({"query": case["query"], "positive": case["positive"], "negative": negative, "case_id": case["id"]}, ensure_ascii=False) + "\n")
        return target

    @staticmethod
    def _select_threshold(scores: list[float], labels: list[int], max_pollution_rate: float) -> tuple[float, dict[str, float]]:
        candidates = sorted(set([0.0, 1.0, *scores]))
        best = None
        for threshold in candidates:
            predictions = [score >= threshold for score in scores]
            tp = sum(prediction and label == 1 for prediction, label in zip(predictions, labels))
            fp = sum(prediction and label == 0 for prediction, label in zip(predictions, labels))
            fn = sum((not prediction) and label == 1 for prediction, label in zip(predictions, labels))
            negatives = max(1, sum(label == 0 for label in labels))
            precision = tp / max(1, tp + fp)
            recall = tp / max(1, tp + fn)
            f1 = 2 * precision * recall / max(precision + recall, 1e-12)
            pollution = fp / negatives
            candidate = (pollution <= max_pollution_rate, f1, recall, threshold, precision, pollution)
            if best is None or candidate[:3] > best[:3]:
                best = candidate
        assert best is not None
        _, f1, recall, threshold, precision, pollution = best
        return float(threshold), {"precision": round(precision, 6), "recall": round(recall, 6), "f1": round(f1, 6), "pollution_rate": round(pollution, 6)}
