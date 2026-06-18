from pathlib import Path
from types import SimpleNamespace

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


def test_vivado_create_project_sanitizes_hls4ml_legacy_stdio_includes(tmp_path):
    firmware = tmp_path / "hls_project" / "firmware"
    nnet_utils = firmware / "nnet_utils"
    nnet_utils.mkdir(parents=True)
    (firmware / "myproject.cpp").write_text('#include <iostream>\n#include "myproject.h"\nvoid myproject(float x[1]) {}\n', encoding="utf-8")
    (firmware / "myproject.h").write_text("void myproject(float x[1]);\n", encoding="utf-8")
    (nnet_utils / "nnet_helpers.h").write_text(
        "#include <algorithm>\n#include <fstream>\n#include <iostream>\n#include <map>\n#include <math.h>\n",
        encoding="utf-8",
    )
    (nnet_utils / "nnet_mult.h").write_text("#include <iostream>\n#include <math.h>\n", encoding="utf-8")
    (nnet_utils / "nnet_pooling.h").write_text("#include <iostream>\n", encoding="utf-8")

    adapter = VivadoHLSAdapter(mock_mode=True)
    result = adapter.create_project(
        {"hls_project_dir": str(tmp_path / "hls_project"), "top_function": "myproject", "work_dir": str(tmp_path / "vivado")}
    )

    assert result["status"] == "success"
    copied_top = (tmp_path / "vivado" / "myproject.cpp").read_text(encoding="utf-8")
    copied_helpers = (tmp_path / "vivado" / "nnet_utils" / "nnet_helpers.h").read_text(encoding="utf-8")
    assert "#include <iostream>" not in copied_top
    assert "#ifndef __SYNTHESIS__" in copied_helpers
    assert result["sanitized_files"]


def test_vitis_create_project_skips_legacy_sanitizer(tmp_path):
    firmware = tmp_path / "hls_project" / "firmware"
    firmware.mkdir(parents=True)
    (firmware / "myproject.cpp").write_text('#include <iostream>\n#include "myproject.h"\nvoid myproject(float x[1]) {}\n', encoding="utf-8")
    (firmware / "myproject.h").write_text("void myproject(float x[1]);\n", encoding="utf-8")

    adapter = VivadoHLSAdapter(mock_mode=True, hls_toolchain="vitis_hls")
    result = adapter.create_project(
        {"hls_project_dir": str(tmp_path / "hls_project"), "top_function": "myproject", "work_dir": str(tmp_path / "vitis")}
    )

    assert result["status"] == "success"
    assert result["toolchain"] == "vitis_hls"
    assert result["sanitized_files"] == []
    assert "#include <iostream>" in (tmp_path / "vitis" / "myproject.cpp").read_text(encoding="utf-8")


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
    adapter.vivado_hls_path = None
    monkeypatch.setattr(adapter, "_resolve_vivado_executable", lambda configured_path=None: None)
    result = adapter.run_csynth({"work_dir": str(tmp_path), "tcl_path": str(tmp_path / "run.tcl"), "top_function": "demo"})
    assert result["status"] == "skipped"
    assert result["error"]["error_type"] == "VivadoNotFoundError"


def test_vitis_missing_binary_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    adapter = VivadoHLSAdapter(mock_mode=False, hls_toolchain="vitis_hls", vitis_hls_path=str(tmp_path / "missing.bat"))
    monkeypatch.setattr(adapter, "_resolve_vitis_executable", lambda: None)
    result = adapter.run_csynth({"work_dir": str(tmp_path), "tcl_path": str(tmp_path / "run.tcl"), "top_function": "demo"})
    assert result["status"] == "skipped"
    assert result["error"]["error_type"] == "VivadoNotFoundError"
    assert result["error"]["details"]["command"] == "vitis_hls/vitis-run"


