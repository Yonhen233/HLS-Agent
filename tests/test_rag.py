"""Test contracts and regression checks for test_rag.py.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

import json

from dl_op_to_hls.db.database import Database
from dl_op_to_hls.db.repositories import MetadataRepository
from dl_op_to_hls.rag.memory import RagMemory
from dl_op_to_hls.rag.retriever import RagRetriever
from dl_op_to_hls.rag.semantic import SemanticRagConfig


class _FakeEmbedder:
    """Coordinate _FakeEmbedder within the test_rag boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    model_id = "test-embedding-v1"

    def __init__(self, vectors):
        """Verify the __init__ contract.

        The test should fail on a real contract regression rather than hide an unsupported path.

        Args:
            vectors: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        self.vectors = vectors
        self.batches = []

    def encode(self, texts, *, batch_size):
        """Verify the encode contract.

        The test should fail on a real contract regression rather than hide an unsupported path.

        Args:
            texts: Value supplied by the caller and validated by the surrounding schema.
            batch_size: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        self.batches.append(list(texts))
        return [list(self.vectors[text]) for text in texts]


class _FakeReranker:
    """Coordinate _FakeReranker within the test_rag boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    model_id = "test-cross-encoder-v1"

    def __init__(self, scores):
        """Verify the __init__ contract.

        The test should fail on a real contract regression rather than hide an unsupported path.

        Args:
            scores: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        self.scores = scores
        self.pairs = []

    def predict(self, pairs, *, batch_size):
        """Verify the predict contract.

        The test should fail on a real contract regression rather than hide an unsupported path.

        Args:
            pairs: Value supplied by the caller and validated by the surrounding schema.
            batch_size: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        self.pairs.extend(pairs)
        return [float(self.scores[document]) for _, document in pairs]


def _semantic_memory(tmp_path, vectors, rerank_scores):
    """Verify the _semantic_memory contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.
        vectors: Value supplied by the caller and validated by the surrounding schema.
        rerank_scores: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    database = Database(tmp_path / "metadata.db", "src/dl_op_to_hls/db/schema.sql")
    repository = MetadataRepository(database)
    embedder = _FakeEmbedder(vectors)
    reranker = _FakeReranker(rerank_scores)
    config = SemanticRagConfig(
        enabled=True,
        candidate_pool_size=8,
        min_embedding_score=0.0,
        min_reranker_score=0.01,
    )
    memory = RagMemory(
        repository,
        semantic_config=config,
        embedder=embedder,
        reranker=reranker,
    )
    return memory, repository, embedder, reranker


def _memory(tmp_path):
    """Verify the _memory contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    database = Database(tmp_path / "metadata.db", "src/dl_op_to_hls/db/schema.sql")
    return RagMemory(MetadataRepository(database))


def _memory_with_workspace(tmp_path):
    """Verify the _memory_with_workspace contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    database = Database(tmp_path / "metadata.db", "src/dl_op_to_hls/db/schema.sql")
    return RagMemory(MetadataRepository(database), workspace_root=tmp_path)


def test_rag_index_text(tmp_path):
    """Verify the test_rag_index_text contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    memory = _memory(tmp_path)
    result = memory.index_text("doc1", "Dense DSP reuse factor hint", {"op_type": "Dense"})
    assert result["chunks_indexed"] >= 1


def test_rag_retrieve_experience(tmp_path):
    """Verify the test_rag_retrieve_experience contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    memory = _memory(tmp_path)
    memory.index_text("doc1", "Dense DSP reuse factor hint", {"op_type": "Dense"})
    results = memory.retrieve("Dense reuse factor", top_k=3)
    assert results
    assert results[0]["retrieval"]["hybrid_score"] >= results[0]["retrieval"]["lexical_score"]
    assert results[0]["provenance"]["trust_score"] > 0


def test_rag_retrieve_filters_generic_resource_overlap_when_anchor_mismatches(tmp_path):
    """Verify the test_rag_retrieve_filters_generic_resource_overlap_when_anchor_mismatches contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    memory = _memory(tmp_path)
    memory.index_text("matmul", "MatMul resource reuse factor DSP hint", {"op_type": "MatMul"})
    results = memory.retrieve("resnet18_boundary_demo resource reuse factor DSP Vivado HLS", top_k=3)
    assert results == []


def test_hardware_part_and_fixed_precision_are_soft_not_hard_entity_anchors(tmp_path):
    """Verify the test_hardware_part_and_fixed_precision_are_soft_not_hard_entity_anchors contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    memory = _memory(tmp_path)
    memory.index_text(
        "runs/dense_verified/parameter_advice.json",
        "Dense verified parameter experience recommends resource reuse.",
        {"domain": "parameter", "op_type": "Dense"},
    )

    results = memory.retrieve(
        "Dense input 16 output 32 ap_fixed<16,6> xc7z020clg400-1",
        top_k=1,
        domain="parameter",
    )

    assert results
    assert results[0]["source_id"].endswith("parameter_advice.json")


def test_rag_index_and_retrieve_strip_second_order_prior_experience(tmp_path):
    """Verify the test_rag_index_and_retrieve_strip_second_order_prior_experience contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    memory = _memory(tmp_path)
    memory.index_text(
        "resnet",
        "ResNet boundary unsupported report. Prior experience hint: MatMul resource reuse factor DSP hint.",
        {"op_type": "ResNet"},
    )

    results = memory.retrieve("resnet18_boundary_demo unsupported", top_k=3)

    assert results
    assert "prior experience hint" not in results[0]["text"].lower()
    assert "matmul" not in results[0]["text"].lower()


def test_rag_index_run_artifacts(tmp_path):
    """Verify the test_rag_index_run_artifacts contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    memory = _memory(tmp_path)
    summary = tmp_path / "summary.md"
    summary.write_text("Dense DSP reuse factor summary", encoding="utf-8")
    result = memory.index_run("r1", [str(summary)])
    assert result["chunks_indexed"] >= 1


def test_refresh_artifact_metadata_does_not_create_new_chunks(tmp_path):
    """Verify the test_refresh_artifact_metadata_does_not_create_new_chunks contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    memory = _memory(tmp_path)
    run_dir = tmp_path / "runs" / "dense_real"
    run_dir.mkdir(parents=True)
    advice = run_dir / "parameter_advice.json"
    advice.write_text("Dense parameter advice.", encoding="utf-8")
    (run_dir / "state.json").write_text(
        '{"objective":"resource","task":{"task_type":"operator","op_type":"Dense"},"pipeline_status":{"functional_verified":true}}',
        encoding="utf-8",
    )
    (run_dir / "tool_evidence.json").write_text(
        '{"receipts":[{"valid":true,"mock_evidence":false,"evidence_class":"real_csynth"}]}',
        encoding="utf-8",
    )
    memory.index_text(str(advice), "Dense parameter advice.", {"domain": "parameter"})
    before = memory.repository.get_rag_chunks()

    result = memory.refresh_artifact_metadata("dense_real", [str(advice)])
    after = memory.repository.get_rag_chunks()

    assert result == {"status": "success", "sources_updated": 1, "chunks_updated": 1}
    assert len(after) == len(before) == 1
    metadata = json.loads(after[0]["metadata_json"])
    assert metadata["evidence_verified"] is True
    assert metadata["op_type"] == "Dense"


def test_rag_retrieves_static_vivado_failure_playbook(tmp_path):
    """Verify the test_rag_retrieves_static_vivado_failure_playbook contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True)
    playbook = docs_dir / "vivado_failure_playbook.md"
    playbook.write_text(
        "VivadoNotFoundError is recoverable. Mark synthesis as skipped and keep partial_success.",
        encoding="utf-8",
    )
    generic = tmp_path / "summary.md"
    generic.write_text("Synthesis was skipped for an unrelated boundary demo.", encoding="utf-8")

    memory = _memory_with_workspace(tmp_path)
    memory.index_text(str(generic), generic.read_text(encoding="utf-8"), {"task_type": "model"})
    results = memory.retrieve("VivadoNotFoundError recoverable skipped synthesis", top_k=3)

    assert results
    assert any("vivado_failure_playbook.md" in item["source_id"] for item in results)
    assert all("summary.md" not in item["source_id"] for item in results)


