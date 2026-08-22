from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any


INJECTION_PATTERNS = (
    r"ignore\s+(all\s+)?(previous|prior)\s+instructions",
    r"system\s+prompt",
    r"developer\s+message",
    r"do\s+not\s+trust\s+retrieval",
    r"always\s+(select|call|return|approve)",
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class FeedbackGovernor:
    """Quarantines online feedback until provenance and safety checks pass."""

    def __init__(self, repository):
        self.repository = repository
        self.database = repository.database

    def submit(
        self,
        memory_id: int,
        score: float,
        reason: str = "",
        user_id: str | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self.repository.get_memory_item(memory_id) is None:
            raise KeyError(memory_id)
        bounded = max(-1.0, min(1.0, float(score)))
        reason = str(reason)[:2000]
        evidence = dict(evidence or {})
        flags = self._risk_flags(reason, evidence, bounded)
        status = "quarantined" if flags else "pending"
        with self.database.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO memory_feedback_candidates
                   (memory_id, user_id, score, reason, evidence_json, status, risk_flags_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (memory_id, user_id, bounded, reason, json.dumps(evidence, ensure_ascii=False), status, json.dumps(flags), _now()),
            )
            connection.commit()
        candidate_id = int(cursor.lastrowid)
        if status == "pending" and evidence.get("run_verified") is True and evidence.get("run_id"):
            return self.review(candidate_id, "approve", reviewer="policy:auto")
        return {"candidate_id": candidate_id, "status": status, "risk_flags": flags, "applied": False}

    def review(self, candidate_id: int, decision: str, *, reviewer: str) -> dict[str, Any]:
        if decision not in {"approve", "reject", "quarantine"}:
            raise ValueError("decision must be approve, reject, or quarantine")
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM memory_feedback_candidates WHERE id=?", (candidate_id,)).fetchone()
            if not row:
                connection.rollback()
                raise KeyError(candidate_id)
            if row["status"] in {"approved", "rejected"}:
                connection.commit()
                return {"candidate_id": candidate_id, "status": row["status"], "applied": row["status"] == "approved", "replayed": True}
            status = {"approve": "approved", "reject": "rejected", "quarantine": "quarantined"}[decision]
            feedback_id = None
            aggregate = None
            if decision == "approve":
                feedback = connection.execute(
                    "INSERT INTO memory_feedback (memory_id, user_id, score, reason, created_at) VALUES (?, ?, ?, ?, ?)",
                    (row["memory_id"], row["user_id"], row["score"], row["reason"], _now()),
                )
                feedback_id = int(feedback.lastrowid)
                aggregate = connection.execute(
                    "SELECT AVG(score) FROM memory_feedback WHERE memory_id=?", (row["memory_id"],)
                ).fetchone()[0]
                connection.execute(
                    "UPDATE memory_items SET feedback_score=?, updated_at=? WHERE id=?",
                    (aggregate, _now(), row["memory_id"]),
                )
            connection.execute(
                "UPDATE memory_feedback_candidates SET status=?, reviewer=?, reviewed_at=?, applied_feedback_id=? WHERE id=?",
                (status, reviewer, _now(), feedback_id, candidate_id),
            )
            connection.commit()
        return {"candidate_id": candidate_id, "status": status, "applied": decision == "approve", "feedback_score": aggregate}

    def revoke(self, candidate_id: int, *, reviewer: str, reason: str = "") -> dict[str, Any]:
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM memory_feedback_candidates WHERE id=?", (candidate_id,)).fetchone()
            if not row or row["status"] != "approved" or not row["applied_feedback_id"]:
                connection.rollback()
                raise ValueError("Only applied feedback can be revoked.")
            connection.execute("DELETE FROM memory_feedback WHERE id=?", (row["applied_feedback_id"],))
            aggregate = connection.execute("SELECT AVG(score) FROM memory_feedback WHERE memory_id=?", (row["memory_id"],)).fetchone()[0]
            aggregate = float(aggregate or 0.0)
            connection.execute("UPDATE memory_items SET feedback_score=?, updated_at=? WHERE id=?", (aggregate, _now(), row["memory_id"]))
            flags = json.loads(row["risk_flags_json"] or "[]") + [f"revoked:{reason[:120]}"]
            connection.execute(
                "UPDATE memory_feedback_candidates SET status='revoked', reviewer=?, reviewed_at=?, risk_flags_json=? WHERE id=?",
                (reviewer, _now(), json.dumps(flags), candidate_id),
            )
            connection.commit()
        return {"candidate_id": candidate_id, "status": "revoked", "feedback_score": aggregate}

    def list_candidates(self, status: str | None = None) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            if status:
                rows = connection.execute("SELECT * FROM memory_feedback_candidates WHERE status=? ORDER BY id DESC", (status,)).fetchall()
            else:
                rows = connection.execute("SELECT * FROM memory_feedback_candidates ORDER BY id DESC").fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["evidence"] = json.loads(item.pop("evidence_json"))
            item["risk_flags"] = json.loads(item.pop("risk_flags_json"))
            result.append(item)
        return result

    @staticmethod
    def _risk_flags(reason: str, evidence: dict[str, Any], score: float) -> list[str]:
        lowered = reason.lower()
        flags = [f"prompt_injection:{index}" for index, pattern in enumerate(INJECTION_PATTERNS) if re.search(pattern, lowered)]
        if evidence.get("source_user_id") and evidence.get("target_user_id") and evidence["source_user_id"] != evidence["target_user_id"]:
            flags.append("cross_tenant_provenance")
        if abs(score) >= 0.95 and not evidence.get("run_verified"):
            flags.append("extreme_unverified_score")
        if evidence.get("artifact_hash_valid") is False:
            flags.append("invalid_evidence_hash")
        return flags
