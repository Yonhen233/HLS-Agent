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
        total = 0
        for path in artifact_paths:
            metadata = {"run_id": run_id, **self._metadata_for_path(path)}
            result = self.indexer.index_paths([path], metadata=metadata)
            total += int(result.get("chunks_indexed", 0))
        return {"status": "success", "chunks_indexed": total}

    def retrieve(self, query: str, top_k: int = 5, domain: str | None = None) -> list[dict]:
        return self.retriever.retrieve(query, top_k=top_k, domain=domain)

    def index_text(self, source_id: str, text: str, metadata: dict) -> dict:
        return self.indexer.index_text(source_id, text, metadata=metadata)

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
