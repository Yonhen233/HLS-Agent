from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .token_budget import TokenBudgetManager
from .trace import stable_hash


@dataclass
class ContextBlock:
    category: str
    content: Any
    priority: int = 50
    pinned: bool = False
    source: str = "runtime"
    block_id: str = ""

    def __post_init__(self) -> None:
        if not self.block_id:
            self.block_id = stable_hash({"category": self.category, "content": self.content})[:16]


@dataclass
class ContextPack:
    blocks: list[ContextBlock] = field(default_factory=list)
    token_budget: int = 4000
    query: str = ""

    def compile(self, manager: TokenBudgetManager | None = None) -> dict[str, Any]:
        manager = manager or TokenBudgetManager()
        selected: list[dict[str, Any]] = []
        dropped: list[dict[str, Any]] = []
        seen: set[str] = set()
        used = 0
        ordered = sorted(self.blocks, key=lambda item: (not item.pinned, -item.priority))
        for block in ordered:
            fingerprint = stable_hash(block.content)
            if fingerprint in seen:
                dropped.append({"block_id": block.block_id, "reason": "duplicate"})
                continue
            content = block.content
            cost = manager.estimate_tokens(content)
            if used + cost > self.token_budget and not block.pinned:
                remaining = max(0, self.token_budget - used)
                content = self._extract(content, remaining, manager)
                cost = manager.estimate_tokens(content) if content not in (None, "", [], {}) else 0
            if cost == 0 or (used + cost > self.token_budget and not block.pinned):
                dropped.append({"block_id": block.block_id, "reason": "budget"})
                continue
            selected.append({
                "block_id": block.block_id,
                "category": block.category,
                "source": block.source,
                "priority": block.priority,
                "pinned": block.pinned,
                "content": content,
                "estimated_tokens": cost,
            })
            seen.add(fingerprint)
            used += cost
        return {
            "blocks": selected,
            "ledger": {
                "token_budget": self.token_budget,
                "estimated_tokens": used,
                "pinned_tokens": sum(item["estimated_tokens"] for item in selected if item["pinned"]),
                "selected_blocks": len(selected),
                "dropped_blocks": dropped,
                "compression_strategy": "priority_dedup_query_extract",
            },
        }

    def _extract(self, value: Any, max_tokens: int, manager: TokenBudgetManager) -> Any:
        if max_tokens <= 0:
            return None
        if isinstance(value, str):
            sentences = [item.strip() for item in re.split(r"(?<=[.!?。！？])\s+|\n+", value) if item.strip()]
            query_terms = set(re.findall(r"[A-Za-z_]\w+|[\u4e00-\u9fff]+", self.query.lower()))
            ranked = sorted(
                enumerate(sentences),
                key=lambda pair: (
                    -sum(term in pair[1].lower() for term in query_terms),
                    pair[0],
                ),
            )
            chosen: list[tuple[int, str]] = []
            used = 0
            for index, sentence in ranked:
                cost = manager.estimate_tokens(sentence)
                if chosen and used + cost > max_tokens:
                    continue
                chosen.append((index, sentence))
                used += cost
                if used >= max_tokens:
                    break
            return "\n".join(item for _, item in sorted(chosen))
        if isinstance(value, list):
            selected = []
            used = 0
            for item in value:
                compact = self._extract(item, max_tokens - used, manager)
                if compact in (None, "", [], {}):
                    continue
                cost = manager.estimate_tokens(compact)
                if selected and used + cost > max_tokens:
                    break
                selected.append(compact)
                used += cost
            return selected
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            used = 0
            for key, item in value.items():
                compact = self._extract(item, max_tokens - used, manager)
                if compact in (None, "", [], {}):
                    continue
                result[key] = compact
                used += manager.estimate_tokens({key: compact})
                if used >= max_tokens:
                    break
            return result
        return value if manager.estimate_tokens(value) <= max_tokens else None
