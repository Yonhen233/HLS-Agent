from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..db.database import Database
from .context_pack import ContextBlock, ContextPack
from .trace import stable_hash


SESSION_STATUSES = {
    "created",
    "running",
    "interrupt_requested",
    "waiting_for_approval",
    "interrupted",
    "completed",
    "failed",
    "rolled_back",
}


class SessionVersionConflict(RuntimeError):
    """Raised when another worker committed a newer session version."""


class CancellationToken:
    def __init__(self, manager: "SessionManager", session_id: str | None):
        self.manager = manager
        self.session_id = session_id

    @property
    def cancelled(self) -> bool:
        return bool(self.session_id and self.manager.pause_requested(self.session_id))

    @property
    def reason(self) -> str:
        if not self.session_id:
            return ""
        return str(self.manager.get(self.session_id).get("interrupt_reason") or "User requested interruption")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


class SessionManager:
    """Database-backed durable Agent sessions with append-only audit projections.

    SQLite is the source of truth for session state, messages, approvals, events,
    and checkpoints. JSON/JSONL files under ``runs/sessions`` are rebuildable
    operator-facing projections, never the concurrency authority.
    """

    def __init__(
        self,
        sessions_root: str | Path,
        database: Database | None = None,
        *,
        mirror_files: bool = True,
        import_legacy_files: bool = True,
    ):
        self.sessions_root = Path(sessions_root)
        self.sessions_root.mkdir(parents=True, exist_ok=True)
        if database is None:
            schema_path = Path(__file__).resolve().parents[1] / "db" / "schema.sql"
            database = Database(self.sessions_root / "sessions.db", schema_path)
        self.database = database
        self.mirror_files = bool(mirror_files)
        self._projection_lock = threading.RLock()
        if import_legacy_files:
            self._import_legacy_files()

    def create(
        self,
        user_input: Any,
        session_id: str | None = None,
        *,
        user_id: str = "local-user",
        project_id: str = "default-project",
    ) -> dict[str, Any]:
        session_id = session_id or f"session_{uuid.uuid4().hex[:12]}"
        now = _now()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM agent_sessions WHERE session_id=?", (session_id,)).fetchone()
            if row:
                metadata = _loads(row["metadata_json"], {})
                metadata.update({"replan_required": False, "user_id": user_id, "project_id": project_id})
                sequence = int(row["next_message_seq"])
                self._insert_message_tx(
                    connection,
                    session_id,
                    sequence,
                    "user",
                    self._input_preview(user_input),
                    {"kind": "follow_up_input"},
                    now,
                )
                self._update_session_tx(
                    connection,
                    session_id,
                    int(row["version"]),
                    status="created",
                    metadata_json=_json(metadata),
                    next_message_seq=sequence + 1,
                    updated_at=now,
                )
                self._append_event_tx(connection, session_id, "SessionInputAppended", {"message_id": f"turn_{sequence:04d}"})
            else:
                connection.execute(
                    """INSERT INTO agent_sessions
                       (session_id, run_id, run_ids_json, status, generation, active_checkpoint_id,
                        created_at, updated_at, summary, next_message_seq, next_event_seq,
                        metadata_json, compaction_history_json, interrupt_reason, version)
                       VALUES (?, NULL, '[]', 'created', 1, NULL, ?, ?, '', 2, 1, ?, '[]', NULL, 1)""",
                    (session_id, now, now, _json({"user_id": user_id, "project_id": project_id})),
                )
                self._insert_message_tx(
                    connection,
                    session_id,
                    1,
                    "user",
                    self._input_preview(user_input),
                    {"kind": "initial_input"},
                    now,
                )
                self._append_event_tx(connection, session_id, "SessionCreated", {"status": "created"})
            connection.commit()
        self._project_session(session_id)
        return self.get(session_id)

    def bind_run(self, session_id: str, run_id: str) -> dict[str, Any]:
        record = self.get(session_id)
        run_ids = list(record.get("run_ids", []))
        if run_id not in run_ids:
            run_ids.append(run_id)
        return self._update(session_id, run_id=run_id, run_ids=run_ids, status="running")

    def set_metadata(self, session_id: str, **metadata: Any) -> dict[str, Any]:
        record = self.get(session_id)
        merged = dict(record.get("metadata", {}))
        merged.update(metadata)
        return self._update(session_id, metadata=merged)

    def get(self, session_id: str) -> dict[str, Any]:
        with self.database.connect() as connection:
            return self._load_record_tx(connection, session_id)

    def list_sessions(self) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            ids = [
                row["session_id"]
                for row in connection.execute(
                    "SELECT session_id FROM agent_sessions ORDER BY updated_at DESC"
                ).fetchall()
            ]
            return [self._load_record_tx(connection, session_id) for session_id in ids]

    def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = _now()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._session_row_tx(connection, session_id)
            sequence = int(row["next_message_seq"])
            message = self._insert_message_tx(
                connection, session_id, sequence, role, str(content), dict(metadata or {}), now
            )
            self._update_session_tx(
                connection,
                session_id,
                int(row["version"]),
                next_message_seq=sequence + 1,
                updated_at=now,
            )
            self._append_event_tx(
                connection,
                session_id,
                "SessionMessageAppended",
                {"message_id": message["message_id"], "role": role},
            )
            connection.commit()
        self._project_session(session_id)
        return message

    def retract_last_user_message(self, session_id: str) -> dict[str, Any]:
        now = _now()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._session_row_tx(connection, session_id)
            message = connection.execute(
                """SELECT * FROM agent_session_messages
                   WHERE session_id=? AND role='user' AND retracted=0
                   ORDER BY sequence DESC LIMIT 1""",
                (session_id,),
            ).fetchone()
            if not message:
                connection.rollback()
                raise ValueError("Session has no active user message to retract")
            descendants = connection.execute(
                """SELECT message_id FROM agent_session_messages
                   WHERE session_id=? AND sequence>=? AND retracted=0 ORDER BY sequence""",
                (session_id, message["sequence"]),
            ).fetchall()
            retracted_ids = [item["message_id"] for item in descendants]
            connection.execute(
                """UPDATE agent_session_messages
                   SET retracted=1, retracted_at=?, retracted_by_message_id=?
                   WHERE session_id=? AND sequence>=? AND retracted=0""",
                (now, message["message_id"], session_id, message["sequence"]),
            )
            metadata = _loads(row["metadata_json"], {})
            metadata["replan_required"] = True
            generation = int(row["generation"]) + 1
            self._update_session_tx(
                connection,
                session_id,
                int(row["version"]),
                generation=generation,
                status="interrupted",
                summary="",
                compaction_history_json="[]",
                metadata_json=_json(metadata),
                updated_at=now,
            )
            self._append_event_tx(
                connection,
                session_id,
                "SessionMessageRetracted",
                {
                    "message_id": message["message_id"],
                    "retracted_message_ids": retracted_ids,
                    "generation": generation,
                },
            )
            connection.commit()
        self._project_session(session_id)
        payload = self._message_row(message)
        payload["retracted_message_ids"] = retracted_ids
        return payload

    def request_interrupt(self, session_id: str, reason: str = "User requested interruption") -> dict[str, Any]:
        return self._transition(
            session_id,
            status="interrupt_requested",
            interrupt_reason=reason,
            event="SessionInterruptRequested",
            event_payload={"reason": reason},
        )

    def create_approval_request(
        self,
        session_id: str,
        *,
        tool_name: str,
        args_hash: str,
        reason: str,
        ttl_seconds: int = 900,
        max_uses: int = 1,
    ) -> dict[str, Any]:
        now = _now()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._session_row_tx(connection, session_id)
            existing = connection.execute(
                """SELECT * FROM agent_session_approvals
                   WHERE session_id=? AND tool_name=? AND args_hash=? AND status='pending'
                   ORDER BY created_at DESC LIMIT 1""",
                (session_id, tool_name, args_hash),
            ).fetchone()
            if existing:
                expires_at = datetime.fromisoformat(str(existing["expires_at"]))
                if expires_at > datetime.now(timezone.utc):
                    connection.commit()
                    return self._approval_row(existing)
                connection.execute(
                    "UPDATE agent_session_approvals SET status='expired' WHERE approval_id=?",
                    (existing["approval_id"],),
                )
            approval = {
                "approval_id": f"approval_{uuid.uuid4().hex[:10]}",
                "tool_name": tool_name,
                "args_hash": args_hash,
                "reason": reason,
                "status": "pending",
                "created_at": now,
                "expires_at": (
                    datetime.now(timezone.utc) + timedelta(seconds=max(1, int(ttl_seconds)))
                ).replace(microsecond=0).isoformat(),
                "max_uses": max(1, int(max_uses)),
                "use_count": 0,
            }
            connection.execute(
                """INSERT INTO agent_session_approvals
                   (approval_id, session_id, tool_name, args_hash, reason, status, created_at,
                    expires_at, max_uses, use_count)
                   VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, 0)""",
                (
                    approval["approval_id"], session_id, tool_name, args_hash, reason, now,
                    approval["expires_at"], approval["max_uses"],
                ),
            )
            self._update_session_tx(
                connection,
                session_id,
                int(row["version"]),
                status="waiting_for_approval",
                interrupt_reason=f"Approval required for {tool_name}",
                updated_at=now,
            )
            self._append_event_tx(
                connection,
                session_id,
                "SessionApprovalRequested",
                {"approval_id": approval["approval_id"], "tool_name": tool_name},
            )
            connection.commit()
        self._project_session(session_id)
        return approval

    def decide_approval(self, session_id: str, approval_id: str, decision: str, feedback: str = "") -> dict[str, Any]:
        if decision not in {"approved", "rejected"}:
            raise ValueError("Approval decision must be approved or rejected")
        now = _now()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._session_row_tx(connection, session_id)
            approval = connection.execute(
                "SELECT * FROM agent_session_approvals WHERE session_id=? AND approval_id=?",
                (session_id, approval_id),
            ).fetchone()
            if not approval:
                connection.rollback()
                raise KeyError(f"Unknown approval: {approval_id}")
            current_status = str(approval["status"])
            if current_status == decision:
                connection.commit()
                return self._approval_row(approval)
            if current_status != "pending":
                connection.rollback()
                raise ValueError(f"Approval {approval_id} is already {current_status}")
            if datetime.fromisoformat(str(approval["expires_at"])) <= datetime.now(timezone.utc):
                connection.execute(
                    "UPDATE agent_session_approvals SET status='expired' WHERE approval_id=?",
                    (approval_id,),
                )
                connection.commit()
                self._project_session(session_id)
                raise ValueError(f"Approval {approval_id} has expired")
            connection.execute(
                """UPDATE agent_session_approvals SET status=?, feedback=?, decided_at=?
                   WHERE session_id=? AND approval_id=?""",
                (decision, feedback, now, session_id, approval_id),
            )
            self._update_session_tx(
                connection, session_id, int(row["version"]), status="interrupted", updated_at=now
            )
            self._append_event_tx(
                connection,
                session_id,
                "SessionApprovalDecided",
                {"approval_id": approval_id, "decision": decision, "tool_name": approval["tool_name"]},
            )
            updated = connection.execute(
                "SELECT * FROM agent_session_approvals WHERE approval_id=?", (approval_id,)
            ).fetchone()
            connection.commit()
        self._project_session(session_id)
        return self._approval_row(updated)

    def approval_status(self, session_id: str, tool_name: str, args_hash: str) -> str | None:
        now = datetime.now(timezone.utc)
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            approval = connection.execute(
                """SELECT * FROM agent_session_approvals
                   WHERE session_id=? AND tool_name=? AND args_hash=?
                   ORDER BY created_at DESC LIMIT 1""",
                (session_id, tool_name, args_hash),
            ).fetchone()
            if not approval:
                connection.commit()
                return None
            session_row = self._session_row_tx(connection, session_id)
            status = str(approval["status"])
            if approval["expires_at"] and datetime.fromisoformat(str(approval["expires_at"])) <= now:
                status = "expired"
            elif int(approval["use_count"]) >= int(approval["max_uses"]):
                status = "consumed"
            if status != approval["status"]:
                connection.execute(
                    "UPDATE agent_session_approvals SET status=? WHERE approval_id=?",
                    (status, approval["approval_id"]),
                )
                self._update_session_tx(
                    connection,
                    session_id,
                    int(session_row["version"]),
                    updated_at=_now(),
                )
                self._append_event_tx(
                    connection,
                    session_id,
                    "SessionApprovalExpired" if status == "expired" else "SessionApprovalConsumed",
                    {"approval_id": approval["approval_id"], "status": status},
                )
            connection.commit()
        if status != approval["status"]:
            self._project_session(session_id)
        return status

    def consume_approval(self, session_id: str, tool_name: str, args_hash: str) -> bool:
        now = _now()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            session_row = self._session_row_tx(connection, session_id)
            approval = connection.execute(
                """SELECT * FROM agent_session_approvals
                   WHERE session_id=? AND tool_name=? AND args_hash=? AND status='approved'
                   ORDER BY created_at DESC LIMIT 1""",
                (session_id, tool_name, args_hash),
            ).fetchone()
            if not approval or datetime.fromisoformat(str(approval["expires_at"])) <= datetime.now(timezone.utc):
                connection.commit()
                return False
            uses = int(approval["use_count"]) + 1
            status = "consumed" if uses >= int(approval["max_uses"]) else "approved"
            cursor = connection.execute(
                """UPDATE agent_session_approvals
                   SET use_count=?, status=?, last_used_at=?
                   WHERE approval_id=? AND use_count=? AND status='approved'""",
                (uses, status, now, approval["approval_id"], approval["use_count"]),
            )
            if cursor.rowcount == 1:
                self._update_session_tx(
                    connection,
                    session_id,
                    int(session_row["version"]),
                    updated_at=now,
                )
                self._append_event_tx(
                    connection,
                    session_id,
                    "SessionApprovalConsumed",
                    {
                        "approval_id": approval["approval_id"],
                        "tool_name": tool_name,
                        "use_count": uses,
                        "status": status,
                    },
                )
            connection.commit()
        if cursor.rowcount == 1:
            self._project_session(session_id)
            return True
        return False

    def interrupt_requested(self, session_id: str) -> bool:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT status FROM agent_sessions WHERE session_id=?", (session_id,)
            ).fetchone()
        if not row:
            raise KeyError(f"Unknown session: {session_id}")
        return row["status"] == "interrupt_requested"

    def pause_requested(self, session_id: str) -> bool:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT status FROM agent_sessions WHERE session_id=?", (session_id,)
            ).fetchone()
        if not row:
            raise KeyError(f"Unknown session: {session_id}")
        return row["status"] in {"interrupt_requested", "waiting_for_approval"}

    def mark_interrupted(self, session_id: str, reason: str) -> dict[str, Any]:
        return self._transition(
            session_id,
            status="interrupted",
            interrupt_reason=reason,
            event="SessionInterrupted",
            event_payload={"reason": reason},
        )

    def mark_running(self, session_id: str) -> dict[str, Any]:
        record = self.get(session_id)
        return self._transition(
            session_id,
            status="running",
            interrupt_reason=None,
            event="SessionResumed",
            event_payload={"generation": record["generation"]},
        )

    def mark_finished(self, session_id: str, status: str, summary: str = "") -> dict[str, Any]:
        session_status = "completed" if status in {"success", "partial_success", "unsupported"} else "failed"
        return self._transition(
            session_id,
            status=session_status,
            summary=summary,
            event="SessionFinished",
            event_payload={"run_status": status, "status": session_status},
        )

    def create_checkpoint(
        self,
        session_id: str,
        state: dict[str, Any],
        reason: str,
        runtime: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = _now()
        runtime = dict(runtime or {})
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._session_row_tx(connection, session_id)
            sequence_row = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence FROM agent_session_checkpoints WHERE session_id=?",
                (session_id,),
            ).fetchone()
            sequence = int(sequence_row["next_sequence"])
            checkpoint_id = f"cp_{sequence:06d}"
            payload = {
                "checkpoint_id": checkpoint_id,
                "parent_checkpoint_id": row["active_checkpoint_id"],
                "session_id": session_id,
                "run_id": row["run_id"] or state.get("run_id"),
                "generation": int(row["generation"]),
                "reason": reason,
                "created_at": now,
                "state": state,
                "runtime": runtime,
            }
            connection.execute(
                """INSERT INTO agent_session_checkpoints
                   (checkpoint_id, session_id, sequence, parent_checkpoint_id, run_id, generation,
                    reason, state_json, runtime_json, state_hash, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    checkpoint_id, session_id, sequence, row["active_checkpoint_id"], payload["run_id"],
                    payload["generation"], reason, _json(state), _json(runtime), stable_hash(state), now,
                ),
            )
            self._update_session_tx(
                connection,
                session_id,
                int(row["version"]),
                active_checkpoint_id=checkpoint_id,
                updated_at=now,
            )
            self._append_event_tx(
                connection,
                session_id,
                "SessionCheckpointCreated",
                {"checkpoint_id": checkpoint_id, "reason": reason, "state_hash": stable_hash(state)},
            )
            connection.commit()
        self._project_session(session_id)
        return payload

    def load_active_checkpoint(self, session_id: str) -> dict[str, Any]:
        record = self.get(session_id)
        checkpoint_id = record.get("active_checkpoint_id")
        if not checkpoint_id:
            raise ValueError(f"Session {session_id} has no checkpoint")
        return self.load_checkpoint(session_id, checkpoint_id)

    def load_checkpoint(self, session_id: str, checkpoint_id: str) -> dict[str, Any]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM agent_session_checkpoints WHERE session_id=? AND checkpoint_id=?",
                (session_id, checkpoint_id),
            ).fetchone()
        if not row:
            raise KeyError(f"Unknown checkpoint: {checkpoint_id}")
        return self._checkpoint_row(row)

    def list_checkpoints(self, session_id: str) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM agent_session_checkpoints WHERE session_id=? ORDER BY sequence",
                (session_id,),
            ).fetchall()
        return [
            {
                key: payload.get(key)
                for key in ("checkpoint_id", "parent_checkpoint_id", "reason", "created_at", "generation", "state_hash")
            }
            for payload in (self._checkpoint_row(row) for row in rows)
        ]

    def rollback(self, session_id: str, checkpoint_id: str | None = None, steps: int = 1) -> dict[str, Any]:
        now = _now()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._session_row_tx(connection, session_id)
            checkpoints = connection.execute(
                "SELECT * FROM agent_session_checkpoints WHERE session_id=? ORDER BY sequence",
                (session_id,),
            ).fetchall()
            if not checkpoints:
                connection.rollback()
                raise ValueError("Session has no checkpoints")
            ids = [item["checkpoint_id"] for item in checkpoints]
            active = row["active_checkpoint_id"]
            current_index = ids.index(active) if active in ids else len(ids) - 1
            target = checkpoint_id or ids[max(0, current_index - max(1, int(steps)))]
            if target not in ids:
                connection.rollback()
                raise KeyError(f"Unknown checkpoint: {target}")
            generation = int(row["generation"]) + 1
            self._update_session_tx(
                connection,
                session_id,
                int(row["version"]),
                active_checkpoint_id=target,
                generation=generation,
                status="rolled_back",
                updated_at=now,
            )
            self._append_event_tx(
                connection,
                session_id,
                "SessionRolledBack",
                {"from_checkpoint_id": active, "checkpoint_id": target, "generation": generation},
            )
            checkpoint_row = next(item for item in checkpoints if item["checkpoint_id"] == target)
            connection.commit()
        self._project_session(session_id)
        return {"session": self.get(session_id), "checkpoint": self._checkpoint_row(checkpoint_row)}

    def compact_messages(self, session_id: str, keep_recent: int = 8) -> dict[str, Any]:
        keep_recent = max(1, int(keep_recent))
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._session_row_tx(connection, session_id)
            messages = connection.execute(
                """SELECT * FROM agent_session_messages
                   WHERE session_id=? AND retracted=0 ORDER BY sequence""",
                (session_id,),
            ).fetchall()
            active = [self._message_row(item) for item in messages]
            older = active[:-keep_recent] if len(active) > keep_recent else []
            history = _loads(row["compaction_history_json"], [])
            compacted_ids = {
                message_id
                for item in history
                for message_id in item.get("compacted_message_ids", [])
            }
            new_older = [item for item in older if item["message_id"] not in compacted_ids]
            if new_older:
                transcript = "\n".join(
                    f"[{item['message_id']}] {item['role']}: {item['content']}" for item in new_older
                )
                recent_query = " ".join(str(item.get("content") or "") for item in active[-keep_recent:])
                compiled = ContextPack(
                    blocks=[ContextBlock("conversation_history", transcript, priority=80)],
                    token_budget=1200,
                    query=recent_query,
                ).compile()
                compacted = "\n".join(str(item.get("content") or "") for item in compiled["blocks"])
                prior_lines = str(row["summary"] or "").splitlines()
                summary = "\n".join((prior_lines + ([compacted] if compacted else []))[-40:])
                history.append(
                    {
                        "created_at": _now(),
                        "compacted_message_ids": [item["message_id"] for item in new_older],
                        "ledger": compiled["ledger"],
                    }
                )
                self._update_session_tx(
                    connection,
                    session_id,
                    int(row["version"]),
                    summary=summary,
                    compaction_history_json=_json(history),
                    updated_at=_now(),
                )
            connection.commit()
        if new_older:
            self._project_session(session_id)
        record = self.get(session_id)
        return {"summary": record.get("summary", ""), "recent_messages": active[-keep_recent:]}

    def list_events(self, session_id: str) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM agent_session_events WHERE session_id=? ORDER BY sequence",
                (session_id,),
            ).fetchall()
        return [self._event_row(row) for row in rows]

    def _transition(
        self,
        session_id: str,
        *,
        event: str,
        event_payload: dict[str, Any],
        **updates: Any,
    ) -> dict[str, Any]:
        status = updates.get("status")
        if status and status not in SESSION_STATUSES:
            raise ValueError(f"Invalid session status: {status}")
        updates["updated_at"] = _now()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._session_row_tx(connection, session_id)
            self._update_session_tx(connection, session_id, int(row["version"]), **updates)
            self._append_event_tx(connection, session_id, event, event_payload)
            connection.commit()
        self._project_session(session_id)
        return self.get(session_id)

    def _update(self, session_id: str, **updates: Any) -> dict[str, Any]:
        status = updates.get("status")
        if status and status not in SESSION_STATUSES:
            raise ValueError(f"Invalid session status: {status}")
        normalized = self._normalize_session_updates(updates)
        normalized["updated_at"] = _now()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._session_row_tx(connection, session_id)
            self._update_session_tx(connection, session_id, int(row["version"]), **normalized)
            connection.commit()
        self._project_session(session_id)
        return self.get(session_id)

    def _load_record_tx(self, connection, session_id: str) -> dict[str, Any]:
        row = self._session_row_tx(connection, session_id)
        messages = connection.execute(
            "SELECT * FROM agent_session_messages WHERE session_id=? ORDER BY sequence", (session_id,)
        ).fetchall()
        approvals = connection.execute(
            "SELECT * FROM agent_session_approvals WHERE session_id=? ORDER BY created_at", (session_id,)
        ).fetchall()
        return {
            "session_id": row["session_id"],
            "run_id": row["run_id"],
            "run_ids": _loads(row["run_ids_json"], []),
            "status": row["status"],
            "generation": int(row["generation"]),
            "active_checkpoint_id": row["active_checkpoint_id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "summary": row["summary"] or "",
            "messages": [self._message_row(item) for item in messages],
            "next_message_seq": int(row["next_message_seq"]),
            "approvals": [self._approval_row(item) for item in approvals],
            "metadata": _loads(row["metadata_json"], {}),
            "compaction_history": _loads(row["compaction_history_json"], []),
            "interrupt_reason": row["interrupt_reason"],
            "version": int(row["version"]),
            "storage_backend": "sqlite",
        }

    @staticmethod
    def _normalize_session_updates(updates: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(updates)
        for public, stored in (
            ("run_ids", "run_ids_json"),
            ("metadata", "metadata_json"),
            ("compaction_history", "compaction_history_json"),
        ):
            if public in normalized:
                normalized[stored] = _json(normalized.pop(public))
        return normalized

    def _update_session_tx(self, connection, session_id: str, expected_version: int, **updates: Any) -> None:
        updates = self._normalize_session_updates(updates)
        allowed = {
            "run_id", "run_ids_json", "status", "generation", "active_checkpoint_id", "updated_at",
            "summary", "next_message_seq", "next_event_seq", "metadata_json",
            "compaction_history_json", "interrupt_reason",
        }
        invalid = set(updates) - allowed
        if invalid:
            raise ValueError(f"Unsupported session fields: {sorted(invalid)}")
        if not updates:
            return
        assignments = ", ".join(f"{name}=?" for name in updates)
        values = [updates[name] for name in updates]
        cursor = connection.execute(
            f"UPDATE agent_sessions SET {assignments}, version=version+1 WHERE session_id=? AND version=?",
            (*values, session_id, expected_version),
        )
        if cursor.rowcount != 1:
            raise SessionVersionConflict(
                f"Session {session_id} changed while applying version {expected_version}; reload and retry."
            )

    def _append_event_tx(self, connection, session_id: str, event: str, payload: dict[str, Any]) -> dict[str, Any]:
        row = self._session_row_tx(connection, session_id)
        sequence = int(row["next_event_seq"])
        created_at = _now()
        event_id = f"evt_{uuid.uuid4().hex[:16]}"
        connection.execute(
            """INSERT INTO agent_session_events
               (event_id, session_id, sequence, event_type, payload_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (event_id, session_id, sequence, event, _json(payload), created_at),
        )
        connection.execute(
            "UPDATE agent_sessions SET next_event_seq=? WHERE session_id=?",
            (sequence + 1, session_id),
        )
        return {"event_id": event_id, "ts": created_at, "event": event, "session_id": session_id, **payload}

    @staticmethod
    def _insert_message_tx(
        connection,
        session_id: str,
        sequence: int,
        role: str,
        content: str,
        metadata: dict[str, Any],
        created_at: str,
    ) -> dict[str, Any]:
        message_id = f"turn_{sequence:04d}"
        connection.execute(
            """INSERT INTO agent_session_messages
               (session_id, message_id, sequence, role, content, metadata_json, created_at, retracted)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
            (session_id, message_id, sequence, role, content, _json(metadata), created_at),
        )
        return {
            "message_id": message_id,
            "role": role,
            "content": content,
            "metadata": metadata,
            "created_at": created_at,
            "retracted": False,
        }

    @staticmethod
    def _message_row(row) -> dict[str, Any]:
        payload = {
            "message_id": row["message_id"],
            "role": row["role"],
            "content": row["content"],
            "metadata": _loads(row["metadata_json"], {}),
            "created_at": row["created_at"],
            "retracted": bool(row["retracted"]),
        }
        if row["retracted_at"]:
            payload["retracted_at"] = row["retracted_at"]
        if row["retracted_by_message_id"]:
            payload["retracted_by_message_id"] = row["retracted_by_message_id"]
        return payload

    @staticmethod
    def _approval_row(row) -> dict[str, Any]:
        payload = {
            "approval_id": row["approval_id"],
            "tool_name": row["tool_name"],
            "args_hash": row["args_hash"],
            "reason": row["reason"],
            "status": row["status"],
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
            "max_uses": int(row["max_uses"]),
            "use_count": int(row["use_count"]),
        }
        for key in ("feedback", "decided_at", "last_used_at"):
            if row[key] is not None:
                payload[key] = row[key]
        return payload

    @staticmethod
    def _checkpoint_row(row) -> dict[str, Any]:
        return {
            "checkpoint_id": row["checkpoint_id"],
            "parent_checkpoint_id": row["parent_checkpoint_id"],
            "session_id": row["session_id"],
            "run_id": row["run_id"],
            "generation": int(row["generation"]),
            "reason": row["reason"],
            "created_at": row["created_at"],
            "state": _loads(row["state_json"], {}),
            "runtime": _loads(row["runtime_json"], {}),
            "state_hash": row["state_hash"],
        }

    @staticmethod
    def _event_row(row) -> dict[str, Any]:
        return {
            "event_id": row["event_id"],
            "ts": row["created_at"],
            "event": row["event_type"],
            "session_id": row["session_id"],
            **_loads(row["payload_json"], {}),
        }

    @staticmethod
    def _session_row_tx(connection, session_id: str):
        row = connection.execute("SELECT * FROM agent_sessions WHERE session_id=?", (session_id,)).fetchone()
        if not row:
            raise KeyError(f"Unknown session: {session_id}")
        return row

    def _project_session(self, session_id: str) -> None:
        if not self.mirror_files:
            return
        try:
            record = self.get(session_id)
            events = self.list_events(session_id)
            with self.database.connect() as connection:
                checkpoints = connection.execute(
                    "SELECT * FROM agent_session_checkpoints WHERE session_id=? ORDER BY sequence",
                    (session_id,),
                ).fetchall()
            directory = self._session_dir(session_id)
            directory.mkdir(parents=True, exist_ok=True)
            with self._projection_lock:
                self._atomic_write(self._session_path(session_id), record)
                self._atomic_write_text(
                    directory / "events.jsonl",
                    "".join(_json(item) + "\n" for item in events),
                )
                checkpoint_dir = directory / "checkpoints"
                checkpoint_dir.mkdir(parents=True, exist_ok=True)
                for row in checkpoints:
                    payload = self._checkpoint_row(row)
                    self._atomic_write(checkpoint_dir / f"{payload['checkpoint_id']}.json", payload)
        except Exception:
            # Projections are rebuildable; a projection failure must not roll back
            # the already committed session transaction.
            return

    def _import_legacy_files(self) -> None:
        for path in self.sessions_root.glob("*/session.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                session_id = str(payload["session_id"])
            except (OSError, KeyError, json.JSONDecodeError, TypeError):
                continue
            with self.database.connect() as connection:
                if connection.execute(
                    "SELECT 1 FROM agent_sessions WHERE session_id=?", (session_id,)
                ).fetchone():
                    continue
            self._import_legacy_session(payload, path.parent)

    def _import_legacy_session(self, payload: dict[str, Any], directory: Path) -> None:
        session_id = str(payload["session_id"])
        created_at = str(payload.get("created_at") or _now())
        updated_at = str(payload.get("updated_at") or created_at)
        messages = list(payload.get("messages") or [])
        approvals = list(payload.get("approvals") or [])
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """INSERT OR IGNORE INTO agent_sessions
                   (session_id, run_id, run_ids_json, status, generation, active_checkpoint_id,
                    created_at, updated_at, summary, next_message_seq, next_event_seq, metadata_json,
                    compaction_history_json, interrupt_reason, version)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, 1)""",
                (
                    session_id, payload.get("run_id"), _json(payload.get("run_ids") or []),
                    payload.get("status") or "created", int(payload.get("generation") or 1),
                    payload.get("active_checkpoint_id"), created_at, updated_at,
                    str(payload.get("summary") or ""), int(payload.get("next_message_seq") or 1),
                    _json(payload.get("metadata") or {}), _json(payload.get("compaction_history") or []),
                    payload.get("interrupt_reason"),
                ),
            )
            for message in messages:
                identifier = str(message.get("message_id") or "")
                sequence = int(identifier[5:]) if identifier.startswith("turn_") and identifier[5:].isdigit() else 0
                if sequence <= 0:
                    continue
                connection.execute(
                    """INSERT OR IGNORE INTO agent_session_messages
                       (session_id, message_id, sequence, role, content, metadata_json, created_at,
                        retracted, retracted_at, retracted_by_message_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        session_id, identifier, sequence, message.get("role") or "user",
                        str(message.get("content") or ""), _json(message.get("metadata") or {}),
                        message.get("created_at") or created_at, int(bool(message.get("retracted"))),
                        message.get("retracted_at"), message.get("retracted_by_message_id"),
                    ),
                )
            next_message_seq = max(
                [
                    int(str(item.get("message_id"))[5:])
                    for item in messages
                    if str(item.get("message_id") or "").startswith("turn_")
                    and str(item.get("message_id"))[5:].isdigit()
                ]
                or [0]
            ) + 1
            connection.execute(
                "UPDATE agent_sessions SET next_message_seq=MAX(next_message_seq, ?) WHERE session_id=?",
                (next_message_seq, session_id),
            )
            for approval in approvals:
                if not approval.get("approval_id"):
                    continue
                connection.execute(
                    """INSERT OR IGNORE INTO agent_session_approvals
                       (approval_id, session_id, tool_name, args_hash, reason, status, created_at,
                        expires_at, max_uses, use_count, feedback, decided_at, last_used_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        approval["approval_id"], session_id, approval.get("tool_name") or "unknown",
                        approval.get("args_hash") or "", approval.get("reason") or "legacy import",
                        approval.get("status") or "pending", approval.get("created_at") or created_at,
                        approval.get("expires_at") or created_at, int(approval.get("max_uses") or 1),
                        int(approval.get("use_count") or 0), approval.get("feedback"),
                        approval.get("decided_at"), approval.get("last_used_at"),
                    ),
                )
            connection.commit()

        checkpoint_dir = directory / "checkpoints"
        for checkpoint_path in sorted(checkpoint_dir.glob("cp_*.json")):
            try:
                checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                identifier = str(checkpoint["checkpoint_id"])
                sequence = int(identifier[3:])
            except (OSError, KeyError, ValueError, json.JSONDecodeError):
                continue
            with self.database.connect() as connection:
                connection.execute(
                    """INSERT OR IGNORE INTO agent_session_checkpoints
                       (checkpoint_id, session_id, sequence, parent_checkpoint_id, run_id, generation,
                        reason, state_json, runtime_json, state_hash, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        identifier, session_id, sequence, checkpoint.get("parent_checkpoint_id"),
                        checkpoint.get("run_id"), int(checkpoint.get("generation") or 1),
                        checkpoint.get("reason") or "legacy_import", _json(checkpoint.get("state") or {}),
                        _json(checkpoint.get("runtime") or {}), stable_hash(checkpoint.get("state") or {}),
                        checkpoint.get("created_at") or created_at,
                    ),
                )
                connection.commit()

        event_path = directory / "events.jsonl"
        if event_path.exists():
            for line in event_path.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                with self.database.connect() as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    self._append_event_tx(
                        connection,
                        session_id,
                        str(event.get("event") or "LegacySessionEvent"),
                        {
                            key: value
                            for key, value in event.items()
                            if key not in {"event_id", "ts", "event", "session_id"}
                        },
                    )
                    connection.commit()

    def _session_dir(self, session_id: str) -> Path:
        return self.sessions_root / session_id

    def _session_path(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "session.json"

    @staticmethod
    def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
        SessionManager._atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False, default=str))

    @staticmethod
    def _atomic_write_text(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)

    @staticmethod
    def _input_preview(value: Any) -> str:
        if isinstance(value, str):
            return value[:4000]
        return json.dumps(value, ensure_ascii=False, default=str)[:4000]
