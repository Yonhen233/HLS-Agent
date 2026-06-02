from dl_op_to_hls.tools.suggest_optimization import suggest_optimization


class PlaceholderSuggestionClient:
    context = {}

    def is_enabled(self):
        return True

    def complete_json(self, **kwargs):
        return {"summary": "placeholder", "suggestions": [{"title": "Suggestion", "reason": ""}], "memory_used": []}


class JustificationSuggestionClient:
    context = {}

    def is_enabled(self):
        return True

    def complete_json(self, **kwargs):
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


def test_llm_optimizer_falls_back_to_rules():
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


def test_llm_optimizer_strict_mode_fails_without_llm():
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
