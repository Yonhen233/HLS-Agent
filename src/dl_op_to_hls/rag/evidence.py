from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Callable


TOKEN_RE = re.compile(r"[A-Za-z0-9_<>.-]+")
GENERIC_TOKENS = {
    "agent",
    "clock",
    "cycles",
    "dsp",
    "factor",
    "hls",
    "hls4ml",
    "latency",
    "model",
    "operator",
    "optimization",
    "report",
    "resource",
    "reuse",
    "run",
    "timing",
    "vivado",
}
ENTITY_TOKENS = {
    "cnn",
    "conv1d",
    "conv2d",
    "dense",
    "lstm",
    "matmul",
    "mlp",
    "mnist",
    "pooling",
    "qkeras",
    "qonnx",
    "resnet",
    "resnet18",
    "transformer",
}
PROMPT_INJECTION_MARKERS = (
    "ignore previous instructions",
    "ignore all previous",
    "reveal the system prompt",
    "override your instructions",
    "send the api key",
    "exfiltrate",
)


def _tokens(text: str) -> set[str]:
    values: set[str] = set()
    for token in TOKEN_RE.findall(text or ""):
        lowered = token.lower()
        values.add(lowered)
        values.update(part for part in re.split(r"[_<>.\-]+", lowered) if part)
    return values


def _anchors(text: str) -> set[str]:
    return {token for token in _tokens(text) if len(token) >= 4 and token not in GENERIC_TOKENS and not token.isdigit()}


def _entity_anchor_groups(text: str) -> list[set[str]]:
    groups: list[set[str]] = []
    for raw_token in TOKEN_RE.findall(text or ""):
        token = raw_token.lower()
        parts = {
            part
            for part in re.split(r"[_<>.\-]+", token)
            if len(part) >= 4 and part not in GENERIC_TOKENS and part != "demo"
        }
        alpha_numeric = any(char.isalpha() for char in token) and any(char.isdigit() for char in token)
        known_entities = parts.intersection(ENTITY_TOKENS)
        is_entity = token in ENTITY_TOKENS or alpha_numeric or token.endswith("error") or bool(known_entities)
        if not is_entity:
            continue
        specific = {
            part
            for part in parts
            if any(char.isdigit() for char in part) or part.endswith("error") or part in ENTITY_TOKENS
        }
        groups.append(specific or known_entities or {token})
    return groups


