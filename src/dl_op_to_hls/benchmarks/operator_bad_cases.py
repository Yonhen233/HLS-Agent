from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from ..adapters.vivado_hls_adapter import VivadoHLSAdapter
from ..core.candidate_sandbox import CandidateSandbox
from ..core.errors import AgentRuntimeError
from ..core.goal_contract import CompletionGate, GoalContractBuilder
from ..core.progress import ProgressSupervisor
from ..core.tool_evidence import ToolPostconditionRegistry
from ..core.tool_registry import ToolRegistry, ToolSpec
from ..main_agent.state import AgentState
from ..main_agent.todo import TodoItem
from ..schemas.operator_schema import normalize_operator_task
from ..tools.functional_verification import parse_csim_verification
from ..tools.report_parser import parse_csynth_report_file
from ..tools.verify_candidate import validate_candidate_contract
from .operator_evidence import assess_tool_evidence
from .operator_suite_specs import bad_case_suite


def run_operator_bad_cases(workspace_root: str | Path, output_path: str | Path) -> dict[str, Any]:
    root = Path(workspace_root).resolve()
    work = root / "runs" / "operator_bad_case_probe"
    work.mkdir(parents=True, exist_ok=True)
    probes = _build_probes(work)
    results: list[dict[str, Any]] = []
    for spec in bad_case_suite()["cases"]:
        try:
            observed = probes[spec["case_id"]]()
        except AgentRuntimeError as exc:
            observed = {"error_type": exc.error.error_type, "recoverable": exc.error.recoverable, "detail": exc.error.to_dict()}
        except Exception as exc:  # A crash is a failed bad-case test, never a success.
            observed = {"error_type": type(exc).__name__, "recoverable": False, "detail": str(exc)}
        passed = observed.get("error_type") == spec["expected_error_type"] and not observed.get("accepted", False)
        results.append(
            {
                **spec,
                "status": "passed" if passed else "failed",
                "passed": passed,
                "failure_stage": observed.get("failure_stage", _stage(spec["case_id"])),
                "error_type": observed.get("error_type"),
                "recoverable": bool(observed.get("recoverable", True)),
                "repair_action": observed.get("repair_action", "repair_or_reject"),
                "attempt_count": int(observed.get("attempt_count", 1)),
                "final_outcome": "rejected" if not observed.get("accepted", False) else "unsafe_acceptance",
                "artifact_evidence": observed.get("artifact_evidence", observed.get("detail")),
            }
        )
    unsafe_ids = {"bad_04", "bad_05", "bad_06", "bad_07"}
    report = {
        "schema_version": "1.0",
        "suite_name": "operator_bad_case_results",
        "case_count": len(results),
        "passed_count": sum(item["passed"] for item in results),
        "pass_rate": sum(item["passed"] for item in results) / max(1, len(results)),
        "false_success_rate": sum(item["final_outcome"] == "unsafe_acceptance" for item in results) / max(1, len(results)),
        "stale_artifact_acceptance": sum(item["case_id"] == "bad_15" and not item["passed"] for item in results),
        "unsafe_candidate_acceptance": sum(item["case_id"] in unsafe_ids and not item["passed"] for item in results),
        "unsupported_fake_metric_rate": sum(item["case_id"] == "bad_20" and not item["passed"] for item in results),
        "cases": results,
    }
    output = Path(output_path)
    if not output.is_absolute():
        output = root / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return report


def _error(error_type: str, detail: Any = None, **extra: Any) -> dict[str, Any]:
    return {"error_type": error_type, "recoverable": True, "detail": detail, **extra}


def _sandbox(payload: str, *, contract: dict[str, Any] | None = None) -> dict[str, Any]:
    result = CandidateSandbox().scan_candidate_payload(
        {"files": [{"relative_path": "candidate/top.cpp", "content": payload}]}, contract
    )
    return _error("PermissionDeniedError", result) if result["status"] == "invalid" else {"accepted": True}


