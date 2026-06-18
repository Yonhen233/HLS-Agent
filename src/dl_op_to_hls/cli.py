from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .benchmarks.agent_quality_benchmark import main as benchmark_main
from .main_agent.agent import MainAgent
from .main_agent.workflow import run_task, run_task_llm


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dl-op-to-hls")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("task_path")
    run_parser.add_argument("--mock-tools", action="store_true", help="Force mock hls4ml/Vivado tools for demo runs.")
    run_parser.add_argument("--real-tools", action="store_true", help="Force real hls4ml/Vivado tools for toolchain validation.")

    run_llm_parser = subparsers.add_parser("run-llm")
    run_llm_parser.add_argument("task_input")

    run_nl_parser = subparsers.add_parser("run-nl")
    run_nl_parser.add_argument("prompt")

    subparsers.add_parser("llm-status")

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
    benchmark_parser.add_argument("--runner", choices=["deterministic", "llm"], default="deterministic")
    benchmark_parser.add_argument("--mock-tools", action="store_true")
    benchmark_parser.add_argument("--repeat", type=int, default=1)
    benchmark_parser.add_argument(
        "--tasks",
        nargs="*",
        default=["examples/dense_operator.json", "examples/matmul_resource.json", "examples/resnet18_boundary.json"],
    )

    llm_trace_parser = subparsers.add_parser("llm-trace")
    llm_trace_parser.add_argument("run_id_or_path")

    report_parser = subparsers.add_parser("report")
    report_parser.add_argument("run_id_or_path")

    suggest_parser = subparsers.add_parser("suggest")
    suggest_parser.add_argument("run_id_or_path")

    rag_parser = subparsers.add_parser("rag-search")
    rag_parser.add_argument("query")

    db_parser = subparsers.add_parser("db-list-runs")

    memory_list_parser = subparsers.add_parser("memory-list")

    memory_search_parser = subparsers.add_parser("memory-search")
    memory_search_parser.add_argument("query")

    memory_show_parser = subparsers.add_parser("memory-show")
    memory_show_parser.add_argument("memory_id", type=int)

    memory_promote_parser = subparsers.add_parser("memory-promote")
    memory_promote_parser.add_argument("run_id_or_path")

    skills_list_parser = subparsers.add_parser("skills-list")

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
        state = run_task(args.task_path, agent=agent)
        print(json.dumps(state.to_dict(), indent=2, ensure_ascii=False))
        return 0
    if args.command == "run-llm":
        agent = _build_agent()
        try:
            state = run_task_llm(args.task_input, agent=agent)
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
            state = run_task_llm(args.prompt, agent=agent)
        except Exception as exc:
            print(json.dumps({"error_type": type(exc).__name__, "message": str(exc)}, indent=2, ensure_ascii=False))
            return 2
        if state.status == "failed" and any("LLM is not enabled or API key is missing." in (item.get("message", "")) for item in state.errors):
            print(json.dumps(state.errors[0], indent=2, ensure_ascii=False))
            return 2
        print(json.dumps(state.to_dict(), indent=2, ensure_ascii=False))
        return 0
    if args.command == "llm-status":
        agent = _build_agent()
        cfg = agent.llm_client.config
        payload = {
            "runtime_mode_default": "deterministic",
            "llm_enabled": cfg.enabled,
            "llm_configured": cfg.configured,
            "provider": cfg.provider,
            "base_url": cfg.base_url,
            "model": cfg.model,
            "max_tool_calls": cfg.max_tool_calls,
            "max_repair_attempts": cfg.max_repair_attempts,
            "rate_bytes_per_minute": cfg.rate_bytes_per_minute,
            "min_request_interval_sec": cfg.min_request_interval_sec,
            "min_retry_429_seconds": cfg.min_retry_429_seconds,
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
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
        if args.run_suite:
            forwarded.append("--run-suite")
        if args.mock_tools:
            forwarded.append("--mock-tools")
        forwarded.extend(["--runner", args.runner, "--repeat", str(args.repeat)])
        if args.tasks:
            forwarded.extend(["--tasks", *args.tasks])
        return benchmark_main(forwarded)
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
    if args.command == "skills-list":
        agent = _build_agent()
        print("\n".join(item["name"] for item in agent.list_skills()))
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
        print("Mock hls4ml MCP server ready. Use ToolRegistry in-process for P0.")
        return 0
    if args.command == "serve-vivado-hls":
        print("Mock Vivado HLS MCP server ready. Use ToolRegistry in-process for P0.")
        return 0
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