def test_vitis_run_csynth_uses_vitis_run_command(tmp_path, monkeypatch):
    project_dir = tmp_path / "project"
    _write_design(project_dir)
    vitis_run = tmp_path / "vitis-run.bat"
    vitis_run.write_text("@echo off\n", encoding="utf-8")
    adapter = VivadoHLSAdapter(mock_mode=False, hls_toolchain="vitis_hls", vitis_hls_path=str(vitis_run))
    create = adapter.create_project({"hls_project_dir": str(project_dir), "top_function": "demo", "work_dir": str(tmp_path / "vitis")})
    captured = {}

    def fake_run(command, cwd, capture_output, text, timeout, shell):
        del capture_output, text, timeout, shell
        captured["command"] = command
        report_dir = Path(cwd) / "solution1" / "syn" / "report"
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "demo_csynth.rpt").write_text("Latency (cycles): min = 7, max = 8\nDSP48E = 1\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="Vitis HLS done", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    result = adapter.run_csynth({"work_dir": create["work_dir"], "tcl_path": create["tcl_path"], "top_function": "demo"})

    assert result["status"] == "success"
    assert result["toolchain"] == "vitis_hls"
    assert "--mode" in captured["command"]
    assert "hls" in captured["command"]
    assert "--tcl" in captured["command"]
    assert result["report_path"].endswith("demo_csynth.rpt")


def test_vitis_run_csynth_uses_vitis_hls_legacy_command(tmp_path, monkeypatch):
    project_dir = tmp_path / "project"
    _write_design(project_dir)
    vitis_hls = tmp_path / "vitis_hls.bat"
    vitis_hls.write_text("@echo off\n", encoding="utf-8")
    adapter = VivadoHLSAdapter(mock_mode=False, hls_toolchain="vitis_hls", vitis_hls_path=str(vitis_hls))
    create = adapter.create_project({"hls_project_dir": str(project_dir), "top_function": "demo", "work_dir": str(tmp_path / "vitis")})
    captured = {}

    def fake_run(command, cwd, capture_output, text, timeout, shell):
        del capture_output, text, timeout, shell
        captured["command"] = command
        report_dir = Path(cwd) / "solution1" / "syn" / "report"
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "demo_csynth.rpt").write_text("Latency (cycles): min = 7, max = 8\nDSP48E = 1\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="Vitis HLS 2022.2 done", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    result = adapter.run_csynth({"work_dir": create["work_dir"], "tcl_path": create["tcl_path"], "top_function": "demo"})

    assert result["status"] == "success"
    assert result["toolchain"] == "vitis_hls"
    assert "-f" in captured["command"]
    assert "--mode" not in captured["command"]
    assert "--tcl" not in captured["command"]
    assert result["report_path"].endswith("demo_csynth.rpt")


def test_vitis_log_zero_errors_is_not_synthesis_error(tmp_path, monkeypatch):
    project_dir = tmp_path / "project"
    _write_design(project_dir)
    vitis_run = tmp_path / "vitis-run.bat"
    vitis_run.write_text("@echo off\n", encoding="utf-8")
    adapter = VivadoHLSAdapter(mock_mode=False, hls_toolchain="vitis_hls", vitis_hls_path=str(vitis_run))
    create = adapter.create_project({"hls_project_dir": str(project_dir), "top_function": "demo", "work_dir": str(tmp_path / "vitis")})

    def fake_run(command, cwd, capture_output, text, timeout, shell):
        del command, capture_output, text, timeout, shell
        report_dir = Path(cwd) / "solution1" / "syn" / "report"
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "demo_csynth.rpt").write_text("Latency (cycles): min = 7, max = 8\nDSP48E = 1\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="INFO: [SYNCHK 200-10] 0 error(s), 1 warning(s).", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    result = adapter.run_csynth({"work_dir": create["work_dir"], "tcl_path": create["tcl_path"], "top_function": "demo"})

    assert result["status"] == "success"
    assert "error" not in result


def test_vitis_returncode_zero_with_compilation_failed_is_error(tmp_path, monkeypatch):
    project_dir = tmp_path / "project"
    _write_design(project_dir)
    vitis_hls = tmp_path / "vitis_hls.bat"
    vitis_hls.write_text("@echo off\n", encoding="utf-8")
    adapter = VivadoHLSAdapter(mock_mode=False, hls_toolchain="vitis_hls", vitis_hls_path=str(vitis_hls))
    create = adapter.create_project({"hls_project_dir": str(project_dir), "top_function": "demo", "work_dir": str(tmp_path / "vitis")})

    def fake_run(command, cwd, capture_output, text, timeout, shell):
        del command, cwd, capture_output, text, timeout, shell
        return SimpleNamespace(returncode=0, stdout="Compilation of the preprocessed source 'demo' failed", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    result = adapter.run_csynth({"work_dir": create["work_dir"], "tcl_path": create["tcl_path"], "top_function": "demo"})

    assert result["status"] == "error"
    assert result["error"]["error_type"] == "VivadoSynthesisError"
    assert "preprocessed source" in result["error"]["details"]["errors"][0]


def test_vivado_parse_sample_report(sample_csynth_report_path):
    adapter = VivadoHLSAdapter(mock_mode=True)
    result = adapter.parse_report({"report_path": str(sample_csynth_report_path)})
    assert result["resources"]["dsp"] == 32


def test_vivado_parse_log(sample_vivado_log_path):
    adapter = VivadoHLSAdapter(mock_mode=True)
    result = adapter.parse_log({"log_path": str(sample_vivado_log_path)})
    assert result["warnings"]
