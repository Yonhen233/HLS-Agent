from __future__ import annotations

import json
import gc
import re
import statistics
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .agent_quality_benchmark import aggregate_metrics, collect_run_metrics, evaluate_rag_cases
from ..core.durable_queue import DurableJobQueue
from ..core.hooks import HookManager
from ..core.sessions import SessionManager
from ..core.tool_registry import ToolRegistry, ToolSpec
from ..db.database import Database
from ..rag.retriever import RagRetriever


OPEN_TASK_SUITE = Path("benchmarks/agent_interview_open_tasks.json")
RAG_CORPUS = Path("benchmarks/agent_interview_rag_corpus.json")


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * quantile)))
    return round(float(ordered[index]), 4)


def _rate(numerator: int, denominator: int) -> dict[str, Any]:
    if denominator <= 0:
        return {"numerator": numerator, "denominator": denominator, "rate": None, "statistically_usable": False}
    estimate = numerator / denominator
    z = 1.959963984540054
    adjusted = 1 + z * z / denominator
    center = (estimate + z * z / (2 * denominator)) / adjusted
    margin = z * ((estimate * (1 - estimate) + z * z / (4 * denominator)) / denominator) ** 0.5 / adjusted
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": round(estimate, 4),
        "wilson_95": [round(max(0.0, center - margin), 4), round(min(1.0, center + margin), 4)],
        "statistically_usable": denominator >= 20,
    }


def _llm_usage(events: list[dict[str, Any]]) -> dict[str, int]:
    usage = [item for item in events if item.get("event") == "LLMUsageRecorded"]
    input_tokens = sum(int(item.get("input_tokens") or 0) for item in usage)
    output_tokens = sum(int(item.get("output_tokens") or 0) for item in usage)
    return {
        "calls": len(usage),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }


