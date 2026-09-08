"""rag layer implementation for retriever.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

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
    "add",
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
    "relu",
    "resnet",
    "resnet18",
    "scaleshift",
    "transformer",
}


def _tokenize(text: str) -> list[str]:
    """Implement the internal _tokenize helper.

    Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

    Args:
        text: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    tokens: list[str] = []
    for token in TOKEN_RE.findall(text or ""):
        lowered = token.lower()
        tokens.append(lowered)
        tokens.extend(part for part in re.split(r"[_<>.\-]+", lowered) if part)
    return tokens


def _anchor_tokens(query: str) -> set[str]:
    """Implement the internal _anchor_tokens helper.

    Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

    Args:
        query: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    return {
        token
        for token in _tokenize(query)
        if len(token) >= 4 and token not in GENERIC_QUERY_TOKENS and not token.isdigit()
    }


def _strong_anchor_tokens(query: str) -> set[str]:
    """Structured error identities must not be diluted by generic overlap."""
    return {
        token
        for token in _anchor_tokens(query)
        if token.endswith("error") or token.endswith("notfounderror")
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
        known_entities = parts.intersection(ENTITY_TOKENS)
        # Shapes, fixed-point spellings, FPGA parts, and clock values are soft
        # retrieval features. Treating every alphanumeric token as a hard
        # identity constraint caused valid same-operator memories to vanish.
        is_entity = token in ENTITY_TOKENS or token.endswith("error") or bool(known_entities)
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
    """Implement the internal _matches_entity_anchors helper.

    Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

    Args:
        query: Value supplied by the caller and validated by the surrounding schema.
        row: Value supplied by the caller and validated by the surrounding schema.
        text_tokens: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    groups = _entity_anchor_groups(query)
    if not groups:
        return True
    searchable = text_tokens.union(_source_tokens(row))
    return all(bool(group.intersection(searchable)) for group in groups)


def _score(query_tokens: Counter, text: str) -> float:
    """Implement the internal _score helper.

    Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

    Args:
        query_tokens: Value supplied by the caller and validated by the surrounding schema.
        text: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    text_tokens = Counter(_tokenize(text))
    numerator = sum(query_tokens[token] * text_tokens[token] for token in query_tokens)
    if numerator == 0:
        return 0.0
    query_norm = math.sqrt(sum(value * value for value in query_tokens.values()))
    text_norm = math.sqrt(sum(value * value for value in text_tokens.values()))
    return numerator / max(query_norm * text_norm, 1e-9)


def _fts_query(query: str) -> str:
    """Implement the internal _fts_query helper.

    Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

    Args:
        query: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    tokens = []
    for token in _tokenize(query):
        if len(token) >= 3 and token not in GENERIC_QUERY_TOKENS and token not in tokens:
            tokens.append(token)
    return " OR ".join(f'"{token}"' for token in tokens[:12])


