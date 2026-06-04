from __future__ import annotations

from pathlib import Path

from .indexer import RagIndexer
from .retriever import RagRetriever


class RagMemory:
    def __init__(self, repository, workspace_root: str | Path | None = None):
        self.repository = repository
        self.indexer = RagIndexer(repository)
        root = Path(workspace_root) if workspace_root is not None else None
        static_paths = []
        if root is not None:
            static_paths = [
                root / "docs" / "vivado_failure_playbook.md",
                root / "docs" / "legacy_workflow_map.md",
                root / "docs" / "memory_design.md",
            ]
        self.retriever = RagRetriever(repository, static_paths=static_paths)

    def index_run(self, run_id: str, artifact_paths: list[str]) -> dict:
        metadata = {"run_id": run_id}
        return self.indexer.index_paths(artifact_paths, metadata=metadata)

    def retrieve(self, query: str, top_k: int = 5) -> list[dict]:
        return self.retriever.retrieve(query, top_k=top_k)

    def index_text(self, source_id: str, text: str, metadata: dict) -> dict:
        return self.indexer.index_text(source_id, text, metadata=metadata)
