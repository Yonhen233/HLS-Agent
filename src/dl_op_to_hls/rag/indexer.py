from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.memory_hygiene import sanitize_memory_text
from .chunker import chunk_records


class RagIndexer:
    def __init__(self, repository, semantic_engine=None):
        self.repository = repository
        self.semantic_engine = semantic_engine

    def index_text(self, source_id: str, text: str, metadata: dict[str, Any] | None = None, source_type: str = "text") -> dict[str, Any]:
        return self.index_documents(
            [{"source_id": source_id, "source_type": source_type, "text": text, "metadata": metadata or {}}]
        )

    def index_documents(self, documents: list[dict[str, Any]]) -> dict[str, Any]:
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
