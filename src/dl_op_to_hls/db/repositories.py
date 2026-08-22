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
            existing = connection.execute(
                "SELECT id FROM rag_chunks WHERE source_id = ? AND chunk_text = ? LIMIT 1",
                (payload["source_id"], payload["chunk_text"]),
            ).fetchone()
            if existing:
                connection.execute(
                    "UPDATE rag_chunks SET source_type = ?, metadata_json = ? WHERE id = ?",
                    (payload["source_type"], metadata_json, int(existing["id"])),
                )
                connection.commit()
                return int(existing["id"])
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

    def insert_rag_chunks(self, payloads: list[dict[str, Any]]) -> list[int]:
        if not payloads:
            return []
        now = _now()
        row_ids: list[int] = []
        with self.database.connect() as connection:
            for payload in payloads:
                metadata_json = json.dumps(payload.get("metadata", {}), ensure_ascii=False)
                existing = connection.execute(
                    "SELECT id FROM rag_chunks WHERE source_id = ? AND chunk_text = ? LIMIT 1",
                    (payload["source_id"], payload["chunk_text"]),
                ).fetchone()
                if existing:
                    row_id = int(existing["id"])
                    connection.execute(
                        "UPDATE rag_chunks SET source_type = ?, metadata_json = ? WHERE id = ?",
                        (payload["source_type"], metadata_json, row_id),
                    )
                else:
                    cursor = connection.execute(
                        """
                        INSERT INTO rag_chunks (source_id, source_type, chunk_text, metadata_json, created_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (payload["source_id"], payload["source_type"], payload["chunk_text"], metadata_json, now),
                    )
                    row_id = int(cursor.lastrowid)
                    try:
                        connection.execute(
                            "INSERT INTO rag_chunks_fts (rowid, chunk_text, source_id, metadata_json) VALUES (?, ?, ?, ?)",
                            (row_id, payload["chunk_text"], payload["source_id"], metadata_json),
                        )
                    except Exception:
                        pass
                row_ids.append(row_id)
            connection.commit()
        return row_ids

    def list_runs(self) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT run_id, task_type, name, objective, selected_path, status, created_at, updated_at FROM experiments ORDER BY id DESC"
            ).fetchall()
            return [dict(row) for row in rows]

    def get_rag_chunks(self) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute("SELECT id, source_id, source_type, chunk_text, metadata_json, created_at FROM rag_chunks").fetchall()
            return [dict(row) for row in rows]

    def search_rag_fts(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        if not query.strip():
            return []
        with self.database.connect() as connection:
            try:
                rows = connection.execute(
                    """
                    SELECT r.id, r.source_id, r.source_type, r.chunk_text, r.metadata_json,
                           r.created_at, bm25(rag_chunks_fts) AS fts_rank
                    FROM rag_chunks_fts
                    JOIN rag_chunks AS r ON r.id = rag_chunks_fts.rowid
                    WHERE rag_chunks_fts MATCH ?
                    ORDER BY fts_rank ASC
                    LIMIT ?
                    """,
                    (query, max(1, int(limit))),
                ).fetchall()
                return [dict(row) for row in rows]
            except Exception:
                return []

    def get_rag_embeddings(self, chunk_ids: list[int], model_id: str) -> dict[int, dict[str, Any]]:
        if not chunk_ids:
            return {}
        placeholders = ",".join("?" for _ in chunk_ids)
        with self.database.connect() as connection:
            rows = connection.execute(
                f"""SELECT chunk_id, content_hash, dimensions, embedding_json
                    FROM rag_embeddings
                    WHERE model_id = ? AND chunk_id IN ({placeholders})""",
                (model_id, *chunk_ids),
            ).fetchall()
        return {
            int(row["chunk_id"]): {
                "content_hash": row["content_hash"],
                "dimensions": int(row["dimensions"]),
                "embedding": json.loads(row["embedding_json"]),
            }
            for row in rows
        }

    def upsert_rag_embeddings(self, records: list[dict[str, Any]]) -> int:
        if not records:
            return 0
        now = _now()
        with self.database.connect() as connection:
            connection.executemany(
                """INSERT INTO rag_embeddings (
                       chunk_id, model_id, content_hash, dimensions, embedding_json, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(chunk_id, model_id) DO UPDATE SET
                       content_hash = excluded.content_hash,
                       dimensions = excluded.dimensions,
                       embedding_json = excluded.embedding_json,
                       updated_at = excluded.updated_at""",
                [
                    (
                        int(item["chunk_id"]),
                        str(item["model_id"]),
                        str(item["content_hash"]),
                        len(item["embedding"]),
                        json.dumps(item["embedding"]),
                        now,
                    )
                    for item in records
                ],
            )
            connection.commit()
        return len(records)

    def get_unembedded_rag_chunks(self, model_id: str, limit: int = 256) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT r.id, r.source_id, r.source_type, r.chunk_text, r.metadata_json, r.created_at
                   FROM rag_chunks AS r
                   LEFT JOIN rag_embeddings AS e
                     ON e.chunk_id = r.id AND e.model_id = ?
                   WHERE e.chunk_id IS NULL
                   ORDER BY r.id ASC
                   LIMIT ?""",
                (model_id, max(1, int(limit))),
            ).fetchall()
        return [dict(row) for row in rows]

    def rag_embedding_coverage(self, model_id: str) -> dict[str, Any]:
        with self.database.connect() as connection:
            total = int(connection.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0])
            embedded = int(
                connection.execute(
                    "SELECT COUNT(*) FROM rag_embeddings WHERE model_id = ?",
                    (model_id,),
                ).fetchone()[0]
            )
        return {
            "model_id": model_id,
            "total_chunks": total,
            "embedded_chunks": embedded,
            "missing_chunks": max(0, total - embedded),
            "coverage": round(embedded / max(total, 1), 4),
        }

    def list_rag_embeddings(self, model_id: str) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT chunk_id, content_hash, dimensions, embedding_json, updated_at
                   FROM rag_embeddings WHERE model_id=? ORDER BY chunk_id""",
                (model_id,),
            ).fetchall()
        return [
            {
                "chunk_id": int(row["chunk_id"]),
                "content_hash": row["content_hash"],
                "dimensions": int(row["dimensions"]),
                "embedding": json.loads(row["embedding_json"]),
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def save_memory_item(self, payload: dict[str, Any]) -> int:
        now = _now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO memory_items (
                    memory_type, scope, key, value_json, source_run_id,
                    importance, confidence, status, namespace, user_id,
                    project_id, session_id, expires_at, supersedes_id, content_hash,
                    access_count, feedback_score, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    payload.get("namespace", "global"),
                    payload.get("user_id"),
                    payload.get("project_id"),
                    payload.get("session_id"),
                    payload.get("expires_at"),
                    payload.get("supersedes_id"),
                    payload.get("content_hash"),
                    payload.get("access_count", 0),
                    payload.get("feedback_score", 0.0),
                    now,
                    now,
                ),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def list_memory_items(
        self,
        memory_types: list[str] | None = None,
        status: str | None = "active",
        *,
        namespace: str | None = None,
        user_id: str | None = None,
        project_id: str | None = None,
        include_shared: bool = True,
    ) -> list[dict[str, Any]]:
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
        clauses.append("(expires_at IS NULL OR expires_at > ?)")
        params.append(_now())
        if namespace:
            if include_shared and namespace != "global":
                clauses.append("namespace IN (?, 'global')")
                params.append(namespace)
            else:
                clauses.append("namespace = ?")
                params.append(namespace)
        if user_id:
            clauses.append("(user_id IS NULL OR user_id = ?)")
            params.append(user_id)
        if project_id:
            clauses.append("(project_id IS NULL OR project_id = ?)")
            params.append(project_id)
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

    def find_active_memory_by_hash(
        self,
        content_hash: str,
        *,
        namespace: str,
        user_id: str | None,
        project_id: str | None,
    ) -> dict[str, Any] | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """SELECT * FROM memory_items
                   WHERE content_hash = ? AND namespace = ?
                     AND COALESCE(user_id, '') = COALESCE(?, '')
                     AND COALESCE(project_id, '') = COALESCE(?, '')
                     AND status = 'active'
                   ORDER BY id DESC LIMIT 1""",
                (content_hash, namespace, user_id, project_id),
            ).fetchone()
            return dict(row) if row else None

    def touch_memory_items(self, memory_ids: list[int]) -> None:
        if not memory_ids:
            return
        placeholders = ", ".join("?" for _ in memory_ids)
        with self.database.connect() as connection:
            connection.execute(
                f"UPDATE memory_items SET access_count = access_count + 1, last_accessed_at = ? WHERE id IN ({placeholders})",
                [_now(), *memory_ids],
            )
            connection.commit()

    def add_memory_feedback(self, memory_id: int, score: float, reason: str = "", user_id: str | None = None) -> dict[str, Any]:
        bounded = max(-1.0, min(1.0, float(score)))
        now = _now()
        with self.database.connect() as connection:
            connection.execute(
                "INSERT INTO memory_feedback (memory_id, user_id, score, reason, created_at) VALUES (?, ?, ?, ?, ?)",
                (memory_id, user_id, bounded, reason, now),
            )
            aggregate = connection.execute(
                "SELECT AVG(score) FROM memory_feedback WHERE memory_id = ?", (memory_id,)
            ).fetchone()[0]
            connection.execute(
                "UPDATE memory_items SET feedback_score = ?, updated_at = ? WHERE id = ?",
                (aggregate, now, memory_id),
            )
            connection.commit()
        return {"memory_id": memory_id, "feedback_score": aggregate}

    def forget_memory(self, memory_id: int, *, reason: str = "user_request") -> bool:
        now = _now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                "UPDATE memory_items SET status = 'deleted', deleted_at = ?, updated_at = ?, value_json = ? WHERE id = ? AND status != 'deleted'",
                (now, now, json.dumps({"forgotten": True, "reason": reason}), memory_id),
            )
            connection.commit()
            return cursor.rowcount > 0

    def supersede_memory(self, memory_id: int, superseded_by: int) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE memory_items SET status = 'superseded', updated_at = ? WHERE id = ?",
                (_now(), memory_id),
            )
            connection.execute(
                "UPDATE memory_items SET supersedes_id = ?, updated_at = ? WHERE id = ?",
                (memory_id, _now(), superseded_by),
            )
            connection.commit()

    def cleanup_expired_memories(self) -> int:
        now = _now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                "UPDATE memory_items SET status = 'expired', updated_at = ? WHERE status = 'active' AND expires_at IS NOT NULL AND expires_at <= ?",
                (now, now),
            )
            connection.commit()
            return int(cursor.rowcount)

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
