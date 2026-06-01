from __future__ import annotations

from pathlib import Path
from typing import Any

from ..schemas.report_schema import empty_report
from .base import BaseSpecialist
from .context import ContextEnvelope
from .result import SpecialistResult


class VivadoSpecialist(BaseSpecialist):
    name = "VivadoSpecialist"
    description = "Handles Vivado HLS project creation, csim/csynth, report parsing, and log summaries."
    allowed_tools = [
        "vivado.create_project",
        "vivado.create_vivado_project",
        "vivado.run_csim",
        "vivado.run_csynth",
        "vivado.parse_report",
        "vivado.parse_csynth_report",
        "vivado.parse_log",
        "vivado.parse_vivado_log",
    ]

    def can_handle(self, todo) -> bool:
        return bool(todo.assigned_tool and todo.assigned_tool.startswith("vivado."))

    def handle(self, envelope: ContextEnvelope, tool_registry, permission_gate) -> SpecialistResult:
        title = envelope.task_summary.get("todo_title") or ""
        if "Parse synthesis report" in title:
            return self._handle_parse_report(envelope, tool_registry, permission_gate)
        return self._handle_synthesis(envelope, tool_registry, permission_gate)

    def _handle_synthesis(self, envelope: ContextEnvelope, tool_registry, permission_gate) -> SpecialistResult:
        scoped = envelope.scoped_state
        observations: list[dict[str, Any]] = []
        artifacts: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        hls_project_dir = scoped.get("hls_project_dir")

        run_dir = Path(self.runtime_context.get("run_dir", "."))
        work_dir = scoped.get("work_dir") or str(run_dir / "vivado_hls")
        create_args = {
            "hls_project_dir": hls_project_dir,
            "top_function": scoped.get("top_function"),
            "part": scoped.get("part") or "xc7z020clg400-1",
            "clock_period": scoped.get("clock_period") or 5,
            "work_dir": work_dir,
        }
        create_decision = self._local_react_step(envelope, observations, "vivado.create_project", create_args)
        if create_decision["decision"] == "mark_blocked":
            result = self._blocked_result_from_decision(envelope, observations, create_decision)
            result.suggested_todos = [{"title": "Generate LLM candidate", "assigned_specialist": None}]
            return self._finalize_result(envelope, result)
        if create_decision["decision"] == "mark_failed":
            return self._finalize_result(envelope, self._failed_result_from_decision(envelope, observations, create_decision))
        create_action = create_decision.get("action") or {}
        create_result = self._call_tool(
            create_action.get("tool_name") or create_action.get("tool") or "vivado.create_project",
            create_action.get("arguments") or create_args,
            envelope,
            tool_registry,
            permission_gate,
        )
        observations.append({"tool": "vivado.create_project", "result": self._compress_result(create_result)})
        if create_result.get("status") != "success":
            errors.append(create_result.get("error", {}))
            return self._finalize_result(
                envelope,
                SpecialistResult(
                    specialist_name=self.name,
                    todo_id=envelope.todo_id,
                    status="failed",
                    summary="Vivado project creation failed.",
                    observations=observations,
                    errors=errors,
                ),
            )

        if create_result.get("tcl_path"):
            artifacts.append({"type": "tcl", "path": create_result["tcl_path"]})
        csynth_args = {
            "work_dir": create_result.get("work_dir"),
            "tcl_path": create_result.get("tcl_path"),
            "top_function": create_result.get("top_function"),
        }
        csynth_decision = self._local_react_step(envelope, observations, "vivado.run_csynth", csynth_args)
        if csynth_decision["decision"] == "mark_blocked":
            return self._finalize_result(envelope, self._blocked_result_from_decision(envelope, observations, csynth_decision))
        if csynth_decision["decision"] == "mark_failed":
            return self._finalize_result(envelope, self._failed_result_from_decision(envelope, observations, csynth_decision))
        csynth_action = csynth_decision.get("action") or {}
        csynth_result = self._call_tool(
            csynth_action.get("tool_name") or csynth_action.get("tool") or "vivado.run_csynth",
            csynth_action.get("arguments") or csynth_args,
            envelope,
            tool_registry,
            permission_gate,
        )
        observations.append({"tool": "vivado.run_csynth", "result": self._compress_result(csynth_result)})
        if csynth_result.get("log_path"):
            artifacts.append({"type": "vivado_log", "path": csynth_result["log_path"]})
        if csynth_result.get("status") != "success":
            error = csynth_result.get("error", {})
            errors.append(error)
            summary = error.get("message", "Vivado synthesis was skipped or failed.")
            status = "partial_success" if error.get("recoverable", True) else "failed"
            return self._finalize_result(
                envelope,
                SpecialistResult(
                    specialist_name=self.name,
                    todo_id=envelope.todo_id,
                    status=status,
                    summary=summary,
                    observations=observations,
                    errors=errors,
                    metrics=empty_report("skipped") if status == "partial_success" else None,
                ),
            )

        report_path = csynth_result.get("report_path")
        metrics = None
        if report_path:
            artifacts.append({"type": "vivado_report", "path": report_path})
            parse_args = {"report_path": report_path}
            parse_decision = self._local_react_step(envelope, observations, "vivado.parse_report", parse_args)
            if parse_decision["decision"] == "mark_blocked":
                return self._finalize_result(envelope, self._blocked_result_from_decision(envelope, observations, parse_decision))
            if parse_decision["decision"] == "mark_failed":
                return self._finalize_result(envelope, self._failed_result_from_decision(envelope, observations, parse_decision))
            parse_action = parse_decision.get("action") or {}
            parse_result = self._call_tool(
                parse_action.get("tool_name") or parse_action.get("tool") or "vivado.parse_report",
                parse_action.get("arguments") or parse_args,
                envelope,
                tool_registry,
                permission_gate,
            )
            observations.append({"tool": "vivado.parse_report", "result": self._compress_result(parse_result)})
            if parse_result.get("status") == "success":
                metrics = parse_result
            else:
                warnings.append({"message": "Vivado report parsing did not produce metrics.", "result": parse_result})
        result = SpecialistResult(
            specialist_name=self.name,
            todo_id=envelope.todo_id,
            status="success",
            summary="Vivado HLS synthesis completed and metrics were parsed.",
            observations=observations,
            metrics=metrics,
            artifacts=artifacts,
            warnings=warnings,
        )
        return self._finalize_result(envelope, result)

    def _handle_parse_report(self, envelope: ContextEnvelope, tool_registry, permission_gate) -> SpecialistResult:
        report = envelope.scoped_state.get("current_report")
        if report and report.get("status") == "success":
            result = SpecialistResult(
                specialist_name=self.name,
                todo_id=envelope.todo_id,
                status="success",
                summary="Synthesis report metrics were already available.",
                metrics=report,
            )
            return self._finalize_result(envelope, result)
        result = SpecialistResult(
            specialist_name=self.name,
            todo_id=envelope.todo_id,
            status="skipped",
            summary="No parseable synthesis report was available.",
        )
        return self._finalize_result(envelope, result)

    def _compress_result(self, result: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in result.items() if key not in {"stdout", "stderr", "raw_log", "content"}}
