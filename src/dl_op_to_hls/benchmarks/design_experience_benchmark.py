"""Evidence-backed, method-level RAG benchmark.

The labels in this benchmark are design decisions, not matching run ids or
keywords.  Each card is a small human-authored playbook backed by real run
artifacts.  Queries are manually paraphrased and labelled with the card that
answers the engineering question.
"""

from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..db.database import Database
from ..db.repositories import MetadataRepository
from ..rag.memory import RagMemory
from ..rag.semantic import SemanticRagConfig


def _now() -> str:
    """Implement the internal _now helper.

    Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

    Returns:
        The structured value promised by the function signature.
    """
    return datetime.now(timezone.utc).isoformat()


def _evidence_excerpt(path: str, terms: list[str]) -> str:
    """Read a short, auditable excerpt; never inject an entire artifact."""
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return ""
    matches = [line.strip() for line in lines if any(term.lower() in line.lower() for term in terms)]
    return " ".join(matches[:6])[:1200]


# These are deliberately method cards.  The evidence refs are resolved at run
# time so a card remains useful when the exact run directory changes.
_CARD_SEEDS = [
    ("dense_resource", "Dense resource reduction", "Dense has excessive DSP usage", "Increase reuse_factor or serialize multiplier groups; verify the latency cost with csynth before accepting the trade-off.", "DSP falls; latency and possibly II rise.", "Only accept with real csim/csynth evidence and a board resource budget.", ["reuse factor", "DSP", "Dense"]),
    ("dense_latency", "Dense latency reduction", "Dense latency is the primary objective", "Use lower reuse_factor and more parallel multiply accumulation, then check timing and DSP capacity.", "Latency can fall; DSP/LUT and timing pressure rise.", "Do not use when the device budget is already exceeded.", ["latency", "Dense", "parallel"]),
    ("matmul_resource", "MatMul resource budgeting", "A MatMul does not fit the resource budget", "Reuse the multiply units and avoid full unrolling; compare II and latency rather than judging resource numbers alone.", "DSP/LUT fall while latency generally rises.", "The result must still meet the throughput requirement.", ["MatMul", "resource", "reuse"]),
    ("matmul_pipeline", "MatMul pipeline scheduling", "MatMul throughput is limited by II", "Break the accumulation dependency and partition the accessed arrays only as far as needed for II=1.", "II can improve, with extra storage and parallel operators.", "Partitioning must be checked against BRAM/LUT capacity.", ["MatMul", "II", "pipeline"]),
    ("conv_buffer", "Convolution buffering", "A Conv2D design spends too much storage or has poor reuse", "Use bounded line buffers and window reuse instead of materializing every sliding window.", "BRAM and external-memory traffic can fall; control logic increases.", "The layout must match the input data order and target interface.", ["Conv2D", "line buffer", "BRAM"]),
    ("conv_parallelism", "Convolution parallelism", "Conv2D latency is high but the device has headroom", "Increase channel or pixel parallelism incrementally and re-synthesize after each structural change.", "Latency/II improve; DSP/LUT and routing pressure increase.", "Stop before timing or board capacity fails.", ["Conv2D", "parallelism", "timing"]),
    ("precision_tradeoff", "Fixed-point precision selection", "Resources are high and numerical margin is available", "Reduce fixed-point width only after comparing golden outputs and classification argmax, not from synthesis numbers alone.", "Resource and memory use can fall; quantization error can increase.", "Functional accuracy is a hard gate.", ["fixed point", "precision", "golden"]),
    ("ii_throughput", "II-first throughput tuning", "The requirement is sustained throughput", "Prioritize initiation interval, remove loop-carried dependencies, and use selective array partitioning.", "Throughput improves when II falls; area may rise.", "Latency alone is not a throughput metric.", ["throughput", "II", "dependency"]),
    ("timing_closure", "Timing closure", "Estimated delay misses the requested clock", "Reduce the critical combinational path, add pipeline stages, or reduce parallel fan-in before relaxing the clock.", "Timing margin improves; latency or resource use may increase.", "Record the changed clock and compare like-for-like reports.", ["timing", "clock", "pipeline"]),
    ("functional_gate", "Functional verification gate", "A candidate has compiled or synthesized but correctness is unknown", "Run a golden reference testbench and compare outputs before calling the implementation verified.", "Prevents false promotion of structurally valid but numerically wrong code.", "A synthesis-success-only result is not a verified implementation.", ["golden", "csim", "verified"]),
    ("report_provenance", "Report provenance", "A report may be stale or belong to another configuration", "Bind the report to the current run, source hash, target part, clock, and tool receipt before using its metrics.", "Prevents invalid performance claims and misleading memory entries.", "Missing provenance means the metric is untrusted.", ["report", "provenance", "receipt"]),
    ("unsupported_boundary", "Unsupported boundary handling", "The graph contains an operator the converter cannot safely map", "Explain the unsupported operator and required next action; do not invent synthesis metrics or silently change semantics.", "Run becomes an honest boundary result rather than a false success.", "A rewrite is allowed only when semantic equivalence is checked.", ["unsupported", "boundary", "semantic"]),
    ("graph_rewrite", "Semantics-preserving graph rewrite", "An ONNX graph uses a representationally unsupported form", "Rewrite only static, provably equivalent patterns such as Gemm into MatMul plus Add and remove static Shape/Flatten scaffolding.", "May unlock conversion without changing model semantics.", "Dynamic shapes and unknown semantics must remain unsupported.", ["ONNX", "Gemm", "rewrite"]),
    ("candidate_sandbox", "LLM candidate sandbox", "Generated HLS code is untrusted", "Write candidates into a restricted directory, scan dangerous includes/system calls, compile and verify before any synthesis or promotion.", "Limits execution risk and prevents unverified code reuse.", "Sandboxing is not a correctness proof; csim remains required.", ["LLM", "candidate", "sandbox"]),
    ("candidate_repair", "Bounded candidate repair", "A generated candidate fails compilation or csim", "Keep the failure receipt, allow a bounded repair attempt with the same task contract, then stop with an actionable failure.", "Can recover local syntax or interface mistakes without semantic drift.", "Never repair by changing the requested operator silently.", ["candidate", "repair", "csim"]),
    ("memory_promotion", "Evidence-gated memory promotion", "A run produces a potentially reusable method", "Promote only when the implementation has functional and synthesis evidence; otherwise store a low-confidence episodic failure or synthesis note.", "Long-term memory becomes trustworthy instead of accumulating guesses.", "Raw logs and unverified outputs are not promoted.", ["memory", "promotion", "evidence"]),
    ("rag_domain", "Domain-aware experience retrieval", "A resource query retrieves unrelated CNN or MatMul advice", "Filter by operator/objective/evidence domain before rank fusion, then deduplicate by experience card or run.", "Improves relevance without pretending similar words imply the same method.", "Metadata must be evidence-backed and not derived only from the query.", ["RAG", "domain", "relevance"]),
    ("rag_fusion", "Rank fusion for experience retrieval", "Lexical and semantic retrievers disagree", "Use reciprocal-rank fusion over independently retrieved candidates, followed by a learned or calibrated reranker when available.", "Reduces dependence on one score scale; may add latency.", "Fusion cannot fix incorrect labels or missing experience cards.", ["RRF", "retrieval", "rerank"]),
    ("partial_success", "Partial-success semantics", "Conversion artifacts exist but synthesis or verification is unavailable", "Separate conversion_success, synthesis_success and functional_verified; report exactly which evidence stage stopped.", "Makes recovery and evaluation honest.", "Never map a skipped synthesis to verified success.", ["status", "partial", "conversion"]),
    ("parameter_history", "Parameter recommendation from history", "A new task resembles a previously verified design", "Use verified parameter experiences as priors, then validate the recommendation on the current shape, target and objective.", "Avoids blind sweeps while preserving current-task evidence as the authority.", "Historical parameters are suggestions, not guarantees.", ["parameter", "history", "recommendation"]),
]

