from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


class DurableJobQueue:
    """SQLite lease queue with at-least-once delivery and exactly-once state commits."""

    def __init__(self, database):
        self.database = database

    def enqueue(
        self,
        payload: dict[str, Any],
        *,
        idempotency_key: str | None = None,
        priority: int = 100,
        max_attempts: int = 3,
        available_at: float | None = None,
    ) -> dict[str, Any]:
        key = idempotency_key or _hash(payload)
        job_id = f"job_{uuid.uuid4().hex[:16]}"
        now = _now_iso()
        with self.database.connect() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO agent_jobs (
                       job_id, idempotency_key, payload_json, status, priority,
                       available_at, attempts, max_attempts, state_version,
                       created_at, updated_at
                   ) VALUES (?, ?, ?, 'pending', ?, ?, 0, ?, 0, ?, ?)""",
                (job_id, key, _stable_json(payload), int(priority), available_at or time.time(), int(max_attempts), now, now),
            )
            row = connection.execute(
                "SELECT * FROM agent_jobs WHERE idempotency_key = ?",
                (key,),
            ).fetchone()
            connection.commit()
        result = self._row(row)
        result["deduplicated"] = result["job_id"] != job_id
        return result

    def claim(self, worker_id: str, *, lease_seconds: float = 60.0) -> dict[str, Any] | None:
        now_epoch = time.time()
        now = _now_iso()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """UPDATE agent_jobs
                   SET status = CASE WHEN attempts >= max_attempts THEN 'dead' ELSE 'pending' END,
                       lease_owner = NULL, lease_expires_at = NULL, updated_at = ?
                   WHERE status = 'running' AND lease_expires_at < ?""",
                (now, now_epoch),
            )
            row = connection.execute(
                """SELECT * FROM agent_jobs
                   WHERE status = 'pending' AND available_at <= ? AND attempts < max_attempts
                   ORDER BY priority ASC, created_at ASC
                   LIMIT 1""",
                (now_epoch,),
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            updated = connection.execute(
                """UPDATE agent_jobs
                   SET status = 'running', lease_owner = ?, lease_expires_at = ?,
                       attempts = attempts + 1, updated_at = ?
                   WHERE job_id = ? AND status = 'pending'""",
                (worker_id, now_epoch + max(1.0, lease_seconds), now, row["job_id"]),
            )
            if updated.rowcount != 1:
                connection.rollback()
                return None
            claimed = connection.execute("SELECT * FROM agent_jobs WHERE job_id = ?", (row["job_id"],)).fetchone()
            connection.commit()
        return self._row(claimed)

    def heartbeat(self, job_id: str, worker_id: str, *, lease_seconds: float = 60.0) -> bool:
        with self.database.connect() as connection:
            cursor = connection.execute(
                """UPDATE agent_jobs SET lease_expires_at = ?, updated_at = ?
                   WHERE job_id = ? AND status = 'running' AND lease_owner = ?""",
                (time.time() + max(1.0, lease_seconds), _now_iso(), job_id, worker_id),
            )
            connection.commit()
            return cursor.rowcount == 1

    def commit(
        self,
        job_id: str,
        worker_id: str,
        result: dict[str, Any],
        *,
        commit_key: str,
        expected_version: int,
    ) -> dict[str, Any]:
        result_json = _stable_json(result)
        payload_hash = _hash(result)
        now = _now_iso()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM agent_state_commits WHERE commit_key = ?",
                (commit_key,),
            ).fetchone()
            if existing is not None:
                connection.commit()
                if existing["payload_hash"] != payload_hash or existing["job_id"] != job_id:
                    raise RuntimeError("Commit key was already used with a different payload or job.")
                return {
                    "status": "completed",
                    "job_id": job_id,
                    "state_version": int(existing["state_version"]),
                    "replayed": True,
                    "result": json.loads(existing["result_json"]),
                }
            job = connection.execute("SELECT * FROM agent_jobs WHERE job_id = ?", (job_id,)).fetchone()
            if job is None:
                connection.rollback()
                raise KeyError(job_id)
            if job["status"] != "running" or job["lease_owner"] != worker_id:
                connection.rollback()
                raise RuntimeError("Worker does not own the active job lease.")
            if float(job["lease_expires_at"] or 0) < time.time():
                connection.rollback()
                raise RuntimeError("Job lease expired before commit.")
            if int(job["state_version"]) != int(expected_version):
                connection.rollback()
                raise RuntimeError("State version changed before commit.")
            next_version = int(expected_version) + 1
            connection.execute(
                """INSERT INTO agent_state_commits (
                       commit_key, job_id, state_version, payload_hash, result_json, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                (commit_key, job_id, next_version, payload_hash, result_json, now),
            )
            updated = connection.execute(
                """UPDATE agent_jobs
                   SET status = 'completed', state_version = ?, result_json = ?,
                       lease_owner = NULL, lease_expires_at = NULL, updated_at = ?
                   WHERE job_id = ? AND state_version = ? AND lease_owner = ?""",
                (next_version, result_json, now, job_id, expected_version, worker_id),
            )
            if updated.rowcount != 1:
                connection.rollback()
                raise RuntimeError("Exactly-once state commit lost its compare-and-swap.")
            event_id = f"job:{job_id}:completed:v{next_version}"
            connection.execute(
                """INSERT OR IGNORE INTO agent_outbox (
                       event_id, job_id, event_type, payload_json, created_at
                   ) VALUES (?, ?, 'AgentJobCompleted', ?, ?)""",
                (event_id, job_id, result_json, now),
            )
            connection.commit()
        return {
            "status": "completed",
            "job_id": job_id,
            "state_version": next_version,
            "replayed": False,
            "result": result,
        }

    def fail(
        self,
        job_id: str,
        worker_id: str,
        error: dict[str, Any],
        *,
        retryable: bool = True,
        retry_delay_seconds: float = 0.0,
    ) -> dict[str, Any]:
        now = _now_iso()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            job = connection.execute("SELECT * FROM agent_jobs WHERE job_id = ?", (job_id,)).fetchone()
            if job is None:
                connection.rollback()
                raise KeyError(job_id)
            if job["status"] != "running" or job["lease_owner"] != worker_id:
                connection.rollback()
                raise RuntimeError("Worker does not own the active job lease.")
            retry = retryable and int(job["attempts"]) < int(job["max_attempts"])
            status = "pending" if retry else "dead"
            connection.execute(
                """UPDATE agent_jobs
                   SET status = ?, error_json = ?, available_at = ?,
                       lease_owner = NULL, lease_expires_at = NULL, updated_at = ?
                   WHERE job_id = ?""",
                (status, _stable_json(error), time.time() + max(0.0, retry_delay_seconds), now, job_id),
            )
            connection.commit()
        return {"job_id": job_id, "status": status, "retryable": retry}

    def get(self, job_id: str) -> dict[str, Any]:
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM agent_jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return self._row(row)

    def pending_outbox(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM agent_outbox WHERE published_at IS NULL ORDER BY created_at LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        return [self._outbox_row(row) for row in rows]

    def acknowledge_outbox(self, event_id: str) -> bool:
        with self.database.connect() as connection:
            cursor = connection.execute(
                "UPDATE agent_outbox SET published_at = ? WHERE event_id = ? AND published_at IS NULL",
                (_now_iso(), event_id),
            )
            connection.commit()
            return cursor.rowcount == 1

    @staticmethod
    def _row(row) -> dict[str, Any]:
        payload = dict(row)
        payload["payload"] = json.loads(payload.pop("payload_json"))
        result_json = payload.pop("result_json")
        error_json = payload.pop("error_json")
        payload["result"] = json.loads(result_json) if result_json else None
        payload["error"] = json.loads(error_json) if error_json else None
        return payload

    @staticmethod
    def _outbox_row(row) -> dict[str, Any]:
        payload = dict(row)
        payload["payload"] = json.loads(payload.pop("payload_json"))
        return payload


class DurableWorker:
    def __init__(self, queue: DurableJobQueue, worker_id: str, handler: Callable[[dict[str, Any]], dict[str, Any]]):
        self.queue = queue
        self.worker_id = worker_id
        self.handler = handler

    def run_once(self, *, lease_seconds: float = 300.0) -> dict[str, Any] | None:
        job = self.queue.claim(self.worker_id, lease_seconds=lease_seconds)
        if job is None:
            return None
        try:
            result = self.handler(job["payload"])
            return self.queue.commit(
                job["job_id"],
                self.worker_id,
                result,
                commit_key=f"{job['job_id']}:attempt:{job['attempts']}",
                expected_version=int(job["state_version"]),
            )
        except Exception as exc:
            return self.queue.fail(
                job["job_id"],
                self.worker_id,
                {"error_type": type(exc).__name__, "message": str(exc)},
                retryable=True,
            )
