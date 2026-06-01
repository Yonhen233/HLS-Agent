from dl_op_to_hls.tools.suggest_optimization import suggest_optimization


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
