"""Test contracts and regression checks for test_memory_governance.py.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from dl_op_to_hls.db.database import Database
from dl_op_to_hls.db.repositories import MetadataRepository
from dl_op_to_hls.memory.memory_manager import MemoryManager
from dl_op_to_hls.rag.memory import RagMemory


def _manager(tmp_path):
    """Verify the _manager contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    schema = __import__("pathlib").Path(__file__).resolve().parents[1] / "src" / "dl_op_to_hls" / "db" / "schema.sql"
    repository = MetadataRepository(Database(tmp_path / "metadata.db", schema))
    return MemoryManager(repository, RagMemory(repository, tmp_path), tmp_path), repository


def test_cross_session_memory_isolated_by_user_and_supports_forgetting(tmp_path):
    """Verify the test_cross_session_memory_isolated_by_user_and_supports_forgetting contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    manager, repository = _manager(tmp_path)
    alice = {"namespace": "user", "user_id": "alice", "project_id": "p", "session_id": "s1"}
    bob = {"namespace": "user", "user_id": "bob", "project_id": "p", "session_id": "s2"}
    saved = manager.remember_conversation(summary="Prefer latency optimization for MNIST", identity=alice)
    duplicate = manager.remember_conversation(summary="Prefer latency optimization for MNIST", identity=alice)
    assert saved["created"] is True
    assert duplicate == {"status": "success", "id": saved["id"], "created": False}
    assert manager.recall_conversation("MNIST latency", alice)
    assert manager.recall_conversation("MNIST latency", bob) == []

    manager.add_feedback(saved["id"], 1.0, "useful", "alice")
    assert repository.get_memory_item(saved["id"])["feedback_score"] == 1.0
    assert manager.forget(saved["id"])["status"] == "success"
    assert manager.recall_conversation("MNIST latency", alice) == []


def test_expired_memory_cleanup(tmp_path):
    """Verify the test_expired_memory_cleanup contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    manager, repository = _manager(tmp_path)
    expired = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    memory_id = repository.save_memory_item(
        {
            "memory_type": "conversation",
            "scope": "long_term",
            "key": "expired",
            "value": {"summary": "old"},
            "namespace": "user",
            "user_id": "alice",
            "expires_at": expired,
        }
    )
    assert manager.cleanup_expired()["expired"] == 1
    assert repository.get_memory_item(memory_id)["status"] == "expired"
