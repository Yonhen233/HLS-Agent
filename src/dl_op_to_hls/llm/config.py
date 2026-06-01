from __future__ import annotations

import os
from dataclasses import dataclass


def _truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class LLMConfig:
    enabled: bool
    provider: str
    base_url: str
    model: str
    api_key: str | None
    max_tool_calls: int
    max_repair_attempts: int
    rate_bytes_per_minute: int
    min_request_interval_sec: float
    min_retry_429_seconds: int

    @classmethod
    def from_env(cls) -> "LLMConfig":
        return cls(
            enabled=_truthy(os.environ.get("DL_OP_TO_HLS_LLM_ENABLED")),
            provider=os.environ.get("DL_OP_TO_HLS_LLM_PROVIDER", "openai"),
            base_url=os.environ.get("DL_OP_TO_HLS_LLM_BASE_URL", "https://api.openai.com/v1"),
            model=os.environ.get("DL_OP_TO_HLS_LLM_MODEL", "gpt-4.1-mini"),
            api_key=os.environ.get("DL_OP_TO_HLS_LLM_API_KEY"),
            max_tool_calls=int(os.environ.get("DL_OP_TO_HLS_LLM_MAX_TOOL_CALLS", "30")),
            max_repair_attempts=int(os.environ.get("DL_OP_TO_HLS_LLM_MAX_REPAIR_ATTEMPTS", "2")),
            rate_bytes_per_minute=int(os.environ.get("DL_OP_TO_HLS_LLM_RATE_BYTES_PER_MIN", "10000")),
            min_request_interval_sec=float(os.environ.get("DL_OP_TO_HLS_LLM_MIN_REQUEST_INTERVAL_SEC", "0")),
            min_retry_429_seconds=int(os.environ.get("DL_OP_TO_HLS_LLM_MIN_RETRY_429_SECONDS", "65")),
        )

    @property
    def configured(self) -> bool:
        return self.enabled and bool(self.api_key)
