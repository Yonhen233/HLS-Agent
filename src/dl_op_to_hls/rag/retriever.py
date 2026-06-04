from __future__ import annotations

import json
import math
import re
from collections import Counter
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


class RagRetriever:
    def __init__(self, repository):
        self.repository = repository

    def retrieve(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        query_tokens = Counter(_tokenize(query))
        anchors = _anchor_tokens(query)
        scored: list[tuple[float, dict[str, Any]]] = []
        for row in self.repository.get_rag_chunks():
            text = sanitize_memory_text(row["chunk_text"])
            if not text:
                continue
            text_tokens = Counter(_tokenize(text))
            if anchors and not anchors.intersection(text_tokens):
                continue
            numerator = sum(query_tokens[token] * text_tokens[token] for token in query_tokens)
            if numerator == 0:
                continue
            query_norm = math.sqrt(sum(value * value for value in query_tokens.values()))
            text_norm = math.sqrt(sum(value * value for value in text_tokens.values()))
            score = numerator / max(query_norm * text_norm, 1e-9)
            scored.append(
                (
                    score,
                    {
                        "source_id": row["source_id"],
                        "score": round(score, 4),
                        "text": text,
                        "metadata": json.loads(row.get("metadata_json") or "{}"),
                    },
                )
            )
        scored.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in scored[:top_k]]
