from pathlib import Path

from dl_op_to_hls.llm.guards import LLMGuard


def test_llm_candidate_cannot_write_outside_run_dir(tmp_path: Path):
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
