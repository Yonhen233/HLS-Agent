from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

from ..core.memory_hygiene import sanitize_memory_payload, sanitize_memory_text
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
    tokens: list[str] = []
    for token in TOKEN_RE.findall(text or ""):
        lowered = token.lower()
        tokens.append(lowered)
        tokens.extend(part for part in re.split(r"[_<>.\-]+", lowered) if part)
    return tokens


def _anchor_tokens(query: str) -> set[str]:
    return {
        token
        for token in _tokenize(query)
        if len(token) >= 4 and token not in GENERIC_QUERY_TOKENS and not token.isdigit()
    }


def _is_failure_query(query: str) -> bool:
    tokens = set(_tokenize(query))
    if tokens.intersection(FAILURE_QUERY_TOKENS):
        return True
    anchors = _anchor_tokens(query)
    return any(token.endswith("error") or token.endswith("notfounderror") for token in anchors)


def _matches_anchor(query_anchors: set[str], text: str) -> bool:
    if not query_anchors:
        return True
    text_tokens = set(_tokenize(text))
    return bool(query_anchors.intersection(text_tokens))


def _score(query: str, text: str) -> float:
    query_tokens = Counter(_tokenize(query))
    text_tokens = Counter(_tokenize(text))
    numerator = sum(query_tokens[token] * text_tokens[token] for token in query_tokens)
    if numerator == 0:
        return 0.0
    query_norm = math.sqrt(sum(value * value for value in query_tokens.values()))
    text_norm = math.sqrt(sum(value * value for value in text_tokens.values()))
    return numerator / max(query_norm * text_norm, 1e-9)