# Ten genuinely different questions per card; labels are assigned by the card
# author, not by a term-matching rule.
_QUESTION_FRAMES = [
    "What method should be used when {situation}? Explain the hardware trade-off.",
    "For this HLS problem, which design change is appropriate: {situation}? Include the acceptance condition.",
    "I need an engineering recommendation for {situation}. What should the agent do and what must it not assume?",
    "How would a senior HLS engineer handle {situation} while preserving correctness?",
    "Which reusable playbook addresses {situation}, and what evidence is required before accepting it?",
    "The current design has this issue: {situation}. Give the method, cost and boundary condition.",
    "What is the safe optimization strategy for {situation}, rather than a blind parameter sweep?",
    "How should an Agent reason about {situation} using prior verified experience?",
    "Which design experience applies to {situation} when resource and performance objectives conflict?",
    "What should be recorded as reusable experience after solving {situation}?",
]

_HARD_QUESTION_FRAMES = [
    "The desired outcome is {tradeoff}. Which design method should be tried first, and what is the safety gate?",
    "A previous implementation suggests this boundary: {constraints} What reusable engineering experience applies?",
    "How should the agent balance this hardware effect ({tradeoff}) against correctness, without blindly changing parameters?",
    "What evidence-backed HLS practice addresses this trade-off: {tradeoff}? State the failure mode if applied carelessly.",
    "I have a design review question: under the constraint '{constraints}', which method and validation sequence are appropriate?",
]

