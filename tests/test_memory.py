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


def test_memory_uses_configured_external_runs_root(tmp_path):
    external_runs = tmp_path / "short_execution_root"
    database = Database(external_runs / "metadata.db", "src/dl_op_to_hls/db/schema.sql")
    repo = MetadataRepository(database)
    manager = MemoryManager(repo, RagMemory(repo), tmp_path, runs_root=external_runs)

    result = manager.write_short_term("r1", "todo_001", {"summary": "isolated"})

    assert Path(result["path"]).resolve() == (external_runs / "r1" / "memory" / "short_term.json").resolve()
    assert not (tmp_path / "runs" / "r1" / "memory" / "short_term.json").exists()


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


def test_memory_extracts_synthesis_success_but_not_verified_without_functional_check(tmp_path):
    manager = _manager(tmp_path)
    run_dir = tmp_path / "runs" / "r1"
    run_dir.mkdir(parents=True, exist_ok=True)
    state = {
        "run_id": "r1",
        "task": {"task_type": "model", "name": "mlp_demo"},
        "selected_path": "hls4ml_path",
        "status": "partial_success",
        "report": {"status": "success", "timing": {"met": True}},
        "verification": {"status": "unknown", "passed": None, "mode": "vivado_csim"},
        "pipeline_status": {"level": "synthesis_success"},
        "suggestions": [],
        "errors": [],
    }
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")

    candidates = manager.extract_memory_candidates("r1")
    kinds = {item.get("kind") for item in candidates}

    assert "synthesis_success" in kinds
    assert "verified_implementation" not in kinds
    assert "parameter_experience" not in kinds


def test_memory_extracts_verified_implementation_and_parameter_experience(tmp_path):
    manager = _manager(tmp_path)
    run_dir = tmp_path / "runs" / "r1"
    run_dir.mkdir(parents=True, exist_ok=True)
    state = {
        "run_id": "r1",
        "task": {"task_type": "model", "name": "mnist_mlp_demo"},
        "selected_path": "hls4ml_path",
        "status": "success",
        "report": {"status": "success", "timing": {"met": True}},
        "verification": {"status": "csim_passed", "passed": True, "mode": "hls4ml_reference_compare"},
        "pipeline_status": {"level": "deployment_ready_candidate"},
        "suggestions": [],
        "errors": [],
    }
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")

    candidates = manager.extract_memory_candidates("r1")
    kinds = {item.get("kind") for item in candidates}

    assert "verified_implementation" in kinds
    assert "parameter_experience" in kinds


def test_memory_does_not_promote_timing_failed_candidate_as_verified(tmp_path):
    manager = _manager(tmp_path)
    run_dir = tmp_path / "runs" / "r1"
    run_dir.mkdir(parents=True, exist_ok=True)
    state = {
        "run_id": "r1",
        "task": {"task_type": "operator", "name": "dense_llm"},
        "selected_path": "llm_candidate_path",
        "status": "partial_success",
        "report": {"status": "success", "timing": {"met": False}},
        "verification": {"status": "csim_passed", "passed": True, "mode": "golden_testbench"},
        "pipeline_status": {"level": "functional_verified", "timing_met": False},
        "suggestions": [],
        "errors": [],
    }
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")

    candidates = manager.extract_memory_candidates("r1")
    kinds = {item.get("kind") for item in candidates}

    assert "failure" in kinds
    assert "verified_implementation" not in kinds
    assert "parameter_experience" not in kinds


def test_memory_extract_candidates_sanitizes_prior_experience_hint(tmp_path):
    manager = _manager(tmp_path)
    run_dir = tmp_path / "runs" / "r1"
    run_dir.mkdir(parents=True, exist_ok=True)
    state = {
        "run_id": "r1",
        "task": {"task_type": "operator", "name": "dense_demo", "op_type": "Dense"},
        "selected_path": "fallback_template_path",
        "status": "success",
        "report": {"status": "success"},
        "suggestions": [
            "RuleSuggestion: Prior experience hint: failure.old_run VivadoNotFoundError was recoverable.",
            "Increase reuse factor if DSP is high.",
        ],
        "retrieved_memories": [{"text": "old noisy hint"}],
        "errors": [],
        "hls4ml_support": {"unsupported_layers": []},
    }
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")

    candidates = manager.extract_memory_candidates("r1")
    dumped = json.dumps(candidates, ensure_ascii=False).lower()

    assert "prior experience hint" not in dumped
    assert "old noisy hint" not in dumped
    assert "increase reuse factor" in dumped


def test_memory_policy_promotes_failure():
    policy = MemoryPolicy()
    candidate = {"kind": "failure", "summary": "Vivado missing", "value": {"error_type": "VivadoNotFoundError"}}
    assert policy.should_promote(candidate) is True


def test_memory_policy_promotes_optimization():
    policy = MemoryPolicy()
    candidate = {
        "kind": "optimization",
        "summary": "Reuse factor reduced DSP.",
        "value": {
            "verification": {"status": "csim_passed", "passed": True, "mode": "hls4ml_reference_compare"},
            "report": {
                "status": "success",
                "evidence_receipt": {"valid": True, "mock_evidence": False, "evidence_class": "real_csynth"},
            },
        },
    }
    assert policy.should_promote(candidate) is True


def test_memory_policy_requires_verified_optimization():
    policy = MemoryPolicy()
    candidate = {"kind": "optimization", "summary": "Unverified synthesis metrics."}
    assert policy.should_promote(candidate) is False


def test_memory_policy_ignores_raw_log():
    policy = MemoryPolicy()
    candidate = {"kind": "semantic", "summary": "raw log dump", "fact": "raw log should not be promoted"}
    assert policy.should_promote(candidate) is False


