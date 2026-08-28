from datetime import datetime, timezone
from pathlib import Path

from dl_op_to_hls.benchmarks.operator_evidence import assess_tool_evidence


def test_mock_and_fixture_are_never_counted_as_real(tmp_path):
    context = {"run_dir": tmp_path, "run_started_at": datetime.now(timezone.utc).isoformat()}
    mock = assess_tool_evidence("vivado.run_csynth", {}, context, mock_evidence=True)
    assert mock.evidence_class == "mock"

    fixture = tmp_path / "tests" / "fixtures" / "sample_csynth.rpt"
    fixture.parent.mkdir(parents=True)
    fixture.write_text("Latency Interval Utilization Estimates Timing", encoding="utf-8")
    result = assess_tool_evidence(
        "vivado.run_csynth",
        {"report_path": str(fixture)},
        {"run_dir": tmp_path},
        mock_evidence=False,
    )
    assert result.evidence_class == "fixture"


def test_real_csim_requires_current_run_and_golden_marker(tmp_path):
    run_dir = tmp_path / "run_1"
    run_dir.mkdir()
    log = run_dir / "csim.log"
    log.write_text("INFO CSim done with 0 errors\nGOLDEN_CHECK_PASSED\n", encoding="utf-8")
    assessment = assess_tool_evidence(
        "vivado.run_csim",
        {"log_path": str(log)},
        {"run_dir": run_dir},
        mock_evidence=False,
    )
    assert assessment.valid is True
    assert assessment.evidence_class == "real_csim"
    assert assessment.sha256


def test_stale_or_cross_run_report_is_rejected(tmp_path):
    current = tmp_path / "current"
    old = tmp_path / "old"
    current.mkdir()
    old.mkdir()
    report = old / "top_csynth.rpt"
    report.write_text("Latency Interval Utilization Estimates Timing", encoding="utf-8")
    assessment = assess_tool_evidence(
        "vivado.run_csynth",
        {"report_path": str(report)},
        {"run_dir": current},
        mock_evidence=False,
    )
    assert assessment.valid is False
    assert assessment.evidence_class == "unit"
    assert "artifact is not inside the current run directory" in assessment.reasons
