from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .benchmarks.agent_quality_benchmark import main as benchmark_main
from .benchmarks.agent_interview_benchmark import run_interview_benchmark
from .benchmarks.bad_case_benchmark import run_bad_case_benchmark
from .benchmarks.context_ablation import run_benchmark as run_context_ablation_benchmark
from .benchmarks.maturity_benchmark import run_maturity_benchmark
from .benchmarks.semantic_rag_benchmark import run_semantic_rag_benchmark
from .benchmarks.operator_benchmark import run_operator_benchmark
from .benchmarks.operator_fair_comparison import analyze_template_vs_llm
from .benchmarks.operator_onnx_cases import run_operator_onnx_cases
from .core.design_objectives import list_objective_modes
from .core.durable_queue import DurableWorker
from .core.observability import SLOEvaluator
from .memory.feedback_governance import FeedbackGovernor
from .rag.calibration import HLSRerankerCalibrator
from .main_agent.agent import MainAgent
from .main_agent.workflow import resume_task_llm, run_task, run_task_llm
from .adapters.hls4ml_adapter import HLS4MLAdapter
from .adapters.vivado_hls_adapter import VivadoHLSAdapter
from .core.config import AppConfig
from .mcp.server import MCPServer
from .mcp_servers.hls4ml_server import build_hls4ml_registry
from .mcp_servers.vivado_hls_server import build_vivado_registry


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dl-op-to-hls")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("task_path")
    run_parser.add_argument("--session-id")
    run_parser.add_argument("--user-id", default="local-user")
    run_parser.add_argument("--project-id")
    run_parser.add_argument("--mock-tools", action="store_true", help="Force mock hls4ml/Vivado tools for demo runs.")
    run_parser.add_argument("--real-tools", action="store_true", help="Force real hls4ml/Vivado tools for toolchain validation.")

    baseline_parser = subparsers.add_parser("run-baseline", help="Compatibility-only deterministic baseline.")
    baseline_parser.add_argument("task_path")
    baseline_parser.add_argument("--mock-tools", action="store_true")
    baseline_parser.add_argument("--real-tools", action="store_true")

    run_llm_parser = subparsers.add_parser("run-llm")
    run_llm_parser.add_argument("task_input")
    run_llm_parser.add_argument("--session-id")
    run_llm_parser.add_argument("--user-id", default="local-user")
    run_llm_parser.add_argument("--project-id")
    run_llm_parser.add_argument("--mock-tools", action="store_true", help="Explicitly use mock toolchains.")
    run_llm_parser.add_argument("--real-tools", action="store_true", help="Explicitly require real toolchains.")

    agent_run_parser = subparsers.add_parser("agent-run", help="Primary durable LLM Agent runtime.")
    agent_run_parser.add_argument("task_input")
    agent_run_parser.add_argument("--session-id")
    agent_run_parser.add_argument("--user-id", default="local-user")
    agent_run_parser.add_argument("--project-id")
    agent_run_parser.add_argument("--mock-tools", action="store_true", help="Explicitly use mock toolchains.")
    agent_run_parser.add_argument("--real-tools", action="store_true", help="Explicitly require real toolchains.")

    run_nl_parser = subparsers.add_parser("run-nl")
    run_nl_parser.add_argument("prompt")
    run_nl_parser.add_argument("--session-id")
    run_nl_parser.add_argument("--user-id", default="local-user")
    run_nl_parser.add_argument("--project-id")

    subparsers.add_parser("session-list")
    session_show_parser = subparsers.add_parser("session-show")
    session_show_parser.add_argument("session_id")
    session_interrupt_parser = subparsers.add_parser("session-interrupt")
    session_interrupt_parser.add_argument("session_id")
    session_interrupt_parser.add_argument("--reason", default="User requested interruption")
    session_resume_parser = subparsers.add_parser("session-resume")
    session_resume_parser.add_argument("session_id")
    session_rollback_parser = subparsers.add_parser("session-rollback")
    session_rollback_parser.add_argument("session_id")
    session_rollback_parser.add_argument("--checkpoint-id")
    session_rollback_parser.add_argument("--steps", type=int, default=1)
    session_checkpoints_parser = subparsers.add_parser("session-checkpoints")
    session_checkpoints_parser.add_argument("session_id")
    session_retract_parser = subparsers.add_parser("session-retract")
    session_retract_parser.add_argument("session_id")
    session_approve_parser = subparsers.add_parser("session-approve")
    session_approve_parser.add_argument("session_id")
    session_approve_parser.add_argument("approval_id")
    session_approve_parser.add_argument("--feedback", default="")
    session_reject_parser = subparsers.add_parser("session-reject")
    session_reject_parser.add_argument("session_id")
    session_reject_parser.add_argument("approval_id")
    session_reject_parser.add_argument("--feedback", default="")

    subparsers.add_parser("llm-status")
    subparsers.add_parser("objective-modes")

    benchmark_parser = subparsers.add_parser("benchmark")
    benchmark_parser.add_argument("--runs-root", default="runs")
    benchmark_parser.add_argument("--runs", nargs="*", default=[])
    benchmark_parser.add_argument("--latest", type=int, default=0)
    benchmark_parser.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"))
    benchmark_parser.add_argument("--rag-eval-file")
    benchmark_parser.add_argument("--rag-top-k", type=int, default=5)
    benchmark_parser.add_argument("--output", default="runs/benchmarks/agent_quality_benchmark.json")
    benchmark_parser.add_argument("--run-suite", action="store_true")
    benchmark_parser.add_argument("--suite-file")
    benchmark_parser.add_argument("--case-id", nargs="*", default=[])
    benchmark_parser.add_argument("--runner", choices=["deterministic", "llm"], default="llm")
    benchmark_parser.add_argument("--mock-tools", action="store_true")
    benchmark_parser.add_argument("--repeat", type=int, default=1)
    benchmark_parser.add_argument("--quiet", action="store_true")
    benchmark_parser.add_argument(
        "--tasks",
        nargs="*",
        default=["examples/mnist_recognition_mlp.json"],
    )

    maturity_parser = subparsers.add_parser("maturity-benchmark")
    maturity_parser.add_argument("--output", default="runs/benchmarks/agent_maturity_probe.json")
    bad_case_parser = subparsers.add_parser("bad-case-benchmark")
    bad_case_parser.add_argument("--output", default="runs/benchmarks/agent_bad_case_probe.json")
    semantic_rag_parser = subparsers.add_parser("semantic-rag-benchmark")
    semantic_rag_parser.add_argument("--output", default="runs/benchmarks/semantic_rag_real_probe.json")
    operator_benchmark_parser = subparsers.add_parser("operator-benchmark")
    operator_benchmark_parser.add_argument("--output", default="runs/benchmarks/operator_release.json")
    operator_onnx_parser = subparsers.add_parser("operator-onnx-benchmark")
    operator_onnx_parser.add_argument("--output", default="benchmarks/operator_onnx_graph_results.json")
    operator_fair_parser = subparsers.add_parser("operator-fair-comparison")
    operator_fair_parser.add_argument("--manifest", default="benchmarks/operator_template_vs_llm_suite.json")
    operator_fair_parser.add_argument("--output", default="benchmarks/operator_template_vs_llm_results.json")
    agent_interview_parser = subparsers.add_parser(
        "agent-interview-benchmark",
        help="Run the unified Agent engineering benchmark and ablations.",
    )
    agent_interview_parser.add_argument(
        "--output",
        default="runs/benchmarks/agent_interview_release.json",
    )
    agent_interview_parser.add_argument(
        "--run-open-llm",
        action="store_true",
        help="Call the configured real LLM once for every fixed open-task case.",
    )

    context_ablation_parser = subparsers.add_parser(
        "context-ablation-benchmark",
        help="Run paired real-HLS context input/result ablations.",
    )
    context_ablation_parser.add_argument("--workspace", default=".")
    context_ablation_parser.add_argument("--tokenizer-path", required=True)
    context_ablation_parser.add_argument("--suite", default="benchmarks/context_ablation_suite.json")
    context_ablation_parser.add_argument("--output-dir")
    context_ablation_parser.add_argument(
        "--execution-root",
        required=True,
        help="Absolute short directory used for real HLS work; reports remain under --output-dir.",
    )
    context_ablation_parser.add_argument("--trials", type=int, default=3)
    context_ablation_parser.add_argument("--max-pair-attempts", type=int, default=4)
    context_ablation_parser.add_argument("--run-timeout-seconds", type=int, default=3600)
    context_ablation_parser.add_argument("--smoke", action="store_true")
    context_ablation_parser.add_argument("--manifest-only", action="store_true")
    context_ablation_parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume only complete validated A/B/C pair checkpoints from an interrupted benchmark.",
    )

    context_ablation_aggregate_parser = subparsers.add_parser(
        "context-ablation-aggregate",
        help="Aggregate initial and repeated context-ablation results.",
    )
    context_ablation_aggregate_parser.add_argument("--source-dir", action="append", required=True)
    context_ablation_aggregate_parser.add_argument("--output-dir", required=True)
    context_ablation_aggregate_parser.add_argument("--summary-output")

    rag_calibrate_parser = subparsers.add_parser("rag-calibrate")
    rag_calibrate_parser.add_argument("--dataset", default="benchmarks/hls_reranker_hard_negatives.json")
    rag_calibrate_parser.add_argument("--output", default="runs/calibration/hls_reranker_calibration.json")
    rag_calibrate_parser.add_argument("--max-pollution-rate", type=float, default=0.05)
    rag_calibrate_parser.add_argument("--training-triples")

    submit_parser = subparsers.add_parser("agent-submit")
    submit_parser.add_argument("task_input")
    submit_parser.add_argument("--idempotency-key")
    submit_parser.add_argument("--priority", type=int, default=100)
    worker_parser = subparsers.add_parser("worker-once")
    worker_parser.add_argument("--worker-id", default=f"worker-{os.getpid()}")
    worker_parser.add_argument("--lease-seconds", type=float, default=900)
    job_parser = subparsers.add_parser("job-show")
    job_parser.add_argument("job_id")

    release_register = subparsers.add_parser("release-register")
    release_register.add_argument("component_type", choices=["model", "prompt", "skill"])
    release_register.add_argument("name")
    release_register.add_argument("version")
    release_register.add_argument("--config", default="{}", help="JSON object")
    release_register.add_argument("--baseline", action="store_true")
    release_canary = subparsers.add_parser("release-canary")
    release_canary.add_argument("component_type", choices=["model", "prompt", "skill"])
    release_canary.add_argument("name")
    release_canary.add_argument("candidate_version")
    release_canary.add_argument("--percent", type=float, default=5)
    release_status = subparsers.add_parser("release-status")
    release_status.add_argument("component_type", choices=["model", "prompt", "skill"])
    release_status.add_argument("name")
    release_evaluate = subparsers.add_parser("release-evaluate")
    release_evaluate.add_argument("component_type", choices=["model", "prompt", "skill"])
    release_evaluate.add_argument("name")
    release_evaluate.add_argument("baseline_metrics", help="JSON object")
    release_evaluate.add_argument("candidate_metrics", help="JSON object")

    slo_parser = subparsers.add_parser("slo-evaluate")
    slo_parser.add_argument("metrics", help="JSON object or path")
    slo_parser.add_argument("--output", default="runs/benchmarks/slo_report.json")

    llm_trace_parser = subparsers.add_parser("llm-trace")
    llm_trace_parser.add_argument("run_id_or_path")

    report_parser = subparsers.add_parser("report")
    report_parser.add_argument("run_id_or_path")

    suggest_parser = subparsers.add_parser("suggest")
    suggest_parser.add_argument("run_id_or_path")

    rag_parser = subparsers.add_parser("rag-search")
    rag_parser.add_argument("query")
    rag_backfill_parser = subparsers.add_parser("rag-backfill")
    rag_backfill_parser.add_argument("--batch-size", type=int, default=256)
    rag_backfill_parser.add_argument("--max-chunks", type=int)

    db_parser = subparsers.add_parser("db-list-runs")

    memory_list_parser = subparsers.add_parser("memory-list")

    memory_search_parser = subparsers.add_parser("memory-search")
    memory_search_parser.add_argument("query")

    memory_show_parser = subparsers.add_parser("memory-show")
    memory_show_parser.add_argument("memory_id", type=int)

    memory_promote_parser = subparsers.add_parser("memory-promote")
    memory_promote_parser.add_argument("run_id_or_path")

    memory_feedback_parser = subparsers.add_parser("memory-feedback")
    memory_feedback_parser.add_argument("memory_id", type=int)
    memory_feedback_parser.add_argument("score", type=float)
    memory_feedback_parser.add_argument("--reason", default="")
    memory_feedback_parser.add_argument("--user-id", default="local-user")
    memory_feedback_parser.add_argument("--run-id")
    memory_feedback_review = subparsers.add_parser("memory-feedback-review")
    memory_feedback_review.add_argument("candidate_id", type=int)
    memory_feedback_review.add_argument("decision", choices=["approve", "reject", "quarantine"])
    memory_feedback_review.add_argument("--reviewer", default="local-admin")
    memory_feedback_list = subparsers.add_parser("memory-feedback-list")
    memory_feedback_list.add_argument("--status")

    memory_forget_parser = subparsers.add_parser("memory-forget")
    memory_forget_parser.add_argument("memory_id", type=int)
    memory_forget_parser.add_argument("--reason", default="user_request")
    subparsers.add_parser("memory-cleanup")

    skills_list_parser = subparsers.add_parser("skills-list")
    subparsers.add_parser("skills-validate")
    skill_promote_parser = subparsers.add_parser("skill-promote")
    skill_promote_parser.add_argument("skill_name")
    skill_promote_parser.add_argument("--version")
    skill_deprecate_parser = subparsers.add_parser("skill-deprecate")
    skill_deprecate_parser.add_argument("skill_name")
    skill_deprecate_parser.add_argument("--version")

    workspace_scan_parser = subparsers.add_parser("workspace-scan")
    workspace_scan_parser.add_argument("paths", nargs="*")
    workspace_search_parser = subparsers.add_parser("workspace-search")
    workspace_search_parser.add_argument("query")
    workspace_search_parser.add_argument("--top-k", type=int, default=20)

    skill_show_parser = subparsers.add_parser("skill-show")
    skill_show_parser.add_argument("skill_name")

    skills_show_parser = subparsers.add_parser("skills-show")
    skills_show_parser.add_argument("skill_id", type=int)

    subparsers.add_parser("specialists-list")

    specialist_show_parser = subparsers.add_parser("specialist-show")
    specialist_show_parser.add_argument("name")

    specialist_trace_parser = subparsers.add_parser("specialist-trace")
    specialist_trace_parser.add_argument("run_id_or_path")
    specialist_trace_parser.add_argument("specialist_name")

    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("task_path")
    inspect_parser.add_argument("--mock-tools", action="store_true", help="Force mock hls4ml/Vivado tools for demo runs.")
    inspect_parser.add_argument("--real-tools", action="store_true", help="Force real hls4ml/Vivado tools for toolchain validation.")

    convert_parser = subparsers.add_parser("convert")
    convert_parser.add_argument("task_path")
    convert_parser.add_argument("--mock-tools", action="store_true", help="Force mock hls4ml/Vivado tools for demo runs.")
    convert_parser.add_argument("--real-tools", action="store_true", help="Force real hls4ml/Vivado tools for toolchain validation.")

    synth_parser = subparsers.add_parser("synth")
    synth_parser.add_argument("run_id_or_path")

    subparsers.add_parser("serve-hls4ml")
    subparsers.add_parser("serve-vivado-hls")
    return parser


def _build_agent(*, mock_tools: bool = False, real_tools: bool = False) -> MainAgent:
    if mock_tools and real_tools:
        raise ValueError("--mock-tools and --real-tools are mutually exclusive.")
    if real_tools:
        os.environ["DL_OP_TO_HLS_MOCK_TOOLS"] = "0"
        os.environ["DL_OP_TO_HLS_MOCK_HLS4ML"] = "0"
        os.environ["DL_OP_TO_HLS_MOCK_VIVADO"] = "0"
    elif mock_tools:
        os.environ["DL_OP_TO_HLS_MOCK_TOOLS"] = "1"
        os.environ["DL_OP_TO_HLS_MOCK_HLS4ML"] = "1"
        os.environ["DL_OP_TO_HLS_MOCK_VIVADO"] = "1"
    return MainAgent(console=False)


def _configure_stdio() -> None:
    """Keep JSON CLI output parseable on Windows consoles with non-UTF-8 codepages."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "run":
        agent = _build_agent(mock_tools=args.mock_tools, real_tools=args.real_tools)
        try:
            state = run_task_llm(
                args.task_path,
                agent=agent,
                session_id=args.session_id,
                user_id=args.user_id,
                project_id=args.project_id,
            )
        except Exception as exc:
            print(json.dumps({"error_type": type(exc).__name__, "message": str(exc)}, indent=2, ensure_ascii=False))
            return 2
        if state.status == "failed" and any("LLM is not enabled or API key is missing." in (item.get("message", "")) for item in state.errors):
            print(json.dumps(state.errors[0], indent=2, ensure_ascii=False))
            return 2
        print(json.dumps(state.to_dict(), indent=2, ensure_ascii=False))
        return 0
    if args.command == "run-baseline":
        agent = _build_agent(mock_tools=args.mock_tools, real_tools=args.real_tools)
        state = run_task(args.task_path, agent=agent)
        print(json.dumps(state.to_dict(), indent=2, ensure_ascii=False))
        return 0
    if args.command in {"run-llm", "agent-run"}:
        agent = _build_agent(mock_tools=args.mock_tools, real_tools=args.real_tools)
        try:
            state = run_task_llm(
                args.task_input,
                agent=agent,
                session_id=args.session_id,
                user_id=args.user_id,
                project_id=args.project_id,
            )
        except Exception as exc:
            print(json.dumps({"error_type": type(exc).__name__, "message": str(exc)}, indent=2, ensure_ascii=False))
            return 2
        if state.status == "failed" and any("LLM is not enabled or API key is missing." in (item.get("message", "")) for item in state.errors):
            print(json.dumps(state.errors[0], indent=2, ensure_ascii=False))
            return 2
        print(json.dumps(state.to_dict(), indent=2, ensure_ascii=False))
        return 0
    if args.command == "run-nl":
        agent = _build_agent()
        try:
            state = run_task_llm(
                args.prompt,
                agent=agent,
                session_id=args.session_id,
                user_id=args.user_id,
                project_id=args.project_id,
            )
        except Exception as exc:
            print(json.dumps({"error_type": type(exc).__name__, "message": str(exc)}, indent=2, ensure_ascii=False))
            return 2
        if state.status == "failed" and any("LLM is not enabled or API key is missing." in (item.get("message", "")) for item in state.errors):
            print(json.dumps(state.errors[0], indent=2, ensure_ascii=False))
            return 2
        print(json.dumps(state.to_dict(), indent=2, ensure_ascii=False))
        return 0
    if args.command == "session-list":
        agent = _build_agent()
        print(json.dumps(agent.session_manager.list_sessions(), indent=2, ensure_ascii=False))
        return 0
    if args.command == "session-show":
        agent = _build_agent()
        print(json.dumps(agent.session_manager.get(args.session_id), indent=2, ensure_ascii=False))
        return 0
    if args.command == "session-interrupt":
        agent = _build_agent()
        print(json.dumps(agent.session_manager.request_interrupt(args.session_id, args.reason), indent=2, ensure_ascii=False))
        return 0
    if args.command == "session-resume":
        agent = _build_agent()
        state = resume_task_llm(args.session_id, agent=agent)
        print(json.dumps(state.to_dict(), indent=2, ensure_ascii=False))
        return 0
    if args.command == "session-rollback":
        agent = _build_agent()
        result = agent.session_manager.rollback(args.session_id, checkpoint_id=args.checkpoint_id, steps=args.steps)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    if args.command == "session-checkpoints":
        agent = _build_agent()
        print(json.dumps(agent.session_manager.list_checkpoints(args.session_id), indent=2, ensure_ascii=False))
        return 0
    if args.command == "session-retract":
        agent = _build_agent()
        print(json.dumps(agent.session_manager.retract_last_user_message(args.session_id), indent=2, ensure_ascii=False))
        return 0
    if args.command == "session-approve":
        agent = _build_agent()
        print(json.dumps(agent.session_manager.decide_approval(args.session_id, args.approval_id, "approved", args.feedback), indent=2, ensure_ascii=False))
        return 0
    if args.command == "session-reject":
        agent = _build_agent()
        print(json.dumps(agent.session_manager.decide_approval(args.session_id, args.approval_id, "rejected", args.feedback), indent=2, ensure_ascii=False))
        return 0
    if args.command == "llm-status":
        agent = _build_agent()
        agent.llm_client.set_context({"release_manifest": agent.release_manager.resolve_bundle("llm-status")})
        cfg = agent.llm_client.config
        payload = {
            "runtime_mode_default": "llm_agent",
            "llm_enabled": cfg.enabled,
            "llm_configured": cfg.configured,
            "provider": cfg.provider,
            "base_url": cfg.base_url,
            "model": cfg.model,
            "release_routed_provider": agent.llm_client.active_provider(),
            "release_routed_base_url": agent.llm_client.active_base_url(),
            "release_routed_model": agent.llm_client.active_model(),
            "max_llm_calls": cfg.max_llm_calls,
            "max_tool_calls": cfg.max_tool_calls,
            "max_repair_attempts": cfg.max_repair_attempts,
            "rate_bytes_per_minute": cfg.rate_bytes_per_minute,
            "min_request_interval_sec": cfg.min_request_interval_sec,
            "min_retry_429_seconds": cfg.min_retry_429_seconds,
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    if args.command == "objective-modes":
        print(json.dumps(list_objective_modes(), indent=2, ensure_ascii=False))
        return 0
    if args.command == "benchmark":
        forwarded = [
            "--runs-root",
            args.runs_root,
            "--output",
            args.output,
            "--rag-top-k",
            str(args.rag_top_k),
        ]
        if args.runs:
            forwarded.extend(["--runs", *args.runs])
        if args.latest:
            forwarded.extend(["--latest", str(args.latest)])
        if args.compare:
            forwarded.extend(["--compare", *args.compare])
        if args.rag_eval_file:
            forwarded.extend(["--rag-eval-file", args.rag_eval_file])
        if args.suite_file:
            forwarded.extend(["--suite-file", args.suite_file])
        if args.case_id:
            forwarded.extend(["--case-id", *args.case_id])
        if args.run_suite:
            forwarded.append("--run-suite")
        if args.mock_tools:
            forwarded.append("--mock-tools")
        if args.quiet:
            forwarded.append("--quiet")
        forwarded.extend(["--runner", args.runner, "--repeat", str(args.repeat)])
        if args.tasks:
            forwarded.extend(["--tasks", *args.tasks])
        return benchmark_main(forwarded)
    if args.command == "maturity-benchmark":
        payload = run_maturity_benchmark(Path.cwd(), args.output)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    if args.command == "bad-case-benchmark":
        payload = run_bad_case_benchmark(Path.cwd(), args.output)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    if args.command == "semantic-rag-benchmark":
        payload = run_semantic_rag_benchmark(Path.cwd(), args.output)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    if args.command == "operator-benchmark":
        payload = run_operator_benchmark(Path.cwd(), args.output)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    if args.command == "operator-onnx-benchmark":
        payload = run_operator_onnx_cases(Path.cwd(), args.output)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    if args.command == "operator-fair-comparison":
        payload = analyze_template_vs_llm(Path.cwd(), args.manifest, args.output)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    if args.command == "agent-interview-benchmark":
        payload = run_interview_benchmark(Path.cwd(), args.output, run_open_llm=args.run_open_llm)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    if args.command == "context-ablation-benchmark":
        payload = run_context_ablation_benchmark(args)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0 if payload.get("status") in {"complete", "manifest_created"} else 2
    if args.command == "context-ablation-aggregate":
        from .benchmarks.context_ablation_aggregate import run_aggregate

        payload = run_aggregate(args)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    if args.command == "rag-calibrate":
        agent = _build_agent()
        calibrator = HLSRerankerCalibrator(agent.rag_memory.semantic_engine)
        report = calibrator.run(args.dataset, max_pollution_rate=args.max_pollution_rate)
        calibrator.save(report, args.output)
        if args.training_triples:
            calibrator.export_training_triples(args.dataset, args.training_triples)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    if args.command == "agent-submit":
        agent = _build_agent()
        result = agent.job_queue.enqueue(
            {"task_input": args.task_input},
            idempotency_key=args.idempotency_key,
            priority=args.priority,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    if args.command == "worker-once":
        agent = _build_agent()

        def handle(payload):
            state = run_task_llm(payload["task_input"], agent=agent)
            return {"run_id": state.run_id, "status": state.status, "selected_path": state.selected_path}

        result = DurableWorker(agent.job_queue, args.worker_id, handle).run_once(lease_seconds=args.lease_seconds)
        print(json.dumps(result or {"status": "idle"}, indent=2, ensure_ascii=False))
        return 0
    if args.command == "job-show":
        agent = _build_agent()
        print(json.dumps(agent.job_queue.get(args.job_id), indent=2, ensure_ascii=False))
        return 0
    if args.command in {"release-register", "release-canary", "release-status", "release-evaluate"}:
        agent = _build_agent()
        manager = agent.release_manager
        if args.command == "release-register":
            result = manager.register(args.component_type, args.name, args.version, json.loads(args.config))
            if args.baseline:
                result = manager.set_baseline(args.component_type, args.name, args.version)
        elif args.command == "release-canary":
            result = manager.start_canary(args.component_type, args.name, args.candidate_version, args.percent)
        elif args.command == "release-status":
            result = manager.status(args.component_type, args.name)
        else:
            result = manager.evaluate(
                args.component_type,
                args.name,
                json.loads(args.baseline_metrics),
                json.loads(args.candidate_metrics),
            )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    if args.command == "slo-evaluate":
        try:
            candidate = Path(args.metrics)
            is_file = candidate.exists()
        except OSError:
            is_file = False
        metrics = json.loads(candidate.read_text(encoding="utf-8")) if is_file else json.loads(args.metrics)
        report = SLOEvaluator().write_report(args.output, metrics)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    if args.command == "llm-trace":
        agent = _build_agent()
        candidate = Path(args.run_id_or_path)
        run_dir = candidate if candidate.exists() else agent.config.runs_root / args.run_id_or_path
        trace_path = run_dir / "trace.jsonl"
        if not trace_path.exists():
            print("")
            return 0
        lines = [
            line
            for line in trace_path.read_text(encoding="utf-8").splitlines()
            if "\"event\": \"LLM" in line or "\"event\":\"LLM" in line
        ]
        print("\n".join(lines))
        return 0
    if args.command == "report":
        agent = _build_agent()
        print(json.dumps(agent.read_run_json(args.run_id_or_path, "report.json"), indent=2, ensure_ascii=False))
        return 0
    if args.command == "suggest":
        agent = _build_agent()
        print(agent.read_run_file(args.run_id_or_path, "suggestions.md"))
        return 0
    if args.command == "rag-search":
        agent = _build_agent()
        print(json.dumps(agent.rag_memory.retrieve(args.query), indent=2, ensure_ascii=False))
        return 0
    if args.command == "rag-backfill":
        agent = _build_agent()
        result = agent.rag_memory.backfill_embeddings(batch_size=args.batch_size, max_chunks=args.max_chunks)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    if args.command == "db-list-runs":
        agent = _build_agent()
        print(json.dumps(agent.list_runs(), indent=2, ensure_ascii=False))
        return 0
    if args.command == "memory-list":
        agent = _build_agent()
        print(json.dumps(agent.list_memories(), indent=2, ensure_ascii=False))
        return 0
    if args.command == "memory-search":
        agent = _build_agent()
        print(json.dumps(agent.search_memories(args.query), indent=2, ensure_ascii=False))
        return 0
    if args.command == "memory-show":
        agent = _build_agent()
        print(json.dumps(agent.get_memory(args.memory_id), indent=2, ensure_ascii=False))
        return 0
    if args.command == "memory-promote":
        agent = _build_agent()
        print(json.dumps(agent.promote_run_memories(args.run_id_or_path), indent=2, ensure_ascii=False))
        return 0
    if args.command == "memory-feedback":
        agent = _build_agent()
        evidence = {"run_id": args.run_id, "run_verified": bool(args.run_id)} if args.run_id else {}
        print(json.dumps(agent.memory_manager.submit_feedback(args.memory_id, args.score, args.reason, args.user_id, evidence), indent=2, ensure_ascii=False))
        return 0
    if args.command == "memory-feedback-review":
        agent = _build_agent()
        print(json.dumps(FeedbackGovernor(agent.repository).review(args.candidate_id, args.decision, reviewer=args.reviewer), indent=2, ensure_ascii=False))
        return 0
    if args.command == "memory-feedback-list":
        agent = _build_agent()
        print(json.dumps(FeedbackGovernor(agent.repository).list_candidates(args.status), indent=2, ensure_ascii=False))
        return 0
    if args.command == "memory-forget":
        agent = _build_agent()
        print(json.dumps(agent.memory_manager.forget(args.memory_id, args.reason), indent=2, ensure_ascii=False))
        return 0
    if args.command == "memory-cleanup":
        agent = _build_agent()
        print(json.dumps(agent.memory_manager.cleanup_expired(), indent=2, ensure_ascii=False))
        return 0
    if args.command == "skills-list":
        agent = _build_agent()
        print("\n".join(item["name"] for item in agent.list_skills()))
        return 0
    if args.command == "skills-validate":
        agent = _build_agent()
        print(json.dumps(agent.skill_registry.validation_reports(), indent=2, ensure_ascii=False))
        return 0
    if args.command in {"skill-promote", "skill-deprecate"}:
        agent = _build_agent()
        target = "approved" if args.command == "skill-promote" else "deprecated"
        skill = agent.skill_registry.transition(args.skill_name, target, args.version)
        print(json.dumps(skill.to_prompt_summary(), indent=2, ensure_ascii=False))
        return 0
    if args.command == "workspace-scan":
        agent = _build_agent()
        print(json.dumps(agent.workspace_context.scan(args.paths or None), indent=2, ensure_ascii=False))
        return 0
    if args.command == "workspace-search":
        agent = _build_agent()
        print(json.dumps(agent.workspace_context.search(args.query, top_k=args.top_k), indent=2, ensure_ascii=False))
        return 0
    if args.command == "skill-show":
        agent = _build_agent()
        print(json.dumps(agent.get_skill(args.skill_name), indent=2, ensure_ascii=False))
        return 0
    if args.command == "skills-show":
        agent = _build_agent()
        print(json.dumps(agent.get_procedural_skill(args.skill_id), indent=2, ensure_ascii=False))
        return 0
    if args.command == "specialists-list":
        agent = _build_agent()
        print("\n".join(item["name"] for item in agent.list_specialists()))
        return 0
    if args.command == "specialist-show":
        agent = _build_agent()
        print(json.dumps(agent.get_specialist(args.name), indent=2, ensure_ascii=False))
        return 0
    if args.command == "specialist-trace":
        agent = _build_agent()
        print(agent.read_specialist_trace(args.run_id_or_path, args.specialist_name))
        return 0
    if args.command == "inspect":
        agent = _build_agent(mock_tools=args.mock_tools, real_tools=args.real_tools)
        task = json.loads(Path(args.task_path).read_text(encoding="utf-8"))
        if task.get("task_type") == "model":
            result = agent.registry.call(
                "hls4ml.inspect_model",
                {"model_path": task["model_path"], "frontend": task.get("frontend", "onnx")},
                {"run_id": "inspect", "hooks": None, "permission_gate": agent.permission_gate},
            )
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(json.dumps(task, indent=2, ensure_ascii=False))
        return 0
    if args.command == "convert":
        agent = _build_agent(mock_tools=args.mock_tools, real_tools=args.real_tools)
        state = run_task(args.task_path, agent=agent)
        print(state.hls_project_dir or "")
        return 0
    if args.command == "synth":
        agent = _build_agent()
        print(agent.read_run_file(args.run_id_or_path, "summary.md"))
        return 0
    if args.command == "serve-hls4ml":
        config = AppConfig.load()
        adapter = HLS4MLAdapter(mock_mode=config.mock_hls4ml, backend_override=config.hls4ml_backend)
        MCPServer("hls4ml", build_hls4ml_registry(adapter)).serve()
        return 0
    if args.command == "serve-vivado-hls":
        config = AppConfig.load()
        adapter = VivadoHLSAdapter(
            mock_mode=config.mock_vivado,
            hls_toolchain=config.hls_toolchain,
            vivado_hls_path=config.vivado_hls_path,
            vitis_hls_path=config.vitis_hls_path,
        )
        MCPServer("vivado_hls", build_vivado_registry(adapter)).serve()
        return 0
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
