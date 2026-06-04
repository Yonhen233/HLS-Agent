from __future__ import annotations

import re
from typing import Any


CONTEXT_ONLY_KEYS = {
    "memory_used",
    "prior_experience",
    "rag_context",
    "retrieved_memories",
    "retrieved_memory_refs",
}

PRIOR_HINT_PREFIX_RE = re.compile(r"^\s*(?:RuleSuggestion:\s*)?Prior experience hint\s*:", re.IGNORECASE)
PRIOR_HINT_INLINE_RE = re.compile(
    r"\s*(?:RuleSuggestion:\s*)?Prior experience hint\s*:.*",
    re.IGNORECASE | re.DOTALL,
)


def sanitize_memory_text(text: str) -> str:
    """Remove second-order retrieved context before it becomes long-term memory."""
    if not text:
        return ""
    if PRIOR_HINT_PREFIX_RE.search(text.strip()):
        return ""
    return PRIOR_HINT_INLINE_RE.sub("", text).strip(" \t\r\n,;")


def sanitize_memory_payload(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if str(key) in CONTEXT_ONLY_KEYS:
                continue
            sanitized = sanitize_memory_payload(item)
            if not _is_empty(sanitized):
                cleaned[key] = sanitized
        return cleaned
    if isinstance(value, list):
        cleaned_list = []
        for item in value:
            sanitized = sanitize_memory_payload(item)
            if not _is_empty(sanitized):
                cleaned_list.append(sanitized)
        return cleaned_list
    if isinstance(value, str):
        return sanitize_memory_text(value)
    return value


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}
