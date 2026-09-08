"""Test contracts and regression checks for test_llm_optimizer_fallback.py.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from dl_op_to_hls.tools.suggest_optimization import suggest_optimization
from dl_op_to_hls.tools.suggest_optimization import build_suggestions


class PlaceholderSuggestionClient:
    """Coordinate PlaceholderSuggestionClient within the test_llm_optimizer_fallback boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    context = {}

    def is_enabled(self):
        """Verify the is_enabled contract.

        The test should fail on a real contract regression rather than hide an unsupported path.

        Returns:
            The structured value promised by the function signature.
        """
        return True

    def complete_json(self, **kwargs):
        """Verify the complete_json contract.

        The test should fail on a real contract regression rather than hide an unsupported path.

        Returns:
            The structured value promised by the function signature.
        """
        return {"summary": "placeholder", "suggestions": [{"title": "Suggestion", "reason": ""}], "memory_used": []}


class JustificationSuggestionClient:
    """Coordinate JustificationSuggestionClient within the test_llm_optimizer_fallback boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    context = {}

    def is_enabled(self):
        """Verify the is_enabled contract.

        The test should fail on a real contract regression rather than hide an unsupported path.

        Returns:
            The structured value promised by the function signature.
        """
        return True

    def complete_json(self, **kwargs):
        """Verify the complete_json contract.

        The test should fail on a real contract regression rather than hide an unsupported path.

        Returns:
            The structured value promised by the function signature.
        """
        return {
            "summary": "resource suggestions",
            "suggestions": [
                {
                    "title": "Suggestion",
                    "justification": "Increase reuse_factor to reduce parallel MAC pressure because DSP is 16 and objective is resource.",
                    "expected_tradeoff": "DSP may decrease while latency increases.",
                    "confidence": 0.7,
                }
            ],
            "memory_used": [],
        }


class ExplodingSuggestionClient:
    """Coordinate ExplodingSuggestionClient within the test_llm_optimizer_fallback boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    context = {}

    def is_enabled(self):
        """Verify the is_enabled contract.

        The test should fail on a real contract regression rather than hide an unsupported path.

        Returns:
            The structured value promised by the function signature.
        """
        return True

    def complete_json(self, **kwargs):
        """Verify the complete_json contract.

        The test should fail on a real contract regression rather than hide an unsupported path.

        Returns:
            The structured value promised by the function signature.
        """
        raise AssertionError("LLM should not be called when optimization is not applicable.")


class CapturingSuggestionClient(JustificationSuggestionClient):
    """Coordinate CapturingSuggestionClient within the test_llm_optimizer_fallback boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    def __init__(self):
        """Verify the __init__ contract.

        The test should fail on a real contract regression rather than hide an unsupported path.

        Returns:
            The structured value promised by the function signature.
        """
        self.user_prompt = ""
        self.bound_context = None

    def set_context(self, context):
        """Verify the set_context contract.

        The test should fail on a real contract regression rather than hide an unsupported path.

        Args:
            context: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        self.context = context
        self.bound_context = context

    def complete_json(self, **kwargs):
        """Verify the complete_json contract.

        The test should fail on a real contract regression rather than hide an unsupported path.

        Returns:
            The structured value promised by the function signature.
        """
        self.user_prompt = kwargs["user_prompt"]
        return super().complete_json(**kwargs)


def test_llm_optimizer_falls_back_to_rules():
    """Verify the test_llm_optimizer_falls_back_to_rules contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    result = suggest_optimization(
        {
            "state": {"objective": "resource"},
            "report": {
                "resources": {"dsp": 64, "lut": 5000, "bram": 2},
                "interval": {"max_ii": 1},
                "timing": {"met": True},
            },
            "rag_context": [{"summary": "reuse_factor can reduce DSP"}],
            "objective": "resource",
        },
        context={},
    )
    assert result["status"] == "success"
    assert result["llm_fallback_used"] is True
    assert result["suggestions"]


def test_rule_suggestions_use_current_reuse_factor():
    """Verify the test_rule_suggestions_use_current_reuse_factor contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    suggestions = build_suggestions(
        {
            "resources": {"dsp": 67, "lut": 20400, "bram": 47},
            "interval": {"max_ii": 2141},
            "timing": {"met": True},
        },
        [],
        "balanced",
        {"task": {"hls4ml": {"reuse_factor": 1024}}},
    )

    dumped = "\n".join(suggestions)
    assert "reuse_factor=2048" in dumped
    assert "from 1 to 2 or 4" not in dumped


