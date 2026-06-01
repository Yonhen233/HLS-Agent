from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from ..core.errors import AgentRuntimeError, build_error
from .config import LLMConfig
from .schemas import validate_required
from .trace import emit_llm_event


@dataclass
class LLMClient:
    config: LLMConfig = field(default_factory=LLMConfig.from_env)
    context: dict[str, Any] = field(default_factory=dict)
    _window_start_ts: float = field(default=0.0, init=False, repr=False)
    _window_bytes_used: int = field(default=0, init=False, repr=False)
    _last_request_ts: float = field(default=0.0, init=False, repr=False)
    _cooldown_until_ts: float = field(default=0.0, init=False, repr=False)
    _adaptive_min_interval_sec: float = field(default=0.0, init=False, repr=False)

    def set_context(self, context: dict[str, Any]) -> None:
        self.context = context

    def is_enabled(self) -> bool:
        return self.config.configured

    def _sync_window(self, now_ts: float) -> None:
        if self._window_start_ts == 0.0:
            self._window_start_ts = now_ts
            return
        if now_ts - self._window_start_ts >= 60.0:
            self._window_start_ts = now_ts
            self._window_bytes_used = 0

    def _pre_request_throttle(self, request_bytes: int) -> None:
        now_ts = time.time()
        if self._cooldown_until_ts > now_ts:
            time.sleep(self._cooldown_until_ts - now_ts)
            now_ts = time.time()

        self._sync_window(now_ts)

        effective_min_interval = max(self.config.min_request_interval_sec, self._adaptive_min_interval_sec)
        if effective_min_interval > 0 and self._last_request_ts > 0:
            elapsed = now_ts - self._last_request_ts
            if elapsed < effective_min_interval:
                time.sleep(effective_min_interval - elapsed)
                now_ts = time.time()
                self._sync_window(now_ts)

        if self.config.rate_bytes_per_minute > 0:
            projected = self._window_bytes_used + request_bytes
            if projected > self.config.rate_bytes_per_minute:
                wait_s = max(0.0, 60.0 - (now_ts - self._window_start_ts))
                if wait_s > 0:
                    time.sleep(wait_s)
                    now_ts = time.time()
                    self._sync_window(now_ts)

    def _record_usage(self, request_bytes: int, response_bytes: int) -> None:
        now_ts = time.time()
        self._sync_window(now_ts)
        self._window_bytes_used += max(0, request_bytes) + max(0, response_bytes)
        self._last_request_ts = now_ts

    def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: dict,
        temperature: float = 0.0,
    ) -> dict:
        if not self.is_enabled():
            raise AgentRuntimeError(
                build_error(
                    "LLMGenerationError",
                    "LLM is not enabled or API key is missing.",
                    recoverable=True,
                    source="llm.complete_json",
                    suggested_action="Set DL_OP_TO_HLS_LLM_ENABLED=1 and provide DL_OP_TO_HLS_LLM_API_KEY.",
                )
            )

        emit_llm_event(
            self.context,
            "LLMCallStarted",
            {
                "run_id": self.context.get("run_id"),
                "prompt_type": "json",
                "model": self.config.model,
                "schema_name": schema.get("title", "unnamed_schema"),
            },
        )
        try:
            text = self.complete_text(system_prompt, user_prompt, temperature=temperature, force_json=True)
            payload = self._parse_json_payload(text)
            payload = self._normalize_payload(payload, schema)
            validate_required(payload, schema)
            emit_llm_event(
                self.context,
                "LLMCallFinished",
                {
                    "run_id": self.context.get("run_id"),
                    "prompt_type": "json",
                    "model": self.config.model,
                    "status": "success",
                },
            )
            return payload
        except Exception as exc:
            emit_llm_event(
                self.context,
                "LLMCallFailed",
                {
                    "run_id": self.context.get("run_id"),
                    "prompt_type": "json",
                    "model": self.config.model,
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                },
            )
            if isinstance(exc, AgentRuntimeError):
                raise
            raise AgentRuntimeError(
                build_error(
                    "LLMGenerationError",
                    str(exc),
                    recoverable=True,
                    source="llm.complete_json",
                )
            ) from exc

    def complete_text(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        force_json: bool = False,
    ) -> str:
        if not self.is_enabled():
            raise AgentRuntimeError(
                build_error(
                    "LLMGenerationError",
                    "LLM is not enabled or API key is missing.",
                    recoverable=True,
                    source="llm.complete_text",
                )
            )
        if self.config.provider.lower() not in {"openai", "openai-compatible"}:
            raise AgentRuntimeError(
                build_error(
                    "LLMGenerationError",
                    f"Unsupported provider: {self.config.provider}",
                    recoverable=True,
                    source="llm.complete_text",
                )
            )

        body: dict[str, Any] = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
        }
        if force_json:
            body["response_format"] = {"type": "json_object"}
        request_raw = json.dumps(body).encode("utf-8")
        request_bytes = len(request_raw)
        request = urllib.request.Request(
            f"{self.config.base_url.rstrip('/')}/chat/completions",
            data=request_raw,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.api_key}",
            },
            method="POST",
        )
        payload: dict[str, Any] | None = None
        max_retries = 3
        for attempt in range(max_retries + 1):
            self._pre_request_throttle(request_bytes)
            try:
                with urllib.request.urlopen(request, timeout=90) as response:
                    raw = response.read()
                    self._record_usage(request_bytes, len(raw))
                    payload = json.loads(raw.decode("utf-8"))
                    break
            except urllib.error.HTTPError as exc:  # pragma: no cover - network path
                text = exc.read().decode("utf-8", errors="ignore")
                self._record_usage(request_bytes, len(text.encode("utf-8", errors="ignore")))
                should_retry = exc.code in {429, 500, 502, 503, 504} and attempt < max_retries
                if should_retry:
                    backoff = 2**attempt
                    if exc.code == 429:
                        retry_after_header = exc.headers.get("Retry-After") if exc.headers else None
                        retry_after = 0
                        if retry_after_header:
                            try:
                                retry_after = int(float(retry_after_header))
                            except Exception:
                                retry_after = 0
                        backoff = max(backoff, retry_after, self.config.min_retry_429_seconds)
                        self._adaptive_min_interval_sec = max(self._adaptive_min_interval_sec, float(backoff))
                        self._cooldown_until_ts = max(self._cooldown_until_ts, time.time() + backoff)
                    time.sleep(backoff)
                    continue
                raise AgentRuntimeError(
                    build_error(
                        "LLMGenerationError",
                        f"OpenAI API HTTP error: {exc.code} {text[:500]}",
                        recoverable=True,
                        source="llm.complete_text",
                    )
                ) from exc
            except Exception as exc:  # pragma: no cover - network path
                if attempt < max_retries:
                    time.sleep(2**attempt)
                    continue
                raise AgentRuntimeError(
                    build_error(
                        "LLMGenerationError",
                        f"OpenAI API call failed: {exc}",
                        recoverable=True,
                        source="llm.complete_text",
                    )
                ) from exc
        if payload is None:
            raise AgentRuntimeError(
                build_error(
                    "LLMGenerationError",
                    "OpenAI API call failed after retries.",
                    recoverable=True,
                    source="llm.complete_text",
                )
            )

        try:
            return payload["choices"][0]["message"]["content"]
        except Exception as exc:
            raise AgentRuntimeError(
                build_error(
                    "LLMGenerationError",
                    "OpenAI response is missing choices[0].message.content",
                    recoverable=True,
                    source="llm.complete_text",
                    details={"payload": payload},
                )
            ) from exc

    def _parse_json_payload(self, text: str) -> dict[str, Any]:
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
        if fenced:
            parsed = json.loads(fenced.group(1))
            if isinstance(parsed, dict):
                return parsed
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            parsed = json.loads(text[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        raise json.JSONDecodeError("No JSON object found in LLM response.", text, 0)

    def _normalize_payload(self, payload: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
        required = set(schema.get("required", []))
        normalized = dict(payload)
        properties = schema.get("properties", {})

        if "todos" in properties and not isinstance(normalized.get("todos"), list):
            normalized["todos"] = []
        if "new_todos" in properties and not isinstance(normalized.get("new_todos"), list):
            normalized["new_todos"] = []
        if "memory_candidates" in properties and not isinstance(normalized.get("memory_candidates"), list):
            normalized["memory_candidates"] = []

        if "decision" in required and "decision" not in normalized:
            inferred_decision = (
                normalized.get("next_step")
                or normalized.get("action_decision")
                or normalized.get("status_decision")
                or normalized.get("todo_status")
                or normalized.get("run_status")
            )
            if inferred_decision:
                normalized["decision"] = inferred_decision
            elif "todo_status" in required and "run_status" in required:
                normalized["decision"] = "keep_current_flow"
        if "reason_summary" in required and "reason_summary" not in normalized:
            normalized["reason_summary"] = (
                normalized.get("decision_summary")
                or normalized.get("reason")
                or normalized.get("rationale")
                or normalized.get("thought")
                or "LLM did not provide an explicit reason_summary."
            )
        if "new_todos" in required and "new_todos" not in normalized:
            normalized["new_todos"] = []
        if "memory_candidates" in required and "memory_candidates" not in normalized:
            normalized["memory_candidates"] = []
        if "run_status" in required and "run_status" not in normalized:
            normalized["run_status"] = "partial_success"
        if "todo_status" in required and "todo_status" not in normalized:
            normalized["todo_status"] = "completed_with_warning"
        return normalized


class FakeLLMClient(LLMClient):
    def __init__(self, json_responses: list[dict[str, Any]] | None = None, text_responses: list[str] | None = None):
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
                min_request_interval_sec=0.0,
                min_retry_429_seconds=0,
            )
        )
        self._json_responses = list(json_responses or [])
        self._text_responses = list(text_responses or [])

    def is_enabled(self) -> bool:
        return True

    def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: dict,
        temperature: float = 0.0,
    ) -> dict:
        emit_llm_event(
            self.context,
            "LLMCallStarted",
            {"run_id": self.context.get("run_id"), "prompt_type": "json", "model": "fake"},
        )
        if not self._json_responses:
            raise AgentRuntimeError(
                build_error(
                    "LLMGenerationError",
                    "FakeLLMClient has no queued JSON response.",
                    recoverable=False,
                    source="fake_llm.complete_json",
                )
            )
        payload = self._json_responses.pop(0)
        validate_required(payload, schema)
        emit_llm_event(
            self.context,
            "LLMCallFinished",
            {"run_id": self.context.get("run_id"), "prompt_type": "json", "model": "fake", "status": "success"},
        )
        return payload

    def complete_text(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        force_json: bool = False,
    ) -> str:
        emit_llm_event(
            self.context,
            "LLMCallStarted",
            {"run_id": self.context.get("run_id"), "prompt_type": "text", "model": "fake"},
        )
        if self._text_responses:
            text = self._text_responses.pop(0)
        elif self._json_responses and force_json:
            text = json.dumps(self._json_responses.pop(0), ensure_ascii=False)
        else:
            text = "ok"
        emit_llm_event(
            self.context,
            "LLMCallFinished",
            {"run_id": self.context.get("run_id"), "prompt_type": "text", "model": "fake", "status": "success"},
        )
        return text
