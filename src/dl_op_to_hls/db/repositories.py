from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from ..core.trace import stable_hash
from .database import Database


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class MetadataRepository:
    def __init__(self, database: Database):
        self.database = database

    def save_experiment(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = _now()
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO experiments (run_id, task_type, name, objective, selected_path, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    task_type=excluded.task_type,
                    name=excluded.name,
                    objective=excluded.objective,
                    selected_path=excluded.selected_path,
                    status=excluded.status,
                    updated_at=excluded.updated_at
                """,
                (
                    payload["run_id"],
                    payload["task_type"],
                    payload["name"],
                    payload.get("objective"),
                    payload.get("selected_path"),
                    payload["status"],
                    now,
                    now,
                ),
            )
            connection.commit()
        return {"status": "success", "run_id": payload["run_id"]}

    def save_operator(self, payload: dict[str, Any]) -> int:
        spec_hash = stable_hash(payload)
        now = _now()
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO operators (op_type, name, input_shape, output_shape, dtype, params_json, spec_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["op_type"],
                    payload["name"],
                    json.dumps(payload.get("input_shape")),
                    json.dumps(payload.get("output_shape")),
                    payload.get("dtype"),
                    json.dumps(payload, ensure_ascii=False),
                    spec_hash,
                    now,
                ),
            )
            row = connection.execute("SELECT id FROM operators WHERE spec_hash = ?", (spec_hash,)).fetchone()
            connection.commit()
            return int(row["id"])

    def save_implementation(self, payload: dict[str, Any]) -> int:
        now = _now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO implementations (run_id, operator_id, source, status, hls_project_dir, hls_file_path, testbench_path, tcl_path, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["run_id"],
                    payload.get("operator_id"),
                    payload["source"],
                    payload["status"],
                    payload.get("hls_project_dir"),
                    payload.get("hls_file_path"),
                    payload.get("testbench_path"),
                    payload.get("tcl_path"),
                    payload.get("notes"),
                    now,
                ),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def save_synthesis_run(self, payload: dict[str, Any]) -> int:
        now = _now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO synthesis_runs (
                    run_id, implementation_id, tool, tool_version, part, clock_period,
                    latency_min, latency_max, ii_min, ii_max, dsp, bram, lut, ff, timing_met, report_path, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["run_id"],
                    payload.get("implementation_id"),
                    payload.get("tool"),
                    payload.get("tool_version"),
                    payload.get("part"),
                    payload.get("clock_period"),
                    payload.get("latency_min"),
                    payload.get("latency_max"),
                    payload.get("ii_min"),
                    payload.get("ii_max"),
                    payload.get("dsp"),
                    payload.get("bram"),
                    payload.get("lut"),
                    payload.get("ff"),
                    payload.get("timing_met"),
                    payload.get("report_path"),
                    now,
                ),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def save_failure(self, payload: dict[str, Any]) -> int:
        now = _now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO failures (run_id, implementation_id, error_type, error_message, log_summary, suggested_fix, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["run_id"],
                    payload.get("implementation_id"),
                    payload.get("error_type"),
                    payload.get("error_message"),
                    payload.get("log_summary"),
                    payload.get("suggested_fix"),
                    now,
                ),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def save_tool_call(self, payload: dict[str, Any]) -> int:
        now = _now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO tool_calls (run_id, tool_name, server, status, input_hash, output_hash, duration_ms, error_type, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["run_id"],
                    payload["tool_name"],
                    payload.get("server"),
                    payload["status"],
                    payload.get("input_hash"),
                    payload.get("output_hash"),
                    payload.get("duration_ms"),
                    payload.get("error_type"),
                    now,
                ),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def insert_rag_chunk(self, payload: dict[str, Any]) -> int:
        now = _now()
        metadata_json = json.dumps(payload.get("metadata", {}), ensure_ascii=False)
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO rag_chunks (source_id, source_type, chunk_text, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    payload["source_id"],
                    payload["source_type"],
                    payload["chunk_text"],
                    metadata_json,
                    now,
                ),
            )
            row_id = int(cursor.lastrowid)
            try:
                connection.execute(
                    "INSERT INTO rag_chunks_fts (rowid, chunk_text, source_id, metadata_json) VALUES (?, ?, ?, ?)",
                    (row_id, payload["chunk_text"], payload["source_id"], metadata_json),
                )
            except Exception:
                pass
            connection.commit()
            return row_id

    def list_runs(self) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT run_id, task_type, name, objective, selected_path, status, created_at, updated_at FROM experiments ORDER BY id DESC"
            ).fetchall()
            return [dict(row) for row in rows]

    def get_rag_chunks(self) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute("SELECT source_id, source_type, chunk_text, metadata_json FROM rag_chunks").fetchall()
            return [dict(row) for row in rows]

    def save_memory_item(self, payload: dict[str, Any]) -> int:
        now = _now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO memory_items (
                    memory_type, scope, key, value_json, source_run_id,
                    importance, confidence, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["memory_type"],
                    payload.get("scope", "run"),
                    payload["key"],
                    json.dumps(payload.get("value", {}), ensure_ascii=False),
                    payload.get("source_run_id"),
                    payload.get("importance", 1),
                    payload.get("confidence", 1.0),
                    payload.get("status", "active"),
                    now,
                    now,
                ),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def list_memory_items(self, memory_types: list[str] | None = None, status: str | None = "active") -> list[dict[str, Any]]:
        query = "SELECT * FROM memory_items"
        clauses = []
        params: list[Any] = []
        if memory_types:
            placeholders = ", ".join("?" for _ in memory_types)
            clauses.append(f"memory_type IN ({placeholders})")
            params.extend(memory_types)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY id DESC"
        with self.database.connect() as connection:
            rows = connection.execute(query, params).fetchall()
            return [dict(row) for row in rows]

    def get_memory_item(self, memory_id: int) -> dict[str, Any] | None:
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM memory_items WHERE id = ?", (memory_id,)).fetchone()
            return dict(row) if row else None

    def save_memory_fact(self, payload: dict[str, Any]) -> int:
        now = _now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO memory_facts (fact, source_run_id, source_artifact, confidence, tags_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["fact"],
                    payload.get("source_run_id"),
                    payload.get("source_artifact"),
                    payload.get("confidence", 1.0),
                    json.dumps(payload.get("tags", []), ensure_ascii=False),
                    now,
                ),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def list_memory_facts(self) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute("SELECT * FROM memory_facts ORDER BY id DESC").fetchall()
            return [dict(row) for row in rows]

    def save_procedural_memory(self, payload: dict[str, Any]) -> int:
        now = _now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO procedural_memories (
                    name, description, steps_json, trigger_conditions_json,
                    success_criteria_json, source_run_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["name"],
                    payload["description"],
                    json.dumps(payload.get("steps", []), ensure_ascii=False),
                    json.dumps(payload.get("trigger_conditions", {}), ensure_ascii=False),
                    json.dumps(payload.get("success_criteria", {}), ensure_ascii=False),
                    payload.get("source_run_id"),
                    now,
                    now,
                ),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def list_skills(self) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute("SELECT * FROM procedural_memories ORDER BY id DESC").fetchall()
            return [dict(row) for row in rows]

    def get_skill(self, skill_id: int) -> dict[str, Any] | None:
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM procedural_memories WHERE id = ?", (skill_id,)).fetchone()
            return dict(row) if row else None

    def list_failures(self) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute("SELECT * FROM failures ORDER BY id DESC").fetchall()
            return [dict(row) for row in rows]
