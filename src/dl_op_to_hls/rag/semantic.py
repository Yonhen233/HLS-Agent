"""rag layer implementation for semantic.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

import hashlib
import math
import threading
import json
from pathlib import Path
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Protocol


_MODEL_INFERENCE_LOCK = threading.RLock()


def _content_hash(text: str) -> str:
    """Implement the internal _content_hash helper.

    Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

    Args:
        text: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _cosine(left: list[float], right: list[float]) -> float:
    """Implement the internal _cosine helper.

    Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

    Args:
        left: Value supplied by the caller and validated by the surrounding schema.
        right: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    if not left or len(left) != len(right):
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    return numerator / max(left_norm * right_norm, 1e-12)


def _sigmoid(value: float) -> float:
    """Implement the internal _sigmoid helper.

    Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

    Args:
        value: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    if value >= 0:
        factor = math.exp(-min(value, 60.0))
        return 1.0 / (1.0 + factor)
    factor = math.exp(max(value, -60.0))
    return factor / (1.0 + factor)


class EmbeddingBackend(Protocol):
    """Coordinate EmbeddingBackend within the semantic boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    model_id: str

    def encode(self, texts: list[str], *, batch_size: int) -> list[list[float]]:
        """Execute encode at the semantic boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            texts: Value supplied by the caller and validated by the surrounding schema.
            batch_size: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        ...


class RerankerBackend(Protocol):
    """Coordinate RerankerBackend within the semantic boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    model_id: str

    def predict(self, pairs: list[tuple[str, str]], *, batch_size: int) -> list[float]:
        """Execute predict at the semantic boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            pairs: Value supplied by the caller and validated by the surrounding schema.
            batch_size: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        ...


@dataclass(frozen=True)
class SemanticRagConfig:
    """Coordinate SemanticRagConfig within the semantic boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    enabled: bool = True
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    candidate_pool_size: int = 32
    embedding_batch_size: int = 32
    rerank_batch_size: int = 16
    # Rank fusion is scale-independent. Legacy score weights are intentionally
    # not part of the ranking contract because they were not learned from a
    # held-out relevance set.
    fusion_method: str = "rrf"
    rrf_k: int = 60
    min_embedding_score: float = 0.12
    min_reranker_score: float = 0.02
    local_files_only: bool = True
    allow_lexical_fallback: bool = True
    max_online_embeddings: int = 64
    cache_size: int = 2048
    vector_backend: str = "faiss_hnsw"
    vector_index_path: str | None = None
    ann_min_rows: int = 256
    hnsw_m: int = 32
    hnsw_ef_search: int = 96
    calibration_path: str | None = None

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> "SemanticRagConfig":
        """Execute from_mapping at the semantic boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            value: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        value = value or {}
        fields = cls.__dataclass_fields__
        payload = {key: item for key, item in value.items() if key in fields}
        fusion_method = str(payload.get("fusion_method", "rrf")).lower()
        if fusion_method != "rrf":
            raise ValueError(f"Unsupported RAG fusion_method: {fusion_method}; only rrf is supported")
        payload["fusion_method"] = fusion_method
        payload["rrf_k"] = max(1, int(payload.get("rrf_k", 60)))
        return cls(**payload)