class RAGEvidenceGrader:
    """Calibrate retrieval evidence before it is allowed into an LLM context."""

    def grade(self, query: str, item: dict[str, Any], *, require_citation: bool = True) -> dict[str, Any]:
        text = str(item.get("text") or item.get("summary") or "")
        query_anchors = _anchors(query)
        text_tokens = _tokens(text)
        overlap_tokens = query_anchors.intersection(text_tokens)
        overlap = len(overlap_tokens) / max(1, len(query_anchors)) if query_anchors else 0.0
        provenance = item.get("provenance") if isinstance(item.get("provenance"), dict) else {}
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        trust = float(provenance.get("trust_score") or item.get("trust_score") or 0.7)
        retrieval = item.get("retrieval") if isinstance(item.get("retrieval"), dict) else {}
        raw_score = float(retrieval.get("hybrid_score") or item.get("score") or 0.0)
        normalized_score = raw_score / (1.0 + abs(raw_score))
        semantic_score = retrieval.get("semantic_score")
        cross_encoder_score = retrieval.get("cross_encoder_score")
        entity_search_text = " ".join(
            [
                text,
                str(item.get("source_id") or ""),
                str(item.get("citation") or ""),
                str(metadata),
            ]
        )
        entity_tokens = _tokens(entity_search_text)
        entity_anchor_groups = _entity_anchor_groups(query)
        entity_anchor_match = all(bool(group.intersection(entity_tokens)) for group in entity_anchor_groups)
        semantic_support = (
            semantic_score is not None
            and float(semantic_score) >= 0.30
            and cross_encoder_score is not None
            and float(cross_encoder_score) >= 0.20
            and entity_anchor_match
        )
        untrusted_text = f"{text} {metadata}".lower()
        injection_markers = [marker for marker in PROMPT_INJECTION_MARKERS if marker in untrusted_text]
        citation_present = bool(item.get("citation") or item.get("source_id") or item.get("source_run_id") or item.get("id"))
        expired = self._is_expired(metadata.get("expires_at"))
        quarantined = bool(metadata.get("quarantined") or metadata.get("deleted_at") or metadata.get("superseded_by"))
        mock_only = bool(metadata.get("mock") or metadata.get("mock_evidence")) and "mock" not in _tokens(query)

        reasons: list[str] = []
        if injection_markers:
            label = "unsafe"
            reasons.append("prompt_injection_marker")
        elif quarantined:
            label = "irrelevant"
            reasons.append("quarantined_or_superseded")
        elif expired:
            label = "irrelevant"
            reasons.append("expired_evidence")
        elif mock_only:
            label = "ambiguous"
            reasons.append("mock_evidence_not_allowed_for_real_claim")
        elif require_citation and not citation_present:
            label = "irrelevant"
            reasons.append("missing_provenance")
        elif query_anchors and not overlap_tokens and not semantic_support:
            label = "irrelevant"
            reasons.append("missing_query_anchor")
        elif semantic_support:
            label = "relevant"
            reasons.append("embedding_and_cross_encoder_passed")
        elif overlap >= 0.5 or (overlap >= 0.25 and trust >= 0.8):
            label = "relevant"
            reasons.append("anchor_and_trust_passed")
        elif overlap > 0 or (not query_anchors and normalized_score >= 0.15):
            label = "ambiguous"
            reasons.append("weak_support")
        else:
            label = "irrelevant"
            reasons.append("insufficient_support")

        semantic_confidence = 0.0
        if semantic_score is not None:
            semantic_confidence += 0.4 * max(0.0, min(1.0, (float(semantic_score) + 1.0) / 2.0))
        if cross_encoder_score is not None:
            semantic_confidence += 0.6 * max(0.0, min(1.0, float(cross_encoder_score)))
        confidence = max(
            0.0,
            min(1.0, 0.45 * overlap + 0.20 * trust + 0.15 * normalized_score + 0.20 * semantic_confidence),
        )
        return {
            "label": label,
            "confidence": round(confidence, 4),
            "anchor_overlap": round(overlap, 4),
            "matched_anchors": sorted(overlap_tokens),
            "semantic_support": semantic_support,
            "entity_anchor_guard_passed": entity_anchor_match,
            "semantic_score": round(float(semantic_score), 4) if semantic_score is not None else None,
            "cross_encoder_score": round(float(cross_encoder_score), 4) if cross_encoder_score is not None else None,
            "citation_present": citation_present,
            "injection_markers": injection_markers,
            "expired": expired,
            "quarantined": quarantined,
            "mock_only": mock_only,
            "reasons": reasons,
        }

    @staticmethod
    def _is_expired(raw_value: Any) -> bool:
        if not raw_value:
            return False
        try:
            parsed = datetime.fromisoformat(str(raw_value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed <= datetime.now(timezone.utc)
        except (TypeError, ValueError):
            return True

    def grade_many(
        self,
        query: str,
        items: list[dict[str, Any]],
        *,
        require_citation: bool = True,
    ) -> dict[str, Any]:
        graded = [{**item, "evidence_grade": self.grade(query, item, require_citation=require_citation)} for item in items]
        self._mark_structured_contradictions(graded)
        accepted = [item for item in graded if item["evidence_grade"]["label"] == "relevant"]
        rejected = [item for item in graded if item["evidence_grade"]["label"] != "relevant"]
        confidence = sum(item["evidence_grade"]["confidence"] for item in accepted) / max(1, len(accepted))
        return {
            "status": "sufficient_evidence" if accepted else "insufficient_evidence",
            "results": accepted,
            "rejected": rejected,
            "confidence": round(confidence, 4),
            "evaluated_count": len(graded),
        }

    @staticmethod
    def _mark_structured_contradictions(items: list[dict[str, Any]]) -> None:
        facts: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
        for item in items:
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            fact_key = metadata.get("fact_key")
            if fact_key is None or "fact_value" not in metadata:
                continue
            facts[str(fact_key)][str(metadata.get("fact_value"))].append(item)
        for values in facts.values():
            if len(values) <= 1:
                continue
            for conflicting_items in values.values():
                for item in conflicting_items:
                    item["evidence_grade"]["label"] = "contradictory"
                    item["evidence_grade"]["reasons"].append("conflicting_structured_fact")


class CorrectiveRetriever:
    """Retrieve, grade, rewrite once, and abstain when evidence remains weak."""

    def __init__(self, retrieve_fn: Callable[..., list[dict[str, Any]]], grader: RAGEvidenceGrader | None = None):
        self.retrieve_fn = retrieve_fn
        self.grader = grader or RAGEvidenceGrader()

    def retrieve(
        self,
        query: str,
        *,
        top_k: int = 5,
        domain: str | None = None,
        identity: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        attempts: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        for candidate_query in self._query_variants(query):
            candidates = self.retrieve_fn(candidate_query, top_k=max(top_k * 2, 8), domain=domain, identity=identity)
            graded = self.grader.grade_many(query, candidates, require_citation=True)
            attempts.append(
                {
                    "query": candidate_query,
                    "candidate_count": len(candidates),
                    "accepted_count": len(graded["results"]),
                    "confidence": graded["confidence"],
                }
            )
            rejected.extend(graded["rejected"])
            if graded["results"]:
                selected = sorted(
                    graded["results"],
                    key=lambda item: (item["evidence_grade"]["confidence"], float(item.get("score") or 0.0)),
                    reverse=True,
                )[:top_k]
                return {
                    "status": "sufficient_evidence",
                    "results": selected,
                    "rejected": rejected,
                    "attempts": attempts,
                    "confidence": round(
                        sum(item["evidence_grade"]["confidence"] for item in selected) / max(1, len(selected)), 4
                    ),
                    "abstained": False,
                }
        return {
            "status": "insufficient_evidence",
            "results": [],
            "rejected": rejected,
            "attempts": attempts,
            "confidence": 0.0,
            "abstained": True,
        }

    @staticmethod
    def _query_variants(query: str) -> list[str]:
        anchors = sorted(_anchors(query))
        variants = [query.strip()]
        rewritten = " ".join(anchors)
        if rewritten and rewritten.lower() != query.strip().lower():
            variants.append(rewritten)
        return list(dict.fromkeys(item for item in variants if item))


class ClaimEvidenceVerifier:
    def verify(self, claims: list[str], evidence: list[dict[str, Any]]) -> dict[str, Any]:
        evidence_tokens = [(_tokens(str(item.get("text") or "")), item) for item in evidence]
        checks: list[dict[str, Any]] = []
        for claim in claims:
            claim_anchors = _anchors(claim)
            supporting = []
            for tokens, item in evidence_tokens:
                overlap = len(claim_anchors.intersection(tokens)) / max(1, len(claim_anchors))
                if overlap >= 0.5:
                    supporting.append(item.get("citation") or item.get("source_id") or item.get("source_run_id"))
            checks.append(
                {
                    "claim": claim,
                    "supported": bool(supporting),
                    "supporting_citations": supporting,
                }
            )
        return {
            "passed": all(item["supported"] for item in checks),
            "claim_count": len(checks),
            "supported_count": sum(1 for item in checks if item["supported"]),
            "checks": checks,
        }
