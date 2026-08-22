from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from ..core.config import _simple_yaml_load


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
    max_output_tokens: int
    rate_bytes_per_minute: int
    min_request_interval_sec: float
    min_retry_429_seconds: int
    max_total_tokens: int = 120_000
    max_llm_calls: int = 30

    @classmethod
    def from_env(cls) -> "LLMConfig":
        runtime_llm = {}
        runtime_path = Path.cwd() / "runtime.yaml"
        if runtime_path.exists():
            runtime = _simple_yaml_load(runtime_path.read_text(encoding="utf-8"))
            runtime_llm = ((runtime.get("runtime") or {}).get("llm") or {})
        return cls(
            enabled=_truthy(os.environ.get("DL_OP_TO_HLS_LLM_ENABLED")),
            provider=os.environ.get("DL_OP_TO_HLS_LLM_PROVIDER", runtime_llm.get("provider", "openai")),
            base_url=os.environ.get("DL_OP_TO_HLS_LLM_BASE_URL", runtime_llm.get("base_url", "https://api.openai.com/v1")),
            model=os.environ.get("DL_OP_TO_HLS_LLM_MODEL", runtime_llm.get("model", "gpt-4.1-mini")),
            api_key=os.environ.get("DL_OP_TO_HLS_LLM_API_KEY"),
            max_tool_calls=int(os.environ.get("DL_OP_TO_HLS_LLM_MAX_TOOL_CALLS", "30")),
            max_repair_attempts=int(os.environ.get("DL_OP_TO_HLS_LLM_MAX_REPAIR_ATTEMPTS", "2")),
            max_output_tokens=int(os.environ.get("DL_OP_TO_HLS_LLM_MAX_TOKENS", "4096")),
            rate_bytes_per_minute=int(os.environ.get("DL_OP_TO_HLS_LLM_RATE_BYTES_PER_MIN", "10000")),
            min_request_interval_sec=float(os.environ.get("DL_OP_TO_HLS_LLM_MIN_REQUEST_INTERVAL_SEC", "0")),
            min_retry_429_seconds=int(os.environ.get("DL_OP_TO_HLS_LLM_MIN_RETRY_429_SECONDS", "65")),
            max_total_tokens=int(os.environ.get("DL_OP_TO_HLS_LLM_MAX_TOTAL_TOKENS", "120000")),
            max_llm_calls=int(os.environ.get("DL_OP_TO_HLS_MAX_LLM_CALLS", "30")),
        )

    @property
    def configured(self) -> bool:
        return self.enabled and bool(self.api_key)