def test_rule_suggestions_ignore_raw_episodic_memory_json():
    """Verify the test_rule_suggestions_ignore_raw_episodic_memory_json contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    suggestions = build_suggestions(
        {
            "resources": {"dsp": 16, "lut": 549, "bram": 0},
            "interval": {"max_ii": 269},
            "timing": {"met": True},
        },
        [
            {"summary": 'episode.dense_001 {"run_id": "dense_001", "task_type": "operator", "status": "partial_success"}'},
            {"summary": "Increasing reuse_factor can reduce DSP at the cost of latency."},
        ],
        "latency",
    )

    dumped = "\n".join(suggestions)
    assert "episode.dense_001" not in dumped
    assert "Prior experience hint: Increasing reuse_factor" in dumped


def test_rule_suggestions_ignore_structured_optimization_memory_json():
    """Verify the test_rule_suggestions_ignore_structured_optimization_memory_json contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    suggestions = build_suggestions(
        {
            "resources": {"dsp": 16, "lut": 624, "bram": 0},
            "interval": {"max_ii": 2052},
            "timing": {"met": False},
        },
        [
            {"summary": 'optimization.matmul.todo_006 {"objective": "resource"}'},
            {"summary": "MatMul resource runs should relax timing first when timing is not met."},
        ],
        "resource",
    )

    dumped = "\n".join(suggestions)
    assert "optimization.matmul.todo_006" not in dumped
    assert "Prior experience hint: MatMul resource runs" in dumped


def test_llm_optimizer_strict_mode_fails_without_llm():
    """Verify the test_llm_optimizer_strict_mode_fails_without_llm contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    result = suggest_optimization(
        {
            "state": {"objective": "resource"},
            "report": {
                "resources": {"dsp": 64, "lut": 5000, "bram": 2},
                "interval": {"max_ii": 1},
                "timing": {"met": True},
            },
            "rag_context": [],
            "objective": "resource",
            "fallback_mode": "strict",
        },
        context={},
    )
    assert result["status"] == "error"
    assert result["error"]["error_type"] == "LLMGenerationError"


def test_llm_optimizer_strict_mode_rejects_placeholder_suggestions():
    """Verify the test_llm_optimizer_strict_mode_rejects_placeholder_suggestions contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    result = suggest_optimization(
        {
            "state": {"objective": "resource"},
            "report": {
                "resources": {"dsp": 64, "lut": 5000, "bram": 2},
                "interval": {"max_ii": 1},
                "timing": {"met": True},
            },
            "rag_context": [],
            "objective": "resource",
            "fallback_mode": "strict",
        },
        context={"llm_client": PlaceholderSuggestionClient()},
    )
    assert result["status"] == "error"
    assert result["error"]["error_type"] == "LLMGenerationError"
    assert "placeholder" in result["error"]["message"]


def test_llm_optimizer_accepts_concrete_justification_field():
    """Verify the test_llm_optimizer_accepts_concrete_justification_field contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    result = suggest_optimization(
        {
            "state": {"objective": "resource"},
            "report": {
                "resources": {"dsp": 16, "lut": 624, "bram": 0},
                "interval": {"max_ii": 2052},
                "timing": {"met": False},
            },
            "rag_context": [],
            "objective": "resource",
            "fallback_mode": "strict",
        },
        context={"llm_client": JustificationSuggestionClient()},
    )
    assert result["status"] == "success"
    assert "Increase reuse_factor" in result["suggestions"][0]


def test_llm_optimizer_skips_unsupported_missing_report_without_calling_llm():
    """Verify the test_llm_optimizer_skips_unsupported_missing_report_without_calling_llm contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    result = suggest_optimization(
        {
            "state": {"objective": "resource", "selected_path": "unsupported_path"},
            "report": {"status": "missing"},
            "rag_context": [{"summary": "MatMul DSP reuse factor hint"}],
            "objective": "resource",
            "fallback_mode": "strict",
        },
        context={"llm_client": ExplodingSuggestionClient()},
    )
    assert result["status"] == "skipped"
    assert result["llm_skipped"] is True
    assert "not applicable" in result["suggestions"][0]


def test_llm_optimizer_does_not_send_full_agent_state():
    """Verify the test_llm_optimizer_does_not_send_full_agent_state contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    client = CapturingSuggestionClient()
    huge_internal = "raw-trace-content" * 10000
    result = suggest_optimization(
        {
            "state": {
                "run_id": "r1",
                "objective": "resource",
                "selected_path": "llm_candidate_path",
                "task": {"task_type": "operator", "op_type": "Conv2D", "name": "conv", "optimization": {"reuse_factor": 64}},
                "todos": [{"raw": huge_internal}],
                "tool_results": [{"raw": huge_internal}],
                "full_trace": huge_internal,
            },
            "report": {"resources": {"dsp": 1}, "interval": {"max_ii": 100}, "timing": {"met": True}},
            "rag_context": [{"summary": "verified Conv2D history"}],
            "objective": "resource",
            "fallback_mode": "strict",
        },
        context={"llm_client": client},
    )

    assert result["status"] == "success"
    assert "raw-trace-content" not in client.user_prompt
    assert len(client.user_prompt) < 5000
    assert client.bound_context is not None
