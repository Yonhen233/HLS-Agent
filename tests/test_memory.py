import json
from pathlib import Path

from dl_op_to_hls.db.database import Database
from dl_op_to_hls.db.repositories import MetadataRepository
from dl_op_to_hls.memory.memory_manager import MemoryManager
from dl_op_to_hls.memory.memory_policy import MemoryPolicy
from dl_op_to_hls.rag.memory import RagMemory


def _manager(tmp_path):
    database = Database(tmp_path / "metadata.db", "src/dl_op_to_hls/db/schema.sql")
    repo = MetadataRepository(database)
    rag = RagMemory(repo)
    return MemoryManager(repo, rag, tmp_path)


def test_memory_write_short_term(tmp_path):
    manager = _manager(tmp_path)
    result = manager.write_short_term("r1", "todo_001", {"summary": "ok"})
    assert Path(result["path"]).exists()


def test_memory_compress_run_context(tmp_path):
    manager = _manager(tmp_path)
    manager.write_short_term("r1", "todo_001", {"summary": "ok"})
    result = manager.compress_run_context("r1")
    assert result["compressed_context"]["entry_count"] == 1


def test_memory_extract_candidates(tmp_path):
    manager = _manager(tmp_path)
    run_dir = tmp_path / "runs" / "r1"
    run_dir.mkdir(parents=True, exist_ok=True)
    state = {
        "run_id": "r1",
        "task": {"task_type": "operator", "name": "dense_demo", "op_type": "Dense"},
        "selected_path": "fallback_template_path",
        "status": "success",
        "report": {"status": "success"},
        "suggestions": ["Increase reuse factor."],
        "errors": [],
        "hls4ml_support": {"unsupported_layers": []},
    }
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    candidates = manager.extract_memory_candidates("r1")
    assert candidates


def test_memory_policy_promotes_failure():
    policy = MemoryPolicy()
    candidate = {"kind": "failure", "summary": "Vivado missing", "value": {"error_type": "VivadoNotFoundError"}}
    assert policy.should_promote(candidate) is True


def test_memory_policy_promotes_optimization():
    policy = MemoryPolicy()
    candidate = {"kind": "optimization", "summary": "Reuse factor reduced DSP."}
    assert policy.should_promote(candidate) is True


def test_memory_policy_ignores_raw_log():
    policy = MemoryPolicy()
    candidate = {"kind": "semantic", "summary": "raw log dump", "fact": "raw log should not be promoted"}
    assert policy.should_promote(candidate) is False


def test_memory_promote_to_long_term(tmp_path):
    manager = _manager(tmp_path)
    result = manager.promote_to_long_term(
        "r1",
        [{"kind": "optimization", "key": "optimization.r1", "summary": "Reuse factor reduced DSP.", "value": {"dsp": 12}}],
    )
    assert result["promoted_memories"]


def test_memory_retrieve_similar_experiences(tmp_path):
    manager = _manager(tmp_path)
    manager.promote_to_long_term(
        "r1",
        [{"kind": "episodic", "key": "episode.r1", "summary": "Dense fallback succeeded.", "value": {"name": "dense"}}],
    )
    results = manager.retrieve_similar_experiences("Dense fallback", top_k=3)
    assert results


def test_memory_retrieve_failure_cases(tmp_path):
    manager = _manager(tmp_path)
    manager.repository.save_failure({"run_id": "r1", "error_type": "VivadoNotFoundError", "error_message": "vivado missing"})
    results = manager.retrieve_failure_cases("Vivado missing", top_k=3)
    assert results


def test_memory_save_skill(tmp_path):
    manager = _manager(tmp_path)
    result = manager.save_skill("fallback_template_skill", ["Generate fallback"], {"op_type": "Dense"}, {"generated": True})
    assert result["status"] == "success"

