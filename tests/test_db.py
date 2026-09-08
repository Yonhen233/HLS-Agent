"""Test contracts and regression checks for test_db.py.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from dl_op_to_hls.db.database import Database
from dl_op_to_hls.db.repositories import MetadataRepository


def _repo(tmp_path):
    """Verify the _repo contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    database = Database(tmp_path / "metadata.db", "src/dl_op_to_hls/db/schema.sql")
    return MetadataRepository(database)


def test_db_create_experiment(tmp_path):
    """Verify the test_db_create_experiment contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    repo = _repo(tmp_path)
    result = repo.save_experiment({"run_id": "r1", "task_type": "operator", "name": "demo", "objective": "latency", "selected_path": "fallback", "status": "success"})
    assert result["run_id"] == "r1"


def test_db_save_implementation(tmp_path):
    """Verify the test_db_save_implementation contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    repo = _repo(tmp_path)
    row_id = repo.save_implementation({"run_id": "r1", "operator_id": None, "source": "fallback_template", "status": "generated"})
    assert row_id > 0


def test_db_save_synthesis_run(tmp_path):
    """Verify the test_db_save_synthesis_run contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    repo = _repo(tmp_path)
    row_id = repo.save_synthesis_run({"run_id": "r1", "tool": "vivado_hls", "latency_min": 1})
    assert row_id > 0


def test_db_save_failure(tmp_path):
    """Verify the test_db_save_failure contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    repo = _repo(tmp_path)
    row_id = repo.save_failure({"run_id": "r1", "error_type": "VivadoNotFoundError", "error_message": "missing"})
    assert row_id > 0

