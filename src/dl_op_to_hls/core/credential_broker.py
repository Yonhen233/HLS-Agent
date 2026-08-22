from __future__ import annotations

import hashlib
import json
import secrets
import time
from datetime import datetime, timezone
from typing import Any, Callable


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class CredentialBroker:
    """Issues opaque, scoped leases; plaintext secrets never enter durable state."""

    def __init__(self, database, secret_provider: Callable[[str], str | None] | None = None):
        self.database = database
        self.secret_provider = secret_provider or (lambda _audience: None)

    def issue(self, run_id: str, audience: str, scopes: list[str], *, ttl_seconds: int = 300, max_uses: int = 1) -> dict[str, Any]:
        if not run_id or not audience or not scopes:
            raise ValueError("run_id, audience and at least one scope are required.")
        token = "cred_" + secrets.token_urlsafe(32)
        token_hash = self._hash(token)
        expires_at = time.time() + max(1, min(int(ttl_seconds), 3600))
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO short_lived_credentials
                   (token_hash, run_id, audience, scopes_json, expires_at, max_uses, uses, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 0, 'active', ?)""",
                (token_hash, run_id, audience, json.dumps(sorted(set(scopes))), expires_at, max(1, int(max_uses)), _now()),
            )
            connection.commit()
        return {"token": token, "expires_at": expires_at, "audience": audience, "scopes": sorted(set(scopes))}

    def consume(self, token: str, *, run_id: str, audience: str, scope: str) -> dict[str, Any]:
        token_hash = self._hash(token)
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM short_lived_credentials WHERE token_hash=?", (token_hash,)).fetchone()
            if not row or row["status"] != "active":
                connection.rollback()
                raise PermissionError("Credential is unknown, revoked, or exhausted.")
            if row["run_id"] != run_id or row["audience"] != audience:
                connection.rollback()
                raise PermissionError("Credential audience or run binding does not match.")
            if float(row["expires_at"]) <= time.time():
                connection.execute("UPDATE short_lived_credentials SET status='expired' WHERE token_hash=?", (token_hash,))
                connection.commit()
                raise PermissionError("Credential expired.")
            scopes = set(json.loads(row["scopes_json"]))
            if scope not in scopes:
                connection.rollback()
                raise PermissionError("Credential does not grant the requested scope.")
            uses = int(row["uses"]) + 1
            status = "exhausted" if uses >= int(row["max_uses"]) else "active"
            connection.execute(
                "UPDATE short_lived_credentials SET uses=?, status=?, last_used_at=? WHERE token_hash=? AND uses=?",
                (uses, status, _now(), token_hash, row["uses"]),
            )
            connection.commit()
        secret = self.secret_provider(audience)
        return {"secret": secret, "audience": audience, "scope": scope, "remaining_uses": max(0, int(row["max_uses"]) - uses)}

    def revoke(self, token: str) -> bool:
        with self.database.connect() as connection:
            cursor = connection.execute(
                "UPDATE short_lived_credentials SET status='revoked' WHERE token_hash=? AND status='active'",
                (self._hash(token),),
            )
            connection.commit()
        return cursor.rowcount == 1

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()
