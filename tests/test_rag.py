from dl_op_to_hls.db.database import Database
from dl_op_to_hls.db.repositories import MetadataRepository
from dl_op_to_hls.rag.memory import RagMemory


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
