from __future__ import annotations

import json
from pathlib import Path

from .evidence import CorrectiveRetriever, RAGEvidenceGrader
from .indexer import RagIndexer
from .retriever import RagRetriever
from .semantic import EmbeddingBackend, RerankerBackend, SemanticRagConfig, SemanticRagEngine


class RagMemory:
    def __init__(
        self,
        repository,
        workspace_root: str | Path | None = None,
        *,
        semantic_config: SemanticRagConfig | dict | None = None,
        embedder: EmbeddingBackend | None = None,
        reranker: RerankerBackend | None = None,
    ):
        self.repository = repository
        if isinstance(semantic_config, SemanticRagConfig):
            config = semantic_config
        elif semantic_config is None:
            config = SemanticRagConfig(enabled=embedder is not None or reranker is not None)
        else:
            config = SemanticRagConfig.from_mapping(semantic_config)
        if workspace_root is not None and config.calibration_path and not Path(config.calibration_path).is_absolute():
            config = SemanticRagConfig.from_mapping({**config.__dict__, "calibration_path": str(Path(workspace_root) / config.calibration_path)})
        if workspace_root is not None and config.vector_backend == "faiss_hnsw" and not config.vector_index_path:
            config = SemanticRagConfig.from_mapping({
                **config.__dict__,
                "vector_index_path": str(Path(workspace_root) / "runs" / "rag_indexes" / "hls_chunks.faiss"),
            })
        self.semantic_engine = SemanticRagEngine(config, embedder=embedder, reranker=reranker)
        self.indexer = RagIndexer(repository, self.semantic_engine)
        root = Path(workspace_root) if workspace_root is not None else None
        static_paths = []
        if root is not None:
            static_paths = [
                root / "docs" / "vivado_failure_playbook.md",
                root / "docs" / "legacy_workflow_map.md",
                root / "docs" / "memory_design.md",
            ]
        self.retriever = RagRetriever(repository, static_paths=static_paths, semantic_engine=self.semantic_engine)
        self.evidence_grader = RAGEvidenceGrader()
        self.corrective_retriever = CorrectiveRetriever(self.retriever.retrieve, self.evidence_grader)

    def index_run(self, run_id: str, artifact_paths: list[str]) -> dict:
        documents = []
        for path in artifact_paths:
            candidate = Path(path)
            if not candidate.exists() or not candidate.is_file():
                continue
            metadata = {"run_id": run_id, **self._metadata_for_path(path)}
            documents.append(
                {
                    "source_id": str(candidate),
                    "source_type": candidate.suffix.lstrip(".") or "file",
                    "text": candidate.read_text(encoding="utf-8", errors="ignore"),
                    "metadata": metadata,
                }
            )
        return self.indexer.index_documents(documents)

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        domain: str | None = None,
        identity: dict | None = None,
    ) -> list[dict]:
        return self.retriever.retrieve(query, top_k=top_k, domain=domain, identity=identity)

    def retrieve_corrective(
        self,
        query: str,
        top_k: int = 5,
        domain: str | None = None,
        identity: dict | None = None,
    ) -> dict:
        result = self.corrective_retriever.retrieve(
            query,
            top_k=top_k,
            domain=domain,
            identity=identity,
        )
        return {**result, "retrieval_diagnostics": dict(self.retriever.last_diagnostics)}

    def index_text(self, source_id: str, text: str, metadata: dict) -> dict:
        return self.indexer.index_text(source_id, text, metadata=metadata)

    def backfill_embeddings(self, *, batch_size: int = 256, max_chunks: int | None = None) -> dict:
        if not self.semantic_engine.config.enabled:
            return {"status": "disabled", "embeddings_indexed": 0}
        processed = 0
        unique_texts_encoded = 0
        while max_chunks is None or processed < max_chunks:
            remaining = batch_size if max_chunks is None else min(batch_size, max_chunks - processed)
            rows = self.repository.get_unembedded_rag_chunks(self.semantic_engine.embedder.model_id, remaining)
            if not rows:
                break
            normalized_rows = [
                {
                    "id": row["id"],
                    "source_id": row["source_id"],
                    "source_type": row.get("source_type"),
                    "text": row["chunk_text"],
                    "metadata": json.loads(row.get("metadata_json") or "{}"),
                }
                for row in rows
            ]
            result = self.semantic_engine.index_rows(normalized_rows, self.repository)
            if result.get("status") != "success":
                return {
                    "status": "fallback",
                    "embeddings_indexed": processed,
                    "last_batch": result,
                    "coverage": self.repository.rag_embedding_coverage(self.semantic_engine.embedder.model_id),
                }
            processed += int(result.get("embeddings_indexed", 0))
            unique_texts_encoded += int(result.get("unique_texts_encoded", 0))
            if not result.get("embeddings_indexed"):
                break
        return {
            "status": "success",
            "embeddings_indexed": processed,
            "unique_texts_encoded": unique_texts_encoded,
            "coverage": self.repository.rag_embedding_coverage(self.semantic_engine.embedder.model_id),
        }

    def _metadata_for_path(self, path: str) -> dict:
        lowered = str(path).replace("\\", "/").lower()
        if lowered.endswith("suggestions.md"):
            return {"domain": "optimization", "source_type": "suggestions"}
        if lowered.endswith("verification.json") or lowered.endswith("report.json") or lowered.endswith("parameter_advice.json"):
            return {"domain": "parameter", "source_type": "parameter_experience"}
        if lowered.endswith("unsupported_report.md"):
            return {"domain": "failure", "source_type": "unsupported_report"}
        if lowered.endswith("compressed_context.json"):
            return {"domain": "episodic", "source_type": "compressed_context"}
        if lowered.endswith("summary.md"):
            return {"domain": "episodic", "source_type": "summary"}
        return {"domain": "general", "source_type": "artifact"}
