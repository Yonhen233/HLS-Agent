"""Content-oriented benchmark for real historical HLS experience.

The benchmark deliberately labels evidence windows (all chunks from one source)
by method evidence, rather than treating a run identifier as the answer.
"""
from __future__ import annotations

import json
import statistics
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..core.config import AppConfig
from ..db.database import Database
from ..db.repositories import MetadataRepository
from ..rag.memory import RagMemory
from ..rag.semantic import SemanticRagConfig
from .agent_quality_benchmark import evaluate_rag_case


METHOD_LABELS = [
    {
        "id": "resource_reuse",
        "query": "reduce DSP and LUT resource by increasing reuse factor",
        "domain": "parameter",
        "terms": ["reuse_factor", "dsp"],
        "metadata": {"domain": "parameter"},
    },
    {
        "id": "latency_parallelism",
        "query": "reduce latency with lower reuse factor and pipeline parallelism",
        "domain": "parameter",
        "terms": ["latency", "reuse_factor"],
        "metadata": {"domain": "parameter", "objective": "latency"},
    },
    {
        "id": "resource_budget",
        "query": "resource feasible DSP LUT FF BRAM budget utilization",
        "domain": "parameter",
        "terms": ["resource", "dsp", "lut"],
        "metadata": {"domain": "parameter"},
    },
    {
        "id": "timing_closure",
        "query": "meet timing target clock period estimated delay uncertainty",
        "domain": "parameter",
        "terms": ["timing", "clock_period"],
        "metadata": {"domain": "parameter"},
    },
    {
        "id": "precision_tradeoff",
        "query": "fixed point precision bit width resource accuracy tradeoff",
        "domain": "parameter",
        "terms": ["precision", "fixed"],
        "metadata": {"domain": "parameter"},
    },
    {
        "id": "functional_gate",
        "query": "golden testbench CSim functional verification passed before synthesis",
        "domain": "episodic",
        "terms": ["golden_testbench", "csim_passed"],
        "metadata": {"domain": "episodic"},
    },
    {
        "id": "vivado_recovery",
        "query": "VivadoNotFoundError preserve artifacts and retry synthesis on configured host",
        "domain": "failure",
        "terms": ["vivadonotfounderror", "recoverable"],
        "metadata": {"domain": "failure"},
    },
    {
        "id": "unsupported_boundary",
        "query": "unsupported operator boundary report without inventing synthesis metrics",
        "domain": "failure",
        "terms": ["unsupported"],
        "metadata": {"domain": "failure"},
    },
    {
        "id": "memory_evidence",
        "query": "promote verified implementation to long term memory after real evidence",
        "domain": "optimization",
        "terms": ["verified", "memory"],
        "metadata": {"domain": "optimization"},
    },
    {
        "id": "pipeline_ii",
        "query": "pipeline initiation interval II dependency and throughput optimization",
        "domain": "parameter",
        "terms": ["pipeline_ii", "ii"],
        "metadata": {"domain": "parameter"},
    },
]


def _normalize(value: str) -> str:
    return " ".join(value.lower().replace("_", " ").split())


def _source_rows(repository) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in repository.get_rag_chunks():
        source_id = str(row["source_id"])
        entry = grouped.setdefault(source_id, {"source_id": source_id, "texts": [], "metadata": {}})
        entry["texts"].append(str(row.get("chunk_text") or ""))
        entry["metadata"].update(json.loads(row.get("metadata_json") or "{}"))
    for entry in grouped.values():
        entry["text"] = "\n".join(entry.pop("texts"))
    return list(grouped.values())


