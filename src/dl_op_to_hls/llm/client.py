from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..core.budgets import BudgetExceededError
from ..core.errors import AgentRuntimeError, build_error
from . import prompts
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
    _call_sequence: int = field(default=0, init=False, repr=False)
    _previous_input_tokens: int = field(default=0, init=False, repr=False)

    def set_context(self, context: dict[str, Any]) -> None:
        self.context = context

    def active_model(self) -> str:
        release = (self.context.get("release_manifest") or {}).get("model:main-agent") or {}
        return str(release.get("selected_version") or self.config.model)

    def active_provider(self) -> str:
        release = (self.context.get("release_manifest") or {}).get("model:main-agent") or {}
        return str((release.get("selected_config") or {}).get("provider") or self.config.provider)

    def active_base_url(self) -> str:
        release = (self.context.get("release_manifest") or {}).get("model:main-agent") or {}
        return str((release.get("selected_config") or {}).get("base_url") or self.config.base_url)

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

        policy = self._json_request_policy(schema)
        previous_policy = self.context.get("_llm_request_policy")
        previous_stage = self.context.get("llm_stage")
        self.context["_llm_request_policy"] = policy
        self.context["llm_stage"] = policy["stage"]
        emit_llm_event(
            self.context,
            "LLMCallStarted",
            {
                "run_id": self.context.get("run_id"),
                "prompt_type": "json",
                "model": self.active_model(),
                "schema_name": schema.get("title", "unnamed_schema"),
            },
        )
        try:
            text = self.complete_text(system_prompt, user_prompt, temperature=temperature, force_json=True)
            try:
                payload = self._parse_json_payload(text)
            except json.JSONDecodeError as parse_exc:
                if schema.get("title") == "CandidateGenerationSchema":
                    artifact_path = self._write_llm_debug_artifact(
                        schema=schema,
                        error=str(parse_exc),
                        raw_text=text,
                        parsed_payload=None,
                    )
                    raise AgentRuntimeError(
                        build_error(
                            "LLMGenerationError",
                            "Candidate response was incomplete or malformed; regenerate the complete candidate instead of repairing partial source code.",
                            recoverable=True,
                            source="llm.complete_json",
                            suggested_action="Regenerate the candidate with a compact implementation and complete JSON payload.",
                            details={
                                "failure_kind": "candidate_payload_incomplete",
                                **({"llm_debug_artifact": artifact_path} if artifact_path else {}),
                            },
                        )
                    ) from parse_exc
                payload = self._repair_json_payload(
                    original_text=text,
                    parsed_payload={},
                    schema=schema,
                    validation_error=str(parse_exc),
                    context_prompt=user_prompt,
                )
            try:
                payload = self._normalize_payload(payload, schema)
                validate_required(payload, schema)
            except Exception as validation_exc:
                payload = self._repair_json_payload(
                    original_text=text,
                    parsed_payload=payload,
                    schema=schema,
                    validation_error=str(validation_exc),
                )
            emit_llm_event(
                self.context,
                "LLMCallFinished",
                {
                    "run_id": self.context.get("run_id"),
                    "prompt_type": "json",
                    "model": self.active_model(),
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
                    "model": self.active_model(),
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                },
            )
            if isinstance(exc, AgentRuntimeError):
                raise
            artifact_path = self._write_llm_debug_artifact(
                schema=schema,
                error=str(exc),
                raw_text=locals().get("text", ""),
                parsed_payload=locals().get("payload", None),
            )
            raise AgentRuntimeError(
                build_error(
                    "LLMGenerationError",
                    str(exc),
                    recoverable=True,
                    source="llm.complete_json",
                    details={"llm_debug_artifact": artifact_path} if artifact_path else {},
                )
            ) from exc
        finally:
            if previous_policy is None:
                self.context.pop("_llm_request_policy", None)
            else:
                self.context["_llm_request_policy"] = previous_policy
            if previous_stage is None:
                self.context.pop("llm_stage", None)
            else:
                self.context["llm_stage"] = previous_stage

    def complete_text(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        force_json: bool = False,
        _finalization_attempted: bool = False,
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
        permission_gate = self.context.get("permission_gate")
        if permission_gate is not None:
            network_decision = permission_gate.check_url(self.active_base_url())
            if network_decision["decision"] != "allow":
                raise AgentRuntimeError(
                    build_error(
                        "PermissionDeniedError",
                        network_decision["reason"],
                        recoverable=True,
                        source="llm.complete_text",
                        suggested_action="Allow-list the configured LLM provider domain in permissions.yaml.",
                    )
                )
        if self.active_provider().lower() not in {"openai", "openai-compatible"}:
            raise AgentRuntimeError(
                build_error(
                    "LLMGenerationError",
                    f"Unsupported provider: {self.active_provider()}",
                    recoverable=True,
                    source="llm.complete_text",
                )
            )

        self._call_sequence += 1
        call_id = f"llm_{self._call_sequence:04d}"
        stage = str(
            self.context.get("llm_stage")
            or self.context.get("current_todo_id")
            or self.context.get("specialist_name")
            or "unclassified"
        )
        request_policy = self.context.get("_llm_request_policy") or {}
        effective_max_tokens = min(
            self.config.max_output_tokens,
            int(request_policy.get("max_output_tokens") or self.config.max_output_tokens),
        )
        body: dict[str, Any] = {
            "model": self.active_model(),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": effective_max_tokens,
        }
        thinking_mode = request_policy.get("thinking")
        if thinking_mode in {"enabled", "disabled"} and self.active_model().lower().startswith("deepseek"):
            body["thinking"] = {"type": thinking_mode}
            if thinking_mode == "enabled":
                body["reasoning_effort"] = str(request_policy.get("reasoning_effort") or "low")
        if force_json:
            body["response_format"] = {"type": "json_object"}
        request_raw = json.dumps(body).encode("utf-8")
        request_bytes = len(request_raw)
        estimated_input_tokens = max(1, len(system_prompt + user_prompt) // 4)
        run_budget = self.context.get("run_budget")
        if run_budget is not None:
            try:
                run_budget.reserve_llm_call(estimated_input_tokens)
            except BudgetExceededError as exc:
                emit_llm_event(
                    self.context,
                    "BudgetExceeded",
                    {"run_id": self.context.get("run_id"), "budget_type": "llm", "message": str(exc)},
                )
                raise AgentRuntimeError(
                    build_error(
                        "BudgetExceededError",
                        str(exc),
                        recoverable=True,
                        source="llm.complete_text",
                        suggested_action="Reduce plan/reflection calls or increase the explicit run token budget.",
                    )
                ) from exc
        request = urllib.request.Request(
            self._chat_completions_url(),
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
            choice = payload["choices"][0]
            message = choice["message"]
            content = message.get("content")
            usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
            input_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or estimated_input_tokens)
            output_tokens = int(
                usage.get("completion_tokens")
                or usage.get("output_tokens")
                or max(1, len(str(content or message.get("reasoning_content") or "")) // 4)
            )
            if run_budget is not None:
                try:
                    run_budget.record_llm_usage(input_tokens, output_tokens)
                except BudgetExceededError as exc:
                    emit_llm_event(
                        self.context,
                        "BudgetExceeded",
                        {"run_id": self.context.get("run_id"), "budget_type": "tokens", "message": str(exc)},
                    )
                    raise AgentRuntimeError(
                        build_error(
                            "BudgetExceededError",
                            str(exc),
                            recoverable=True,
                            source="llm.complete_text",
                        )
                    ) from exc
            token_source = "provider" if usage else "estimated"
            token_anomalies: list[str] = []
            if output_tokens >= int(effective_max_tokens * 0.95):
                token_anomalies.append("output_near_limit")
            if input_tokens > 12_000:
                token_anomalies.append("large_input_context")
            if self._previous_input_tokens and input_tokens > max(4_000, self._previous_input_tokens * 2.5):
                token_anomalies.append("input_context_growth_spike")
            estimate_ratio = input_tokens / max(1, estimated_input_tokens)
            if token_source == "provider" and (estimate_ratio > 2.5 or estimate_ratio < 0.4):
                token_anomalies.append("provider_estimate_divergence")
            self._previous_input_tokens = input_tokens
            cumulative = run_budget.to_dict() if run_budget is not None else {}
            emit_llm_event(
                self.context,
                "LLMUsageRecorded",
                {
                    "run_id": self.context.get("run_id"),
                    "call_id": call_id,
                    "stage": stage,
                    "model": self.active_model(),
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "token_source": token_source,
                    "estimated_input_tokens": estimated_input_tokens,
                    "request_bytes": request_bytes,
                    "response_bytes": len(json.dumps(payload, ensure_ascii=False).encode("utf-8")),
                    "max_output_tokens": effective_max_tokens,
                    "thinking": thinking_mode or "provider_default",
                    "reasoning_effort": request_policy.get("reasoning_effort"),
                    "cumulative_total_tokens": cumulative.get("total_tokens"),
                    "token_anomalies": token_anomalies,
                },
            )
            if content:
                return content
            reasoning_content = message.get("reasoning_content") or (message.get("provider_specific_fields") or {}).get("reasoning_content")
            if reasoning_content:
                if not _finalization_attempted:
                    emit_llm_event(
                        self.context,
                        "LLMFinalizationRetryStarted",
                        {
                            "run_id": self.context.get("run_id"),
                            "model": self.active_model(),
                            "finish_reason": choice.get("finish_reason"),
                        },
                    )
                    previous_policy = self.context.get("_llm_request_policy")
                    final_policy = dict(previous_policy or {})
                    final_policy.update({"thinking": "disabled", "reasoning_effort": None})
                    self.context["_llm_request_policy"] = final_policy
                    try:
                        return self.complete_text(
                            system_prompt,
                            user_prompt
                            + "\n\nThe prior attempt spent its response budget on reasoning. Return only the concise final response now; do not include reasoning.",
                            temperature=0.0,
                            force_json=force_json,
                            _finalization_attempted=True,
                        )
                    finally:
                        if previous_policy is None:
                            self.context.pop("_llm_request_policy", None)
                        else:
                            self.context["_llm_request_policy"] = previous_policy
                raise AgentRuntimeError(
                    build_error(
                        "LLMGenerationError",
                        "OpenAI response contained reasoning_content but no final message.content.",
                        recoverable=True,
                        source="llm.complete_text",
                        suggested_action="Increase DL_OP_TO_HLS_LLM_MAX_TOKENS or simplify the prompt so the model can finish final JSON output.",
                        details={
                            "finish_reason": choice.get("finish_reason"),
                            "reasoning_chars": len(str(reasoning_content)),
                            "max_tokens": effective_max_tokens,
                        },
                    )
                )
            return content or ""
        except AgentRuntimeError:
            raise
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

    def _chat_completions_url(self) -> str:
        base_url = self.active_base_url().rstrip("/")
        parsed = urllib.parse.urlparse(base_url)
        if parsed.path in {"", "/"}:
            base_url = f"{base_url}/v1"
        return f"{base_url}/chat/completions"

    @staticmethod
    def _json_request_policy(schema: dict[str, Any]) -> dict[str, Any]:
        """Keep control-plane JSON concise while preserving reasoning for HLS code generation."""
        title = str(schema.get("title") or "unnamed_schema")
        policies = {
            "TodoPlan": {"max_output_tokens": 1800, "thinking": "disabled"},
            "MainAgentReActDecision": {"max_output_tokens": 900, "thinking": "disabled"},
            "SpecialistLocalReActDecision": {"max_output_tokens": 900, "thinking": "disabled"},
            "OptimizationSuggestionSchema": {"max_output_tokens": 1800, "thinking": "disabled"},
            "CandidateGenerationSchema": {
                "max_output_tokens": 8000,
                "thinking": "enabled",
                "reasoning_effort": "low",
            },
        }
        return {"stage": title, **policies.get(title, {"max_output_tokens": 1600, "thinking": "disabled"})}

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

    def _repair_json_payload(
        self,
        *,
        original_text: str,
        parsed_payload: dict[str, Any],
        schema: dict[str, Any],
        validation_error: str,
        context_prompt: str | None = None,
    ) -> dict[str, Any]:
        emit_llm_event(
            self.context,
            "LLMJsonRepairStarted",
            {
                "run_id": self.context.get("run_id"),
                "schema_name": schema.get("title", "unnamed_schema"),
                "validation_error": validation_error,
            },
        )
        repair_payload = {
            "schema": schema,
            "validation_error": validation_error,
            "parsed_payload": parsed_payload,
            "raw_response_preview": self._redact_text(original_text)[:2000],
            "context_prompt_preview": self._redact_text(context_prompt or "")[:2000],
            "repair_rules": [
                "Preserve the original semantic intent.",
                "Only add or rename fields required by the schema.",
                "If decision is missing, infer it from action/tool/specialist and allowed enum values.",
                "Do not introduce tools or specialists not present in the parsed payload.",
            ],
        }
        repaired_text = self.complete_text(
            prompts.resolve_prompt(self.context, "json_repair"),
            json.dumps(repair_payload, ensure_ascii=False, default=str),
            temperature=0.0,
            force_json=True,
        )
        repaired = self._parse_json_payload(repaired_text)
        repaired = self._normalize_payload(repaired, schema)
        validate_required(repaired, schema)
        emit_llm_event(
            self.context,
            "LLMJsonRepairFinished",
            {
                "run_id": self.context.get("run_id"),
                "schema_name": schema.get("title", "unnamed_schema"),
                "status": "success",
            },
        )
        return repaired

    def _redact_text(self, text: str) -> str:
        if not text:
            return ""
        redacted = re.sub(r"(?i)(api[_-]?key|authorization|bearer)\s*[:=]\s*['\"]?[^'\"\s,}]+", r"\1=<redacted>", text)
        redacted = re.sub(r"tp-[A-Za-z0-9_-]+", "tp-<redacted>", redacted)
        return redacted

    def _redact_payload(self, value: Any) -> Any:
        if isinstance(value, str):
            return self._redact_text(value)
        if isinstance(value, list):
            return [self._redact_payload(item) for item in value]
        if isinstance(value, dict):
            redacted: dict[str, Any] = {}
            for key, item in value.items():
                if re.search(r"(?i)(api[_-]?key|authorization|secret|token)", str(key)):
                    redacted[key] = "<redacted>"
                else:
                    redacted[key] = self._redact_payload(item)
            return redacted
        return value

    def _write_llm_debug_artifact(
        self,
        *,
        schema: dict[str, Any],
        error: str,
        raw_text: str,
        parsed_payload: Any,
    ) -> str | None:
        artifact_manager = self.context.get("artifact_manager")
        if artifact_manager is None:
            return None
        payload = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "schema_name": schema.get("title", "unnamed_schema"),
            "error": error,
            "raw_response_preview": self._redact_text(raw_text)[:4000],
            "parsed_payload": self._redact_payload(parsed_payload),
        }
        try:
            path = artifact_manager.write_json(
                f"llm_debug/{payload['schema_name']}_{int(time.time() * 1000)}.json",
                payload,
                "llm_debug",
            )
            return str(path)
        except Exception:
            return None

    def _normalize_payload(self, payload: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
        required = set(schema.get("required", []))
        normalized = dict(payload)
        properties = schema.get("properties", {})

        if schema.get("title") == "CandidateGenerationSchema":
            files = normalized.get("files") if isinstance(normalized.get("files"), list) else []
            if not normalized.get("candidate_name"):
                for item in files:
                    if not isinstance(item, dict):
                        continue
                    relative_path = str(item.get("relative_path") or "")
                    stem = relative_path.replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0]
                    if stem and stem not in {"testbench", "run_hls"}:
                        normalized["candidate_name"] = stem
                        break
            normalized.setdefault("assumptions", [])
            normalized.setdefault("requires_verification", True)

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
                max_output_tokens=4096,
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
