from dl_op_to_hls.db.database import Database
from dl_op_to_hls.db.repositories import MetadataRepository
from dl_op_to_hls.rag.memory import RagMemory
from dl_op_to_hls.rag.retriever import RagRetriever
from dl_op_to_hls.rag.semantic import SemanticRagConfig


class _FakeEmbedder:
    model_id = "test-embedding-v1"

    def __init__(self, vectors):
        self.vectors = vectors
        self.batches = []

    def encode(self, texts, *, batch_size):
        self.batches.append(list(texts))
        return [list(self.vectors[text]) for text in texts]


class _FakeReranker:
    model_id = "test-cross-encoder-v1"

    def __init__(self, scores):
        self.scores = scores
        self.pairs = []

    def predict(self, pairs, *, batch_size):
        self.pairs.extend(pairs)
        return [float(self.scores[document]) for _, document in pairs]


def _semantic_memory(tmp_path, vectors, rerank_scores):
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
    database = Database(tmp_path / "metadata.db", "src/dl_op_to_hls/db/schema.sql")
    return RagMemory(MetadataRepository(database))


def _memory_with_workspace(tmp_path):
    database = Database(tmp_path / "metadata.db", "src/dl_op_to_hls/db/schema.sql")
    return RagMemory(MetadataRepository(database), workspace_root=tmp_path)


def test_rag_index_text(tmp_path):
    memory = _memory(tmp_path)
    result = memory.index_text("doc1", "Dense DSP reuse factor hint", {"op_type": "Dense"})
    assert result["chunks_indexed"] >= 1


def test_rag_retrieve_experience(tmp_path):
    memory = _memory(tmp_path)
    memory.index_text("doc1", "Dense DSP reuse factor hint", {"op_type": "Dense"})
    results = memory.retrieve("Dense reuse factor", top_k=3)
    assert results
    assert results[0]["retrieval"]["hybrid_score"] >= results[0]["retrieval"]["lexical_score"]
    assert results[0]["provenance"]["trust_score"] > 0


def test_rag_retrieve_filters_generic_resource_overlap_when_anchor_mismatches(tmp_path):
    memory = _memory(tmp_path)
    memory.index_text("matmul", "MatMul resource reuse factor DSP hint", {"op_type": "MatMul"})
    results = memory.retrieve("resnet18_boundary_demo resource reuse factor DSP Vivado HLS", top_k=3)
    assert results == []


def test_rag_index_and_retrieve_strip_second_order_prior_experience(tmp_path):
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
    memory = _memory(tmp_path)
    summary = tmp_path / "summary.md"
    summary.write_text("Dense DSP reuse factor summary", encoding="utf-8")
    result = memory.index_run("r1", [str(summary)])
    assert result["chunks_indexed"] >= 1


def test_rag_retrieves_static_vivado_failure_playbook(tmp_path):
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


def test_embedding_recall_finds_semantic_match_without_lexical_anchor(tmp_path):
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


def test_indexed_embeddings_are_persisted_and_reused(tmp_path):
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


def test_windows_paths_are_distinct_rag_source_families():
    assert RagRetriever._source_family(r"D:\runs\one\summary.md") != RagRetriever._source_family(
        r"D:\runs\two\summary.md"
    )
    assert RagRetriever._source_family("memory_fact:1") == RagRetriever._source_family("memory_fact:2")
