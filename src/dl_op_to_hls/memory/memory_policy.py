from __future__ import annotations


class MemoryPolicy:
    def _is_functionally_verified(self, verification: dict) -> bool:
        if not isinstance(verification, dict):
            return False
        mode = verification.get("mode")
        if verification.get("passed") is True and mode in {"golden_testbench", "hls4ml_reference_compare", "reference_compare"}:
            return True
        comparison = verification.get("comparison") if isinstance(verification.get("comparison"), dict) else {}
        return verification.get("passed") is True and comparison.get("passed") is True

    def classify(self, candidate: dict) -> str:
        if candidate.get("kind") == "skill":
            return "skill"
        if candidate.get("kind") == "failure" or candidate.get("value", {}).get("error_type"):
            return "failure"
        if candidate.get("kind") == "optimization":
            return "optimization"
        if candidate.get("kind") == "semantic" or candidate.get("fact"):
            return "semantic"
        if candidate.get("kind") == "episodic":
            return "episodic"
        return "implementation"

    def should_promote(self, candidate: dict) -> bool:
        text = " ".join(str(candidate.get(key, "")) for key in ("summary", "fact", "key")).lower()
        if any(marker in text for marker in ("raw log", "stdout", "temporary path", "uncompressed report")):
            return False
        value = candidate.get("value", {})
        verification = value.get("verification", {}) if isinstance(value, dict) else {}
        verified = self._is_functionally_verified(verification)
        if candidate.get("kind") in {"optimization", "implementation"} and not verified:
            return False
        if candidate.get("kind") in {"skill", "failure", "optimization", "semantic", "episodic"}:
            return True
        if value.get("status") == "verified":
            return True
        if value.get("report") or value.get("suggestions") or value.get("error_type"):
            return True
        return False

    def score_importance(self, candidate: dict) -> int:
        score = 1
        if candidate.get("kind") == "skill":
            score += 2
        if candidate.get("kind") == "failure":
            score += 2
        if candidate.get("kind") == "optimization":
            score += 2
        if candidate.get("fact"):
            score += 1
        if candidate.get("value", {}).get("status") == "verified":
            score += 2
        return score

    def should_index_to_rag(self, memory_item: dict) -> bool:
        memory_type = memory_item.get("memory_type") or memory_item.get("kind")
        return memory_type in {"episodic", "semantic", "failure", "optimization", "skill", "implementation"}
