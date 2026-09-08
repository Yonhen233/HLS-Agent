"""memory layer implementation for memory_manager.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

import json
import hashlib
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

from ..core.memory_hygiene import sanitize_memory_payload, sanitize_memory_text
from ..main_agent.status import is_functionally_verified
from .episodic_memory import build_episodic_candidate
from .memory_policy import MemoryPolicy
from .semantic_memory import build_semantic_candidates
from .skills import build_skill_candidates


TOKEN_RE = re.compile(r"[A-Za-z0-9_<>.-]+")
GENERIC_QUERY_TOKENS = {
    "agent",
    "clock",
    "cycles",
    "demo",
    "dsp",
    "factor",
    "hls",
    "hls4ml",
    "high",
    "ii",
    "latency",
    "low",
    "model",
    "objective",
    "optimization",
    "operator",
    "path",
    "report",
    "resource",
    "reuse",
    "run",
    "suggestion",
    "timing",
    "vivado",
}
TASK_FAMILY_TOKENS = {
    "add",
    "cnn",
    "dense",
    "matmul",
    "mlp",
    "qkeras",
    "qonnx",
    "relu",
    "residual",
    "resnet18",
}
FAILURE_QUERY_TOKENS = {
    "blocked",
    "error",
    "failed",
    "failure",
    "missing",
    "notfound",
    "notfounderror",
    "recoverable",
    "skipped",
    "unsupported",
    "vivadonotfounderror",
}


def _tokenize(text: str) -> list[str]:
    """Implement the internal _tokenize helper.

    Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

    Args:
        text: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    tokens: list[str] = []
    for token in TOKEN_RE.findall(text or ""):
        lowered = token.lower()
        tokens.append(lowered)
        tokens.extend(part for part in re.split(r"[_<>.\-]+", lowered) if part)
    return tokens


def _anchor_tokens(query: str) -> set[str]:
    """Implement the internal _anchor_tokens helper.

    Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

    Args:
        query: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    return {
        token
        for token in _tokenize(query)
        if len(token) >= 4 and token not in GENERIC_QUERY_TOKENS and not token.isdigit()
    }


def _is_failure_query(query: str) -> bool:
    """Implement the internal _is_failure_query helper.

    Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

    Args:
        query: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    tokens = set(_tokenize(query))
    if tokens.intersection(FAILURE_QUERY_TOKENS):
        return True
    anchors = _anchor_tokens(query)
    return any(token.endswith("error") or token.endswith("notfounderror") for token in anchors)


def _matches_anchor(query_anchors: set[str], text: str) -> bool:
    """Implement the internal _matches_anchor helper.

    Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

    Args:
        query_anchors: Value supplied by the caller and validated by the surrounding schema.
        text: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    if not query_anchors:
        return True
    text_tokens = set(_tokenize(text))
    return bool(query_anchors.intersection(text_tokens))


def _score(query: str, text: str) -> float:
    """Implement the internal _score helper.

    Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

    Args:
        query: Value supplied by the caller and validated by the surrounding schema.
        text: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    query_tokens = Counter(_tokenize(query))
    text_tokens = Counter(_tokenize(text))
    numerator = sum(query_tokens[token] * text_tokens[token] for token in query_tokens)
    if numerator == 0:
        return 0.0
    query_norm = math.sqrt(sum(value * value for value in query_tokens.values()))
    text_norm = math.sqrt(sum(value * value for value in text_tokens.values()))
    return numerator / max(query_norm * text_norm, 1e-9)


