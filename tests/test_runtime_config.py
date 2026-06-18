from dl_op_to_hls.core.config import AppConfig


def test_runtime_yaml_loads_explicit_mode(tmp_path, monkeypatch):
    monkeypatch.delenv("DL_OP_TO_HLS_RUNTIME_MODE", raising=False)
    monkeypatch.delenv("DL_OP_TO_HLS_OPTIMIZATION_FALLBACK_MODE", raising=False)
    monkeypatch.delenv("DL_OP_TO_HLS_SPECIALIST_LLM_DECIDER_ENABLED", raising=False)
    (tmp_path / "runtime.yaml").write_text(
        "\n".join(
            [
                "runtime:",
                "  mode: strict",
                "  llm:",
                "    fallback: error",
                "  optimization:",
                "    fallback: strict",
                "  specialist:",
                "    llm_decider_enabled: true",
            ]
        ),
        encoding="utf-8",
    )

    config = AppConfig.load(tmp_path)

    assert config.runtime_mode == "strict"
    assert config.llm_fallback_policy == "error"
    assert config.optimization_fallback_mode == "strict"
    assert config.specialist_llm_decider_enabled is True


def test_runtime_env_overrides_yaml(tmp_path, monkeypatch):
    (tmp_path / "runtime.yaml").write_text("runtime:\n  mode: demo\n", encoding="utf-8")
    monkeypatch.setenv("DL_OP_TO_HLS_RUNTIME_MODE", "production")
    monkeypatch.setenv("DL_OP_TO_HLS_OPTIMIZATION_FALLBACK_MODE", "strict")

    config = AppConfig.load(tmp_path)

    assert config.runtime_mode == "production"
    assert config.optimization_fallback_mode == "strict"


def test_runtime_vitis_toolchain_defaults_hls4ml_backend(tmp_path, monkeypatch):
    monkeypatch.setenv("DL_OP_TO_HLS_HLS_TOOLCHAIN", "vitis")
    monkeypatch.delenv("DL_OP_TO_HLS_HLS4ML_BACKEND", raising=False)
    monkeypatch.setenv("DL_OP_TO_HLS_VITIS_HLS_PATH", r"D:\vitis25.2.1\2025.2.1\Vitis\bin\vitis-run.bat")

    config = AppConfig.load(tmp_path)

    assert config.hls_toolchain == "vitis_hls"
    assert config.hls4ml_backend == "Vitis"
    assert config.vitis_hls_path.endswith("vitis-run.bat")


def test_runtime_generic_mock_tools_env_controls_both_adapters(tmp_path, monkeypatch):
    monkeypatch.setenv("DL_OP_TO_HLS_MOCK_TOOLS", "0")
    monkeypatch.delenv("DL_OP_TO_HLS_MOCK_HLS4ML", raising=False)
    monkeypatch.delenv("DL_OP_TO_HLS_MOCK_VIVADO", raising=False)

    config = AppConfig.load(tmp_path)

    assert config.mock_hls4ml is False
    assert config.mock_vivado is False


def test_runtime_specific_mock_env_overrides_generic(tmp_path, monkeypatch):
    monkeypatch.setenv("DL_OP_TO_HLS_MOCK_TOOLS", "0")
    monkeypatch.setenv("DL_OP_TO_HLS_MOCK_HLS4ML", "1")
    monkeypatch.delenv("DL_OP_TO_HLS_MOCK_VIVADO", raising=False)

    config = AppConfig.load(tmp_path)

    assert config.mock_hls4ml is True
    assert config.mock_vivado is False