def _build_probes(work: Path) -> dict[str, Callable[[], dict[str, Any]]]:
    def schema(task: dict[str, Any]) -> dict[str, Any]:
        normalize_operator_task(task)
        return {"accepted": True}

    def contract(required: list[str], source: str, signature: str | None = None) -> dict[str, Any]:
        candidate = work / ("contract_" + str(len(list(work.glob("contract_*")))))
        candidate.mkdir(exist_ok=True)
        (candidate / "top.cpp").write_text(source, encoding="utf-8")
        result = validate_candidate_contract(candidate, {"required_files": required, "signature": signature})
        return result.get("error") or {"accepted": True}

    def csim(name: str, text: str) -> dict[str, Any]:
        path = work / name
        path.write_text(text, encoding="utf-8")
        result = parse_csim_verification(path)
        return _error("VerificationFailedError", result, artifact_evidence=str(path)) if result.get("passed") is not True else {"accepted": True}

    def compiler_error() -> dict[str, Any]:
        path = work / "compiler_error.log"
        path.write_text("INFO: command returned 0\nERROR: compilation failed\n", encoding="utf-8")
        parsed = VivadoHLSAdapter(mock_mode=False).parse_log({"log_path": str(path)})
        return _error("VivadoSynthesisError", parsed, artifact_evidence=str(path)) if parsed["errors"] else {"accepted": True}

    def missing_timing() -> dict[str, Any]:
        path = work / "missing_timing.rpt"
        path.write_text("| 10 | 10 | 1 | 1 | none |\n|Total | 0 | 1 | 10 | 20 |\n", encoding="utf-8")
        result = parse_csynth_report_file(str(path))
        return result.get("error") or {"accepted": True}

    def stale() -> dict[str, Any]:
        current, old = work / "current", work / "old"
        current.mkdir(exist_ok=True); old.mkdir(exist_ok=True)
        report = old / "stale.rpt"; report.write_text("stale", encoding="utf-8")
        assessment = assess_tool_evidence("vivado.run_csynth", {"report_path": str(report)}, {"run_dir": current}, mock_evidence=False)
        return _error("ToolPostconditionError", assessment.to_dict()) if not assessment.valid else {"accepted": True}

    def missing_vivado() -> dict[str, Any]:
        adapter = VivadoHLSAdapter(mock_mode=False, vivado_hls_path=str(work / "missing_vivado_hls.bat"))
        adapter._binary_available = lambda: False  # Isolate the missing-binary branch from host auto-discovery.
        tcl = work / "missing.tcl"
        tcl.write_text("csynth_design\n", encoding="utf-8")
        result = adapter.run_csynth({"work_dir": str(work), "tcl_path": str(tcl), "top_function": "top"})
        return result.get("error") or {"accepted": True}

    def timeout() -> dict[str, Any]:
        registry = ToolRegistry()
        registry.register(ToolSpec("probe.timeout", "timeout", {}, {}, "read", lambda arguments, context: (time.sleep(0.02) or {"status": "success"}), timeout_seconds=0.001))
        result = registry.call("probe.timeout", {}, {"run_id": "bad_17"})
        return result.get("error") or {"accepted": True}

    def timing_failure() -> dict[str, Any]:
        task = {"task_type": "operator", "name": "timing", "op_type": "Dense"}
        state = AgentState("timing", task, status="success")
        state.selected_path = "llm_candidate_path"; state.hls_project_dir = str(work)
        state.verification = {"passed": True}; state.report = {"status": "success", "timing": {"met": False}}
        state.todos = [TodoItem(id="t1", title="validate", description="validate", status="completed", priority=1, dependencies=[], assigned_tool="task.validate_schema", assigned_specialist=None, inputs={}, outputs={}, error=None)]
        gate = CompletionGate().evaluate(state, GoalContractBuilder().build(task), [])
        return _error("VivadoSynthesisError", gate) if gate["recommended_status"] != "success" else {"accepted": True}

    def max_repairs() -> dict[str, Any]:
        supervisor = ProgressSupervisor(replan_after=2, terminate_after=3)
        state = AgentState("repair", {"task_type": "operator", "op_type": "Dense"})
        todo = TodoItem(id="t", title="verify", description="verify", status="failed", priority=1, dependencies=[], assigned_tool="verify_candidate.run", assigned_specialist=None, inputs={}, outputs=None, error={"error_type": "VerificationFailedError"})
        state.todos = [todo]
        decisions = [supervisor.observe(state, todo, {"status": "failed", "observation": {"error": {"error_type": "VerificationFailedError", "message": "same"}}})["decision"] for _ in range(3)]
        return _error("VerificationFailedError", decisions, attempt_count=3) if decisions[-1] == "terminate" else {"accepted": True}

    def fake_metrics() -> dict[str, Any]:
        result = {"status": "success", "latency": {}, "resources": {}, "timing": {}}
        receipt = ToolPostconditionRegistry().verify("vivado.parse_report", {"report_path": str(work / "missing.rpt")}, result, {"run_dir": work})
        return _error("ToolPostconditionError", receipt) if not receipt["valid"] else {"accepted": True}

    return {
        "bad_01": lambda: schema({"op_type": "MatMul", "input_shape": [4, 8], "weight_shape": [7, 2], "output_shape": [4, 2], "dtype": "ap_fixed<12,4>"}),
        "bad_02": lambda: schema({"op_type": "Add", "input_shape": [16], "dtype": "float32"}),
        "bad_03": lambda: schema({"op_type": "ReLU", "input_shape": ["N"], "dtype": "ap_fixed<12,4>"}),
        "bad_04": lambda: _sandbox("void top(int n){ float *x = new float[n]; }"),
        "bad_05": lambda: _sandbox("#include <winsock2.h>\nvoid top(){ system(\"x\"); }"),
        "bad_06": lambda: _sandbox("#pragma HLS INTERFACE m_axi port=x\nvoid top(){}", contract={"data_bitwidth": 10}),
        "bad_07": lambda: _sandbox("void top(){\nfloat x[1024];\n#pragma HLS ARRAY_PARTITION variable=x complete\n}"),
        "bad_08": lambda: contract(["candidate/top.h", "candidate/top.cpp"], "void top(){}"),
        "bad_09": lambda: contract(["candidate/top.cpp"], "void wrong(){}", "void expected()"),
        "bad_10": lambda: csim("compile_fail.log", "ERROR: compilation failed\ncsim_design failed"),
        "bad_11": lambda: csim("missing_marker.log", "Starting C simulation\nCSim finished"),
        "bad_12": lambda: csim("numeric_mismatch.log", "Starting C simulation\nGOLDEN_CHECK_FAILED\nmismatch"),
        "bad_13": compiler_error,
        "bad_14": missing_timing,
        "bad_15": stale,
        "bad_16": missing_vivado,
        "bad_17": timeout,
        "bad_18": timing_failure,
        "bad_19": max_repairs,
        "bad_20": fake_metrics,
    }


def _stage(case_id: str) -> str:
    number = int(case_id.split("_")[1])
    return "task_validation" if number <= 3 else "candidate_guard" if number <= 9 else "verification" if number <= 12 else "synthesis_or_evidence"