def _trust_score(row: dict[str, Any]) -> float:
    """Implement the internal _trust_score helper.

    Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

    Args:
        row: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
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
    """Implement the internal _source_tokens helper.

    Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

    Args:
        row: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
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
    """Implement the internal _rank_adjustment helper.

    Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

    Args:
        row: Value supplied by the caller and validated by the surrounding schema.
        anchors: Value supplied by the caller and validated by the surrounding schema.
        strong_anchors: Value supplied by the caller and validated by the surrounding schema.
        text_tokens: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    metadata = row.get("metadata") or {}
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
    return adjustment


class RagRetriever:
    """Coordinate RagRetriever within the retriever boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    def __init__(
        self,
        repository,
        static_paths: list[str | Path] | None = None,
        semantic_engine: SemanticRagEngine | None = None,
    ):
        """Implement the internal __init__ helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            repository: Value supplied by the caller and validated by the surrounding schema.
            static_paths: Value supplied by the caller and validated by the surrounding schema.
            semantic_engine: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
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
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Execute retrieve at the retriever boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            query: Value supplied by the caller and validated by the surrounding schema.
            top_k: Value supplied by the caller and validated by the surrounding schema.
            domain: Value supplied by the caller and validated by the surrounding schema.
            identity: Value supplied by the caller and validated by the surrounding schema.
            metadata_filter: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
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
            if not self._matches_metadata_filter(row, metadata_filter):
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

        if domain == "parameter":
            verified_candidates = [
                item
                for item in candidates
                if item["entity_anchor_match"] and self._is_verified_parameter_evidence(item["row"])
            ]
            if verified_candidates:
                candidates = verified_candidates
                for item in candidates:
                    item["result"]["retrieval"]["evidence_gate_passed"] = True

        # Missing legacy vectors are backfilled only for this bounded lexical/trust
        # frontier; already-indexed rows still participate in full dense recall.
        candidates.sort(
            key=lambda item: (
                item["lexical_score"] + item["fts_score"] + max(-0.15, min(0.15, item["rank_adjustment"])),
                str(item["result"].get("source_id", "")),
            ),
            reverse=True,
        )

        scored = self._semantic_rank(query, candidates, top_k)
        if scored is None:
            scored = self._lexical_rank(candidates, anchors, strong_anchors)
        selected: list[dict[str, Any]] = []
        experience_counts: Counter = Counter()
        for _, result in scored:
            experience_key = self._experience_key(result)
            if experience_counts[experience_key] >= 1:
                continue
            selected.append(result)
            experience_counts[experience_key] += 1
            if len(selected) >= top_k:
                break
        return selected

    @staticmethod
    def _source_family(source_id: str) -> str:
        """Implement the internal _source_family helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            source_id: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        normalized = source_id.replace("\\", "/")
        if re.match(r"^[A-Za-z]:/", normalized):
            return normalized.lower()
        if normalized.startswith(("memory_fact:", "skill:")):
            return normalized.split(":", 1)[0]
        return normalized.split(":", 1)[0] if ":" in normalized and "://" not in normalized else normalized

    @classmethod
    def _experience_key(cls, result: dict[str, Any]) -> str:
        """Implement the internal _experience_key helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            result: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        metadata = result.get("metadata") or {}
        run_id = str(metadata.get("run_id") or "").strip().lower()
        if run_id:
            return f"run:{run_id}"
        return f"source:{cls._source_family(str(result.get('source_id') or ''))}"

    @classmethod
    def _limit_candidates_per_experience(
        cls,
        scored: list[tuple[float, dict[str, Any]]],
        *,
        limit: int,
    ) -> list[tuple[float, dict[str, Any]]]:
        """Implement the internal _limit_candidates_per_experience helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            scored: Value supplied by the caller and validated by the surrounding schema.
            limit: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        counts: Counter = Counter()
        selected: list[tuple[float, dict[str, Any]]] = []
        for score, result in scored:
            key = cls._experience_key(result)
            if counts[key] >= limit:
                continue
            counts[key] += 1
            selected.append((score, result))
        return selected

    def _semantic_rank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        top_k: int,
    ) -> list[tuple[float, dict[str, Any]]] | None:
        """Implement the internal _semantic_rank helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            query: Value supplied by the caller and validated by the surrounding schema.
            candidates: Value supplied by the caller and validated by the surrounding schema.
            top_k: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
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

        eligible: list[tuple[int, dict[str, Any], float, float]] = []
        for index, item in enumerate(candidates):
            if not item["entity_anchor_match"]:
                continue
            semantic_score = float(semantic_scores.get(index, -1.0))
            lexical_signal = min(1.0, max(0.0, item["lexical_score"] + item["fts_score"]))
            evidence_gated = bool(item["result"]["retrieval"].get("evidence_gate_passed"))
            if (
                semantic_score < self.semantic_engine.config.min_embedding_score
                and lexical_signal == 0.0
                and not evidence_gated
            ):
                continue
            eligible.append((index, item, semantic_score, lexical_signal))

        # Domain/entity filtering happens before either ranking. RRF therefore
        # fuses the same safe candidate set instead of allowing a second
        # retriever to reintroduce out-of-domain evidence.
        lexical_order = sorted(
            eligible,
            key=lambda value: (
                value[3] + max(-0.15, min(0.15, value[1]["rank_adjustment"])),
                str(value[1]["result"].get("source_id", "")),
            ),
            reverse=True,
        )
        semantic_order = sorted(
            eligible,
            key=lambda value: (value[2], str(value[1]["result"].get("source_id", ""))),
            reverse=True,
        )
        lexical_rank = {value[0]: rank for rank, value in enumerate(lexical_order, start=1)}
        semantic_rank = {value[0]: rank for rank, value in enumerate(semantic_order, start=1)}
        fusion_method = self.semantic_engine.config.fusion_method
        if fusion_method != "rrf":
            return None
        rrf_k = self.semantic_engine.config.rrf_k
        rrf_scores = {
            index: (1.0 / (rrf_k + lexical_rank[index])) + (1.0 / (rrf_k + semantic_rank[index]))
            for index, _, _, _ in eligible
        }

        pre_ranked: list[tuple[float, dict[str, Any]]] = []
        for index, item, semantic_score, lexical_signal in eligible:
            pre_score = rrf_scores[index]
            result = item["result"]
            result["retrieval"].update(
                {
                    "mode": "rrf_recall",
                    "embedding_model": self.semantic_engine.embedder.model_id,
                    "semantic_score": round(semantic_score, 4),
                    "pre_rerank_score": round(pre_score, 4),
                    "lexical_rank": lexical_rank[index],
                    "semantic_rank": semantic_rank[index],
                    "rrf_k": rrf_k,
                    "rrf_score": round(pre_score, 6),
                    "entity_anchor_guard_passed": True,
                }
            )
            pre_ranked.append((pre_score, result))
        pre_ranked.sort(key=lambda value: (value[0], str(value[1].get("source_id", ""))), reverse=True)
        # A long artifact can yield dozens of chunks. Bound its representation
        # before CrossEncoder reranking so chunk count cannot crowd independent
        # historical runs out of the candidate pool.
        pre_ranked = self._limit_candidates_per_experience(pre_ranked, limit=2)
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
            "experience_limited_candidate_count": len(pre_ranked),
            "reranked_count": len(pool),
        }
        final: list[tuple[float, dict[str, Any]]] = []
        for index, (pre_score, result) in enumerate(pool):
            retrieval = result["retrieval"]
            cross_score = rerank_scores.get(index)
            evidence_gated = bool(retrieval.get("evidence_gate_passed"))
            if (
                cross_score is not None
                and cross_score < self.semantic_engine.min_reranker_score
                and not evidence_gated
            ):
                continue
            if cross_score is None:
                final_score = float(retrieval["rrf_score"])
                mode = "rrf_embedding"
            else:
                # The learned Cross-Encoder owns the final ordering. RRF is a
                # deterministic tie-breaker, not an arbitrary score blend.
                final_score = float(cross_score)
                mode = "embedding_cross_encoder"
            retrieval.update(
                {
                    "mode": mode,
                    "reranker_model": self.semantic_engine.reranker.model_id if cross_score is not None else None,
                    "cross_encoder_score": round(cross_score, 4) if cross_score is not None else None,
                    "fusion_method": fusion_method,
                    "hybrid_score": round(final_score, 4),
                }
            )
            result["score"] = round(final_score, 4)
            final.append((final_score, result))
        final.sort(
            key=lambda value: (
                value[0],
                float((value[1].get("retrieval") or {}).get("rrf_score") or 0.0),
                str(value[1].get("source_id", "")),
            ),
            reverse=True,
        )
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
        """Implement the internal _lexical_rank helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            candidates: Value supplied by the caller and validated by the surrounding schema.
            anchors: Value supplied by the caller and validated by the surrounding schema.
            strong_anchors: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        self.last_diagnostics = {
            **self.last_diagnostics,
            "mode": "lexical_fallback" if self.semantic_engine is not None else "lexical",
        }
        scored: list[tuple[float, dict[str, Any], int]] = []
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
            )
            result = item["result"]
            metadata = result.get("metadata") or {}
            curated_playbook = int(
                metadata.get("source_type") == "static_doc"
                and bool(str(result.get("text") or ""))
                and bool(strong_anchors)
                and bool(strong_anchors.intersection(item["text_tokens"]))
            )
            result["score"] = round(adjusted_score, 4)
            result["retrieval"].update(
                {
                    "mode": self.last_diagnostics["mode"],
                    "hybrid_score": round(adjusted_score, 4),
                    "curated_playbook_precedence": bool(curated_playbook),
                }
            )
            # This is a hard provenance policy for curated playbooks, not a
            # numeric trust bonus: a matching playbook outranks duplicate run
            # memories, while unrelated static documents remain ineligible.
            scored.append((adjusted_score, result, curated_playbook))
        scored.sort(
            key=lambda value: (value[2], value[0], str(value[1].get("source_id", ""))),
            reverse=True,
        )
        deduplicated = self._deduplicate_scored([(score, result) for score, result, _ in scored])
        deduplicated.sort(
            key=lambda value: (
                int(bool((value[1].get("retrieval") or {}).get("curated_playbook_precedence"))),
                value[0],
                str(value[1].get("source_id", "")),
            ),
            reverse=True,
        )
        return deduplicated

    @classmethod
    def _deduplicate_scored(cls, scored: list[tuple[float, dict[str, Any]]]) -> list[tuple[float, dict[str, Any]]]:
        """Implement the internal _deduplicate_scored helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            scored: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        by_text: dict[str, tuple[float, dict[str, Any]]] = {}
        for score, result in scored:
            normalized_text = " ".join(str(result.get("text") or "").lower().split())
            key = f"{cls._experience_key(result)}\n{normalized_text}"
            previous = by_text.get(key)
            if previous is None or score > previous[0]:
                by_text[key] = (score, result)
        return sorted(by_text.values(), key=lambda value: (value[0], str(value[1].get("source_id", ""))), reverse=True)

    @staticmethod
    def _matches_identity(row: dict[str, Any], identity: dict[str, Any] | None) -> bool:
        """Implement the internal _matches_identity helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            row: Value supplied by the caller and validated by the surrounding schema.
            identity: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
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
    def _matches_metadata_filter(row: dict[str, Any], metadata_filter: dict[str, Any] | None) -> bool:
        """Implement the internal _matches_metadata_filter helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            row: Value supplied by the caller and validated by the surrounding schema.
            metadata_filter: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        if not metadata_filter:
            return True
        metadata = row.get("metadata") or {}
        for key, expected in metadata_filter.items():
            if expected is None or expected == "":
                continue
            actual = metadata.get(key)
            if isinstance(expected, (list, tuple, set)):
                allowed = {str(item).strip().lower() for item in expected}
                if str(actual or "").strip().lower() not in allowed:
                    return False
            elif str(actual or "").strip().lower() != str(expected).strip().lower():
                return False
        return True

    @staticmethod
    def _citation(row: dict[str, Any]) -> dict[str, Any]:
        """Implement the internal _citation helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            row: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        metadata = row.get("metadata") or {}
        return {
            "source_id": row.get("source_id"),
            "chunk_id": row.get("id"),
            "start_line": metadata.get("start_line"),
            "end_line": metadata.get("end_line"),
        }

    def _matches_domain(self, row: dict[str, Any], domain: str) -> bool:
        """Implement the internal _matches_domain helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            row: Value supplied by the caller and validated by the surrounding schema.
            domain: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
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

    @staticmethod
    def _is_verified_parameter_evidence(row: dict[str, Any]) -> bool:
        """Implement the internal _is_verified_parameter_evidence helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            row: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        metadata = row.get("metadata") or {}
        return bool(
            metadata.get("evidence_verified") is True
            or metadata.get("memory_type") == "verified_implementation"
        )

    def _candidate_rows(self) -> list[dict[str, Any]]:
        """Implement the internal _candidate_rows helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Returns:
            The structured value promised by the function signature.
        """
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
