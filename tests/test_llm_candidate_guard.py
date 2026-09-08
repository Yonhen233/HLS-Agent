"""Test contracts and regression checks for test_llm_candidate_guard.py.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from pathlib import Path

from dl_op_to_hls.llm.guards import LLMGuard


def test_llm_candidate_cannot_write_outside_run_dir(tmp_path: Path):
    """Verify the test_llm_candidate_cannot_write_outside_run_dir contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    run_dir = tmp_path / "runs" / "r1"
    run_dir.mkdir(parents=True)
    payload = {
        "candidate_name": "bad",
        "files": [{"relative_path": "../escape.cpp", "content": "x"}],
        "assumptions": [],
        "requires_verification": True,
    }
    result = LLMGuard().validate_candidate_files(payload, str(run_dir))
    assert result["status"] == "invalid"


def test_llm_candidate_cannot_mark_verified(tmp_path: Path):
    """Verify the test_llm_candidate_cannot_mark_verified contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    run_dir = tmp_path / "runs" / "r2"
    run_dir.mkdir(parents=True)
    payload = {
        "status": "verified",
        "candidate_name": "bad",
        "files": [{"relative_path": "candidate/x.cpp", "content": "x"}],
        "assumptions": [],
        "requires_verification": True,
    }
    result = LLMGuard().validate_candidate_files(payload, str(run_dir))
    assert result["status"] == "invalid"


def test_llm_candidate_requires_file_content(tmp_path: Path):
    """Verify the test_llm_candidate_requires_file_content contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    run_dir = tmp_path / "runs" / "r3"
    run_dir.mkdir(parents=True)
    payload = {
        "candidate_name": "missing_content",
        "files": [{"relative_path": "candidate/missing.cpp"}],
        "assumptions": [],
        "requires_verification": True,
    }

    result = LLMGuard().validate_candidate_files(payload, str(run_dir))

    assert result["status"] == "invalid"
    assert any("content" in err for err in result["errors"])
