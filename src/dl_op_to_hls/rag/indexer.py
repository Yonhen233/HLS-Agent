"""rag layer implementation for indexer.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.memory_hygiene import sanitize_memory_text
from .chunker import chunk_records


class RagIndexer:
    """Coordinate RagIndexer within the indexer boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    def __init__(self, repository, semantic_engine=None):
        """Implement the internal __init__ helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            repository: Value supplied by the caller and validated by the surrounding schema.
            semantic_engine: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        self.repository = repository
        self.semantic_engine = semantic_engine

    def index_text(self, source_id: str, text: str, metadata: dict[str, Any] | None = None, source_type: str = "text") -> dict[str, Any]:
        """Execute index_text at the indexer boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            source_id: Value supplied by the caller and validated by the surrounding schema.
            text: Value supplied by the caller and validated by the surrounding schema.
            metadata: Value supplied by the caller and validated by the surrounding schema.
            source_type: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        return self.index_documents(
            [{"source_id": source_id, "source_type": source_type, "text": text, "metadata": metadata or {}}]
        )

    def index_documents(self, documents: list[dict[str, Any]]) -> dict[str, Any]:
        """Execute index_documents at the indexer boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            documents: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        payloads: list[dict[str, Any]] = []
        for document in documents:
            text = sanitize_memory_text(str(document.get("text") or ""))
            if not text:
                continue
            for chunk in chunk_records(text):
                payloads.append(
                    {
                        "source_id": str(document["source_id"]),
                        "source_type": str(document.get("source_type") or "text"),
                        "chunk_text": chunk["text"],
                        "metadata": {
                            **(document.get("metadata") or {}),
                            **{key: value for key, value in chunk.items() if key != "text"},
                        },
                    }
                )
        if not payloads:
            return {
                "status": "success",
                "chunks_indexed": 0,
                "embeddings_indexed": 0,
                "semantic_index": {"status": "disabled", "embeddings_indexed": 0},
            }
        row_ids: list[int] = []
        if hasattr(self.repository, "insert_rag_chunks"):
            row_ids = self.repository.insert_rag_chunks(payloads)
            inserted = len(row_ids)
        else:
            inserted = 0
            for payload in payloads:
                row_ids.append(self.repository.insert_rag_chunk(payload))
                inserted += 1
        semantic_result = {"status": "disabled", "embeddings_indexed": 0}
        if self.semantic_engine is not None:
            semantic_result = self.semantic_engine.index_rows(
                [{**payload, "id": row_id, "text": payload["chunk_text"]} for payload, row_id in zip(payloads, row_ids)],
                self.repository,
            )
        return {
            "status": "success",
            "chunks_indexed": inserted,
            "embeddings_indexed": int(semantic_result.get("embeddings_indexed", 0)),
            "semantic_index": semantic_result,
        }

    def index_paths(self, paths: list[str], metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute index_paths at the indexer boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            paths: Value supplied by the caller and validated by the surrounding schema.
            metadata: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        documents: list[dict[str, Any]] = []
        for raw_path in paths:
            path = Path(raw_path)
            if not path.exists() or not path.is_file():
                continue
            documents.append(
                {
                    "source_id": str(path),
                    "source_type": path.suffix.lstrip(".") or "file",
                    "text": path.read_text(encoding="utf-8", errors="ignore"),
                    "metadata": metadata or {},
                }
            )
        return self.index_documents(documents)
