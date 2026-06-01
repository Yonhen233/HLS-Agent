from dl_op_to_hls.llm.client import LLMClient
from dl_op_to_hls.llm.config import LLMConfig


def test_llm_config_disabled_by_default(monkeypatch):
    monkeypatch.delenv("DL_OP_TO_HLS_LLM_ENABLED", raising=False)
    monkeypatch.delenv("DL_OP_TO_HLS_LLM_API_KEY", raising=False)
    config = LLMConfig.from_env()
    assert config.enabled is False
    assert config.configured is False


def test_llm_client_enabled(monkeypatch):
    monkeypatch.setenv("DL_OP_TO_HLS_LLM_ENABLED", "1")
    monkeypatch.setenv("DL_OP_TO_HLS_LLM_API_KEY", "test")
    client = LLMClient()
    assert client.is_enabled() is True