def test_memory_policy_rejects_mock_verified_implementation():
    policy = MemoryPolicy()
    candidate = {
        "kind": "verified_implementation",
        "value": {
            "verification": {"passed": True, "mode": "golden_testbench"},
            "report": {
                "status": "success",
                "evidence_receipt": {
                    "valid": True,
                    "mock_evidence": True,
                    "evidence_class": "mock",
                },
            },
        },
    }

    assert policy.should_promote(candidate) is False


def test_memory_policy_promotes_real_verified_implementation():
    policy = MemoryPolicy()
    candidate = {
        "kind": "verified_implementation",
        "value": {
            "verification": {"passed": True, "mode": "golden_testbench"},
            "report": {
                "status": "success",
                "evidence_receipt": {
                    "valid": True,
                    "mock_evidence": False,
                    "evidence_class": "real_csynth",
                },
            },
        },
    }

    assert policy.should_promote(candidate) is True


def test_memory_promote_to_long_term(tmp_path):
    manager = _manager(tmp_path)
    result = manager.promote_to_long_term(
        "r1",
        [
            {
                "kind": "optimization",
                "key": "optimization.r1",
                "summary": "Reuse factor reduced DSP.",
                "value": {
                    "dsp": 12,
                    "verification": {"status": "csim_passed", "passed": True, "mode": "hls4ml_reference_compare"},
                    "report": {
                        "status": "success",
                        "evidence_receipt": {"valid": True, "mock_evidence": False, "evidence_class": "real_csynth"},
                    },
                },
            }
        ],
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


def test_memory_retrieve_uses_task_anchors_to_filter_irrelevant_experiences(tmp_path):
    manager = _manager(tmp_path)
    manager.promote_to_long_term(
        "matmul_run",
        [
            {
                "kind": "optimization",
                "key": "optimization.matmul_run",
                "summary": "MatMul resource run increased reuse_factor to reduce DSP.",
                "value": {"name": "matmul_16x16_resource", "objective": "resource", "suggestions": ["increase reuse"]},
            }
        ],
    )

    results = manager.retrieve_similar_experiences("resnet18_boundary_demo resource reuse factor DSP Vivado HLS", top_k=3)

    assert results == []


def test_memory_promotion_strips_second_order_prior_experience(tmp_path):
    manager = _manager(tmp_path)
    manager.promote_to_long_term(
        "resnet_run",
        [
            {
                "kind": "optimization",
                "key": "optimization.resnet_run",
                "summary": "ResNet boundary run recorded unsupported status.",
                    "value": {
                        "name": "resnet18_boundary_demo",
                        "verification": {"status": "csim_passed", "passed": True, "mode": "hls4ml_reference_compare"},
                        "report": {
                            "status": "success",
                            "evidence_receipt": {"valid": True, "mock_evidence": False, "evidence_class": "real_csynth"},
                        },
                        "suggestions": [
                        "Optimization is not applicable yet.",
                        "RuleSuggestion: Prior experience hint: optimization.matmul_run increased reuse_factor to reduce DSP.",
                    ],
                    "retrieved_memories": [{"text": "MatMul resource hint"}],
                },
            }
        ],
    )

    results = manager.retrieve_similar_experiences("resnet18_boundary_demo resource", top_k=3)

    assert results
    assert "matmul" not in results[0]["text"].lower()
    assert "prior experience hint" not in results[0]["text"].lower()


def test_memory_retrieve_failure_cases(tmp_path):
    manager = _manager(tmp_path)
    manager.repository.save_failure({"run_id": "r1", "error_type": "VivadoNotFoundError", "error_message": "vivado missing"})
    results = manager.retrieve_failure_cases("Vivado missing", top_k=3)
    assert results


def test_memory_failure_cases_not_returned_for_normal_optimization_query(tmp_path):
    manager = _manager(tmp_path)
    manager.repository.save_failure({"run_id": "r1", "error_type": "VivadoNotFoundError", "error_message": "vivado missing"})

    results = manager.retrieve_failure_cases("dense_16x32 Dense latency reuse factor DSP Vivado HLS", top_k=3)

    assert results == []


def test_memory_successful_runs_rank_above_error_partial_runs_for_optimization_query(tmp_path):
    manager = _manager(tmp_path)
    manager.promote_to_long_term(
        "success_dense",
        [
            {
                "kind": "episodic",
                "key": "episode.success_dense",
                "summary": "Dense fallback generated and synthesized successfully.",
                "value": {
                    "run_id": "success_dense",
                    "name": "dense_16x32",
                    "task_type": "operator",
                    "selected_path": "fallback_template_path",
                    "objective": "latency",
                    "status": "success",
                    "errors": [],
                },
            }
        ],
    )
    manager.promote_to_long_term(
        "missing_dense",
        [
            {
                "kind": "episodic",
                "key": "episode.missing_dense",
                "summary": "Dense fallback generated but Vivado HLS was missing.",
                "value": {
                    "run_id": "missing_dense",
                    "name": "dense_vivado_missing_eval",
                    "task_type": "operator",
                    "selected_path": "fallback_template_path",
                    "objective": "latency",
                    "status": "partial_success",
                    "errors": [{"error_type": "VivadoNotFoundError"}],
                },
            }
        ],
    )

    results = manager.retrieve_similar_experiences("dense_16x32 Dense latency reuse factor DSP Vivado HLS", top_k=2)

    assert results
    assert results[0]["source_run_id"] == "success_dense"


def test_memory_save_skill(tmp_path):
    manager = _manager(tmp_path)
    result = manager.save_skill("fallback_template_skill", ["Generate fallback"], {"op_type": "Dense"}, {"generated": True})
    assert result["status"] == "success"