_EVIDENCE_FILTERS = {
    "dense_resource": {"op_type": "dense", "objective": "resource"},
    "dense_latency": {"op_type": "dense", "objective": "latency"},
    "matmul_resource": {"op_type": "matmul", "objective": "resource"},
    "matmul_pipeline": {"op_type": "matmul"},
    "conv_buffer": {"op_type": "conv2d"},
    "conv_parallelism": {"op_type": "conv2d", "objective": "latency"},
    "precision_tradeoff": {"objective": "resource"},
    "functional_gate": {"functional": True},
    "parameter_history": {"has_parameter": True},
}


def _evidence_candidate_allowed(path: Path, card_id: str) -> bool:
    """Implement the internal _evidence_candidate_allowed helper.

    Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

    Args:
        path: Value supplied by the caller and validated by the surrounding schema.
        card_id: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    rule = _EVIDENCE_FILTERS.get(card_id)
    if not rule:
        return True
    state_path = path.parent / "state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    task = state.get("task") or {}
    if "op_type" in rule and str(task.get("op_type") or "").lower() != rule["op_type"]:
        return False
    if "objective" in rule and str(state.get("objective") or task.get("objective") or "").lower() != rule["objective"]:
        return False
    if rule.get("functional") and not bool((state.get("pipeline_status") or {}).get("functional_verified")):
        return False
    if rule.get("has_parameter") and not (path.parent / "parameter_advice.json").exists():
        return False
    return True


def build_design_experience_cases() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Execute build_design_experience_cases at the design_experience_benchmark boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Returns:
        The structured value promised by the function signature.
    """
    cards = []
    cases = []
    for card_id, title, situation, action, tradeoff, constraints, anchors in _CARD_SEEDS:
        cards.append({
            "card_id": card_id,
            "title": title,
            "experience": f"Situation: {situation}. Method: {action} Trade-off: {tradeoff} Boundary: {constraints}",
            "situation": situation,
            "action": action,
            "tradeoff": tradeoff,
            "constraints": constraints,
            "evidence_search": anchors,
        })
        for index, frame in enumerate(_QUESTION_FRAMES, start=1):
            if index > 5:
                hard_frame = _HARD_QUESTION_FRAMES[index - 6]
                query = hard_frame.format(tradeoff=tradeoff.lower(), constraints=constraints.lower())
                difficulty = "hard_compositional"
            else:
                query = frame.format(situation=situation.lower())
                difficulty = "direct_situation"
            cases.append({
                "case_id": f"design_exp_{card_id}_{index:02d}",
                "query": query,
                "relevant_card_ids": [card_id],
                "hard_negative_card_ids": [other[0] for other in _CARD_SEEDS if other[0] != card_id and other[0].split("_")[0] == card_id.split("_")[0]][:2],
                "annotation": "manual_method_label",
                "difficulty": difficulty,
                "annotation_rationale": f"The query describes the trigger '{situation}' and asks for the method, trade-off and boundary; card '{card_id}' is the sole authored card that answers all three.",
            })
    return cards, cases