class SentenceTransformerBackend:
    """Coordinate SentenceTransformerBackend within the semantic boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    _models: dict[tuple[str, bool], Any] = {}
    _errors: dict[tuple[str, bool], str] = {}
    _lock = threading.RLock()

    def __init__(self, model_id: str, *, local_files_only: bool = False):
        """Implement the internal __init__ helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            model_id: Value supplied by the caller and validated by the surrounding schema.
            local_files_only: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        self.model_id = model_id
        self.local_files_only = local_files_only

    def _model(self):
        """Implement the internal _model helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Returns:
            The structured value promised by the function signature.
        """
        key = (self.model_id, self.local_files_only)
        with self._lock:
            if key in self._errors:
                raise RuntimeError(self._errors[key])
            if key not in self._models:
                from sentence_transformers import SentenceTransformer  # type: ignore

                try:
                    model_source = self._model_source()
                    self._models[key] = SentenceTransformer(
                        model_source,
                        local_files_only=self.local_files_only,
                    )
                except Exception as exc:
                    self._errors[key] = f"{type(exc).__name__}: {exc}"
                    raise
            return self._models[key]

    def _model_source(self) -> str:
        """Implement the internal _model_source helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Returns:
            The structured value promised by the function signature.
        """
        if not self.local_files_only:
            return self.model_id
        from huggingface_hub import snapshot_download  # type: ignore

        return snapshot_download(self.model_id, local_files_only=True)

    def encode(self, texts: list[str], *, batch_size: int) -> list[list[float]]:
        """Execute encode at the semantic boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            texts: Value supplied by the caller and validated by the surrounding schema.
            batch_size: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        if not texts:
            return []
        with _MODEL_INFERENCE_LOCK:
            values = self._model().encode(
                texts,
                batch_size=max(1, batch_size),
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
        return [[float(item) for item in vector] for vector in values]


class CrossEncoderBackend:
    """Coordinate CrossEncoderBackend within the semantic boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    _models: dict[tuple[str, bool], Any] = {}
    _errors: dict[tuple[str, bool], str] = {}
    _lock = threading.RLock()

    def __init__(self, model_id: str, *, local_files_only: bool = False):
        """Implement the internal __init__ helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            model_id: Value supplied by the caller and validated by the surrounding schema.
            local_files_only: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        self.model_id = model_id
        self.local_files_only = local_files_only

    def _model(self):
        """Implement the internal _model helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Returns:
            The structured value promised by the function signature.
        """
        key = (self.model_id, self.local_files_only)
        with self._lock:
            if key in self._errors:
                raise RuntimeError(self._errors[key])
            if key not in self._models:
                from sentence_transformers import CrossEncoder  # type: ignore

                try:
                    model_source = self._model_source()
                    self._models[key] = CrossEncoder(
                        model_source,
                        local_files_only=self.local_files_only,
                    )
                except Exception as exc:
                    self._errors[key] = f"{type(exc).__name__}: {exc}"
                    raise
            return self._models[key]

    def _model_source(self) -> str:
        """Implement the internal _model_source helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Returns:
            The structured value promised by the function signature.
        """
        if not self.local_files_only:
            return self.model_id
        from huggingface_hub import snapshot_download  # type: ignore

        return snapshot_download(self.model_id, local_files_only=True)

    def predict(self, pairs: list[tuple[str, str]], *, batch_size: int) -> list[float]:
        """Execute predict at the semantic boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            pairs: Value supplied by the caller and validated by the surrounding schema.
            batch_size: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        if not pairs:
            return []
        with _MODEL_INFERENCE_LOCK:
            values = self._model().predict(
                pairs,
                batch_size=max(1, batch_size),
                show_progress_bar=False,
            )
        return [float(item) for item in values]


