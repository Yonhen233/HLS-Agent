from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class FaissHNSWIndex:
    """Persistent cosine ANN index with stable SQLite chunk IDs."""

    def __init__(self, path: str | Path, *, model_id: str, m: int = 32, ef_search: int = 96, ef_construction: int = 160):
        self.path = Path(path)
        self.manifest_path = self.path.with_suffix(self.path.suffix + ".json")
        self.model_id = model_id
        self.m = int(m)
        self.ef_search = int(ef_search)
        self.ef_construction = int(ef_construction)
        self._index = None
        self._signature: str | None = None

    def ensure(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        signature = self._records_signature(records)
        if self._index is not None and self._signature == signature:
            return {"status": "reused", "count": int(self._index.ntotal), "signature": signature}
        if self.path.exists() and self.manifest_path.exists():
            manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            if manifest.get("model_id") == self.model_id and manifest.get("signature") == signature:
                import faiss  # type: ignore

                self._index = faiss.read_index(str(self.path))
                self._set_search_depth()
                self._signature = signature
                return {"status": "loaded", "count": int(self._index.ntotal), "signature": signature}
        return self.rebuild(records, signature=signature)

    def rebuild(self, records: list[dict[str, Any]], *, signature: str | None = None) -> dict[str, Any]:
        if not records:
            self._index = None
            self._signature = signature or self._records_signature(records)
            return {"status": "empty", "count": 0, "signature": self._signature}
        import faiss  # type: ignore
        import numpy as np  # type: ignore

        dimensions = {int(item["dimensions"]) for item in records}
        if len(dimensions) != 1:
            raise ValueError("FAISS index cannot mix embedding dimensions.")
        dim = dimensions.pop()
        vectors = np.asarray([item["embedding"] for item in records], dtype="float32")
        ids = np.asarray([int(item["chunk_id"]) for item in records], dtype="int64")
        faiss.normalize_L2(vectors)
        base = faiss.IndexHNSWFlat(dim, self.m, faiss.METRIC_INNER_PRODUCT)
        base.hnsw.efConstruction = self.ef_construction
        base.hnsw.efSearch = self.ef_search
        index = faiss.IndexIDMap2(base)
        index.add_with_ids(vectors, ids)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        faiss.write_index(index, str(self.path))
        signature = signature or self._records_signature(records)
        self.manifest_path.write_text(
            json.dumps({"model_id": self.model_id, "signature": signature, "count": len(records), "dimensions": dim, "m": self.m}, indent=2),
            encoding="utf-8",
        )
        self._index = index
        self._signature = signature
        return {"status": "rebuilt", "count": len(records), "signature": signature}

    def search(self, query_vector: list[float], k: int) -> list[tuple[int, float]]:
        if self._index is None or not query_vector:
            return []
        import faiss  # type: ignore
        import numpy as np  # type: ignore

        query = np.asarray([query_vector], dtype="float32")
        faiss.normalize_L2(query)
        scores, ids = self._index.search(query, max(1, min(int(k), int(self._index.ntotal))))
        return [(int(chunk_id), float(score)) for chunk_id, score in zip(ids[0], scores[0]) if int(chunk_id) >= 0]

    def _set_search_depth(self) -> None:
        base = getattr(self._index, "index", self._index)
        if hasattr(base, "hnsw"):
            base.hnsw.efSearch = self.ef_search

    def _records_signature(self, records: list[dict[str, Any]]) -> str:
        digest = hashlib.sha256(self.model_id.encode("utf-8"))
        for item in records:
            digest.update(f"{item['chunk_id']}:{item['content_hash']}:{item['dimensions']}".encode("utf-8"))
        return digest.hexdigest()


class PgVectorIndex:
    """Optional pgvector adapter; the connection factory owns pooling and credentials."""

    def __init__(self, connection_factory, table: str = "rag_embeddings_pg"):
        if not table.replace("_", "").isalnum():
            raise ValueError("Unsafe pgvector table name.")
        self.connection_factory = connection_factory
        self.table = table

    def search(self, model_id: str, query_vector: list[float], k: int) -> list[tuple[int, float]]:
        vector_literal = "[" + ",".join(f"{float(value):.9g}" for value in query_vector) + "]"
        sql = f"SELECT chunk_id, 1 - (embedding <=> %s::vector) AS score FROM {self.table} WHERE model_id=%s ORDER BY embedding <=> %s::vector LIMIT %s"
        with self.connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, (vector_literal, model_id, vector_literal, max(1, int(k))))
                return [(int(row[0]), float(row[1])) for row in cursor.fetchall()]
