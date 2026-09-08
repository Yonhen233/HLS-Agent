"""benchmarks layer implementation for historical_rag_benchmark.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

import json
import statistics
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..core.config import AppConfig
from ..db.database import Database
from ..db.repositories import MetadataRepository
from ..rag.memory import RagMemory
from ..rag.retriever import RagRetriever
from ..rag.semantic import SemanticRagConfig
from .agent_quality_benchmark import evaluate_rag_cases


def _read_json(path: Path) -> dict[str, Any]:
    """Implement the internal _read_json helper.

    Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

    Args:
        path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _normalized_path(path: str | Path) -> str:
    """Implement the internal _normalized_path helper.

    Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

    Args:
        path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    return str(Path(path).resolve()).replace("\\", "/").lower()


def _has_real_csynth_evidence(tool_evidence: dict[str, Any]) -> bool:
    """Implement the internal _has_real_csynth_evidence helper.

    Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

    Args:
        tool_evidence: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    return any(
        receipt.get("valid") is True
        and receipt.get("mock_evidence") is not True
        and receipt.get("evidence_class") == "real_csynth"
        for receipt in tool_evidence.get("receipts", [])
        if isinstance(receipt, dict)
    )


def _task_family(task: dict[str, Any]) -> str:
    """Implement the internal _task_family helper.

    Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

    Args:
        task: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    return str(task.get("op_type") or task.get("name") or "unknown")


def _shape_text(value: Any) -> str:
    """Implement the internal _shape_text helper.

    Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

    Args:
        value: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    if not isinstance(value, list):
        return ""
    return "x".join(str(item) for item in value)


