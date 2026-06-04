from dl_op_to_hls.db.database import Database
from dl_op_to_hls.db.repositories import MetadataRepository
from dl_op_to_hls.rag.memory import RagMemory


def _memory(tmp_path):
    database = Database(tmp_path / "metadata.db", "src/dl_op_to_hls/db/schema.sql")
    return RagMemory(MetadataRepository(database))


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