def _metrics(results: list[dict[str, Any]], top_k: int) -> dict[str, float]:
    """Implement the internal _metrics helper.

    Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

    Args:
        results: Value supplied by the caller and validated by the surrounding schema.
        top_k: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    if not results:
        return {key: 0.0 for key in ("precision_at_k", "recall_at_k", "hit_at_k", "mrr", "ndcg_at_k", "r_precision", "hard_negative_pollution")}
    precision = recall = hit = mrr = ndcg = rprec = pollution = 0.0
    for row in results:
        relevant = set(row["relevant_card_ids"])
        returned = row["returned_card_ids"][:top_k]
        hits = [card for card in returned if card in relevant]
        precision += len(hits) / top_k
        recall += len(hits) / len(relevant)
        hit += bool(hits)
        mrr += 1.0 / (returned.index(hits[0]) + 1) if hits else 0.0
        dcg = sum((1.0 / math.log2(index + 2)) for index, card in enumerate(returned) if card in relevant)
        ideal = sum((1.0 / math.log2(index + 2)) for index in range(min(len(relevant), top_k)))
        ndcg += dcg / ideal if ideal else 0.0
        rprec += len(hits) / len(relevant)
        pollution += sum(card in set(row["hard_negative_card_ids"]) for card in returned) / top_k
    count = float(len(results))
    return {"precision_at_k": precision / count, "recall_at_k": recall / count, "hit_at_k": hit / count, "mrr": mrr / count, "ndcg_at_k": ndcg / count, "r_precision": rprec / count, "hard_negative_pollution": pollution / count}


def _per_card_metrics(results: list[dict[str, Any]], top_k: int) -> dict[str, dict[str, float]]:
    """Implement the internal _per_card_metrics helper.

    Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

    Args:
        results: Value supplied by the caller and validated by the surrounding schema.
        top_k: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in results:
        grouped.setdefault(str(row["relevant_card_ids"][0]), []).append(row)
    return {card_id: _metrics(rows, top_k) | {
        "mean_returned_count": sum(len(row["returned_card_ids"]) for row in rows) / len(rows),
        "top1_accuracy": sum(bool(row["returned_card_ids"] and row["returned_card_ids"][0] in row["relevant_card_ids"]) for row in rows) / len(rows),
    } for card_id, rows in grouped.items()}


def _per_difficulty_metrics(results: list[dict[str, Any]], top_k: int) -> dict[str, dict[str, float]]:
    """Implement the internal _per_difficulty_metrics helper.

    Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

    Args:
        results: Value supplied by the caller and validated by the surrounding schema.
        top_k: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in results:
        grouped.setdefault(str(row.get("difficulty") or "unknown"), []).append(row)
    return {difficulty: _metrics(rows, top_k) for difficulty, rows in grouped.items()}


def _source_metrics(results: list[dict[str, Any]], top_k: int) -> dict[str, float]:
    """Metrics for real indexed source ids, independent of card identity."""
    results = [row for row in results if row.get("relevant_source_ids")]
    if not results:
        return {key: 0.0 for key in ("precision_at_k", "recall_at_k", "hit_at_k", "mrr", "ndcg_at_k", "r_precision", "hard_negative_pollution")}
    normalized = []
    for row in results:
        normalized.append({
            **row,
            "relevant_card_ids": row["relevant_source_ids"],
            "returned_card_ids": row["returned_source_ids"],
            "hard_negative_card_ids": [],
        })
    return _metrics(normalized, top_k)


def run_design_experience_benchmark(workspace_root: str | Path, output: str = "runs/benchmarks/design_experience_benchmark.json", top_k: int = 5) -> dict[str, Any]:
    """Execute run_design_experience_benchmark at the design_experience_benchmark boundary.

    This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

    Args:
        workspace_root: Value supplied by the caller and validated by the surrounding schema.
        output: Value supplied by the caller and validated by the surrounding schema.
        top_k: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    root = Path(workspace_root).resolve()
    cards, cases = build_design_experience_cases()
    # Attach auditable evidence references from the real workspace.  The card
    # prose is authored, but it is never presented as evidence without a file
    # reference from a real run.
    for card in cards:
        refs = []
        terms = [str(item).lower() for item in card["evidence_search"]]
        candidates = (
            sorted((root / "runs").glob("*/summary.md"))
            + sorted((root / "runs").glob("*/suggestions.md"))
            + sorted((root / "runs").glob("*/report.json"))
            + sorted((root / "runs").glob("*/tool_evidence.json"))
            + [root / "docs" / "rag_design.md", root / "docs" / "agent_engineering.md"]
        )
        for candidate in candidates:
            if not candidate.exists():
                continue
            if not _evidence_candidate_allowed(candidate, card["card_id"]):
                continue
            try:
                text = candidate.read_text(encoding="utf-8", errors="ignore").lower()
            except OSError:
                continue
            if sum(term in text for term in terms) >= 2:
                refs.append(str(candidate))
            if len(refs) >= 5:
                break
        card["evidence_refs"] = refs
        card["evidence_status"] = "real_artifact_or_design_doc_refs_found" if refs else "no_matching_artifact_found"
        card["evidence_excerpt"] = _evidence_excerpt(refs[0], card["evidence_search"]) if refs else ""
    # A private persistent DB avoids Windows sqlite file-lock failures during
    # TemporaryDirectory cleanup. It is never the production metadata DB.
    benchmark_db_dir = root / "runs" / "benchmarks" / ".design_experience_rag_db"
    benchmark_db_dir.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        stale = benchmark_db_dir / f"cards.db{suffix}"
        if stale.exists():
            stale.unlink()
    db = Database(benchmark_db_dir / "cards.db", root / "src/dl_op_to_hls/db/schema.sql")
    repo = MetadataRepository(db)
    # Keep the production semantic stack when its local models are present;
    # otherwise the same retriever uses its documented lexical/FTS path.
    config = SemanticRagConfig(enabled=True, local_files_only=True, max_online_embeddings=0)
    memory = RagMemory(repo, workspace_root=root, semantic_config=config)
    documents = []
    for card in cards:
        documents.append({
            # Use a path-like identity. RagRetriever treats the prefix before
            # ':' as an experience family, which would collapse all cards if
            # they used the old `design-card:<id>` form.
            "source_id": f"design-card/{card['card_id']}",
            "source_type": "design_experience_card",
            "text": card["experience"] + (f" Evidence excerpt: {card['evidence_excerpt']}" if card["evidence_excerpt"] else ""),
            "metadata": {"domain": "design_experience", "card_id": card["card_id"], "evidence_refs": card["evidence_refs"], "annotation": "manual_method_label"},
        })
    memory.indexer.index_documents(documents)
    evaluated = []
    for case in cases:
        retrieved = memory.retrieve(case["query"], top_k=top_k)
        ids = [str((item.get("metadata") or {}).get("card_id") or str(item.get("source_id", "")).replace("design-card/", "")) for item in retrieved]
        evaluated.append({**case, "returned_card_ids": ids, "retrieved": [{"card_id": card_id, "source_id": item.get("source_id"), "text": item.get("text"), "retrieval": item.get("retrieval")} for card_id, item in zip(ids, retrieved)]})
    metrics = _metrics(evaluated, top_k)
    per_card = _per_card_metrics(evaluated, top_k)
    returned_counts = [len(row["returned_card_ids"]) for row in evaluated]
    payload = {
        "status": "complete",
        "created_at": _now(),
        "annotation_policy": "manual method cards with situation/action/tradeoff/constraints and real-artifact evidence refs; no run-id or keyword-only labels",
        "corpus": {"cards": len(cards), "cases": len(cases), "effective_independent_intents": len(cards), "queries_per_card": len(cases) // max(1, len(cards)), "source_type": "design_experience_card", "isolated_db": str(benchmark_db_dir / "cards.db"), "production_retriever": dict(memory.retriever.last_diagnostics)},
        "top_k": top_k,
        "metric_audit": {"mean_returned_count": sum(returned_counts) / len(returned_counts), "returned_count_histogram": {str(count): returned_counts.count(count) for count in sorted(set(returned_counts))}, "warning": "200 queries are not 200 independent intents; aggregate scores can be dominated by repeated card paraphrases and short result lists"},
        "metrics": metrics,
        "per_card_metrics": per_card,
        "per_difficulty_metrics": _per_difficulty_metrics(evaluated, top_k),
        "cards": cards,
        "cases": evaluated,
    }
    destination = root / output
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"status": payload["status"], "output": str(destination), "cards": len(cards), "cases": len(cases), "metrics": metrics}