def test_rag_static_playbook_not_buried_by_duplicate_failure_memories(tmp_path):
    """Verify the test_rag_static_playbook_not_buried_by_duplicate_failure_memories contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True)
    playbook = docs_dir / "vivado_failure_playbook.md"
    playbook.write_text(
        "VivadoNotFoundError means vivado_hls is unavailable. It is recoverable; skip synthesis and keep partial_success.",
        encoding="utf-8",
    )
    memory = _memory_with_workspace(tmp_path)
    for idx in range(6):
        memory.index_text(
            f"memory:{idx}",
            "VivadoNotFoundError is recoverable and synthesis can be skipped while keeping generated HLS artifacts.",
            {"source_type": "memory_fact"},
        )

    results = memory.retrieve("VivadoNotFoundError recoverable skipped synthesis", top_k=3)

    assert results
    assert "vivado_failure_playbook.md" in results[0]["source_id"]
    assert len({item["text"] for item in results}) == len(results)


def test_rag_source_anchor_prioritizes_matching_task_family(tmp_path):
    """Verify the test_rag_source_anchor_prioritizes_matching_task_family contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    memory = _memory(tmp_path)
    memory.index_text(
        "runs/dense_16x32/suggestions.md",
        "Dense high DSP usage can be reduced by increasing reuse factor.",
        {"task_type": "operator", "op_type": "Dense"},
    )
    memory.index_text(
        "runs/mnist_qkeras_cnn/suggestions.md",
        "QKeras CNN failed, but a retrieved Dense high DSP reuse factor hint appeared in prior context.",
        {"task_type": "model", "frontend": "qkeras"},
    )

    results = memory.retrieve("Dense high DSP reuse factor", top_k=2)

    assert results
    assert results[0]["source_id"] == "runs/dense_16x32/suggestions.md"


def test_rag_domain_filter_separates_parameter_and_optimization_memory(tmp_path):
    """Verify the test_rag_domain_filter_separates_parameter_and_optimization_memory contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    memory = _memory(tmp_path)
    memory.index_text(
        "runs/mnist_mlp/parameter_advice.json",
        "mnist_mlp_demo verified parameter precision fixed<8,3> reuse_factor 512 clock 10",
        {"domain": "parameter", "memory_type": "parameter_experience"},
    )
    memory.index_text(
        "runs/dense/suggestions.md",
        "Dense high DSP can be reduced by increasing reuse factor.",
        {"domain": "optimization", "memory_type": "optimization"},
    )

    parameter_results = memory.retrieve("reuse factor precision", top_k=5, domain="parameter")
    optimization_results = memory.retrieve("reuse factor DSP", top_k=5, domain="optimization")

    assert parameter_results
    assert all(item["metadata"].get("domain") == "parameter" for item in parameter_results)
    assert optimization_results
    assert all(item["metadata"].get("domain") == "optimization" for item in optimization_results)


def test_parameter_retrieval_uses_hard_evidence_gate_when_verified_peer_exists(tmp_path):
    """Verify the test_parameter_retrieval_uses_hard_evidence_gate_when_verified_peer_exists contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    memory = _memory(tmp_path)
    memory.index_text(
        "runs/dense_mock/parameter_advice.json",
        "Dense resource parameter recommendation reuse factor.",
        {"domain": "parameter", "op_type": "Dense", "evidence_verified": False},
    )
    memory.index_text(
        "runs/dense_real/parameter_advice.json",
        "Dense resource parameter recommendation reuse factor.",
        {"domain": "parameter", "op_type": "Dense", "evidence_verified": True},
    )

    results = memory.retrieve("Dense resource reuse factor", top_k=5, domain="parameter")

    assert results
    assert {item["source_id"] for item in results} == {"runs/dense_real/parameter_advice.json"}
    assert results[0]["retrieval"]["evidence_gate_passed"] is True


def test_metadata_filter_separates_operator_from_model_parameter_experience(tmp_path):
    """Verify the test_metadata_filter_separates_operator_from_model_parameter_experience contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    memory = _memory(tmp_path)
    memory.index_text(
        "runs/dense_operator/parameter_advice.json",
        "Dense operator latency parameter experience.",
        {"domain": "parameter", "task_type": "operator", "op_type": "Dense", "objective": "latency"},
    )
    memory.index_text(
        "runs/mlp_model/parameter_advice.json",
        "Dense MLP model latency parameter experience.",
        {"domain": "parameter", "task_type": "model", "name": "mlp_demo", "objective": "latency"},
    )

    results = memory.retrieve(
        "Dense latency parameter experience",
        top_k=5,
        domain="parameter",
        metadata_filter={"task_type": "operator", "op_type": "Dense", "objective": "latency"},
    )

    assert [item["source_id"] for item in results] == ["runs/dense_operator/parameter_advice.json"]


def test_embedding_recall_finds_semantic_match_without_lexical_anchor(tmp_path):
    """Verify the test_embedding_recall_finds_semantic_match_without_lexical_anchor contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    query = "lower multiplier energy"
    relevant = "Reducing parallel arithmetic saves power in the synthesized circuit."
    irrelevant = "The report parser reads XML files from the build directory."
    memory, _, _, _ = _semantic_memory(
        tmp_path,
        {
            query: [1.0, 0.0],
            relevant: [0.95, 0.05],
            irrelevant: [0.0, 1.0],
        },
        {relevant: 4.0, irrelevant: -4.0},
    )
    memory.index_text("power-guide", relevant, {"source_type": "static_doc"})
    memory.index_text("parser-guide", irrelevant, {"source_type": "static_doc"})

    result = memory.retrieve_corrective(query, top_k=2)

    assert result["abstained"] is False
    assert result["results"][0]["source_id"] == "power-guide"
    assert result["results"][0]["retrieval"]["mode"] == "embedding_cross_encoder"
    assert result["results"][0]["evidence_grade"]["semantic_support"] is True