def build_experience_content_cases(repository, *, per_label: int = 12) -> dict[str, Any]:
    """Create auditable source-window qrels from persisted real chunks.

    A positive source must contain every method term in its aggregated source
    window. This is intentionally stricter than matching a task/run identity.
    """
    sources = _source_rows(repository)
    cases: list[dict[str, Any]] = []
    label_stats: dict[str, int] = {}
    for label in METHOD_LABELS:
        eligible = []
        for source in sources:
            metadata = source["metadata"]
            if label["domain"] and metadata.get("domain") != label["domain"]:
                continue
            text = _normalize(source["text"])
            if not all(_normalize(term) in text for term in label["terms"]):
                continue
            eligible.append(source)
        eligible = sorted(eligible, key=lambda item: item["source_id"])
        label_stats[label["id"]] = len(eligible)
        for anchor in eligible[: max(0, int(per_label))]:
            peers = [item for item in eligible if item["source_id"] != anchor["source_id"]]
            if not peers:
                continue
            metadata = anchor["metadata"]
            query = label["query"]
            if metadata.get("op_type"):
                query += f" {metadata['op_type']}"
            if metadata.get("objective"):
                query += f" objective {metadata['objective']}"
            cases.append(
                {
                    "case_id": f"content:{label['id']}:{Path(anchor['source_id']).parent.name or 'source'}",
                    "query": query,
                    "domain": label["domain"],
                    "top_k": 5,
                    "relevant_source_ids": [item["source_id"] for item in peers],
                    "anchor_source_id": anchor["source_id"],
                    "method_label": label["id"],
                    "required_method_terms": label["terms"],
                    "metadata_filter": label.get("metadata", {}),
                    "label_policy": "source evidence window contains every method term; anchor excluded",
                }
            )
    return {
        "cases": cases,
        "source_count": len(sources),
        "label_stats": label_stats,
        "label_count": len(METHOD_LABELS),
    }


def _evaluate(repository, memory: RagMemory, cases: list[dict[str, Any]], *, use_filter: bool) -> dict[str, Any]:
    latencies: list[float] = []
    case_metrics: list[dict[str, Any]] = []
    for case in cases:
        started = time.perf_counter()
        results = memory.retrieve(
            case["query"],
            top_k=case["top_k"],
            domain=case.get("domain"),
            metadata_filter=case.get("metadata_filter") if use_filter else None,
        )
        results = [item for item in results if str(item.get("source_id")) != str(case.get("anchor_source_id"))]
        metrics = evaluate_rag_case(case, results, default_top_k=case["top_k"])
        metrics.update({"case_id": case["case_id"], "method_label": case["method_label"]})
        case_metrics.append(metrics)
        latencies.append((time.perf_counter() - started) * 1000.0)

    def mean(key: str) -> float | None:
        values = [float(item[key]) for item in case_metrics if isinstance(item.get(key), (int, float))]
        return round(statistics.fmean(values), 4) if values else None

    return {
        "case_count": len(case_metrics),
        "macro_precision_at_k": mean("precision_at_k"),
        "macro_r_precision": mean("r_precision"),
        "macro_recall_at_k": mean("recall_at_k"),
        "macro_hit_at_k": mean("hit_at_k"),
        "macro_mrr": mean("mrr"),
        "macro_ndcg_at_k": mean("ndcg_at_k"),
        "macro_pollution_at_k": mean("pollution_at_k"),
        "latency_ms": {
            "median": round(statistics.median(latencies), 3) if latencies else None,
            "p95": round(sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)], 3) if latencies else None,
        },
        "cases": case_metrics,
    }


def run_experience_content_benchmark(workspace_root: str | Path, output_path: str | Path, *, per_label: int = 12) -> dict[str, Any]:
    root = Path(workspace_root).resolve()
    config = AppConfig.load(root)
    repository = MetadataRepository(Database(config.db_path, root / "src" / "dl_op_to_hls" / "db" / "schema.sql"))
    case_set = build_experience_content_cases(repository, per_label=per_label)
    cases = case_set["cases"]
    if not cases:
        raise RuntimeError("No content-oriented experience cases are available.")
    semantic = SemanticRagConfig.from_mapping(config.rag_semantic_config)
    memory = RagMemory(repository, workspace_root=root, semantic_config=semantic)
    filtered = _evaluate(repository, memory, cases, use_filter=True)
    unfiltered = _evaluate(repository, memory, cases, use_filter=False)
    payload = {
        "benchmark": "real_experience_content_window_v1",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "annotation": {
            "type": "method-level source evidence window",
            "positive_definition": "all chunks belonging to one source contain every method term in the label",
            "negative_definition": "all other returned sources for the query",
            "not_run_id_only": True,
            "limitations": [
                "Method labels are human-authored term rules, not independent double annotation.",
                "Source-window labels avoid chunk-boundary false negatives but do not prove the method is optimal.",
                "Downstream CSynth utility still requires a separate parameter recommendation experiment.",
            ],
        },
        "corpus": {"chunk_count": len(repository.get_rag_chunks()), "source_count": case_set["source_count"]},
        "case_construction": {"case_count": len(cases), "per_label": per_label, "label_stats": case_set["label_stats"]},
        "retrievers": {"structured_filter": filtered, "domain_only": unfiltered},
    }
    output = Path(output_path)
    if not output.is_absolute():
        output = root / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload
