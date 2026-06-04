from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.errors import build_error
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
        title = (envelope.task_summary.get("todo_title") or "").lower()
        assigned_tool = envelope.task_summary.get("assigned_tool") or envelope.scoped_state.get("assigned_tool")
        if assigned_tool in {"vivado.create_project", "vivado.create_vivado_project"}:
            return self._handle_create_project(envelope, tool_registry, permission_gate)
        if assigned_tool in {"vivado.parse_report", "vivado.parse_csynth_report"} or "parse" in title and "report" in title:
            return self._handle_parse_report(envelope, tool_registry, permission_gate)
        if assigned_tool in {"vivado.parse_log", "vivado.parse_vivado_log"} or "parse" in title and "log" in title:
            return self._handle_parse_log(envelope, tool_registry, permission_gate)
        return self._handle_synthesis(envelope, tool_registry, permission_gate)

    def _create_project_args(self, envelope: ContextEnvelope) -> dict[str, Any]:
        scoped = envelope.scoped_state
        run_dir = Path(self.runtime_context.get("run_dir", "."))
        work_dir = scoped.get("work_dir") or str(run_dir / "vivado_hls")
        return {
            "hls_project_dir": scoped.get("hls_project_dir"),
            "top_function": scoped.get("top_function"),
            "part": scoped.get("part") or "xc7z020clg400-1",
            "clock_period": scoped.get("clock_period") or 5,
            "work_dir": work_dir,
        }

    def _handle_create_project(self, envelope: ContextEnvelope, tool_registry, permission_gate) -> SpecialistResult:
        observations: list[dict[str, Any]] = []
        artifacts: list[dict[str, Any]] = []
        create_args = self._create_project_args(envelope)
        if not create_args.get("hls_project_dir"):
            error = build_error(
                "HLS4MLConversionError",
                "Vivado project creation requires an HLS project directory, but none is available.",
                recoverable=True,
                source="vivado.create_project",
                suggested_action="Recover the hls4ml/fallback/candidate generation path before delegating to VivadoSpecialist.",
                details={"todo_id": envelope.todo_id, "specialist": self.name},
            ).to_dict()
            return self._finalize_result(
                envelope,
                SpecialistResult(
                    specialist_name=self.name,
                    todo_id=envelope.todo_id,
                    status="blocked",
                    summary=error["message"],
                    errors=[error],
                ),
            )
        decision = self._local_react_step(envelope, observations, "vivado.create_project", create_args)
        if decision["decision"] == "mark_blocked":
            return self._finalize_result(envelope, self._blocked_result_from_decision(envelope, observations, decision))
        if decision["decision"] == "mark_failed":
            return self._finalize_result(envelope, self._failed_result_from_decision(envelope, observations, decision))
        action = decision.get("action") or {}
        result = self._call_tool(
            action.get("tool_name") or action.get("tool") or "vivado.create_project",
            action.get("arguments") or create_args,
            envelope,
            tool_registry,
            permission_gate,
        )
        observations.append({"tool": "vivado.create_project", "result": self._compress_result(result)})
        if result.get("tcl_path"):
            artifacts.append({"type": "tcl", "path": result["tcl_path"]})
        status = "success" if result.get("status") == "success" else "failed"
        errors = [] if status == "success" else [result.get("error", {})]
        return self._finalize_result(
            envelope,
            SpecialistResult(
                specialist_name=self.name,
                todo_id=envelope.todo_id,
                status=status,
                summary="Vivado HLS project was created." if status == "success" else "Vivado project creation failed.",
                observations=observations,
                artifacts=artifacts,
                errors=errors,
            ),
        )

    def _handle_synthesis(self, envelope: ContextEnvelope, tool_registry, permission_gate) -> SpecialistResult:
        scoped = envelope.scoped_state
        observations: list[dict[str, Any]] = []
        artifacts: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        hls_project_dir = scoped.get("hls_project_dir")
        if not hls_project_dir:
            error = build_error(
                "HLS4MLConversionError",
                "Vivado synthesis requires an HLS project directory, but none is available.",
                recoverable=True,
                source="vivado.create_project",
                suggested_action="Recover the hls4ml/fallback/candidate generation path before delegating to VivadoSpecialist.",
                details={"todo_id": envelope.todo_id, "specialist": self.name},
            ).to_dict()
            result = SpecialistResult(
                specialist_name=self.name,
                todo_id=envelope.todo_id,
                status="blocked",
                summary=error["message"],
                observations=observations,
                errors=[error],
                suggested_todos=[
                    {
                        "title": "Generate unsupported report",
                        "assigned_tool": "report.write_unsupported",
                        "assigned_specialist": None,
                    }
                ],
            )
            return self._finalize_result(envelope, result)

        create_args = self._create_project_args(envelope)
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

    def _handle_parse_log(self, envelope: ContextEnvelope, tool_registry, permission_gate) -> SpecialistResult:
        log_path = self._artifact_path(envelope, "vivado_log")
        if not log_path:
            work_dir = envelope.scoped_state.get("work_dir")
            if work_dir:
                candidate = Path(work_dir) / "csynth.log"
                if candidate.exists():
                    log_path = str(candidate)
        if not log_path:
            result = SpecialistResult(
                specialist_name=self.name,
                todo_id=envelope.todo_id,
                status="skipped",
                summary="No Vivado log was available to parse.",
            )
            return self._finalize_result(envelope, result)
        observations: list[dict[str, Any]] = []
        args = {"log_path": log_path}
        decision = self._local_react_step(envelope, observations, "vivado.parse_log", args)
        if decision["decision"] == "mark_blocked":
            return self._finalize_result(envelope, self._blocked_result_from_decision(envelope, observations, decision))
        if decision["decision"] == "mark_failed":
            return self._finalize_result(envelope, self._failed_result_from_decision(envelope, observations, decision))
        action = decision.get("action") or {}
        result = self._call_tool(
            action.get("tool_name") or action.get("tool") or "vivado.parse_log",
            action.get("arguments") or args,
            envelope,
            tool_registry,
            permission_gate,
        )
        observations.append({"tool": "vivado.parse_log", "result": self._compress_result(result)})
        status = "success" if result.get("status") == "success" else "skipped"
        return self._finalize_result(
            envelope,
            SpecialistResult(
                specialist_name=self.name,
                todo_id=envelope.todo_id,
                status=status,
                summary=result.get("summary") or "Vivado log parsed.",
                observations=observations,
                warnings=[{"message": warning} for warning in result.get("warnings", [])],
            ),
        )

    def _artifact_path(self, envelope: ContextEnvelope, artifact_type: str) -> str | None:
        for ref in envelope.artifact_refs:
            if ref.get("type") == artifact_type and ref.get("path"):
                return ref["path"]
        return None

    def _compress_result(self, result: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in result.items() if key not in {"stdout", "stderr", "raw_log", "content"}}
