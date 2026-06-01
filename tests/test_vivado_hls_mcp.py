from pathlib import Path

from dl_op_to_hls.adapters.vivado_hls_adapter import VivadoHLSAdapter


def _write_design(work_dir: Path):
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "design.cpp").write_text("void demo(float input[16], float output[16]) { for (int i = 0; i < 16; ++i) output[i] = input[i]; }\n", encoding="utf-8")
    (work_dir / "design.h").write_text("void demo(float input[16], float output[16]);\n", encoding="utf-8")
    (work_dir / "testbench.cpp").write_text('#include "design.h"\nint main(){float in[16]={0}; float out[16]={0}; demo(in,out); return 0;}\n', encoding="utf-8")


def test_vivado_create_project_mock(tmp_path):
    project_dir = tmp_path / "project"
    _write_design(project_dir)
    adapter = VivadoHLSAdapter(mock_mode=True)
    result = adapter.create_project({"hls_project_dir": str(project_dir), "top_function": "demo", "work_dir": str(tmp_path / "vivado")})
    assert result["status"] == "success"
    assert Path(result["tcl_path"]).exists()


def test_vivado_run_csynth_mock(tmp_path):
    project_dir = tmp_path / "project"
    _write_design(project_dir)
    adapter = VivadoHLSAdapter(mock_mode=True)
    create = adapter.create_project({"hls_project_dir": str(project_dir), "top_function": "demo", "work_dir": str(tmp_path / "vivado")})
    result = adapter.run_csynth({"work_dir": create["work_dir"], "tcl_path": create["tcl_path"], "top_function": "demo"})
    assert result["status"] == "success"
    assert Path(result["report_path"]).exists()


def test_vivado_missing_binary_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    adapter = VivadoHLSAdapter(mock_mode=False, vivado_hls_path="")
    result = adapter.run_csynth({"work_dir": str(tmp_path), "tcl_path": str(tmp_path / "run.tcl"), "top_function": "demo"})
    assert result["status"] == "skipped"
    assert result["error"]["error_type"] == "VivadoNotFoundError"


def test_vivado_parse_sample_report(sample_csynth_report_path):
    adapter = VivadoHLSAdapter(mock_mode=True)
    result = adapter.parse_report({"report_path": str(sample_csynth_report_path)})
    assert result["resources"]["dsp"] == 32


def test_vivado_parse_log(sample_vivado_log_path):
    adapter = VivadoHLSAdapter(mock_mode=True)
    result = adapter.parse_log({"log_path": str(sample_vivado_log_path)})
    assert result["warnings"]

