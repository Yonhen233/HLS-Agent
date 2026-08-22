from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..db.database import Database


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class AgentMessage:
    message_id: str
    message_type: str
    sender: str
    recipient: str
    correlation_id: str
    created_at: str
    payload: dict[str, Any] = field(default_factory=dict)
    parent_message_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AgentMessageBus:
    """Transactional delegation log with a rebuildable JSONL projection."""

    def __init__(
        self,
        path: str | Path,
        hooks=None,
        *,
        database: Database | None = None,
        run_id: str | None = None,
        session_id: str | None = None,
    ):
        self.path = Path(path)
        self.hooks = hooks
        self.run_id = run_id or self.path.parent.name or f"run_{uuid.uuid4().hex[:12]}"
        self.session_id = session_id
        if database is None:
            schema_path = Path(__file__).resolve().parents[1] / "db" / "schema.sql"
            database = Database(self.path.with_suffix(".db"), schema_path)
        self.database = database
        self._projection_lock = threading.Lock()

    def publish(
        self,
        *,
        message_type: str,
        sender: str,
        recipient: str,
        payload: dict[str, Any] | None = None,
        correlation_id: str | None = None,
        parent_message_id: str | None = None,
    ) -> AgentMessage:
        message = AgentMessage(
            message_id=f"msg_{uuid.uuid4().hex[:16]}",
            message_type=message_type,
            sender=sender,
            recipient=recipient,
            correlation_id=correlation_id or f"corr_{uuid.uuid4().hex[:16]}",
            created_at=_now(),
            payload=dict(payload or {}),
            parent_message_id=parent_message_id,
        )
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence "
                "FROM agent_delegation_messages WHERE run_id=?",
                (self.run_id,),
            ).fetchone()
            connection.execute(
                """INSERT INTO agent_delegation_messages
                   (message_id, run_id, session_id, sequence, message_type, sender, recipient,
                    correlation_id, parent_message_id, payload_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    message.message_id,
                    self.run_id,
                    self.session_id,
                    int(row["next_sequence"]),
                    message.message_type,
                    message.sender,
                    message.recipient,
                    message.correlation_id,
                    message.parent_message_id,
                    json.dumps(message.payload, ensure_ascii=False, sort_keys=True, default=str),
                    message.created_at,
                ),
            )
            connection.commit()
        self._project()
        if self.hooks:
            self.hooks.emit(
                "AgentMessageSent",
                {
                    "message_id": message.message_id,
                    "message_type": message.message_type,
                    "sender": sender,
                    "recipient": recipient,
                    "correlation_id": message.correlation_id,
                },
            )
        return message

    def history(
        self,
        *,
        recipient: str | None = None,
        correlation_id: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["run_id=?"]
        parameters: list[Any] = [self.run_id]
        if recipient:
            clauses.append("recipient=?")
            parameters.append(recipient)
        if correlation_id:
            clauses.append("correlation_id=?")
            parameters.append(correlation_id)
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM agent_delegation_messages WHERE "
                + " AND ".join(clauses)
                + " ORDER BY sequence",
                parameters,
            ).fetchall()
        return [self._row(item) for item in rows]

    def _project(self) -> None:
        try:
            messages = self.history()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(f"{self.path.name}.{uuid.uuid4().hex}.tmp")
            content = "".join(
                json.dumps(item, ensure_ascii=False, sort_keys=True, default=str) + "\n"
                for item in messages
            )
            with self._projection_lock:
                temporary.write_text(content, encoding="utf-8")
                temporary.replace(self.path)
        except OSError:
            # The database log is authoritative; a projection failure is recoverable.
            return

    @staticmethod
    def _row(row) -> dict[str, Any]:
        return {
            "message_id": row["message_id"],
            "message_type": row["message_type"],
            "sender": row["sender"],
            "recipient": row["recipient"],
            "correlation_id": row["correlation_id"],
            "created_at": row["created_at"],
            "payload": json.loads(row["payload_json"]),
            "parent_message_id": row["parent_message_id"],
        }