def _query_from_state(state: dict[str, Any]) -> str:
    """Implement the internal _query_from_state helper.

    Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

    Args:
        state: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    task = state.get("task") or {}
    target = task.get("target") or {}
    parts = [
        _task_family(task),
        str(task.get("task_type") or "task"),
        str(state.get("objective") or task.get("objective") or "balanced"),
        "verified HLS parameter experience",
    ]
    input_shape = _shape_text(task.get("input_shape"))
    output_shape = _shape_text(task.get("output_shape"))
    if input_shape:
        parts.append(f"input shape {input_shape}")
    if output_shape:
        parts.append(f"output shape {output_shape}")
    if task.get("dtype"):
        parts.append(f"dtype {task['dtype']}")
    if target.get("part"):
        parts.append(f"part {target['part']}")
    return " ".join(parts)


def build_historical_rag_cases(
    workspace_root: str | Path,
    indexed_source_ids: list[str],
    *,
    max_cases: int = 64,
) -> dict[str, Any]:
    """Build evidence-gated leave-one-run-out labels from actual run artifacts."""
    root = Path(workspace_root).resolve()
    indexed_by_path = {_normalized_path(source_id): source_id for source_id in indexed_source_ids}
    records: list[dict[str, Any]] = []
    excluded = defaultdict(int)

    for advice_path in sorted((root / "runs").glob("*/parameter_advice.json")):
        state_path = advice_path.parent / "state.json"
        evidence_path = advice_path.parent / "tool_evidence.json"
        if not state_path.exists() or not evidence_path.exists():
            excluded["missing_state_or_evidence"] += 1
            continue
        source_id = indexed_by_path.get(_normalized_path(advice_path))
        if source_id is None:
            excluded["not_indexed"] += 1
            continue
        state = _read_json(state_path)
        pipeline = state.get("pipeline_status") or {}
        if pipeline.get("functional_verified") is not True:
            excluded["not_functionally_verified"] += 1
            continue
        if not _has_real_csynth_evidence(_read_json(evidence_path)):
            excluded["no_real_csynth_receipt"] += 1
            continue
        task = state.get("task") or {}
        key = (
            str(task.get("task_type") or "unknown").lower(),
            _task_family(task).lower(),
            str(state.get("objective") or task.get("objective") or "balanced").lower(),
        )
        records.append(
            {
                "run_id": state.get("run_id") or advice_path.parent.name,
                "source_id": source_id,
                "group_key": key,
                "query": _query_from_state(state),
                "task_family": _task_family(task),
                "task_type": task.get("task_type"),
                "objective": state.get("objective") or task.get("objective"),
            }
        )

    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[record["group_key"]].append(record)

    cases = []
    for record in records:
        peer_records = [item for item in groups[record["group_key"]] if item["run_id"] != record["run_id"]]
        if not peer_records:
            excluded["no_leave_one_out_peer"] += 1
            continue
        cases.append(
            {
                "case_id": f"history:{record['run_id']}",
                "query": record["query"],
                "domain": "parameter",
                "top_k": 5,
                "relevant_source_ids": [item["source_id"] for item in peer_records],
                "relevant_run_ids": [item["run_id"] for item in peer_records],
                "anchor_source_id": record["source_id"],
                "anchor_run_id": record["run_id"],
                "task_family": record["task_family"],
                "task_type": record["task_type"],
                "objective": record["objective"],
                "metadata_filter": {
                    "task_type": record["task_type"],
                    "op_type": record["task_family"] if str(record["task_type"]).lower() == "operator" else None,
                    "objective": record["objective"],
                },
                "label_policy": "same task family, task type, and objective; current run excluded",
            }
        )
    cases.sort(key=lambda item: (str(item["task_family"]), str(item["objective"]), str(item["case_id"])))
    return {
        "cases": cases[: max(1, int(max_cases))],
        "eligible_run_count": len(records),
        "group_count": len(groups),
        "excluded": dict(sorted(excluded.items())),
    }


def _timed_evaluation(
    cases: list[dict[str, Any]],
    retrieve: Callable[[str, int, str | None], list[dict[str, Any]]],
) -> dict[str, Any]:
    """Implement the internal _timed_evaluation helper.

    Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

    Args:
        cases: Value supplied by the caller and validated by the surrounding schema.
        retrieve: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    latencies = []
    by_query: dict[str, list[dict[str, Any]]] = {}
    for case in cases:
        started = time.perf_counter()
        top_k = int(case["top_k"])
        raw_results = retrieve(
            case["query"],
            max(top_k * 3, top_k),
            case.get("domain"),
            case.get("metadata_filter"),
        )
        unique_results = []
        seen_experiences = set()
        for item in raw_results:
            source_id = str(item.get("source_id") or "")
            metadata = item.get("metadata") or {}
            run_id = str(metadata.get("run_id") or "")
            if source_id == str(case.get("anchor_source_id") or "") or (
                run_id and run_id == str(case.get("anchor_run_id") or "")
            ):
                continue
            experience_id = f"run:{run_id}" if run_id else f"source:{source_id}"
            if experience_id in seen_experiences:
                continue
            seen_experiences.add(experience_id)
            unique_results.append(item)
            if len(unique_results) >= top_k:
                break
        by_query[case["case_id"]] = unique_results
        latencies.append((time.perf_counter() - started) * 1000.0)
    case_by_query = {case["query"]: [] for case in cases}
    for case in cases:
        case_by_query[case["query"]].append(case["case_id"])

    def retrieve_cached(query: str, top_k: int) -> list[dict[str, Any]]:
        """Execute retrieve_cached at the historical_rag_benchmark boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            query: Value supplied by the caller and validated by the surrounding schema.
            top_k: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        case_ids = case_by_query[query]
        case_id = case_ids.pop(0)
        return by_query[case_id][:top_k]

    metrics = evaluate_rag_cases(cases, retrieve_cached, default_top_k=5)
    for case, case_metrics in zip(cases, metrics["cases"]):
        case_metrics.update(
            {
                "case_id": case["case_id"],
                "anchor_source_id": case["anchor_source_id"],
                "anchor_run_id": case["anchor_run_id"],
                "task_family": case["task_family"],
                "objective": case["objective"],
            }
        )
    ordered = sorted(latencies)
    p95_index = max(0, min(len(ordered) - 1, int(round(0.95 * len(ordered) + 0.499999)) - 1)) if ordered else 0
    metrics["latency_ms"] = {
        "median": round(statistics.median(latencies), 3) if latencies else None,
        "p95": round(ordered[p95_index], 3) if ordered else None,
        "mean": round(statistics.fmean(latencies), 3) if latencies else None,
    }
    return metrics


def run_historical_rag_benchmark(
    workspace_root: str | Path,
    output_path: str | Path,
    *,
    max_cases: int = 64,
) -> dict[str, Any]:
    """Execute run_historical_rag_benchmark at the historical_rag_benchmark boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Args:
        workspace_root: Value supplied by the caller and validated by the surrounding schema.
        output_path: Value supplied by the caller and validated by the surrounding schema.
        max_cases: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    root = Path(workspace_root).resolve()
    output = Path(output_path)
    if not output.is_absolute():
        output = root / output
    output.parent.mkdir(parents=True, exist_ok=True)

    app_config = AppConfig.load(root)
    repository = MetadataRepository(Database(app_config.db_path, root / "src" / "dl_op_to_hls" / "db" / "schema.sql"))
    corpus_rows = repository.get_rag_chunks()
    case_set = build_historical_rag_cases(root, [row["source_id"] for row in corpus_rows], max_cases=max_cases)
    cases = case_set.pop("cases")
    if not cases:
        raise RuntimeError("No evidence-gated leave-one-run-out RAG cases are available.")

    lexical = RagRetriever(repository)
    semantic_config = SemanticRagConfig.from_mapping(app_config.rag_semantic_config)
    production = RagMemory(repository, workspace_root=root, semantic_config=semantic_config)
    lexical_metrics = _timed_evaluation(
        cases,
        lambda query, top_k, domain, metadata_filter: lexical.retrieve(
            query, top_k=top_k, domain=domain, metadata_filter=metadata_filter
        ),
    )
    production_metrics = _timed_evaluation(
        cases,
        lambda query, top_k, domain, metadata_filter: production.retrieve(
            query, top_k=top_k, domain=domain, metadata_filter=metadata_filter
        ),
    )
    payload = {
        "benchmark": "historical_rag_leave_one_run_out_v1",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "evidence_class": "weak_supervision_from_functionally_verified_real_csynth_runs",
        "label_limitations": [
            "Labels are derived from verified run metadata, not independent human relevance judgments.",
            "A relevant item shares task type, task family, and objective; this evaluates historical-experience reuse, not arbitrary knowledge QA.",
            "The anchor run is excluded from its own relevant set to prevent self-retrieval from inflating the score.",
        ],
        "corpus": {
            "chunk_count": len(corpus_rows),
            "source_count": len({row["source_id"] for row in corpus_rows}),
            "embedding_coverage": repository.rag_embedding_coverage(semantic_config.embedding_model),
        },
        "case_construction": case_set,
        "case_count": len(cases),
        "top_k": 5,
        "retrievers": {
            "lexical_baseline": lexical_metrics,
            "production_domain_bm25_embedding_rrf_cross_encoder": production_metrics,
        },
        "production_last_diagnostics": dict(production.retriever.last_diagnostics),
        "delta_vs_lexical": {
            metric: round((production_metrics.get(metric) or 0.0) - (lexical_metrics.get(metric) or 0.0), 4)
            for metric in [
                "macro_precision_at_k",
                "macro_r_precision",
                "macro_recall_at_k",
                "macro_returned_k_fraction",
                "macro_hit_at_k",
                "macro_mrr",
                "macro_ndcg_at_k",
                "macro_pollution_at_k",
            ]
        },
    }
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    output.with_suffix(".md").write_text(_render_markdown(payload), encoding="utf-8")
    return payload