def _trace(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if not path.exists():
        return events
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def _error_payload(exc: Exception) -> dict[str, Any]:
    error = getattr(exc, "error", None)
    if error is not None and hasattr(error, "to_dict"):
        return error.to_dict()
    return {"error_type": type(exc).__name__, "message": str(exc), "recoverable": False}


def _matches_expected_task(task: dict[str, Any], case: dict[str, Any]) -> bool:
    checks = [
        not case.get("expected_task_type") or task.get("task_type") == case["expected_task_type"],
        not case.get("expected_op_type") or task.get("op_type") == case["expected_op_type"],
        not case.get("expected_objective") or task.get("objective") == case["expected_objective"],
    ]
    return all(checks)


def run_open_task_planning(workspace_root: str | Path, suite_path: str | Path = OPEN_TASK_SUITE) -> dict[str, Any]:
    """Run natural-language interpretation and guarded planning without HLS tool execution."""
    from ..llm.task_interpreter import LLMTaskInterpreter
    from ..main_agent.agent import MainAgent
    from ..main_agent.llm_runtime import LLMFirstRuntime

    root = Path(workspace_root).resolve()
    suite = _read_json(root / suite_path, {})
    results: list[dict[str, Any]] = []
    started = time.perf_counter()
    for case in suite.get("cases", []):
        events: list[dict[str, Any]] = []
        hooks = HookManager()
        hooks.register("*", lambda payload, sink=events: sink.append(dict(payload)))
        agent = MainAgent(root, console=False)
        run_id = None
        case_started = time.perf_counter()
        try:
            agent.llm_client.set_context({"run_id": case["id"], "hooks": hooks})
            interpreted = LLMTaskInterpreter().interpret(str(case["prompt"]), agent.llm_client)
            session = agent.session_manager.create(
                str(case["prompt"]),
                user_id="agent-interview-benchmark",
                project_id="fixed-open-task-suite",
            )
            runtime = LLMFirstRuntime(agent, llm_client=agent.llm_client, session_id=session["session_id"])
            state = runtime.initialize(interpreted["task"])
            run_id = state.run_id
            state = runtime.build_skill_context(state)
            state = runtime.plan_todos(state)
            runtime.context["artifact_manager"].write_json("state.json", state.to_dict(), "state")
            run_events = _trace(runtime.context["run_dir"] / "trace.jsonl")
            events.extend(run_events)
            expected_outcome = str(case.get("expected_outcome") or "planned")
            task_correct = _matches_expected_task(state.task, case)
            skill_correct = not case.get("allowed_skills") or state.selected_skill in case["allowed_skills"]
            unsupported_plan = state.selected_skill == "unsupported_boundary_flow" or any(
                todo.assigned_tool == "report.write_unsupported" for todo in state.todos
            )
            outcome_correct = expected_outcome != "structured_rejection" and (
                expected_outcome != "structured_rejection_or_unsupported_plan" or unsupported_plan
            )
            passed = bool(task_correct and skill_correct and outcome_correct and state.todos)
            result = {
                "case_id": case["id"],
                "passed": passed,
                "outcome": "planned",
                "task_correct": task_correct,
                "skill_correct": skill_correct,
                "selected_skill": state.selected_skill,
                "todo_count": len(state.todos),
                "run_id": run_id,
                "error": None,
            }
        except Exception as exc:
            error = _error_payload(exc)
            allowed = set(case.get("allowed_error_types") or ["UnsupportedOperatorError", "InvalidTaskError"])
            expected_outcome = str(case.get("expected_outcome") or "planned")
            rejected_as_expected = expected_outcome in {"structured_rejection", "structured_rejection_or_unsupported_plan"}
            error_allowed = not allowed or error.get("error_type") in allowed
            result = {
                "case_id": case["id"],
                "passed": bool(rejected_as_expected and error_allowed),
                "outcome": "structured_rejection",
                "task_correct": None,
                "skill_correct": None,
                "selected_skill": None,
                "todo_count": 0,
                "run_id": run_id,
                "error": error,
            }
        finally:
            agent.close()
        result["runtime_s"] = round(time.perf_counter() - case_started, 3)
        result["llm_usage"] = _llm_usage(events)
        results.append(result)
    passed = sum(bool(item["passed"]) for item in results)
    total_tokens = sum(item["llm_usage"]["total_tokens"] for item in results)
    return {
        "schema_version": "1.0",
        "evidence_class": "real_llm_planning",
        "selection_policy": suite.get("selection_policy"),
        "model": "deepseek-v4-pro",
        "rate": _rate(passed, len(results)),
        "runtime_s": round(time.perf_counter() - started, 3),
        "llm_calls": sum(item["llm_usage"]["calls"] for item in results),
        "total_tokens": total_tokens,
        "tokens_per_pass": round(total_tokens / max(passed, 1), 2),
        "results": results,
    }


class _CorpusRepository:
    def __init__(self, documents: list[dict[str, Any]]):
        self.documents = documents

    def get_rag_chunks(self) -> list[dict[str, Any]]:
        return [
            {
                "id": index,
                "source_id": item["source_id"],
                "source_type": (item.get("metadata") or {}).get("source_type", "text"),
                "chunk_text": item["text"],
                "metadata_json": json.dumps(item.get("metadata") or {}),
                "created_at": "2026-08-28T00:00:00+00:00",
            }
            for index, item in enumerate(self.documents, start=1)
        ]

    def search_rag_fts(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        terms = set(re.findall(r"[a-z0-9_]+", query.lower()))
        rows = self.get_rag_chunks()
        return sorted(
            rows,
            key=lambda row: len(terms.intersection(set(re.findall(r"[a-z0-9_]+", row["chunk_text"].lower())))),
            reverse=True,
        )[:limit]

    @staticmethod
    def list_memory_facts() -> list[dict[str, Any]]:
        return []

    @staticmethod
    def list_skills() -> list[dict[str, Any]]:
        return []


def _naive_retrieve(documents: list[dict[str, Any]], query: str, top_k: int) -> list[dict[str, Any]]:
    tokens = re.findall(r"[a-z0-9_]+", query.lower())
    ranked = sorted(
        documents,
        key=lambda item: sum(item["text"].lower().count(token) for token in tokens),
        reverse=True,
    )
    return [{"source_id": item["source_id"], "text": item["text"], "metadata": item.get("metadata", {})} for item in ranked[:top_k]]


def run_rag_ablation(workspace_root: str | Path, corpus_path: str | Path = RAG_CORPUS) -> dict[str, Any]:
    root = Path(workspace_root).resolve()
    payload = _read_json(root / corpus_path, {})
    documents = list(payload.get("documents", []))
    cases = list(payload.get("queries", []))
    retriever = RagRetriever(_CorpusRepository(documents))
    no_memory = evaluate_rag_cases(cases, lambda query, top_k: [], default_top_k=3)
    naive = evaluate_rag_cases(cases, lambda query, top_k: _naive_retrieve(documents, query, top_k), default_top_k=3)
    domains = {str(item["query"]): item.get("domain") for item in cases}
    production = evaluate_rag_cases(
        cases,
        lambda query, top_k: retriever.retrieve(query, top_k=top_k, domain=domains.get(str(query))),
        default_top_k=3,
    )
    return {
        "schema_version": "1.0",
        "evidence_class": "controlled_fixed_corpus",
        "corpus_size": len(documents),
        "query_count": len(cases),
        "no_memory": no_memory,
        "naive_lexical": naive,
        "production_retriever": production,
        "observed_delta_vs_naive": {
            "mrr": round((production["macro_mrr"] or 0) - (naive["macro_mrr"] or 0), 4),
            "ndcg_at_k": round((production["macro_ndcg_at_k"] or 0) - (naive["macro_ndcg_at_k"] or 0), 4),
            "pollution_at_k": round((production["macro_pollution_at_k"] or 0) - (naive["macro_pollution_at_k"] or 0), 4),
        },
    }


def run_guard_ablation(workspace_root: str | Path) -> dict[str, Any]:
    payload = _read_json(Path(workspace_root) / "benchmarks" / "operator_bad_case_results.json", {})
    cases = [item for item in payload.get("cases", []) if item.get("failure_stage") == "candidate_guard"]
    blocked = sum(item.get("final_outcome") == "rejected" for item in cases)
    return {
        "evidence_class": "safe_counterfactual_no_unsafe_execution",
        "case_count": len(cases),
        "guard_enabled": {
            "unsafe_candidate_acceptance": len(cases) - blocked,
            "unsafe_candidate_acceptance_rate": round((len(cases) - blocked) / max(len(cases), 1), 4),
        },
        "schema_only_ablation": {
            "unsafe_candidate_acceptance": len(cases),
            "unsafe_candidate_acceptance_rate": 1.0 if cases else None,
            "note": "Counterfactual assumes syntactically valid candidate payloads pass when semantic sandbox and contract guards are removed.",
        },
        "prevented_unsafe_acceptances": blocked,
    }


def _frozen_run_ids(root: Path) -> list[str]:
    release = _read_json(root / "runs" / "benchmarks" / "operator_release.json", {})
    ids = [item.get("run_id") for item in (release.get("llm_pass3") or {}).get("runs", [])]
    fair = (release.get("template_vs_llm") or {}).get("results", [])
    for item in fair:
        ids.extend([(item.get("template") or {}).get("run_id"), (item.get("llm") or {}).get("run_id")])
    selected = {str(item) for item in ids if item}
    latest_by_path: dict[str, tuple[float, str]] = {}
    for state_path in (root / "runs").glob("*/state.json"):
        state = _read_json(state_path, {})
        path = str(state.get("selected_path") or "")
        if path not in {"hls4ml_path", "fallback_template_path", "existing_hls_project_path", "unsupported_path"}:
            continue
        previous = latest_by_path.get(path)
        if previous is None or state_path.stat().st_mtime > previous[0]:
            latest_by_path[path] = (state_path.stat().st_mtime, state_path.parent.name)
    selected.update(item[1] for item in latest_by_path.values())
    return sorted(selected)


def run_context_ablation(run_dirs: list[Path]) -> dict[str, Any]:
    full_state_bytes: list[float] = []
    returned_bytes: list[float] = []
    raw_bytes: list[float] = []
    compressed_bytes: list[float] = []
    for run_dir in run_dirs:
        state = _read_json(run_dir / "state.json", {})
        state_size = len(json.dumps(state, ensure_ascii=False).encode("utf-8"))
        for todo in state.get("todos", []):
            result = todo.get("specialist_result") if isinstance(todo, dict) else None
            if not isinstance(result, dict) or not result:
                continue
            full_state_bytes.append(float(state_size))
            returned_size = len(json.dumps(result, ensure_ascii=False).encode("utf-8"))
            returned_bytes.append(float(returned_size))
            usage = result.get("context_usage") or {}
            if int(usage.get("raw_bytes_read") or 0) > 0:
                raw_bytes.append(float(usage["raw_bytes_read"]))
                compressed_bytes.append(float(usage.get("summary_bytes_returned") or returned_size))
    reduction = [1.0 - returned / max(full, 1.0) for full, returned in zip(full_state_bytes, returned_bytes)]
    artifact_reduction = [1.0 - summary / max(raw, 1.0) for raw, summary in zip(raw_bytes, compressed_bytes)]
    return {
        "evidence_class": "posthoc_current_run_artifacts",
        "specialist_result_count": len(returned_bytes),
        "full_state_exposure_baseline_bytes_p50": _percentile(full_state_bytes, 0.5),
        "specialist_result_bytes_p50": _percentile(returned_bytes, 0.5),
        "main_agent_context_reduction_p50": _percentile(reduction, 0.5),
        "main_agent_context_reduction_p95": _percentile(reduction, 0.95),
        "raw_artifact_read_count": len(raw_bytes),
        "raw_to_summary_reduction_p50": _percentile(artifact_reduction, 0.5),
    }


def run_recovery_idempotency_probes(workspace_root: str | Path) -> dict[str, Any]:
    root = Path(workspace_root).resolve()
    probes: list[dict[str, Any]] = []
    schema = root / "src" / "dl_op_to_hls" / "db" / "schema.sql"
    with tempfile.TemporaryDirectory(prefix="agent_interview_", dir=root / "runs" / "benchmarks") as temp:
        temp_root = Path(temp)
        database = Database(temp_root / "probe.db", schema)
        queue = DurableJobQueue(database)
        first = queue.enqueue({"task": "probe"}, idempotency_key="same")
        second = queue.enqueue({"task": "changed"}, idempotency_key="same")
        probes.append({"name": "queue_enqueue_dedup", "passed": first["job_id"] == second["job_id"] and second["deduplicated"]})
        claimed = queue.claim("worker-a", lease_seconds=30)
        committed = queue.commit(claimed["job_id"], "worker-a", {"status": "ok"}, commit_key="commit-1", expected_version=0)
        replayed = queue.commit(claimed["job_id"], "worker-a", {"status": "ok"}, commit_key="commit-1", expected_version=0)
        probes.append({"name": "exactly_once_commit_replay", "passed": committed["state_version"] == 1 and replayed["replayed"]})

        sessions = SessionManager(temp_root / "sessions", database)
        session = sessions.create("resume probe", "session_probe")
        sessions.bind_run(session["session_id"], "run_probe")
        expected_state = {"run_id": "run_probe", "status": "interrupted", "todos": [{"id": "todo_1", "status": "pending"}]}
        sessions.create_checkpoint(session["session_id"], expected_state, "interrupted")
        restored = sessions.load_active_checkpoint(session["session_id"])["state"]
        probes.append({"name": "checkpoint_round_trip", "passed": restored == expected_state})

        registry = ToolRegistry()
        calls = {"cache": 0, "retry": 0}
        schema_object = {"type": "object", "properties": {"status": {"type": "string"}}, "required": ["status"]}

        def cached_handler(arguments, context):
            calls["cache"] += 1
            return {"status": "success"}

        registry.register(ToolSpec("probe.cache", "cache probe", {"type": "object"}, schema_object, "read", cached_handler, idempotent=True, cacheable=True))
        context = {"run_id": "probe", "tool_result_cache": {}}
        registry.call("probe.cache", {}, context)
        registry.call("probe.cache", {}, context)
        probes.append({"name": "idempotent_tool_cache", "passed": calls["cache"] == 1})

        def retry_handler(arguments, context):
            calls["retry"] += 1
            if calls["retry"] == 1:
                raise RuntimeError("transient")
            return {"status": "success"}

        registry.register(ToolSpec("probe.retry", "retry probe", {"type": "object"}, schema_object, "read", retry_handler, idempotent=True, max_retries=1))
        retry_result = registry.call("probe.retry", {}, {"run_id": "probe"})
        probes.append({"name": "bounded_idempotent_retry", "passed": retry_result["status"] == "success" and calls["retry"] == 2})
        # sqlite3 connection context managers commit transactions but do not close
        # the connection. Force collection before Windows removes the temporary DB.
        gc.collect()
        checkpoint = database.connect()
        try:
            checkpoint.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            checkpoint.close()
        gc.collect()
    passed = sum(bool(item["passed"]) for item in probes)
    return {"evidence_class": "controlled_production_components", "rate": _rate(passed, len(probes)), "probes": probes}


def build_interview_report(
    workspace_root: str | Path,
    *,
    open_planning: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(workspace_root).resolve()
    run_ids = _frozen_run_ids(root)
    run_dirs = [root / "runs" / run_id for run_id in run_ids if (root / "runs" / run_id / "state.json").exists()]
    historical = aggregate_metrics([collect_run_metrics(path) for path in run_dirs])
    rag = run_rag_ablation(root)
    guard = run_guard_ablation(root)
    context = run_context_ablation(run_dirs)
    recovery = run_recovery_idempotency_probes(root)
    open_planning = open_planning or _read_json(root / "runs" / "benchmarks" / "agent_open_task_results.json", {})
    before_contract = _read_json(root / "benchmarks" / "agent_interview_open_task_before_contract_fix.json", {})
    after_contract = _read_json(root / "benchmarks" / "agent_interview_open_task_after_schema_before_session_fix.json", {})
    before_rate = (before_contract.get("rate") or {}).get("rate")
    final_rate = (open_planning.get("rate") or {}).get("rate")
    framework_improvement = {
        "evidence_class": "same_fixed_suite_before_after",
        "before_contract_fix": before_contract.get("rate") or {},
        "after_schema_before_session_fix": after_contract.get("rate") or {},
        "final": open_planning.get("rate") or {},
        "absolute_percentage_point_gain": (
            round((float(final_rate) - float(before_rate)) * 100, 2)
            if final_rate is not None and before_rate is not None
            else None
        ),
        "stages": [
            "Recursive nested schema validation and a strongly typed task-interpreter contract.",
            "Independent benchmark session creation instead of an unregistered session id.",
            "ONNX source alias canonicalization and pre-plan grouped-Conv capability rejection.",
        ],
        "caveat": "The before/after uses the same fixed 10-case suite and measures regression repair, not population-level generalization.",
    }
    release_gates = {
        "frozen_historical_cohort_present": len(run_dirs) >= 15,
        "historical_false_success_zero": historical.get("false_success_rate") == 0.0,
        "trace_completeness_at_least_95_percent": (historical.get("trace_completeness_avg") or 0.0) >= 0.95,
        "artifact_completeness_at_least_95_percent": (historical.get("artifact_completeness_avg") or 0.0) >= 0.95,
        "real_llm_open_planning_at_least_80_percent": (open_planning.get("rate") or {}).get("rate", 0.0) >= 0.8,
        "rag_mrr_at_least_80_percent": (rag["production_retriever"].get("macro_mrr") or 0.0) >= 0.8,
        "rag_pollution_at_most_10_percent": rag["production_retriever"].get("macro_pollution_at_k") is not None
        and rag["production_retriever"]["macro_pollution_at_k"] <= 0.1,
        "unsafe_candidate_acceptance_zero": guard["guard_enabled"]["unsafe_candidate_acceptance_rate"] == 0.0,
        "recovery_idempotency_all_pass": recovery["rate"]["rate"] == 1.0,
        "context_isolation_measured": context["specialist_result_count"] > 0,
    }
    report = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "benchmark_name": "agent_interview_evidence_v1",
        "interview_ready": all(release_gates.values()),
        "cohort": {"selection_policy": "operator_release_exact_runs_plus_latest_non_candidate_path_per_class", "run_ids": run_ids},
        "historical_real_run_metrics": historical,
        "open_task_generalization": open_planning,
        "framework_improvement": framework_improvement,
        "ablations": {"rag": rag, "guard": guard, "context_and_specialists": context},
        "recovery_and_idempotency": recovery,
        "release_gates": release_gates,
        "limitations": [
            "Open-task generalization evaluates real LLM interpretation and guarded planning, not HLS execution.",
            "Guard ablation is a safe counterfactual and never executes unsafe candidates.",
            "Context ablation is posthoc over frozen current-run artifacts.",
            "Samples below 20 are reported with Wilson intervals and are not claimed as population-level stability.",
        ],
    }
    return report


def render_markdown(report: dict[str, Any]) -> str:
    historical = report["historical_real_run_metrics"]
    open_tasks = report.get("open_task_generalization") or {}
    rag = report["ablations"]["rag"]
    guard = report["ablations"]["guard"]
    context = report["ablations"]["context_and_specialists"]
    recovery = report["recovery_and_idempotency"]
    lines = [
        "# Agent 面试量化评测",
        "",
        f"- Interview Ready: `{report['interview_ready']}`",
        f"- Frozen run cohort: `{historical['run_count']}`",
        f"- Historical task success: `{historical['task_success_rate']}`",
        f"- False success: `{historical['false_success_rate']}`",
        f"- Toolchain selection accuracy: `{historical['toolchain_selection_accuracy']}`",
        f"- Trace / Artifact completeness: `{historical['trace_completeness_avg']}` / `{historical['artifact_completeness_avg']}`",
        f"- Runtime p50 / p95: `{historical['runtime_s']['p50']}` / `{historical['runtime_s']['p95']}` seconds",
        f"- Tokens per success: `{historical['tokens_per_success']}`",
        "",
        "## 开放任务泛化",
        "",
        f"- Real LLM planning pass: `{(open_tasks.get('rate') or {}).get('numerator', 0)}/{(open_tasks.get('rate') or {}).get('denominator', 0)}`",
        f"- LLM calls / tokens: `{open_tasks.get('llm_calls')}` / `{open_tasks.get('total_tokens')}`",
        f"- Same-suite framework repair: `{(report.get('framework_improvement') or {}).get('absolute_percentage_point_gain')}` percentage points",
        "",
        "## 消融",
        "",
        f"- RAG MRR: no-memory `{rag['no_memory']['macro_mrr']}`, naive `{rag['naive_lexical']['macro_mrr']}`, production `{rag['production_retriever']['macro_mrr']}`",
        f"- RAG nDCG@K: naive `{rag['naive_lexical']['macro_ndcg_at_k']}`, production `{rag['production_retriever']['macro_ndcg_at_k']}`",
        f"- RAG pollution@K: naive `{rag['naive_lexical']['macro_pollution_at_k']}`, production `{rag['production_retriever']['macro_pollution_at_k']}`",
        f"- Guard unsafe acceptance: schema-only `{guard['schema_only_ablation']['unsafe_candidate_acceptance_rate']}`, enabled `{guard['guard_enabled']['unsafe_candidate_acceptance_rate']}`",
        f"- Specialist return vs full-state context reduction p50: `{context['main_agent_context_reduction_p50']}`",
        "",
        "## 恢复与幂等",
        "",
        f"- Production component probes: `{recovery['rate']['numerator']}/{recovery['rate']['denominator']}`",
        "",
        "## Release Gates",
        "",
    ]
    lines.extend(f"- [{'x' if value else ' '}] {name}" for name, value in report["release_gates"].items())
    lines.extend(["", "## 口径", ""] + [f"- {item}" for item in report["limitations"]])
    return "\n".join(lines) + "\n"


def run_interview_benchmark(
    workspace_root: str | Path,
    output_path: str | Path,
    *,
    run_open_llm: bool = False,
) -> dict[str, Any]:
    root = Path(workspace_root).resolve()
    open_results = run_open_task_planning(root) if run_open_llm else None
    if open_results is not None:
        _write_json(root / "runs" / "benchmarks" / "agent_open_task_results.json", open_results)
    report = build_interview_report(root, open_planning=open_results)
    output = Path(output_path)
    if not output.is_absolute():
        output = root / output
    _write_json(output, report)
    output.with_suffix(".md").write_text(render_markdown(report), encoding="utf-8")
    return report
