from __future__ import annotations

import json
import math
import re
from collections import Counter
from typing import Any


TOKEN_RE = re.compile(r"[A-Za-z0-9_<>.-]+")


def _tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text or "")]


class RagRetriever:
    def __init__(self, repository):
        self.repository = repository

    def retrieve(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        query_tokens = Counter(_tokenize(query))
        scored: list[tuple[float, dict[str, Any]]] = []
        for row in self.repository.get_rag_chunks():
            text = row["chunk_text"]
            text_tokens = Counter(_tokenize(text))
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

