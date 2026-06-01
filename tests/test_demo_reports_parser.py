from __future__ import annotations

from pathlib import Path

from dl_op_to_hls.tools.report_parser import parse_csynth_report_file


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "tests" / "fixtures" / "reports"


def _parse(name: str) -> dict:
    result = parse_csynth_report_file(str(REPORTS / name))
    assert result["status"] == "success"
    return result


def test_parse_dense_latency_report():
    result = _parse("dense_latency_csynth.rpt")
    assert result["latency"]["min_cycles"] == 45
    assert result["interval"]["max_ii"] == 1
    assert result["resources"]["dsp"] == 32
    assert result["timing"]["met"] is True


def test_parse_matmul_resource_report():
    result = _parse("matmul_resource_csynth.rpt")
    assert result["latency"]["min_cycles"] == 900
    assert result["interval"]["max_ii"] == 2
    assert result["resources"]["dsp"] == 16
    assert result["resources"]["bram"] == 1
    assert result["timing"]["target_ns"] == 8.0


def test_parse_mnist_mlp_report():
    result = _parse("mnist_mlp_csynth.rpt")
    assert result["latency"]["min_cycles"] == 120
    assert result["resources"]["dsp"] == 48
    assert result["resources"]["ff"] == 6000
    assert result["timing"]["estimated_ns"] == 4.8


def test_parse_mnist_tiny_cnn_report():
    result = _parse("mnist_tiny_cnn_csynth.rpt")
    assert result["latency"]["min_cycles"] == 2400
    assert result["interval"]["min_ii"] == 4
    assert result["resources"]["lut"] == 32000
    assert result["timing"]["target_ns"] == 10.0


def test_parse_qkeras_cnn_resource_report():
    result = _parse("qkeras_cnn_resource_csynth.rpt")
    assert result["latency"]["min_cycles"] == 3100
    assert result["resources"]["dsp"] == 18
    assert result["resources"]["bram"] == 5
    assert result["timing"]["met"] is True