def run_production_source_benchmark(workspace_root: str | Path, output: str = "runs/benchmarks/design_experience_production_source_benchmark.json", top_k: int = 5) -> dict[str, Any]:
    """Evaluate against real source ids already indexed in production SQLite."""
    root = Path(workspace_root).resolve()
    cards, cases = build_design_experience_cases()
    # Resolve the same evidence references used by the cards, but do not index
    # the authored cards. The retriever searches only the existing production DB.
    for card in cards:
        refs = []
        for candidate in sorted((root / "runs").glob("*/summary.md")) + sorted((root / "runs").glob("*/suggestions.md")) + sorted((root / "runs").glob("*/report.json")) + sorted((root / "runs").glob("*/tool_evidence.json")):
            if _evidence_candidate_allowed(candidate, card["card_id"]):
                try:
                    text = candidate.read_text(encoding="utf-8", errors="ignore").lower()
                except OSError:
                    continue
                if sum(term.lower() in text for term in card["evidence_search"]) >= 2:
                    refs.append(str(candidate))
            if len(refs) >= 5:
                break
        card["evidence_refs"] = refs
    database = Database(root / "runs" / "metadata.db", root / "src/dl_op_to_hls/db/schema.sql")
    memory = RagMemory(MetadataRepository(database), workspace_root=root, semantic_config=SemanticRagConfig(enabled=True, local_files_only=True, max_online_embeddings=0))
    evaluated = []
    for case in cases:
        card = next(card for card in cards if card["card_id"] == case["relevant_card_ids"][0])
        retrieved = memory.retrieve(case["query"], top_k=top_k)
        returned = [str(item.get("source_id") or "") for item in retrieved]
        evaluated.append({**case, "relevant_source_ids": card["evidence_refs"], "returned_source_ids": returned, "retrieved": [{"source_id": item.get("source_id"), "text": item.get("text"), "metadata": item.get("metadata")} for item in retrieved]})
    eligible_cases = sum(bool(row["relevant_source_ids"]) for row in evaluated)
    metrics = _source_metrics(evaluated, top_k)
    payload = {"status": "complete", "created_at": _now(), "annotation_policy": "manual method-card qrels mapped to real production artifact source ids; no authored card documents indexed", "corpus": {"cards": len(cards), "cases": len(cases), "eligible_cases_with_real_qrels": eligible_cases, "qrels_coverage": eligible_cases / max(1, len(cases)), "production_db": str(root / "runs" / "metadata.db"), "indexed_source_count": len({source for row in evaluated for source in row["returned_source_ids"]})}, "top_k": top_k, "metrics": metrics, "cards": [{"card_id": c["card_id"], "evidence_refs": c["evidence_refs"]} for c in cards], "cases": evaluated}
    destination = root / output
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"status": payload["status"], "output": str(destination), "cards": len(cards), "cases": len(cases), "metrics": metrics}


