from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

from ..core.memory_hygiene import sanitize_memory_text
from .semantic import SemanticRagEngine

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
ENTITY_TOKENS = {
    "cnn",
    "conv1d",
    "conv2d",
    "dense",
    "lstm",
    "matmul",
    "mlp",
    "mnist",
    "pooling",
    "qkeras",
    "qonnx",
    "resnet",
    "resnet18",
    "transformer",
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


def _entity_anchor_groups(query: str) -> list[set[str]]:
    """Extract identifiers that semantic similarity must not wash away."""
    groups: list[set[str]] = []
    for raw_token in TOKEN_RE.findall(query or ""):
        token = raw_token.lower()
        parts = {
            part
            for part in re.split(r"[_<>.\-]+", token)
            if len(part) >= 4 and part not in GENERIC_QUERY_TOKENS and part != "demo"
        }
        alpha_numeric = any(char.isalpha() for char in token) and any(char.isdigit() for char in token)
        known_entities = parts.intersection(ENTITY_TOKENS)
        is_entity = token in ENTITY_TOKENS or alpha_numeric or token.endswith("error") or bool(known_entities)
        if not is_entity:
            continue
        specific = {
            part
            for part in parts
            if any(char.isdigit() for char in part) or part.endswith("error") or part in ENTITY_TOKENS
        }
        groups.append(specific or known_entities or {token})
    return groups


def _matches_entity_anchors(query: str, row: dict[str, Any], text_tokens: set[str]) -> bool:
    groups = _entity_anchor_groups(query)
    if not groups:
        return True
    searchable = text_tokens.union(_source_tokens(row))
    return all(bool(group.intersection(searchable)) for group in groups)


def _score(query_tokens: Counter, text: str) -> float:
    text_tokens = Counter(_tokenize(text))
    numerator = sum(query_tokens[token] * text_tokens[token] for token in query_tokens)
    if numerator == 0:
        return 0.0
    query_norm = math.sqrt(sum(value * value for value in query_tokens.values()))
    text_norm = math.sqrt(sum(value * value for value in text_tokens.values()))
    return numerator / max(query_norm * text_norm, 1e-9)


def _fts_query(query: str) -> str:
    tokens = []
    for token in _tokenize(query):
        if len(token) >= 3 and token not in GENERIC_QUERY_TOKENS and token not in tokens:
            tokens.append(token)
    return " OR ".join(f'"{token}"' for token in tokens[:12])


def _trust_score(row: dict[str, Any]) -> float:
    metadata = row.get("metadata") or {}
    source_type = str(metadata.get("source_type") or row.get("source_type") or "")
    memory_type = str(metadata.get("memory_type") or "")
    if source_type == "static_doc":
        return 1.0
    if memory_type in {"verified_implementation", "parameter_experience"}:
        return 0.95
    if source_type in {"memory_fact", "procedural_memory", "unsupported_report"}:
        return 0.85
    return 0.7


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
            adjustment += 0.75

    if source_type in {"memory_fact", "procedural_memory"}:
        adjustment += 0.04

    return adjustment


class RagRetriever:
    def __init__(
        self,
        repository,
        static_paths: list[str | Path] | None = None,
        semantic_engine: SemanticRagEngine | None = None,
    ):
        self.repository = repository
        self.static_paths = [Path(path) for path in (static_paths or [])]
        self.semantic_engine = semantic_engine
        self.last_diagnostics: dict[str, Any] = {"mode": "lexical"}

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        domain: str | None = None,
        identity: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        query_tokens = Counter(_tokenize(query))
        anchors = _anchor_tokens(query)
        strong_anchors = _strong_anchor_tokens(query)
        fts_rows = self.repository.search_rag_fts(_fts_query(query), limit=max(20, top_k * 6)) if hasattr(self.repository, "search_rag_fts") else []
        fts_rank_by_id = {str(row.get("id")): index for index, row in enumerate(fts_rows, start=1)}
        candidates: list[dict[str, Any]] = []
        for row in self._candidate_rows():
            if domain and not self._matches_domain(row, domain):
                continue
            if not self._matches_identity(row, identity):
                continue
            text = sanitize_memory_text(row["text"])
            if not text:
                continue
            text_tokens = set(_tokenize(text))
            lexical_score = _score(query_tokens, text)
            fts_rank = fts_rank_by_id.get(str(row.get("id")))
            fts_score = 0.0 if fts_rank is None else 0.35 * (60.0 / (60.0 + fts_rank))
            trust = _trust_score(row)
            rank_adjustment = _rank_adjustment(row, anchors, strong_anchors, text_tokens)
            result = {
                "source_id": row["source_id"],
                "citation": self._citation(row),
                "text": text,
                "metadata": row.get("metadata") or {},
                "provenance": {
                    "source_type": (row.get("metadata") or {}).get("source_type") or row.get("source_type"),
                    "created_at": row.get("created_at"),
                    "trust_score": trust,
                },
                "retrieval": {
                    "lexical_score": round(lexical_score, 4),
                    "fts_rank": fts_rank,
                },
            }
            candidates.append(
                {
                    "row": {**row, "text": text},
                    "result": result,
                    "text_tokens": text_tokens,
                    "lexical_score": lexical_score,
                    "fts_score": fts_score,
                    "trust": trust,
                    "rank_adjustment": rank_adjustment,
                    "entity_anchor_match": _matches_entity_anchors(query, row, text_tokens),
                }
            )

        # Missing legacy vectors are backfilled only for this bounded lexical/trust
        # frontier; already-indexed rows still participate in full dense recall.
        candidates.sort(
            key=lambda item: (
                item["lexical_score"] + item["fts_score"] + max(-0.15, min(0.15, item["rank_adjustment"])),
                item["trust"],
            ),
            reverse=True,
        )

        scored = self._semantic_rank(query, candidates, top_k)
        if scored is None:
            scored = self._lexical_rank(candidates, anchors, strong_anchors)
        selected: list[dict[str, Any]] = []
        source_counts: Counter = Counter()
        for _, result in scored:
            source_id = str(result.get("source_id", ""))
            source_family = self._source_family(source_id)
            if source_counts[source_family] >= 2:
                continue
            selected.append(result)
            source_counts[source_family] += 1
            if len(selected) >= top_k:
                break
        return selected

    @staticmethod
    def _source_family(source_id: str) -> str:
        normalized = source_id.replace("\\", "/")
        if re.match(r"^[A-Za-z]:/", normalized):
            return normalized.lower()
        if normalized.startswith(("memory_fact:", "skill:")):
            return normalized.split(":", 1)[0]
        return normalized.split(":", 1)[0] if ":" in normalized and "://" not in normalized else normalized

    def _semantic_rank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        top_k: int,
    ) -> list[tuple[float, dict[str, Any]]] | None:
        if self.semantic_engine is None or not self.semantic_engine.config.enabled:
            return None
        semantic_scores, diagnostics = self.semantic_engine.recall(
            query,
            [item["row"] for item in candidates],
            self.repository,
        )
        recall_diagnostics = diagnostics
        self.last_diagnostics = diagnostics
        if not semantic_scores:
            if self.semantic_engine.config.allow_lexical_fallback:
                return None
            return []

        pre_ranked: list[tuple[float, dict[str, Any]]] = []
        for index, item in enumerate(candidates):
            if not item["entity_anchor_match"]:
                continue
            semantic_score = float(semantic_scores.get(index, -1.0))
            lexical_signal = min(1.0, max(0.0, item["lexical_score"] + item["fts_score"]))
            if semantic_score < self.semantic_engine.config.min_embedding_score and lexical_signal == 0.0:
                continue
            semantic_normalized = max(0.0, min(1.0, (semantic_score + 1.0) / 2.0))
            source_bonus = max(-0.15, min(0.15, item["rank_adjustment"] * 0.2))
            pre_score = 0.72 * semantic_normalized + 0.18 * lexical_signal + 0.10 * item["trust"] + source_bonus
            result = item["result"]
            result["retrieval"].update(
                {
                    "mode": "embedding_recall",
                    "embedding_model": self.semantic_engine.embedder.model_id,
                    "semantic_score": round(semantic_score, 4),
                    "pre_rerank_score": round(pre_score, 4),
                    "entity_anchor_guard_passed": True,
                }
            )
            pre_ranked.append((pre_score, result))
        pre_ranked.sort(key=lambda value: (value[0], str(value[1].get("source_id", ""))), reverse=True)
        pool_size = max(top_k, self.semantic_engine.config.candidate_pool_size)
        pool = pre_ranked[:pool_size]
        if not pool:
            return []
        for pre_rank, (_, result) in enumerate(pool, start=1):
            result["retrieval"]["pre_rerank_rank"] = pre_rank

        rerank_scores, rerank_diagnostics = self.semantic_engine.rerank(query, [item[1] for item in pool])
        self.last_diagnostics = {
            **recall_diagnostics,
            **rerank_diagnostics,
            "candidate_count": len(candidates),
            "reranked_count": len(pool),
        }
        final: list[tuple[float, dict[str, Any]]] = []
        for index, (pre_score, result) in enumerate(pool):
            retrieval = result["retrieval"]
            semantic_normalized = max(0.0, min(1.0, (float(retrieval["semantic_score"]) + 1.0) / 2.0))
            lexical_signal = min(1.0, max(0.0, float(retrieval["lexical_score"])))
            trust = float((result.get("provenance") or {}).get("trust_score") or 0.7)
            cross_score = rerank_scores.get(index)
            if cross_score is not None and cross_score < self.semantic_engine.min_reranker_score:
                continue
            if cross_score is None:
                final_score = 0.75 * semantic_normalized + 0.20 * lexical_signal + 0.05 * trust
                mode = "embedding_only"
            else:
                config = self.semantic_engine.config
                final_score = (
                    config.semantic_weight * semantic_normalized
                    + config.lexical_weight * lexical_signal
                    + config.reranker_weight * cross_score
                    + config.trust_weight * trust
                )
                mode = "embedding_cross_encoder"
            retrieval.update(
                {
                    "mode": mode,
                    "reranker_model": self.semantic_engine.reranker.model_id if cross_score is not None else None,
                    "cross_encoder_score": round(cross_score, 4) if cross_score is not None else None,
                    "hybrid_score": round(final_score, 4),
                }
            )
            result["score"] = round(final_score, 4)
            final.append((final_score, result))
        final.sort(key=lambda value: (value[0], str(value[1].get("source_id", ""))), reverse=True)
        deduplicated = self._deduplicate_scored(final)
        for final_rank, (_, result) in enumerate(deduplicated, start=1):
            result["retrieval"]["final_rank"] = final_rank
        return deduplicated

    def _lexical_rank(
        self,
        candidates: list[dict[str, Any]],
        anchors: set[str],
        strong_anchors: set[str],
    ) -> list[tuple[float, dict[str, Any]]]:
        self.last_diagnostics = {
            **self.last_diagnostics,
            "mode": "lexical_fallback" if self.semantic_engine is not None else "lexical",
        }
        scored: list[tuple[float, dict[str, Any]]] = []
        for item in candidates:
            text_tokens = item["text_tokens"]
            if strong_anchors and not strong_anchors.intersection(text_tokens):
                continue
            if not strong_anchors and anchors and not anchors.intersection(text_tokens):
                continue
            if item["lexical_score"] == 0:
                continue
            adjusted_score = (
                item["lexical_score"]
                + item["fts_score"]
                + item["rank_adjustment"]
                + 0.08 * item["trust"]
            )
            result = item["result"]
            result["score"] = round(adjusted_score, 4)
            result["retrieval"].update(
                {
                    "mode": self.last_diagnostics["mode"],
                    "hybrid_score": round(adjusted_score, 4),
                }
            )
            scored.append((adjusted_score, result))
        scored.sort(key=lambda value: (value[0], str(value[1].get("source_id", ""))), reverse=True)
        return self._deduplicate_scored(scored)

    @staticmethod
    def _deduplicate_scored(scored: list[tuple[float, dict[str, Any]]]) -> list[tuple[float, dict[str, Any]]]:
        by_text: dict[str, tuple[float, dict[str, Any]]] = {}
        for score, result in scored:
            key = " ".join(str(result.get("text") or "").lower().split())
            previous = by_text.get(key)
            if previous is None or score > previous[0]:
                by_text[key] = (score, result)
        return sorted(by_text.values(), key=lambda value: (value[0], str(value[1].get("source_id", ""))), reverse=True)

    @staticmethod
    def _matches_identity(row: dict[str, Any], identity: dict[str, Any] | None) -> bool:
        if not identity:
            return True
        metadata = row.get("metadata") or {}
        namespace = str(metadata.get("namespace") or "global")
        if namespace == "global" or metadata.get("source_type") == "static_doc":
            return True
        if namespace == "user" and metadata.get("user_id") != identity.get("user_id"):
            return False
        if namespace == "project" and metadata.get("project_id") != identity.get("project_id"):
            return False
        if namespace == "session" and metadata.get("session_id") != identity.get("session_id"):
            return False
        return True

    @staticmethod
    def _citation(row: dict[str, Any]) -> dict[str, Any]:
        metadata = row.get("metadata") or {}
        return {
            "source_id": row.get("source_id"),
            "chunk_id": row.get("id"),
            "start_line": metadata.get("start_line"),
            "end_line": metadata.get("end_line"),
        }

    def _matches_domain(self, row: dict[str, Any], domain: str) -> bool:
        metadata = row.get("metadata") or {}
        row_domain = metadata.get("domain")
        memory_type = metadata.get("memory_type")
        source_type = metadata.get("source_type")
        if row_domain == domain:
            return True
        if domain == "parameter":
            return memory_type in {"parameter_experience", "verified_implementation"} or source_type == "parameter_experience"
        if domain == "failure":
            return memory_type == "failure" or source_type in {"failure", "unsupported_report"}
        if domain == "optimization":
            return memory_type in {"optimization", "semantic"} or source_type in {"suggestions", "memory_fact", "procedural_memory"}
        if domain == "episodic":
            return memory_type == "episodic" or source_type in {"summary", "episodic"}
        return False

    def _candidate_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for row in self.repository.get_rag_chunks():
            rows.append(
                {
                    "id": row.get("id"),
                    "source_id": row["source_id"],
                    "source_type": row.get("source_type"),
                    "text": row["chunk_text"],
                    "metadata": json.loads(row.get("metadata_json") or "{}"),
                    "created_at": row.get("created_at"),
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
