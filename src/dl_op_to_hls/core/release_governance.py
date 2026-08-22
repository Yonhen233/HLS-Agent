from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class CanaryGates:
    max_success_drop: float = 0.02
    max_false_success_rate: float = 0.01
    max_rag_pollution_rate: float = 0.05
    max_token_increase: float = 0.15
    max_p95_increase: float = 0.20
    min_sample_size: int = 20


class ReleaseManager:
    """Immutable model/prompt/skill releases with deterministic canary routing."""

    COMPONENTS = {"model", "prompt", "skill"}

    def __init__(self, database):
        self.database = database

    def register(self, component_type: str, name: str, version: str, config: dict[str, Any]) -> dict[str, Any]:
        self._validate(component_type, name, version)
        config_json = json.dumps(config, sort_keys=True, ensure_ascii=False)
        now = _now()
        with self.database.connect() as connection:
            existing = connection.execute(
                "SELECT config_json, status FROM agent_releases WHERE component_type=? AND component_name=? AND version=?",
                (component_type, name, version),
            ).fetchone()
            if existing and existing["config_json"] != config_json:
                raise ValueError("Release versions are immutable; register a new version.")
            connection.execute(
                """INSERT OR IGNORE INTO agent_releases
                   (component_type, component_name, version, status, config_json, created_at, updated_at)
                   VALUES (?, ?, ?, 'registered', ?, ?, ?)""",
                (component_type, name, version, config_json, now, now),
            )
            connection.commit()
        return {"component_type": component_type, "name": name, "version": version, "config": config}

    def set_baseline(self, component_type: str, name: str, version: str) -> dict[str, Any]:
        self._require_release(component_type, name, version)
        now = _now()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE agent_releases SET status='registered', updated_at=? WHERE component_type=? AND component_name=? AND status='baseline'",
                (now, component_type, name),
            )
            connection.execute(
                "UPDATE agent_releases SET status='baseline', updated_at=? WHERE component_type=? AND component_name=? AND version=?",
                (now, component_type, name, version),
            )
            connection.execute(
                """INSERT INTO release_routes
                   (component_type, component_name, baseline_version, candidate_version, canary_percent, status, updated_at)
                   VALUES (?, ?, ?, NULL, 0, 'stable', ?)
                   ON CONFLICT(component_type, component_name) DO UPDATE SET
                     baseline_version=excluded.baseline_version, candidate_version=NULL,
                     canary_percent=0, status='stable', updated_at=excluded.updated_at""",
                (component_type, name, version, now),
            )
            connection.commit()
        return self.status(component_type, name)

    def start_canary(self, component_type: str, name: str, candidate_version: str, percent: float = 5.0) -> dict[str, Any]:
        self._require_release(component_type, name, candidate_version)
        percent = max(0.0, min(100.0, float(percent)))
        with self.database.connect() as connection:
            route = connection.execute(
                "SELECT * FROM release_routes WHERE component_type=? AND component_name=?",
                (component_type, name),
            ).fetchone()
            if not route:
                raise ValueError("Set a baseline before starting a canary.")
            if route["baseline_version"] == candidate_version:
                raise ValueError("Candidate must differ from the baseline.")
            connection.execute(
                "UPDATE release_routes SET candidate_version=?, canary_percent=?, status='canary', updated_at=? WHERE component_type=? AND component_name=?",
                (candidate_version, percent, _now(), component_type, name),
            )
            connection.execute(
                "UPDATE agent_releases SET status='canary', updated_at=? WHERE component_type=? AND component_name=? AND version=?",
                (_now(), component_type, name, candidate_version),
            )
            connection.commit()
        return self.status(component_type, name)

    def resolve(self, component_type: str, name: str, routing_key: str) -> dict[str, Any]:
        route = self.status(component_type, name)
        version = route["baseline_version"]
        cohort = int(hashlib.sha256(routing_key.encode("utf-8")).hexdigest()[:8], 16) % 10000 / 100
        if route["status"] == "canary" and route.get("candidate_version") and cohort < float(route["canary_percent"]):
            version = route["candidate_version"]
        with self.database.connect() as connection:
            release = connection.execute(
                "SELECT config_json FROM agent_releases WHERE component_type=? AND component_name=? AND version=?",
                (component_type, name, version),
            ).fetchone()
        return {
            **route,
            "selected_version": version,
            "selected_config": json.loads(release["config_json"]) if release else {},
            "cohort": cohort,
        }

    def resolve_bundle(self, routing_key: str) -> dict[str, Any]:
        with self.database.connect() as connection:
            rows = connection.execute("SELECT component_type, component_name FROM release_routes ORDER BY component_type, component_name").fetchall()
        return {
            f"{row['component_type']}:{row['component_name']}": self.resolve(row["component_type"], row["component_name"], routing_key)
            for row in rows
        }

    def evaluate(
        self,
        component_type: str,
        name: str,
        baseline_metrics: dict[str, float],
        candidate_metrics: dict[str, float],
        gates: CanaryGates | None = None,
    ) -> dict[str, Any]:
        gates = gates or CanaryGates()
        route = self.status(component_type, name)
        candidate = route.get("candidate_version")
        if route["status"] != "canary" or not candidate:
            raise ValueError("No active canary to evaluate.")
        reasons: list[str] = []
        baseline_samples = int(baseline_metrics.get("sample_count", 0))
        candidate_samples = int(candidate_metrics.get("sample_count", 0))
        if baseline_samples < gates.min_sample_size or candidate_samples < gates.min_sample_size:
            reasons.append("insufficient_sample_size")
        base_success = float(baseline_metrics.get("task_success_rate", 0))
        cand_success = float(candidate_metrics.get("task_success_rate", 0))
        if cand_success < base_success - gates.max_success_drop:
            reasons.append("task_success_rate_regressed")
        if float(candidate_metrics.get("false_success_rate", 0)) > gates.max_false_success_rate:
            reasons.append("false_success_rate_exceeded")
        if float(candidate_metrics.get("rag_pollution_rate", 0)) > gates.max_rag_pollution_rate:
            reasons.append("rag_pollution_rate_exceeded")
        for metric, limit, reason in (
            ("tokens_per_success", gates.max_token_increase, "token_cost_regressed"),
            ("p95_runtime_seconds", gates.max_p95_increase, "p95_latency_regressed"),
        ):
            baseline = float(baseline_metrics.get(metric, 0))
            candidate_value = float(candidate_metrics.get(metric, 0))
            if baseline > 0 and candidate_value > baseline * (1 + limit):
                reasons.append(reason)
        decision = "rollback" if reasons else "promote"
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """INSERT INTO release_evaluations
                   (component_type, component_name, baseline_version, candidate_version,
                    baseline_metrics_json, candidate_metrics_json, decision, reasons_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (component_type, name, route["baseline_version"], candidate,
                 json.dumps(baseline_metrics, sort_keys=True), json.dumps(candidate_metrics, sort_keys=True),
                 decision, json.dumps(reasons), _now()),
            )
            if decision == "promote":
                connection.execute(
                    "UPDATE agent_releases SET status='registered', updated_at=? WHERE component_type=? AND component_name=? AND version=?",
                    (_now(), component_type, name, route["baseline_version"]),
                )
                connection.execute(
                    "UPDATE agent_releases SET status='baseline', updated_at=? WHERE component_type=? AND component_name=? AND version=?",
                    (_now(), component_type, name, candidate),
                )
                connection.execute(
                    "UPDATE release_routes SET baseline_version=?, candidate_version=NULL, canary_percent=0, status='stable', updated_at=? WHERE component_type=? AND component_name=?",
                    (candidate, _now(), component_type, name),
                )
            else:
                connection.execute(
                    "UPDATE agent_releases SET status='rolled_back', updated_at=? WHERE component_type=? AND component_name=? AND version=?",
                    (_now(), component_type, name, candidate),
                )
                connection.execute(
                    "UPDATE release_routes SET candidate_version=NULL, canary_percent=0, status='stable', updated_at=? WHERE component_type=? AND component_name=?",
                    (_now(), component_type, name),
                )
            connection.commit()
        return {"decision": decision, "reasons": reasons, "route": self.status(component_type, name)}

    def status(self, component_type: str, name: str) -> dict[str, Any]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM release_routes WHERE component_type=? AND component_name=?",
                (component_type, name),
            ).fetchone()
        if not row:
            raise KeyError(f"{component_type}:{name}")
        return dict(row)

    def _require_release(self, component_type: str, name: str, version: str) -> None:
        self._validate(component_type, name, version)
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM agent_releases WHERE component_type=? AND component_name=? AND version=?",
                (component_type, name, version),
            ).fetchone()
        if not row:
            raise KeyError(f"Unknown release {component_type}:{name}@{version}")

    @classmethod
    def _validate(cls, component_type: str, name: str, version: str) -> None:
        if component_type not in cls.COMPONENTS or not name.strip() or not version.strip():
            raise ValueError("Invalid release identity.")
