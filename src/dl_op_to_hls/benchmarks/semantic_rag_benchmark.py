from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..core.config import AppConfig
from ..db.database import Database
from ..db.repositories import MetadataRepository
from ..rag.memory import RagMemory
from ..rag.semantic import SemanticRagConfig


def run_semantic_rag_benchmark(workspace_root: str | Path, output_path: str | Path) -> dict[str, Any]:
    root = Path(workspace_root).resolve()
    output = Path(output_path)
    if not output.is_absolute():
        output = root / output
    output.parent.mkdir(parents=True, exist_ok=True)
    probe_id = uuid.uuid4().hex[:10]
    state_dir = output.parent / f"semantic_rag_state_{probe_id}"
    repository = MetadataRepository(
        Database(state_dir / "metadata.db", root / "src" / "dl_op_to_hls" / "db" / "schema.sql")
    )
    app_config = AppConfig.load(root)
    semantic_config = SemanticRagConfig.from_mapping(app_config.rag_semantic_config)
    memory = RagMemory(repository, semantic_config=semantic_config)

    dense_doc = "Dense HLS optimization increases reuse factor to reduce DSP utilization."
    parser_doc = "The report parser reads XML and extracts timing fields."
    resnet_doc = "ResNet18 boundary conversion is unsupported and must be reported honestly."
    matmul_doc = "MatMul resource reuse factor DSP optimization hint."
    started = time.perf_counter()
    index_results = [
        memory.index_text(f"probe:{probe_id}:dense", dense_doc, {"op_type": "Dense"}),
        memory.index_text(f"probe:{probe_id}:parser", parser_doc, {"source_type": "static_doc"}),
        memory.index_text(f"probe:{probe_id}:resnet", resnet_doc, {"op_type": "ResNet18"}),
        memory.index_text(f"probe:{probe_id}:matmul", matmul_doc, {"op_type": "MatMul"}),
    ]
    dense_query = "Dense reuse factor reduce DSP Vivado HLS"
    dense_result = memory.retrieve_corrective(dense_query, top_k=3)
    entity_query = "resnet18_boundary_demo resource reuse factor DSP Vivado HLS"
    entity_result = memory.retrieve_corrective(entity_query, top_k=3)
    runtime_s = round(time.perf_counter() - started, 3)

    rows = repository.get_rag_chunks()
    chunk_ids = [int(row["id"]) for row in rows]
    embeddings = repository.get_rag_embeddings(chunk_ids, semantic_config.embedding_model)
    dense_top = dense_result["results"][0] if dense_result["results"] else {}
    diagnostics = dense_result.get("retrieval_diagnostics") or {}
    checks = [
        _check(
            "semantic.index_persisted",
            len(embeddings) == len(chunk_ids) == 4,
            {"chunk_count": len(chunk_ids), "embedding_count": len(embeddings)},
        ),
        _check(
            "semantic.embedding_recall_used",
            str((dense_top.get("retrieval") or {}).get("mode") or "").startswith("embedding"),
            dense_top.get("retrieval"),
        ),
        _check(
            "semantic.cross_encoder_used",
            (dense_top.get("retrieval") or {}).get("cross_encoder_score") is not None,
            dense_top.get("retrieval"),
        ),
        _check(
            "semantic.relevant_top1",
            str(dense_top.get("source_id") or "").endswith(":dense"),
            [item.get("source_id") for item in dense_result["results"]],
        ),
        _check(
            "semantic.corrective_evidence_passed",
            dense_result.get("status") == "sufficient_evidence" and not dense_result.get("abstained"),
            dense_result,
        ),
        _check(
            "semantic.entity_pollution_blocked",
            bool(entity_result["results"])
            and all(not str(item.get("source_id") or "").endswith(":matmul") for item in entity_result["results"]),
            [item.get("source_id") for item in entity_result["results"]],
        ),
        _check(
            "semantic.no_backend_fallback",
            diagnostics.get("embedding_error") is None
            and diagnostics.get("reranker_error") is None
            and diagnostics.get("mode") == "cross_encoder",
            diagnostics,
        ),
    ]
    passed = sum(1 for item in checks if item["passed"])
    payload = {
        "benchmark": "semantic_rag_real_model_probe_v1",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "probe_id": probe_id,
        "embedding_model": semantic_config.embedding_model,
        "reranker_model": semantic_config.reranker_model,
        "runtime_s": runtime_s,
        "checks_total": len(checks),
        "checks_passed": passed,
        "pass_rate": round(passed / max(len(checks), 1), 4),
        "failed_checks": [item["name"] for item in checks if not item["passed"]],
        "index_results": index_results,
        "checks": checks,
    }
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    output.with_suffix(".md").write_text(_to_markdown(payload), encoding="utf-8")
    return payload


def _check(name: str, passed: bool, details: Any) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "details": details}


def _to_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Semantic RAG Real-model Probe",
        "",
        f"- Models: `{payload['embedding_model']}` + `{payload['reranker_model']}`",
        f"- Passed: `{payload['checks_passed']}/{payload['checks_total']}`",
        f"- Runtime: `{payload['runtime_s']}s`",
        "",
        "| Check | Passed |",
        "|---|---:|",
    ]
    lines.extend(f"| {item['name']} | {item['passed']} |" for item in payload["checks"])
    return "\n".join(lines) + "\n"
