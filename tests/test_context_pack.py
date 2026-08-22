from dl_op_to_hls.core.context_pack import ContextBlock, ContextPack


def test_context_pack_preserves_pinned_blocks_and_deduplicates():
    pack = ContextPack(
        token_budget=100,
        query="repair conversion",
        blocks=[
            ContextBlock("constraints", "Never fabricate verification results.", pinned=True, priority=100),
            ContextBlock("evidence", "irrelevant sentence. conversion failed and needs repair.", priority=80),
            ContextBlock("duplicate", "irrelevant sentence. conversion failed and needs repair.", priority=10),
            ContextBlock("noise", "x" * 2000, priority=1),
        ],
    ).compile()
    categories = {item["category"] for item in pack["blocks"]}
    assert "constraints" in categories
    assert "evidence" in categories
    assert "duplicate" not in categories
    assert pack["ledger"]["pinned_tokens"] > 0
    assert pack["ledger"]["estimated_tokens"] <= 100