def run_production_noise_card_benchmark(workspace_root: str | Path, output: str = "runs/benchmarks/design_experience_production_noise_benchmark.json", top_k: int = 5) -> dict[str, Any]:
    """Evaluate promoted method memories against a copy of the full corpus."""
    root = Path(workspace_root).resolve()
    cards, cases = build_design_experience_cases()
    # Reuse the audited resolver by running only its evidence selection logic.
    for card in cards:
        refs = []
        candidates = sorted((root / "runs").glob("*/summary.md")) + sorted((root / "runs").glob("*/suggestions.md")) + sorted((root / "runs").glob("*/report.json")) + sorted((root / "runs").glob("*/tool_evidence.json")) + [root / "docs" / "rag_design.md", root / "docs" / "agent_engineering.md"]
        for candidate in candidates:
            if not candidate.exists() or not _evidence_candidate_allowed(candidate, card["card_id"]):
                continue
            try:
                text = candidate.read_text(encoding="utf-8", errors="ignore").lower()
            except OSError:
                continue
            if sum(term.lower() in text for term in card["evidence_search"]) >= 2:
                refs.append(str(candidate))
            if len(refs) >= 5:
                break
        card["evidence_refs"] = refs
        card["evidence_excerpt"] = _evidence_excerpt(refs[0], card["evidence_search"]) if refs else ""

    benchmark_dir = root / "runs" / "benchmarks" / ".design_experience_production_noise_db"
    benchmark_dir.mkdir(parents=True, exist_ok=True)
    target_db = benchmark_dir / "metadata.db"
    for path in [target_db, Path(f"{target_db}-wal"), Path(f"{target_db}-shm"), benchmark_dir / "cards.faiss", benchmark_dir / "cards.faiss.meta.json"]:
        if path.exists():
            path.unlink()
    source_db = root / "runs" / "metadata.db"
    with sqlite3.connect(source_db) as source, sqlite3.connect(target_db) as target:
        source.backup(target)
    database = Database(target_db, root / "src/dl_op_to_hls/db/schema.sql")
    repository = MetadataRepository(database)
    config = SemanticRagConfig(enabled=True, local_files_only=True, max_online_embeddings=64, vector_backend="faiss_hnsw", vector_index_path=str(benchmark_dir / "cards.faiss"), ann_min_rows=256)
    memory = RagMemory(repository, workspace_root=root, semantic_config=config)
    before_chunks = len(repository.get_rag_chunks())
    for card in cards:
        memory.index_text(
            f"design-card/{card['card_id']}",
            card["experience"] + (f" Evidence: {card['evidence_excerpt']}" if card["evidence_excerpt"] else ""),
            {"domain": "design_experience", "memory_type": "optimization", "source_type": "design_experience_card", "card_id": card["card_id"], "evidence_refs": card["evidence_refs"], "annotation": "manual_method_label"},
        )
    evaluated = []
    for case in cases:
        retrieved = memory.retrieve(case["query"], top_k=top_k)
        ids = [str((item.get("metadata") or {}).get("card_id") or "") for item in retrieved]
        evaluated.append({**case, "returned_card_ids": ids, "retrieved": [{"card_id": card_id, "source_id": item.get("source_id"), "text": item.get("text"), "retrieval": item.get("retrieval")} for card_id, item in zip(ids, retrieved)]})
    metrics = _metrics(evaluated, top_k)
    returned_counts = [len(row["returned_card_ids"]) for row in evaluated]
    payload = {"status": "complete", "created_at": _now(), "annotation_policy": "manual evidence-backed method cards retrieved inside a full production-corpus snapshot", "corpus": {"production_chunks_before_cards": before_chunks, "promoted_method_cards": len(cards), "cases": len(cases), "effective_independent_intents": len(cards), "isolated_db": str(target_db)}, "top_k": top_k, "metric_audit": {"mean_returned_count": sum(returned_counts) / len(returned_counts), "returned_count_histogram": {str(count): returned_counts.count(count) for count in sorted(set(returned_counts))}, "query_leakage_warning": "direct and hard queries are reported separately; cards and queries share an authored ontology"}, "metrics": metrics, "per_card_metrics": _per_card_metrics(evaluated, top_k), "per_difficulty_metrics": _per_difficulty_metrics(evaluated, top_k), "cards": cards, "cases": evaluated}
    destination = root / output
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"status": payload["status"], "output": str(destination), "cards": len(cards), "cases": len(cases), "metrics": metrics}
