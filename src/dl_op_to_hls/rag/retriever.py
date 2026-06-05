from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

from ..core.memory_hygiene import sanitize_memory_text

TOKEN_RE = re.compile(r"[A-Za-z0-9_<>.-]+")
GENERIC_QUERY_TOKENS = {
    "agent",
    "clock",
    "cycles",
    "demo",
    "dsp",
    "factor",
    "hls",
    "hls4ml",
    "high",
    "ii",
    "latency",
    "low",
    "model",
    "objective",
    "optimization",
    "operator",
    "path",
    "report",
    "resource",
    "reuse",
    "run",
    "suggestion",
    "timing",
    "vivado",
}


def _tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for token in TOKEN_RE.findall(text or ""):
        lowered = token.lower()
        tokens.append(lowered)
        tokens.extend(part for part in re.split(r"[_<>.\-]+", lowered) if part)
    return tokens


def _anchor_tokens(query: str) -> set[str]:
    return {
        token
        for token in _tokenize(query)
        if len(token) >= 4 and token not in GENERIC_QUERY_TOKENS and not token.isdigit()
    }


def _strong_anchor_tokens(query: str) -> set[str]:
    """Rare identifiers such as structured error names should not be diluted by generic overlap."""
    return {
        token
        for token in _anchor_tokens(query)
        if len(token) >= 10 or token.endswith("error") or token.endswith("notfounderror")
    }


def _score(query_tokens: Counter, text: str) -> float:
    text_tokens = Counter(_tokenize(text))
    numerator = sum(query_tokens[token] * text_tokens[token] for token in query_tokens)
    if numerator == 0:
        return 0.0
    query_norm = math.sqrt(sum(value * value for value in query_tokens.values()))
    text_norm = math.sqrt(sum(value * value for value in text_tokens.values()))
    return numerator / max(query_norm * text_norm, 1e-9)


def _source_tokens(row: dict[str, Any]) -> set[str]:
    metadata = row.get("metadata") or {}
    source_text = " ".join(
        str(item or "")
        for item in [
            row.get("source_id"),
            metadata.get("run_id"),
            metadata.get("source_id"),
            metadata.get("name"),
            metadata.get("op_type"),
            metadata.get("task_type"),
        ]
    )
    return set(_tokenize(source_text))


def _rank_adjustment(row: dict[str, Any], anchors: set[str], strong_anchors: set[str], text_tokens: set[str]) -> float:
    metadata = row.get("metadata") or {}
    source_type = str(metadata.get("source_type") or "")
    source_tokens = _source_tokens(row)
    adjustment = 0.0

    if anchors:
        adjustment += 0.12 * len(anchors.intersection(source_tokens))
        # If a run/source name points to a different task family, treat matches in
        # the body as likely second-order memory unless there is a source anchor.
        task_like_tokens = source_tokens.intersection({"dense", "matmul", "qkeras", "qonnx", "cnn", "mlp", "resnet18", "residual"})
        if task_like_tokens and not anchors.intersection(source_tokens):
            adjustment -= 0.12

    if strong_anchors:
        adjustment += 0.25 * len(strong_anchors.intersection(text_tokens))
        if source_type == "static_doc":
            # Playbooks are curated knowledge and should not be buried under many
            # duplicated run memories when the exact structured error is queried.
            adjustment += 0.35

    if source_type in {"memory_fact", "procedural_memory"}:
        adjustment += 0.04

    return adjustment


class RagRetriever:
    def __init__(self, repository, static_paths: list[str | Path] | None = None):
        self.repository = repository
        self.static_paths = [Path(path) for path in (static_paths or [])]

    def retrieve(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        query_tokens = Counter(_tokenize(query))
        anchors = _anchor_tokens(query)
        strong_anchors = _strong_anchor_tokens(query)
        scored_by_text: dict[str, tuple[float, dict[str, Any]]] = {}
        for row in self._candidate_rows():
            text = sanitize_memory_text(row["text"])
            if not text:
                continue
            text_tokens = set(_tokenize(text))
            if strong_anchors and not strong_anchors.intersection(text_tokens):
                continue
            if not strong_anchors and anchors and not anchors.intersection(text_tokens):
                continue
            score = _score(query_tokens, text)
            if score == 0:
                continue
            adjusted_score = score + _rank_adjustment(row, anchors, strong_anchors, text_tokens)
            result = {
                "source_id": row["source_id"],
                "score": round(adjusted_score, 4),
                "text": text,
                "metadata": row.get("metadata") or {},
            }
            dedupe_key = " ".join(text.lower().split())
            previous = scored_by_text.get(dedupe_key)
            if previous is None or adjusted_score > previous[0]:
                scored_by_text[dedupe_key] = (adjusted_score, result)
        scored = list(scored_by_text.values())
        scored.sort(key=lambda item: (item[0], str(item[1].get("source_id", ""))), reverse=True)
        return [item[1] for item in scored[:top_k]]

    def _candidate_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for row in self.repository.get_rag_chunks():
            rows.append(
                {
                    "source_id": row["source_id"],
                    "text": row["chunk_text"],
                    "metadata": json.loads(row.get("metadata_json") or "{}"),
                }
            )
        for fact in self.repository.list_memory_facts():
            rows.append(
                {
                    "source_id": f"memory_fact:{fact['id']}",
                    "text": fact["fact"],
                    "metadata": {
                        "source_type": "memory_fact",
                        "run_id": fact.get("source_run_id"),
                        "tags": json.loads(fact.get("tags_json") or "[]"),
                    },
                }
            )
        for skill in self.repository.list_skills():
            rows.append(
                {
                    "source_id": f"skill:{skill['id']}:{skill['name']}",
                    "text": f"{skill['name']} {skill['description']} {skill['steps_json']} {skill.get('trigger_conditions_json') or ''}",
                    "metadata": {
                        "source_type": "procedural_memory",
                        "run_id": skill.get("source_run_id"),
                        "name": skill["name"],
                    },
                }
            )
        for path in self.static_paths:
            if path.exists() and path.is_file():
                rows.append(
                    {
                        "source_id": str(path),
                        "text": path.read_text(encoding="utf-8", errors="ignore"),
                        "metadata": {"source_type": "static_doc"},
                    }
                )
        return rows
