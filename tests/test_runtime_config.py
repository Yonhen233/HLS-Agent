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
