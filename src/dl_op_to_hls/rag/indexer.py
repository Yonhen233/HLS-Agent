from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.memory_hygiene import sanitize_memory_text
from .chunker import chunk_text


class RagIndexer:
    def __init__(self, repository):
        self.repository = repository

    def index_text(self, source_id: str, text: str, metadata: dict[str, Any] | None = None, source_type: str = "text") -> dict[str, Any]:
        text = sanitize_memory_text(text)
        if not text:
            return {"status": "success", "chunks_indexed": 0}
        chunks = chunk_text(text)
        inserted = 0
        for chunk in chunks:
            self.repository.insert_rag_chunk(
                {
                    "source_id": source_id,
                    "source_type": source_type,
                    "chunk_text": chunk,
                    "metadata": metadata or {},
                }
            )
            inserted += 1
        return {"status": "success", "chunks_indexed": inserted}

    def index_paths(self, paths: list[str], metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        total = 0
        for raw_path in paths:
            path = Path(raw_path)
            if not path.exists() or not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            result = self.index_text(str(path), text, metadata=metadata, source_type=path.suffix.lstrip(".") or "file")
            total += result["chunks_indexed"]
        return {"status": "success", "chunks_indexed": total}