def _render_markdown(payload: dict[str, Any]) -> str:
    """Implement the internal _render_markdown helper.

    Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

    Args:
        payload: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    lexical = payload["retrievers"]["lexical_baseline"]
    production = payload["retrievers"]["production_domain_bm25_embedding_rrf_cross_encoder"]
    lines = [
        "# Historical RAG Leave-one-run-out Benchmark",
        "",
        f"- Evidence class: `{payload['evidence_class']}`",
        f"- Corpus: `{payload['corpus']['chunk_count']}` chunks / `{payload['corpus']['source_count']}` sources",
        f"- Cases: `{payload['case_count']}`",
        f"- Top K: `{payload['top_k']}`",
        "",
        "| Metric | Lexical | Production | Delta |",
        "|---|---:|---:|---:|",
    ]
    for key, label in [
        ("macro_precision_at_k", "Precision@K"),
        ("macro_r_precision", "R-Precision"),
        ("macro_recall_at_k", "Recall@K"),
        ("macro_returned_k_fraction", "Returned K fraction"),
        ("macro_hit_at_k", "Hit@K"),
        ("macro_mrr", "MRR"),
        ("macro_ndcg_at_k", "nDCG@K"),
        ("macro_pollution_at_k", "Pollution@K"),
    ]:
        lines.append(f"| {label} | {lexical.get(key)} | {production.get(key)} | {payload['delta_vs_lexical'][key]} |")
    lines.extend(
        [
            "",
            "## Latency",
            "",
            f"- Lexical median / p95: `{lexical['latency_ms']['median']}` / `{lexical['latency_ms']['p95']}` ms",
            f"- Production median / p95: `{production['latency_ms']['median']}` / `{production['latency_ms']['p95']}` ms",
            "",
            "## Limitations",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in payload["label_limitations"])
    return "\n".join(lines) + "\n"
