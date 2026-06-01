from dl_op_to_hls.llm.client import LLMClient
from dl_op_to_hls.llm.config import LLMConfig
from dl_op_to_hls.llm.schemas import REACT_DECISION_SCHEMA
from dl_op_to_hls.main_agent.agent import MainAgent
from dl_op_to_hls.core.errors import AgentRuntimeError


class SequenceLLMClient(LLMClient):
    def __init__(self, responses):
        super().__init__(
            config=LLMConfig(
                enabled=True,
                provider="fake",
                base_url="fake",
                model="fake",
                api_key="fake",
                max_tool_calls=30,
                max_repair_attempts=2,
                rate_bytes_per_minute=10000,
                min_request_interval_sec=0,
                min_retry_429_seconds=0,
            )
        )
        self.responses = list(responses)

    def complete_text(self, system_prompt, user_prompt, temperature=0.2, force_json=False):
        if not self.responses:
            return "{}"
        return self.responses.pop(0)


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


def test_llm_client_repairs_missing_react_decision():
    client = SequenceLLMClient(
        [
            '{"reason_summary":"validate first","action":{"tool_name":"task.validate_schema"}}',
            '{"reason_summary":"validate first","decision":"direct_tool_only_when_no_specialist","action":{"tool_name":"task.validate_schema","arguments":{}}}',
        ]
    )
    result = client.complete_json("system", "user", REACT_DECISION_SCHEMA)
    assert result["decision"] == "direct_tool_only_when_no_specialist"


def test_llm_client_writes_redacted_debug_artifact_on_repair_failure(temp_workspace):
    agent = MainAgent(temp_workspace, console=False)
    context = agent.create_run_context("llm_debug_test")
    client = SequenceLLMClient(
        [
            '{"reason_summary":"bad","secret":"tp-schljryj10kvh7tq3knk2d5djjuq9wmam27d865wfc6983q1"}',
            '{"reason_summary":"still bad"}',
        ]
    )
    client.set_context(context)
    try:
        client.complete_json("system", "user", REACT_DECISION_SCHEMA)
    except AgentRuntimeError as exc:
        artifact = exc.error.details.get("llm_debug_artifact")
        assert artifact
        content = open(artifact, encoding="utf-8").read()
        assert "tp-schljryj" not in content
        assert "tp-<redacted>" in content
    else:
        raise AssertionError("Expected repair failure to raise AgentRuntimeError")