def test_cross_encoder_reranks_embedding_candidate_pool(tmp_path):
    """Verify the test_cross_encoder_reranks_embedding_candidate_pool contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    query = "best implementation approach"
    embedding_favorite = "Candidate A implementation."
    reranker_favorite = "Candidate B implementation."
    memory, _, _, _ = _semantic_memory(
        tmp_path,
        {
            query: [1.0, 0.0],
            embedding_favorite: [1.0, 0.0],
            reranker_favorite: [0.7, 0.7],
        },
        {embedding_favorite: -4.0, reranker_favorite: 4.0},
    )
    memory.index_text("candidate-a", embedding_favorite, {})
    memory.index_text("candidate-b", reranker_favorite, {})

    results = memory.retrieve(query, top_k=2)

    assert results[0]["source_id"] == "candidate-b"
    assert results[0]["retrieval"]["cross_encoder_score"] > results[1]["retrieval"]["cross_encoder_score"]


def test_provenance_does_not_soft_bias_rrf_or_cross_encoder_ranking(tmp_path):
    """Verify the test_provenance_does_not_soft_bias_rrf_or_cross_encoder_ranking contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    first = "Dense reuse factor option A."
    second = "Dense reuse factor option B."
    memory, _, _, _ = _semantic_memory(
        tmp_path,
        {"Dense reuse factor": [1.0, 0.0], first: [1.0, 0.0], second: [1.0, 0.0]},
        {first: 2.0, second: 2.0},
    )
    memory.index_text("verified-a", first, {"memory_type": "verified_implementation"})
    memory.index_text("ordinary-b", second, {"source_type": "artifact"})

    results = memory.retrieve("Dense reuse factor", top_k=2)

    assert len(results) == 2
    assert {item["retrieval"]["fusion_method"] for item in results} == {"rrf"}
    assert len({item["retrieval"]["hybrid_score"] for item in results}) == 1
    assert {item["provenance"]["trust_score"] for item in results} == {0.7, 0.95}


def test_indexed_embeddings_are_persisted_and_reused(tmp_path):
    """Verify the test_indexed_embeddings_are_persisted_and_reused contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    query = "semantic query"
    document = "Persisted semantic document."
    memory, repository, embedder, _ = _semantic_memory(
        tmp_path,
        {query: [1.0, 0.0], document: [1.0, 0.0]},
        {document: 4.0},
    )
    memory.index_text("doc", document, {})
    document_encoding_count = sum(document in batch for batch in embedder.batches)

    results = memory.retrieve(query, top_k=1)
    stored = repository.get_rag_embeddings([1], embedder.model_id)

    assert results
    assert stored[1]["embedding"] == [1.0, 0.0]
    assert sum(document in batch for batch in embedder.batches) == document_encoding_count


def test_online_embedding_migration_is_bounded(tmp_path):
    """Verify the test_online_embedding_migration_is_bounded contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    database = Database(tmp_path / "metadata.db", "src/dl_op_to_hls/db/schema.sql")
    repository = MetadataRepository(database)
    legacy = RagMemory(repository)
    documents = [f"Power optimization note {index}." for index in range(5)]
    for index, document in enumerate(documents):
        legacy.index_text(f"legacy-{index}", document, {})
    query = "power optimization advice"
    embedder = _FakeEmbedder({query: [1.0, 0.0], **{item: [1.0, 0.0] for item in documents}})
    reranker = _FakeReranker({item: 2.0 for item in documents})
    memory = RagMemory(
        repository,
        semantic_config=SemanticRagConfig(
            enabled=True,
            max_online_embeddings=2,
            min_embedding_score=0.0,
            min_reranker_score=0.01,
        ),
        embedder=embedder,
        reranker=reranker,
    )

    results = memory.retrieve(query, top_k=2)
    diagnostics = memory.retriever.last_diagnostics

    assert results
    assert diagnostics["online_embedding_count"] == 2
    assert diagnostics["unembedded_candidate_count"] == 3
    assert diagnostics["vector_coverage"] == 0.4
    assert sum(len(batch) for batch in embedder.batches if query not in batch) == 2