class MemoryManager:
    def __init__(self, repository, rag_memory, workspace_root: str | Path):
        self.repository = repository
        self.rag_memory = rag_memory
        self.workspace_root = Path(workspace_root)
        self.policy = MemoryPolicy()

    def _run_dir(self, run_id: str) -> Path:
        return self.workspace_root / "runs" / run_id

    def _memory_dir(self, run_id: str) -> Path:
        directory = self._run_dir(run_id) / "memory"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def _read_json(self, path: Path, default):
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_json(self, path: Path, payload: dict | list) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        return str(path)

    def _sanitize_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        sanitized = dict(candidate)
        if "summary" in sanitized:
            sanitized["summary"] = sanitize_memory_text(str(sanitized.get("summary") or ""))
        if "fact" in sanitized:
            sanitized["fact"] = sanitize_memory_text(str(sanitized.get("fact") or ""))
        if "value" in sanitized:
            sanitized["value"] = sanitize_memory_payload(sanitized.get("value"))
        return sanitized

    def _memory_item_value(self, item: dict[str, Any]) -> Any:
        try:
            return json.loads(item.get("value_json") or "{}")
        except json.JSONDecodeError:
            return item.get("value_json") or ""

    def _memory_item_text(self, item: dict[str, Any]) -> str:
        value = self._memory_item_value(item)
        sanitized_value = sanitize_memory_payload(value)
        return sanitize_memory_text(f"{item['key']} {json.dumps(sanitized_value, ensure_ascii=False)}")

    def _memory_source_tokens(self, item: dict[str, Any]) -> set[str]:
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

    def write_short_term(self, run_id: str, key: str, value: dict) -> dict:
        path = self._memory_dir(run_id) / "short_term.json"
        payload = self._read_json(path, {"run_id": run_id, "entries": {}})
        payload["entries"][key] = value
        self._write_json(path, payload)
        self.repository.save_memory_item(
            {
                "memory_type": "short_term",
                "scope": "run",
                "key": key,
                "value": value,
                "source_run_id": run_id,
                "importance": 1,
            }
        )
        return {"status": "success", "path": str(path), "short_term": payload}

    def compress_run_context(self, run_id: str) -> dict:
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
        run_dir = self._run_dir(run_id)
        state = self._read_json(run_dir / "state.json", {})
        candidates: list[dict] = []
        if state:
            candidates.append(build_episodic_candidate(state))
            candidates.extend(build_semantic_candidates(state))
            candidates.extend(build_skill_candidates(state))
            report = state.get("report") or {}
            if report and report.get("status") == "success":
                candidates.append(
                    {
                        "kind": "optimization",
                        "key": f"optimization.{run_id}.metrics",
                        "summary": "Synthesis metrics captured for later comparison.",
                        "value": report,
                    }
                )
        candidates = [self._sanitize_candidate(candidate) for candidate in candidates]
        path = self._memory_dir(run_id) / "memory_candidates.json"
        self._write_json(path, {"run_id": run_id, "candidates": candidates})
        return candidates

    def promote_to_long_term(self, run_id: str, candidates: list[dict]) -> dict:
        promoted: list[dict[str, Any]] = []
        for raw_candidate in candidates:
            candidate = self._sanitize_candidate(raw_candidate)
            memory_type = self.policy.classify(candidate)
            if not self.policy.should_promote(candidate):
                continue
            memory_id = self.repository.save_memory_item(
                {
                    "memory_type": memory_type,
                    "scope": "long_term",
                    "key": candidate["key"],
                    "value": candidate.get("value", {}),
                    "source_run_id": run_id,
                    "importance": self.policy.score_importance(candidate),
                    "confidence": candidate.get("confidence", 1.0),
                }
            )
            promoted_item = {
                "id": memory_id,
                "memory_type": memory_type,
                "key": candidate["key"],
                "summary": candidate.get("summary") or candidate.get("name"),
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
                    {"memory_type": memory_type, "run_id": run_id, "key": candidate["key"]},
                )
            promoted.append(promoted_item)
        path = self._memory_dir(run_id) / "promoted_memories.json"
        self._write_json(path, {"run_id": run_id, "promoted_memories": promoted})
        return {"status": "success", "promoted_memories": promoted, "path": str(path)}

    def retrieve_similar_experiences(self, query: str, top_k: int = 5) -> list[dict]:
        items = self.repository.list_memory_items(["episodic", "implementation", "optimization"])
        scored = []
        anchors = _anchor_tokens(query)
        for item in items:
            text = self._memory_item_text(item)
            if not _matches_anchor(anchors, text):
                continue
            score = self._adjust_memory_score(query, item, text, _score(query, text))
            if score > 0:
                scored.append({"id": item["id"], "memory_type": item["memory_type"], "score": round(score, 4), "text": text[:400], "source_run_id": item.get("source_run_id")})
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:top_k]

    def retrieve_failure_cases(self, query: str, top_k: int = 5) -> list[dict]:
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
        for item in self.repository.list_memory_items(["failure"]):
            text = self._memory_item_text(item)
            if not _matches_anchor(anchors, text):
                continue
            score = self._adjust_memory_score(query, item, text, _score(query, text))
            if score > 0:
                scored.append({"id": item["id"], "score": round(score, 4), "text": text[:400], "source_run_id": item.get("source_run_id")})
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:top_k]

    def retrieve_optimization_rules(self, query: str, top_k: int = 5) -> list[dict]:
        scored = []
        anchors = _anchor_tokens(query)
        for item in self.repository.list_memory_facts():
            text = item["fact"]
            if not _matches_anchor(anchors, text):
                continue
            score = _score(query, text)
            if score > 0:
                scored.append({"id": item["id"], "score": round(score, 4), "text": text[:400], "source_run_id": item.get("source_run_id")})
        for item in self.repository.list_memory_items(["optimization", "semantic"]):
            text = self._memory_item_text(item)
            if not _matches_anchor(anchors, text):
                continue
            score = _score(query, text)
            if score > 0:
                scored.append({"id": item["id"], "score": round(score, 4), "text": text[:400], "source_run_id": item.get("source_run_id")})
        for item in self.repository.list_skills():
            text = f"{item['name']} {item['description']} {item['steps_json']}"
            if not _matches_anchor(anchors, text):
                continue
            score = _score(query, text)
            if score > 0:
                scored.append({"id": item["id"], "score": round(score, 4), "text": text[:400], "source_run_id": item.get("source_run_id")})
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:top_k]

    def save_skill(self, name: str, steps: list[str], trigger_conditions: dict, success_criteria: dict) -> dict:
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
