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
                max_output_tokens=4096,
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


def test_llm_client_root_base_url_appends_v1(monkeypatch):
    monkeypatch.setenv("DL_OP_TO_HLS_LLM_ENABLED", "1")
    monkeypatch.setenv("DL_OP_TO_HLS_LLM_API_KEY", "test")
    monkeypatch.setenv("DL_OP_TO_HLS_LLM_BASE_URL", "https://llmapi.paratera.com")
    client = LLMClient()
    assert client._chat_completions_url() == "https://llmapi.paratera.com/v1/chat/completions"


def test_llm_config_reads_max_tokens(monkeypatch):
    monkeypatch.setenv("DL_OP_TO_HLS_LLM_ENABLED", "1")
    monkeypatch.setenv("DL_OP_TO_HLS_LLM_API_KEY", "test")
    monkeypatch.setenv("DL_OP_TO_HLS_LLM_MAX_TOKENS", "8192")
    assert LLMConfig.from_env().max_output_tokens == 8192


def test_llm_client_repairs_missing_react_decision():
    client = SequenceLLMClient(
        [
            '{"reason_summary":"validate first","action":{"tool_name":"task.validate_schema"}}',
            '{"reason_summary":"validate first","decision":"direct_tool_only_when_no_specialist","action":{"tool_name":"task.validate_schema","arguments":{}}}',
        ]
    )
    result = client.complete_json("system", "user", REACT_DECISION_SCHEMA)
    assert result["decision"] == "direct_tool_only_when_no_specialist"


def test_llm_client_repairs_empty_json_response_with_context_prompt():
    client = SequenceLLMClient(
        [
            "",
            '{"reason_summary":"empty response repaired from context","decision":"direct_tool_only_when_no_specialist","action":{"tool_name":"graph_rewrite.rewrite","arguments":{}}}',
        ]
    )
    result = client.complete_json(
        "system",
        '{"todo":{"assigned_tool":"graph_rewrite.rewrite"},"allowed_actions":["direct_tool_only_when_no_specialist"],"direct_tools":["graph_rewrite.rewrite"]}',
        REACT_DECISION_SCHEMA,
    )
    assert result["decision"] == "direct_tool_only_when_no_specialist"
    assert result["action"]["tool_name"] == "graph_rewrite.rewrite"


def test_llm_client_writes_redacted_debug_artifact_on_repair_failure(temp_workspace):
    agent = MainAgent(temp_workspace, console=False)
    context = agent.create_run_context("llm_debug_test")
    client = SequenceLLMClient(
        [
            '{"reason_summary":"bad","secret":"tp-fake-debug-secret-123456"}',
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
        assert "tp-fake-debug-secret" not in content
        assert "tp-<redacted>" in content
    else:
        raise AssertionError("Expected repair failure to raise AgentRuntimeError")


def test_llm_json_request_policy_separates_control_and_candidate_reasoning():
    planner = LLMClient._json_request_policy({"title": "TodoPlan"})
    candidate = LLMClient._json_request_policy({"title": "CandidateGenerationSchema"})

    assert planner == {"stage": "TodoPlan", "max_output_tokens": 1800, "thinking": "disabled"}
    assert candidate == {
        "stage": "CandidateGenerationSchema",
        "max_output_tokens": 8000,
        "thinking": "enabled",
        "reasoning_effort": "low",
    }


def test_candidate_normalization_fills_only_safe_metadata_fields():
    client = SequenceLLMClient(
        [
            '{"files":[{"relative_path":"candidate/conv2d_anchor.cpp","content":"void conv2d_anchor(){}"}]}'
        ]
    )
    result = client.complete_json(
        "system",
        "user",
        {
            "title": "CandidateGenerationSchema",
            "type": "object",
            "required": ["candidate_name", "files", "assumptions", "requires_verification"],
            "properties": {"files": {"type": "array"}},
        },
    )

    assert result["candidate_name"] == "conv2d_anchor"
    assert result["assumptions"] == []
    assert result["requires_verification"] is True
    assert result["files"][0]["content"] == "void conv2d_anchor(){}"


def test_candidate_truncated_json_is_regenerated_not_generic_repaired():
    client = SequenceLLMClient(
        [
            '{"candidate_name":"truncated","files":[{"relative_path":"candidate/truncated.cpp","content":"void',
            '{"candidate_name":"invented_by_generic_repair","files":[]}',
        ]
    )

    try:
        client.complete_json(
            "system",
            "user",
            {
                "title": "CandidateGenerationSchema",
                "type": "object",
                "required": ["candidate_name", "files", "assumptions", "requires_verification"],
                "properties": {"files": {"type": "array"}},
            },
        )
    except AgentRuntimeError as exc:
        assert exc.error.error_type == "LLMGenerationError"
        assert exc.error.recoverable is True
        assert exc.error.details["failure_kind"] == "candidate_payload_incomplete"
        assert len(client.responses) == 1
    else:
        raise AssertionError("Expected truncated candidate JSON to request regeneration")