class SemanticRagEngine:
    """Two-stage semantic retrieval with persistent document vectors and bounded caches."""

    def __init__(
        self,
        config: SemanticRagConfig | None = None,
        *,
        embedder: EmbeddingBackend | None = None,
        reranker: RerankerBackend | None = None,
    ):
        """Implement the internal __init__ helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            config: Value supplied by the caller and validated by the surrounding schema.
            embedder: Value supplied by the caller and validated by the surrounding schema.
            reranker: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        self.config = config or SemanticRagConfig()
        self.embedder = embedder or SentenceTransformerBackend(
            self.config.embedding_model,
            local_files_only=self.config.local_files_only,
        )
        self.reranker = reranker or CrossEncoderBackend(
            self.config.reranker_model,
            local_files_only=self.config.local_files_only,
        )
        self._vector_cache: OrderedDict[str, list[float]] = OrderedDict()
        self._rerank_cache: OrderedDict[str, float] = OrderedDict()
        self._embedding_error: str | None = None
        self._reranker_error: str | None = None
        self._ann_error: str | None = None
        self._ann_index_count: int | None = None
        self._lock = threading.RLock()
        self.calibrated_min_reranker_score: float | None = None
        self.calibration_diagnostics: dict[str, Any] = {}
        self._load_calibration()
        self.vector_index = None
        if self.config.vector_backend == "faiss_hnsw" and self.config.vector_index_path:
            from .vector_index import FaissHNSWIndex

            self.vector_index = FaissHNSWIndex(
                self.config.vector_index_path,
                model_id=self.embedder.model_id,
                m=self.config.hnsw_m,
                ef_search=self.config.hnsw_ef_search,
            )

    @property
    def embedding_available(self) -> bool:
        """Execute embedding_available at the semantic boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Returns:
            The structured value promised by the function signature.
        """
        return self.config.enabled and self._embedding_error is None

    @property
    def reranker_available(self) -> bool:
        """Execute reranker_available at the semantic boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Returns:
            The structured value promised by the function signature.
        """
        return self.config.enabled and self._reranker_error is None

    @property
    def min_reranker_score(self) -> float:
        """Execute min_reranker_score at the semantic boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Returns:
            The structured value promised by the function signature.
        """
        return self.calibrated_min_reranker_score if self.calibrated_min_reranker_score is not None else self.config.min_reranker_score

    def index_rows(self, rows: list[dict[str, Any]], repository: Any) -> dict[str, Any]:
        """Execute index_rows at the semantic boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            rows: Value supplied by the caller and validated by the surrounding schema.
            repository: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        if not self.config.enabled or not rows:
            return {"status": "disabled", "embeddings_indexed": 0}
        chunk_ids = [int(row["id"]) for row in rows if row.get("id") is not None]
        existing = (
            repository.get_rag_embeddings(chunk_ids, self.embedder.model_id)
            if chunk_ids and hasattr(repository, "get_rag_embeddings")
            else {}
        )
        missing_rows = []
        for row in rows:
            text = str(row.get("text") or row.get("chunk_text") or "")
            chunk_id = row.get("id")
            stored = existing.get(int(chunk_id)) if chunk_id is not None else None
            if stored and stored.get("content_hash") == _content_hash(text):
                continue
            missing_rows.append((row, text))
        if not missing_rows:
            return {
                "status": "success",
                "embeddings_indexed": 0,
                "embeddings_reused": len(rows),
                "model_id": self.embedder.model_id,
            }
        unique_texts: dict[str, str] = {}
        for _, text in missing_rows:
            unique_texts.setdefault(_content_hash(text), text)
        try:
            encoded = self._encode_documents(list(unique_texts.values()))
        except Exception as exc:
            self._embedding_error = f"{type(exc).__name__}: {exc}"
            return {"status": "fallback", "embeddings_indexed": 0, "error": self._embedding_error}
        vectors_by_hash = {
            content_hash: vector
            for content_hash, vector in zip(unique_texts, encoded)
        }
        records = []
        for row, text in missing_rows:
            vector = vectors_by_hash[_content_hash(text)]
            chunk_id = row.get("id")
            if chunk_id is None:
                continue
            records.append(
                {
                    "chunk_id": int(chunk_id),
                    "model_id": self.embedder.model_id,
                    "content_hash": _content_hash(text),
                    "embedding": vector,
                }
            )
        if records and hasattr(repository, "upsert_rag_embeddings"):
            repository.upsert_rag_embeddings(records)
        return {
            "status": "success",
            "embeddings_indexed": len(records),
            "embeddings_reused": len(rows) - len(missing_rows),
            "unique_texts_encoded": len(unique_texts),
            "model_id": self.embedder.model_id,
        }

    def recall(self, query: str, rows: list[dict[str, Any]], repository: Any) -> tuple[dict[int, float], dict[str, Any]]:
        """Execute recall at the semantic boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            query: Value supplied by the caller and validated by the surrounding schema.
            rows: Value supplied by the caller and validated by the surrounding schema.
            repository: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        if not self.config.enabled or not rows:
            return {}, self.diagnostics("disabled")
        try:
            query_vector = self._encode_query(query)
            ann = self._ann_recall(query_vector, rows, repository)
            if ann is not None:
                return ann
            document_vectors, vector_stats = self._document_vectors(rows, repository)
            scores = {
                index: _cosine(query_vector, vector)
                for index, vector in document_vectors.items()
            }
            return scores, {**self.diagnostics("embedding"), **vector_stats}
        except Exception as exc:
            self._embedding_error = f"{type(exc).__name__}: {exc}"
            return {}, self.diagnostics("lexical_fallback")

    def _ann_recall(self, query_vector: list[float], rows: list[dict[str, Any]], repository: Any):
        """Implement the internal _ann_recall helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            query_vector: Value supplied by the caller and validated by the surrounding schema.
            rows: Value supplied by the caller and validated by the surrounding schema.
            repository: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        if self.vector_index is None or len(rows) < self.config.ann_min_rows or not hasattr(repository, "list_rag_embeddings"):
            return None
        try:
            coverage = repository.rag_embedding_coverage(self.embedder.model_id) if hasattr(repository, "rag_embedding_coverage") else {}
            embedded_count = int(coverage.get("embedded_chunks") or 0)
            index_loaded = getattr(self.vector_index, "_index", None) is not None
            if index_loaded and self._ann_index_count == embedded_count and embedded_count > 0:
                record_count = embedded_count
                index_stats = {"status": "reused_in_process", "count": embedded_count}
            else:
                records = repository.list_rag_embeddings(self.embedder.model_id)
                if not records:
                    return None
                index_stats = self.vector_index.ensure(records)
                record_count = len(records)
                self._ann_index_count = record_count
            allowed = {int(row["id"]): index for index, row in enumerate(rows) if row.get("id") is not None}
            target = min(len(allowed), max(self.config.candidate_pool_size, 1))
            overfetch = min(record_count, max(self.config.candidate_pool_size * 16, 128))
            neighbors: list[tuple[int, float]] = []
            scores: dict[int, float] = {}
            while overfetch > 0:
                neighbors = self.vector_index.search(query_vector, overfetch)
                scores = {allowed[chunk_id]: score for chunk_id, score in neighbors if chunk_id in allowed}
                if len(scores) >= target or overfetch >= record_count:
                    break
                overfetch = min(record_count, overfetch * 2)
            if not scores:
                return None
            self._ann_error = None
            return scores, {
                **self.diagnostics("faiss_hnsw"),
                "candidate_count": len(rows),
                "ann_neighbor_count": len(neighbors),
                "filtered_neighbor_count": len(scores),
                "ann_overfetch": overfetch,
                "ann_index": index_stats,
            }
        except (ImportError, ModuleNotFoundError) as exc:
            # ANN is an acceleration backend, not the semantic-retrieval
            # contract. Keep the failure observable and use exact persisted
            # vector scan rather than incorrectly degrading to lexical search.
            self._ann_error = f"{type(exc).__name__}: {exc}"
            self.vector_index = None
            return None

    def rerank(self, query: str, rows: list[dict[str, Any]]) -> tuple[dict[int, float], dict[str, Any]]:
        """Execute rerank at the semantic boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            query: Value supplied by the caller and validated by the surrounding schema.
            rows: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        if not self.config.enabled or not rows:
            return {}, self.diagnostics("disabled")
        scores: dict[int, float] = {}
        missing_indices: list[int] = []
        missing_pairs: list[tuple[str, str]] = []
        for index, row in enumerate(rows):
            text = str(row.get("text") or "")
            key = _content_hash(f"{self.reranker.model_id}\0{query}\0{text}")
            cached = self._cache_get(self._rerank_cache, key)
            if cached is None:
                missing_indices.append(index)
                missing_pairs.append((query, text))
            else:
                scores[index] = cached
        try:
            if missing_pairs:
                raw_scores = self.reranker.predict(missing_pairs, batch_size=self.config.rerank_batch_size)
                for index, pair, raw_score in zip(missing_indices, missing_pairs, raw_scores):
                    calibrated = _sigmoid(raw_score)
                    scores[index] = calibrated
                    key = _content_hash(f"{self.reranker.model_id}\0{pair[0]}\0{pair[1]}")
                    self._cache_put(self._rerank_cache, key, calibrated)
            return scores, self.diagnostics("cross_encoder")
        except Exception as exc:
            self._reranker_error = f"{type(exc).__name__}: {exc}"
            return {}, self.diagnostics("embedding_only")

    def diagnostics(self, mode: str) -> dict[str, Any]:
        """Execute diagnostics at the semantic boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            mode: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        return {
            "mode": mode,
            "embedding_model": self.embedder.model_id,
            "reranker_model": self.reranker.model_id,
            "embedding_error": self._embedding_error,
            "reranker_error": self._reranker_error,
            "ann_error": self._ann_error,
            "lexical_fallback_allowed": self.config.allow_lexical_fallback,
            "min_reranker_score": self.min_reranker_score,
            "calibration": self.calibration_diagnostics,
        }

    def _load_calibration(self) -> None:
        """Implement the internal _load_calibration helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Returns:
            The structured value promised by the function signature.
        """
        if not self.config.calibration_path:
            return
        path = Path(self.config.calibration_path)
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
            if report.get("reranker_model") != self.reranker.model_id:
                self.calibration_diagnostics = {"status": "model_mismatch", "path": str(path)}
                return
            threshold = float(report["threshold"])
            self.calibrated_min_reranker_score = max(0.0, min(1.0, threshold))
            self.calibration_diagnostics = {
                "status": "loaded",
                "path": str(path),
                "dataset_hash": report.get("dataset_hash"),
                "threshold": self.calibrated_min_reranker_score,
            }
        except Exception as exc:
            self.calibration_diagnostics = {"status": "invalid", "path": str(path), "error": f"{type(exc).__name__}: {exc}"}

    def _document_vectors(
        self,
        rows: list[dict[str, Any]],
        repository: Any,
    ) -> tuple[dict[int, list[float]], dict[str, Any]]:
        """Implement the internal _document_vectors helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            rows: Value supplied by the caller and validated by the surrounding schema.
            repository: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        persisted: dict[int, dict[str, Any]] = {}
        chunk_ids = [int(row["id"]) for row in rows if row.get("id") is not None]
        if chunk_ids and hasattr(repository, "get_rag_embeddings"):
            persisted = repository.get_rag_embeddings(chunk_ids, self.embedder.model_id)

        vectors: dict[int, list[float]] = {}
        missing_indices: list[int] = []
        missing_texts: list[str] = []
        for index, row in enumerate(rows):
            text = str(row.get("text") or "")
            content_hash = _content_hash(text)
            chunk_id = row.get("id")
            stored = persisted.get(int(chunk_id)) if chunk_id is not None else None
            if stored and stored.get("content_hash") == content_hash:
                vectors[index] = list(stored.get("embedding") or [])
                continue
            cache_key = f"{self.embedder.model_id}:{content_hash}"
            cached = self._cache_get(self._vector_cache, cache_key)
            if cached is not None:
                vectors[index] = cached
                continue
            missing_indices.append(index)
            missing_texts.append(text)

        total_missing = len(missing_texts)
        online_limit = max(0, int(self.config.max_online_embeddings))
        missing_indices = missing_indices[:online_limit]
        missing_texts = missing_texts[:online_limit]
        if missing_texts:
            unique_texts: dict[str, str] = {}
            for text in missing_texts:
                unique_texts.setdefault(_content_hash(text), text)
            encoded = self._encode_documents(list(unique_texts.values()))
            computed_by_hash = {
                content_hash: vector
                for content_hash, vector in zip(unique_texts, encoded)
            }
            records = []
            for index, text in zip(missing_indices, missing_texts):
                vector = computed_by_hash[_content_hash(text)]
                vectors[index] = vector
                self._cache_put(self._vector_cache, f"{self.embedder.model_id}:{_content_hash(text)}", vector)
                chunk_id = rows[index].get("id")
                if chunk_id is not None:
                    records.append(
                        {
                            "chunk_id": int(chunk_id),
                            "model_id": self.embedder.model_id,
                            "content_hash": _content_hash(text),
                            "embedding": vector,
                        }
                    )
            if records and hasattr(repository, "upsert_rag_embeddings"):
                repository.upsert_rag_embeddings(records)
        return vectors, {
            "candidate_count": len(rows),
            "persisted_vector_count": len(rows) - total_missing,
            "online_embedding_count": len(missing_texts),
            "unembedded_candidate_count": max(0, total_missing - len(missing_texts)),
            "vector_coverage": round(len(vectors) / max(len(rows), 1), 4),
        }

    def _encode_query(self, query: str) -> list[float]:
        """Implement the internal _encode_query helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            query: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        key = f"{self.embedder.model_id}:query:{_content_hash(query)}"
        cached = self._cache_get(self._vector_cache, key)
        if cached is not None:
            return cached
        vector = self.embedder.encode([query], batch_size=1)[0]
        self._cache_put(self._vector_cache, key, vector)
        return vector

    def _encode_documents(self, texts: list[str]) -> list[list[float]]:
        """Implement the internal _encode_documents helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            texts: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        return self.embedder.encode(texts, batch_size=self.config.embedding_batch_size)

    def _cache_get(self, cache: OrderedDict, key: str):
        """Implement the internal _cache_get helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            cache: Value supplied by the caller and validated by the surrounding schema.
            key: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        with self._lock:
            if key not in cache:
                return None
            value = cache.pop(key)
            cache[key] = value
            return value

    def _cache_put(self, cache: OrderedDict, key: str, value: Any) -> None:
        """Implement the internal _cache_put helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            cache: Value supplied by the caller and validated by the surrounding schema.
            key: Value supplied by the caller and validated by the surrounding schema.
            value: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        with self._lock:
            if key in cache:
                cache.pop(key)
            cache[key] = value
            while len(cache) > max(1, self.config.cache_size):
                cache.popitem(last=False)