def test_embedding_backfill_is_resumable_and_reports_coverage(tmp_path):
    """Verify the test_embedding_backfill_is_resumable_and_reports_coverage contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    database = Database(tmp_path / "metadata.db", "src/dl_op_to_hls/db/schema.sql")
    repository = MetadataRepository(database)
    legacy = RagMemory(repository)
    documents = [f"Legacy HLS note {index}." for index in range(3)]
    for index, document in enumerate(documents):
        legacy.index_text(f"legacy-{index}", document, {})
    memory = RagMemory(
        repository,
        semantic_config=SemanticRagConfig(enabled=True),
        embedder=_FakeEmbedder({item: [1.0, 0.0] for item in documents}),
        reranker=_FakeReranker({item: 1.0 for item in documents}),
    )

    first = memory.backfill_embeddings(batch_size=1, max_chunks=2)
    second = memory.backfill_embeddings(batch_size=4)

    assert first["embeddings_indexed"] == 2
    assert first["coverage"]["coverage"] == 0.6667
    assert second["embeddings_indexed"] == 1
    assert second["coverage"]["coverage"] == 1.0


def test_missing_faiss_uses_exact_vector_scan_without_disabling_embeddings(tmp_path):
    """Verify the test_missing_faiss_uses_exact_vector_scan_without_disabling_embeddings contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    query = "Dense resource advice"
    document = "Dense reuse factor lowers DSP usage."
    memory, _, _, _ = _semantic_memory(
        tmp_path,
        {query: [1.0, 0.0], document: [1.0, 0.0]},
        {document: 4.0},
    )
    memory.index_text("dense", document, {"domain": "parameter"})

    class _MissingFaissIndex:
        """Coordinate _MissingFaissIndex within the test_rag boundary.

        The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
        """
        def ensure(self, records):
            """Verify the ensure contract.

            The test should fail on a real contract regression rather than hide an unsupported path.

            Args:
                records: Value supplied by the caller and validated by the surrounding schema.

            Returns:
                The structured value promised by the function signature.
            """
            raise ModuleNotFoundError("No module named 'faiss'")

    memory.semantic_engine.vector_index = _MissingFaissIndex()
    object.__setattr__(memory.semantic_engine.config, "ann_min_rows", 1)

    results = memory.retrieve(query, top_k=1, domain="parameter")

    assert results
    assert results[0]["retrieval"]["mode"] == "embedding_cross_encoder"
    assert memory.retriever.last_diagnostics["embedding_error"] is None
    assert "faiss" in memory.retriever.last_diagnostics["ann_error"]


def test_windows_paths_are_distinct_rag_source_families():
    """Verify the test_windows_paths_are_distinct_rag_source_families contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    assert RagRetriever._source_family(r"D:\runs\one\summary.md") != RagRetriever._source_family(
        r"D:\runs\two\summary.md"
    )
    assert RagRetriever._source_family("memory_fact:1") == RagRetriever._source_family("memory_fact:2")


def test_semantic_candidate_pool_limits_chunks_per_run():
    """Verify the test_semantic_candidate_pool_limits_chunks_per_run contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    scored = [
        (0.9, {"source_id": "run-a/advice.json", "metadata": {"run_id": "run-a"}}),
        (0.8, {"source_id": "run-a/advice.json", "metadata": {"run_id": "run-a"}}),
        (0.7, {"source_id": "run-a/advice.json", "metadata": {"run_id": "run-a"}}),
        (0.6, {"source_id": "run-b/advice.json", "metadata": {"run_id": "run-b"}}),
    ]

    limited = RagRetriever._limit_candidates_per_experience(scored, limit=2)

    assert [item[0] for item in limited] == [0.9, 0.8, 0.6]


def test_rag_deduplication_preserves_identical_evidence_from_distinct_runs():
    """Verify the test_rag_deduplication_preserves_identical_evidence_from_distinct_runs contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    scored = [
        (0.9, {"source_id": "run-a/advice.json", "text": "same advice", "metadata": {"run_id": "run-a"}}),
        (0.8, {"source_id": "run-b/advice.json", "text": "same advice", "metadata": {"run_id": "run-b"}}),
        (0.7, {"source_id": "run-a/advice.json", "text": "same advice", "metadata": {"run_id": "run-a"}}),
    ]

    deduplicated = RagRetriever._deduplicate_scored(scored)

    assert [(score, item["metadata"]["run_id"]) for score, item in deduplicated] == [
        (0.9, "run-a"),
        (0.8, "run-b"),
    ]