def _is_functionally_verified(verification: dict[str, Any] | None) -> bool:
    """Implement the internal _is_functionally_verified helper.

    Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

    Args:
        verification: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    return is_functionally_verified(verification)


class MemoryManager:
    """Coordinate MemoryManager within the memory_manager boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    def __init__(self, repository, rag_memory, workspace_root: str | Path, *, runs_root: str | Path | None = None):
        """Implement the internal __init__ helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            repository: Value supplied by the caller and validated by the surrounding schema.
            rag_memory: Value supplied by the caller and validated by the surrounding schema.
            workspace_root: Value supplied by the caller and validated by the surrounding schema.
            runs_root: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        self.repository = repository
        self.rag_memory = rag_memory
        self.workspace_root = Path(workspace_root).resolve()
        self.runs_root = Path(runs_root).resolve() if runs_root is not None else self.workspace_root / "runs"
        self.policy = MemoryPolicy()

    @staticmethod
    def _identity(identity: dict[str, Any] | None = None, *, default_namespace: str = "global") -> dict[str, Any]:
        """Implement the internal _identity helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            identity: Value supplied by the caller and validated by the surrounding schema.
            default_namespace: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        identity = dict(identity or {})
        return {
            "namespace": str(identity.get("namespace") or default_namespace),
            "user_id": identity.get("user_id"),
            "project_id": identity.get("project_id"),
            "session_id": identity.get("session_id"),
        }

    @staticmethod
    def _content_hash(memory_type: str, key: str, value: Any) -> str:
        """Implement the internal _content_hash helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            memory_type: Value supplied by the caller and validated by the surrounding schema.
            key: Value supplied by the caller and validated by the surrounding schema.
            value: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        encoded = json.dumps(
            {"memory_type": memory_type, "key": key, "value": sanitize_memory_payload(value)},
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _save_governed_memory(self, payload: dict[str, Any], identity: dict[str, Any] | None = None) -> tuple[int, bool]:
        """Implement the internal _save_governed_memory helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            payload: Value supplied by the caller and validated by the surrounding schema.
            identity: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        merged = {**self._identity(identity, default_namespace=str(payload.get("namespace") or "global")), **payload}
        content_hash = self._content_hash(merged["memory_type"], merged["key"], merged.get("value", {}))
        merged["content_hash"] = content_hash
        existing = self.repository.find_active_memory_by_hash(
            content_hash,
            namespace=merged["namespace"],
            user_id=merged.get("user_id"),
            project_id=merged.get("project_id"),
        )
        if existing:
            return int(existing["id"]), False
        return self.repository.save_memory_item(merged), True

    def _run_dir(self, run_id: str) -> Path:
        """Implement the internal _run_dir helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            run_id: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        return self.runs_root / run_id

    def _memory_dir(self, run_id: str) -> Path:
        """Implement the internal _memory_dir helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            run_id: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        directory = self._run_dir(run_id) / "memory"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def _read_json(self, path: Path, default):
        """Implement the internal _read_json helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            path: Value supplied by the caller and validated by the surrounding schema.
            default: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_json(self, path: Path, payload: dict | list) -> str:
        """Implement the internal _write_json helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            path: Value supplied by the caller and validated by the surrounding schema.
            payload: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        return str(path)

    def _sanitize_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        """Implement the internal _sanitize_candidate helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            candidate: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        sanitized = dict(candidate)
        if "summary" in sanitized:
            sanitized["summary"] = sanitize_memory_text(str(sanitized.get("summary") or ""))
        if "fact" in sanitized:
            sanitized["fact"] = sanitize_memory_text(str(sanitized.get("fact") or ""))
        if "value" in sanitized:
            sanitized["value"] = sanitize_memory_payload(sanitized.get("value"))
        return sanitized

    def _memory_item_value(self, item: dict[str, Any]) -> Any:
        """Implement the internal _memory_item_value helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            item: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        try:
            return json.loads(item.get("value_json") or "{}")
        except json.JSONDecodeError:
            return item.get("value_json") or ""

    def _memory_item_text(self, item: dict[str, Any]) -> str:
        """Implement the internal _memory_item_text helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            item: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        value = self._memory_item_value(item)
        sanitized_value = sanitize_memory_payload(value)
        return sanitize_memory_text(f"{item['key']} {json.dumps(sanitized_value, ensure_ascii=False)}")

    def _memory_source_tokens(self, item: dict[str, Any]) -> set[str]:
        """Implement the internal _memory_source_tokens helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            item: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        value = self._memory_item_value(item)
        if isinstance(value, dict):
            source_text = " ".join(
                str(value.get(key, ""))
                for key in ["run_id", "name", "task_type", "selected_path", "objective", "status"]
            )
        else:
            source_text = str(value)
        return set(_tokenize(f"{item.get('key', '')} {item.get('source_run_id', '')} {source_text}"))

    def _adjust_memory_score(self, query: str, item: dict[str, Any], text: str, score: float) -> float:
        """Implement the internal _adjust_memory_score helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            query: Value supplied by the caller and validated by the surrounding schema.
            item: Value supplied by the caller and validated by the surrounding schema.
            text: Value supplied by the caller and validated by the surrounding schema.
            score: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        anchors = _anchor_tokens(query)
        source_tokens = self._memory_source_tokens(item)
        adjusted = score + 0.08 * len(anchors.intersection(source_tokens))

        query_task_tokens = anchors.intersection(TASK_FAMILY_TOKENS)
        source_task_tokens = source_tokens.intersection(TASK_FAMILY_TOKENS)
        if query_task_tokens and source_task_tokens and not query_task_tokens.intersection(source_task_tokens):
            adjusted -= 0.16

        value = self._memory_item_value(item)
        if isinstance(value, dict):
            status = str(value.get("status") or "").lower()
            errors = value.get("errors") or []
            if status == "success":
                adjusted += 0.05
            if status in {"failed", "partial_success"} and errors and not _is_failure_query(query):
                adjusted -= 0.24

        text_tokens = set(_tokenize(text))
        if anchors and not anchors.intersection(text_tokens.union(source_tokens)):
            adjusted -= 0.2
        return adjusted

    def write_short_term(self, run_id: str, key: str, value: dict, identity: dict[str, Any] | None = None) -> dict:
        """Execute write_short_term at the memory_manager boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            run_id: Value supplied by the caller and validated by the surrounding schema.
            key: Value supplied by the caller and validated by the surrounding schema.
            value: Value supplied by the caller and validated by the surrounding schema.
            identity: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        path = self._memory_dir(run_id) / "short_term.json"
        payload = self._read_json(path, {"run_id": run_id, "entries": {}})
        payload["entries"][key] = value
        self._write_json(path, payload)
        run_identity = {**self._identity(identity, default_namespace="session"), "namespace": "session"}
        self._save_governed_memory(
            {
                "memory_type": "short_term",
                "scope": "run",
                "key": key,
                "value": value,
                "source_run_id": run_id,
                "importance": 1,
            },
            run_identity,
        )
        return {"status": "success", "path": str(path), "short_term": payload}

    def compress_run_context(self, run_id: str) -> dict:
        """Execute compress_run_context at the memory_manager boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            run_id: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        memory_dir = self._memory_dir(run_id)
        short_term = self._read_json(memory_dir / "short_term.json", {"entries": {}})
        entries = short_term.get("entries", {})
        summary_items = []
        errors = []
        for key, value in entries.items():
            summary_items.append({"key": key, "summary": value.get("summary") or value.get("status") or str(value)[:200]})
            if value.get("error"):
                errors.append(value["error"])
        compressed = {
            "run_id": run_id,
            "summary_items": summary_items,
            "errors": errors,
            "entry_count": len(entries),
        }
        path = memory_dir / "compressed_context.json"
        self._write_json(path, compressed)
        return {"status": "success", "path": str(path), "compressed_context": compressed}

    def extract_memory_candidates(self, run_id: str) -> list[dict]:
        """Execute extract_memory_candidates at the memory_manager boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            run_id: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        run_dir = self._run_dir(run_id)
        state = self._read_json(run_dir / "state.json", {})
        candidates: list[dict] = []
        if state:
            candidates.append(build_episodic_candidate(state))
            candidates.extend(build_semantic_candidates(state))
            candidates.extend(build_skill_candidates(state))
            report = state.get("report") or {}
            verification = state.get("verification") or {}
            if report and report.get("status") == "success" and _is_functionally_verified(verification):
                timing = report.get("timing") if isinstance(report.get("timing"), dict) else {}
                verified_value = {
                    "report": report,
                    "verification": verification,
                    "task": state.get("task", {}),
                    "selected_path": state.get("selected_path"),
                    "pipeline_status": state.get("pipeline_status", {}),
                }
                if timing.get("met") is False:
                    candidates.append(
                        {
                            "kind": "failure",
                            "key": f"failure.{run_id}.timing_not_met",
                            "summary": "Candidate passed functional verification and synthesis but failed timing closure.",
                            "value": {
                                **verified_value,
                                "error_type": "TimingNotMetError",
                                "error_message": "Functional verification passed, but Vivado timing was not met.",
                            },
                            "confidence": 0.7,
                            "domain": "failure",
                        }
                    )
                    candidates.append(
                        {
                            "kind": "optimization",
                            "key": f"optimization.{run_id}.timing_not_met",
                            "summary": "Timing failed after functional verification; use as optimization guidance, not as a verified implementation.",
                            "value": verified_value,
                            "confidence": 0.6,
                            "domain": "optimization",
                        }
                    )
                else:
                    candidates.append(
                        {
                            "kind": "verified_implementation",
                            "key": f"verified_implementation.{run_id}.metrics",
                            "summary": "Functionally verified implementation with synthesis metrics.",
                            "value": verified_value,
                            "confidence": 1.0,
                            "domain": "parameter",
                        }
                    )
                    candidates.append(
                        {
                            "kind": "parameter_experience",
                            "key": f"parameter_experience.{run_id}",
                            "summary": "Verified parameter experience captured for ParameterAdvisor.",
                            "value": verified_value,
                            "confidence": 1.0,
                            "domain": "parameter",
                        }
                    )
                    candidates.append(
                        {
                            "kind": "optimization",
                            "key": f"optimization.{run_id}.metrics",
                            "summary": "Functionally verified synthesis metrics captured for later comparison.",
                            "value": verified_value,
                            "confidence": 0.95,
                            "domain": "optimization",
                        }
                    )
            elif report and report.get("status") == "success":
                candidates.append(
                    {
                        "kind": "synthesis_success",
                        "key": f"synthesis_success.{run_id}.metrics",
                        "summary": "Synthesis completed, but no functional golden/reference verification was proven.",
                        "value": {
                            "report": report,
                            "verification": verification,
                            "task": state.get("task", {}),
                            "selected_path": state.get("selected_path"),
                            "pipeline_status": state.get("pipeline_status", {}),
                        },
                        "confidence": 0.4,
                        "domain": "parameter",
                    }
                )
        candidates = [self._sanitize_candidate(candidate) for candidate in candidates]
        path = self._memory_dir(run_id) / "memory_candidates.json"
        self._write_json(path, {"run_id": run_id, "candidates": candidates})
        return candidates

    def promote_to_long_term(
        self,
        run_id: str,
        candidates: list[dict],
        identity: dict[str, Any] | None = None,
    ) -> dict:
        """Execute promote_to_long_term at the memory_manager boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            run_id: Value supplied by the caller and validated by the surrounding schema.
            candidates: Value supplied by the caller and validated by the surrounding schema.
            identity: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        promoted: list[dict[str, Any]] = []
        for raw_candidate in candidates:
            candidate = self._sanitize_candidate(raw_candidate)
            memory_type = self.policy.classify(candidate)
            if not self.policy.should_promote(candidate):
                continue
            memory_id, created = self._save_governed_memory(
                {
                    "memory_type": memory_type,
                    "scope": "long_term",
                    "key": candidate["key"],
                    "value": candidate.get("value", {}),
                    "source_run_id": run_id,
                    "importance": self.policy.score_importance(candidate),
                    "confidence": candidate.get("confidence", 1.0),
                },
                self._identity(identity, default_namespace="project"),
            )
            promoted_item = {
                "id": memory_id,
                "memory_type": memory_type,
                "key": candidate["key"],
                "summary": candidate.get("summary") or candidate.get("name"),
                "deduplicated": not created,
            }
            if candidate.get("fact"):
                fact_id = self.repository.save_memory_fact(
                    {
                        "fact": candidate["fact"],
                        "source_run_id": run_id,
                        "source_artifact": candidate.get("source_artifact"),
                        "confidence": candidate.get("confidence", 1.0),
                        "tags": candidate.get("tags", []),
                    }
                )
                promoted_item["fact_id"] = fact_id
            if memory_type == "skill":
                skill_id = self.repository.save_procedural_memory(
                    {
                        "name": candidate["name"],
                        "description": candidate["description"],
                        "steps": candidate.get("steps", []),
                        "trigger_conditions": candidate.get("trigger_conditions", {}),
                        "success_criteria": candidate.get("success_criteria", {}),
                        "source_run_id": run_id,
                    }
                )
                promoted_item["skill_id"] = skill_id
            if self.policy.should_index_to_rag({"memory_type": memory_type}):
                text = sanitize_memory_text(
                    candidate.get("fact") or candidate.get("summary") or json.dumps(candidate.get("value", {}), ensure_ascii=False)
                )
                self.rag_memory.index_text(
                    f"memory:{memory_id}",
                    text,
                    {
                        "memory_type": memory_type,
                        "run_id": run_id,
                        "key": candidate["key"],
                        "domain": candidate.get("domain") or self._domain_for_memory_type(memory_type),
                        **self._identity(identity, default_namespace="project"),
                    },
                )
            promoted.append(promoted_item)
        path = self._memory_dir(run_id) / "promoted_memories.json"
        self._write_json(path, {"run_id": run_id, "promoted_memories": promoted})
        return {"status": "success", "promoted_memories": promoted, "path": str(path)}

    def _domain_for_memory_type(self, memory_type: str) -> str:
        """Implement the internal _domain_for_memory_type helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            memory_type: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        if memory_type in {"parameter_experience", "verified_implementation", "synthesis_success"}:
            return "parameter"
        if memory_type == "failure":
            return "failure"
        if memory_type in {"optimization", "semantic", "skill"}:
            return "optimization"
        if memory_type == "episodic":
            return "episodic"
        return "general"

    def retrieve_similar_experiences(
        self,
        query: str,
        top_k: int = 5,
        identity: dict[str, Any] | None = None,
    ) -> list[dict]:
        """Execute retrieve_similar_experiences at the memory_manager boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            query: Value supplied by the caller and validated by the surrounding schema.
            top_k: Value supplied by the caller and validated by the surrounding schema.
            identity: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        scope = self._identity(identity)
        items = self.repository.list_memory_items(
            ["episodic", "implementation", "optimization", "verified_implementation", "parameter_experience", "conversation"],
            namespace=scope["namespace"] if identity else None,
            user_id=scope.get("user_id"),
            project_id=scope.get("project_id"),
        )
        scored = []
        anchors = _anchor_tokens(query)
        for item in items:
            text = self._memory_item_text(item)
            if not _matches_anchor(anchors, text):
                continue
            score = self._adjust_memory_score(query, item, text, _score(query, text))
            score += 0.12 * float(item.get("feedback_score") or 0.0)
            if score > 0:
                scored.append({"id": item["id"], "memory_type": item["memory_type"], "score": round(score, 4), "text": text[:400], "source_run_id": item.get("source_run_id")})
        scored.sort(key=lambda item: item["score"], reverse=True)
        selected = scored[:top_k]
        self.repository.touch_memory_items([int(item["id"]) for item in selected])
        return selected

    def retrieve_failure_cases(self, query: str, top_k: int = 5, identity: dict[str, Any] | None = None) -> list[dict]:
        """Execute retrieve_failure_cases at the memory_manager boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            query: Value supplied by the caller and validated by the surrounding schema.
            top_k: Value supplied by the caller and validated by the surrounding schema.
            identity: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        if not _is_failure_query(query):
            return []
        scored = []
        anchors = _anchor_tokens(query)
        for item in self.repository.list_failures():
            text = f"{item.get('error_type', '')} {item.get('error_message', '')} {item.get('log_summary', '')}"
            if not _matches_anchor(anchors, text):
                continue
            score = _score(query, text)
            if score > 0:
                scored.append({"id": item["id"], "score": round(score, 4), "text": text[:400], "source_run_id": item.get("run_id")})
        scope = self._identity(identity)
        for item in self.repository.list_memory_items(
            ["failure"],
            namespace=scope["namespace"] if identity else None,
            user_id=scope.get("user_id"),
            project_id=scope.get("project_id"),
        ):
            text = self._memory_item_text(item)
            if not _matches_anchor(anchors, text):
                continue
            score = self._adjust_memory_score(query, item, text, _score(query, text))
            if score > 0:
                scored.append({"id": item["id"], "score": round(score, 4), "text": text[:400], "source_run_id": item.get("source_run_id")})
        scored.sort(key=lambda item: item["score"], reverse=True)
        selected = scored[:top_k]
        self.repository.touch_memory_items([int(item["id"]) for item in selected if item.get("id")])
        return selected

    def retrieve_optimization_rules(self, query: str, top_k: int = 5, identity: dict[str, Any] | None = None) -> list[dict]:
        """Execute retrieve_optimization_rules at the memory_manager boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            query: Value supplied by the caller and validated by the surrounding schema.
            top_k: Value supplied by the caller and validated by the surrounding schema.
            identity: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        scored = []
        anchors = _anchor_tokens(query)
        for item in self.repository.list_memory_facts():
            text = item["fact"]
            if not _matches_anchor(anchors, text):
                continue
            score = _score(query, text)
            if score > 0:
                prefix = str(text).split(".", 1)[0]
                memory_type = prefix if prefix in {"optimization", "parameter_experience", "verified_implementation", "semantic"} else "semantic"
                scored.append({
                    "id": item["id"],
                    "memory_type": memory_type,
                    "score": round(score, 4),
                    "text": text[:400],
                    "source_run_id": item.get("source_run_id"),
                })
        scope = self._identity(identity)
        for item in self.repository.list_memory_items(
            ["optimization", "parameter_experience", "verified_implementation", "semantic"],
            namespace=scope["namespace"] if identity else None,
            user_id=scope.get("user_id"),
            project_id=scope.get("project_id"),
        ):
            text = self._memory_item_text(item)
            if not _matches_anchor(anchors, text):
                continue
            score = _score(query, text)
            if score > 0:
                scored.append({
                    "id": item["id"],
                    "memory_type": item.get("memory_type"),
                    "score": round(score, 4),
                    "text": text[:400],
                    "source_run_id": item.get("source_run_id"),
                })
        for item in self.repository.list_skills():
            text = f"{item['name']} {item['description']} {item['steps_json']}"
            if not _matches_anchor(anchors, text):
                continue
            score = _score(query, text)
            if score > 0:
                scored.append({"id": item["id"], "score": round(score, 4), "text": text[:400], "source_run_id": item.get("source_run_id")})
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:top_k]

    def remember_conversation(
        self,
        *,
        summary: str,
        identity: dict[str, Any],
        key: str = "conversation.summary",
        preferences: dict[str, Any] | None = None,
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        """Execute remember_conversation at the memory_manager boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            summary: Value supplied by the caller and validated by the surrounding schema.
            identity: Value supplied by the caller and validated by the surrounding schema.
            key: Value supplied by the caller and validated by the surrounding schema.
            preferences: Value supplied by the caller and validated by the surrounding schema.
            expires_at: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        scope = self._identity(identity, default_namespace="user")
        memory_id, created = self._save_governed_memory(
            {
                "memory_type": "conversation",
                "scope": "long_term",
                "key": key,
                "value": {"summary": sanitize_memory_text(summary), "preferences": sanitize_memory_payload(preferences or {})},
                "importance": 3,
                "confidence": 1.0,
                "expires_at": expires_at,
            },
            scope,
        )
        return {"status": "success", "id": memory_id, "created": created}

    def recall_conversation(self, query: str, identity: dict[str, Any], top_k: int = 5) -> list[dict[str, Any]]:
        """Execute recall_conversation at the memory_manager boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            query: Value supplied by the caller and validated by the surrounding schema.
            identity: Value supplied by the caller and validated by the surrounding schema.
            top_k: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        return self.retrieve_similar_experiences(query, top_k=top_k, identity=identity)

    def add_feedback(self, memory_id: int, score: float, reason: str = "", user_id: str | None = None) -> dict[str, Any]:
        """Execute add_feedback at the memory_manager boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            memory_id: Value supplied by the caller and validated by the surrounding schema.
            score: Value supplied by the caller and validated by the surrounding schema.
            reason: Value supplied by the caller and validated by the surrounding schema.
            user_id: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        return self.repository.add_memory_feedback(memory_id, score, reason, user_id)

    def submit_feedback(
        self,
        memory_id: int,
        score: float,
        reason: str = "",
        user_id: str | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute submit_feedback at the memory_manager boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            memory_id: Value supplied by the caller and validated by the surrounding schema.
            score: Value supplied by the caller and validated by the surrounding schema.
            reason: Value supplied by the caller and validated by the surrounding schema.
            user_id: Value supplied by the caller and validated by the surrounding schema.
            evidence: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        from .feedback_governance import FeedbackGovernor

        return FeedbackGovernor(self.repository).submit(memory_id, score, reason, user_id, evidence)

    def forget(self, memory_id: int, reason: str = "user_request") -> dict[str, Any]:
        """Execute forget at the memory_manager boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            memory_id: Value supplied by the caller and validated by the surrounding schema.
            reason: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        return {"status": "success" if self.repository.forget_memory(memory_id, reason=reason) else "not_found", "id": memory_id}

    def cleanup_expired(self) -> dict[str, Any]:
        """Execute cleanup_expired at the memory_manager boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Returns:
            The structured value promised by the function signature.
        """
        return {"status": "success", "expired": self.repository.cleanup_expired_memories()}

    def save_skill(self, name: str, steps: list[str], trigger_conditions: dict, success_criteria: dict) -> dict:
        """Execute save_skill at the memory_manager boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            name: Value supplied by the caller and validated by the surrounding schema.
            steps: Value supplied by the caller and validated by the surrounding schema.
            trigger_conditions: Value supplied by the caller and validated by the surrounding schema.
            success_criteria: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        skill_id = self.repository.save_procedural_memory(
            {
                "name": name,
                "description": f"Skill {name}",
                "steps": steps,
                "trigger_conditions": trigger_conditions,
                "success_criteria": success_criteria,
            }
        )
        self.rag_memory.index_text(
            f"skill:{skill_id}",
            " ".join([name] + list(steps)),
            {"memory_type": "skill", "skill_id": skill_id},
        )
        return {"status": "success", "id": skill_id}
