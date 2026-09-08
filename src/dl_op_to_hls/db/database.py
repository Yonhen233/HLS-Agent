"""db layer implementation for database.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


class Database:
    """Coordinate Database within the database boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    def __init__(self, db_path: str | Path, schema_path: str | Path):
        """Implement the internal __init__ helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            db_path: Value supplied by the caller and validated by the surrounding schema.
            schema_path: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        self.db_path = Path(db_path)
        self.schema_path = Path(schema_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _initialize(self) -> None:
        """Implement the internal _initialize helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Returns:
            The structured value promised by the function signature.
        """
        schema_sql = self.schema_path.read_text(encoding="utf-8")
        with sqlite3.connect(self.db_path) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=5000")
            connection.executescript(schema_sql)
            self._migrate(connection)
            connection.commit()

    def _migrate(self, connection: sqlite3.Connection) -> None:
        """Apply additive migrations for workspaces created by older releases."""
        columns = {row[1] for row in connection.execute("PRAGMA table_info(memory_items)").fetchall()}
        additions = {
            "namespace": "TEXT DEFAULT 'global'",
            "user_id": "TEXT",
            "project_id": "TEXT",
            "session_id": "TEXT",
            "expires_at": "TEXT",
            "supersedes_id": "INTEGER",
            "content_hash": "TEXT",
            "access_count": "INTEGER DEFAULT 0",
            "last_accessed_at": "TEXT",
            "feedback_score": "REAL DEFAULT 0.0",
            "deleted_at": "TEXT",
        }
        for name, definition in additions.items():
            if name not in columns:
                connection.execute(f"ALTER TABLE memory_items ADD COLUMN {name} {definition}")
        connection.execute(
            """CREATE TABLE IF NOT EXISTS memory_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_id INTEGER NOT NULL,
                user_id TEXT,
                score REAL NOT NULL,
                reason TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (memory_id) REFERENCES memory_items(id)
            )"""
        )
        connection.execute("CREATE INDEX IF NOT EXISTS idx_memory_namespace ON memory_items(namespace, user_id, project_id, status)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_memory_hash ON memory_items(content_hash, status)")

    def connect(self) -> sqlite3.Connection:
        """Execute connect at the database boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Returns:
            The structured value promised by the function signature.
        """
        connection = sqlite3.connect(self.db_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection
