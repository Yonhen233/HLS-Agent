from __future__ import annotations

from typing import Any

from .base import BaseSpecialist
from .context import ContextEnvelope
from .result import SpecialistResult


class HLS4MLSpecialist(BaseSpecialist):
    name = "HLS4MLSpecialist"
    description = "Handles hls4ml model inspection, support checks, config generation, and conversion."
    allowed_tools = [
        "hls4ml.inspect_model",
        "hls4ml.check_support",
        "hls4ml.check_hls4ml_support",
        "hls4ml.generate_config",
        "hls4ml.generate_hls4ml_config",
        "hls4ml.convert",
        "hls4ml.convert_with_hls4ml",
        "hls4ml.run_csim",
        "hls4ml.run_hls4ml_csim",
    ]

    def can_handle(self, todo) -> bool:
        return bool(todo.assigned_tool and todo.assigned_tool.startswith("hls4ml."))

    def handle(self, envelope: ContextEnvelope, tool_registry, permission_gate) -> SpecialistResult:
        tool = self._select_tool(envelope)
        args = self._arguments_for_tool(tool, envelope)
        observations: list[dict[str, Any]] = []
        decision = self._local_react_step(envelope, observations, tool, args)
        if decision["decision"] == "mark_blocked":
            return self._finalize_result(envelope, self._blocked_result_from_decision(envelope, observations, decision))
        if decision["decision"] == "mark_failed":
            return self._finalize_result(envelope, self._failed_result_from_decision(envelope, observations, decision))
        if decision["decision"] == "finish_with_result":
            return self._finalize_result(
                envelope,
                SpecialistResult(
                    specialist_name=self.name,
                    todo_id=envelope.todo_id,
                    status="success",
                    summary=decision.get("reason_summary") or "hls4ml specialist finished without tool call.",
                    observations=observations,
                ),
            )
        action = decision.get("action") or {}
        tool = action.get("tool_name") or action.get("tool") or tool
        args = action.get("arguments") or args
        result = self._call_tool(tool, args, envelope, tool_registry, permission_gate)
        observations.append({"tool": tool, "result": self._compress_result(result)})
        errors = [result["error"]] if result.get("status") == "error" and result.get("error") else []
        warnings: list[dict[str, Any]] = []
        artifacts: list[dict[str, Any]] = []
        status = "success"
        summary = "hls4ml step completed."

        if tool in {"hls4ml.check_support", "hls4ml.check_hls4ml_support"}:
            support_status = result.get("status")
            if support_status == "unsupported":
                status = "partial_success"
                summary = result.get("recommendation") or "Task is not directly supported by hls4ml."
                warnings.append({"message": summary, "unsupported_layers": result.get("unsupported_layers", [])})
            elif support_status == "supported":
                summary = "Task is supported by hls4ml."
            elif support_status in {"partially_supported", "not_recommended"}:
                status = "partial_success"
                summary = result.get("recommendation") or "Task is only partially supported by hls4ml."
                warnings.append(
                    {
                        "message": summary,
                        "support_status": support_status,
                        "unsupported_layers": result.get("unsupported_layers", []),
                    }
                )
            else:
                status = "failed"
                summary = "hls4ml support check failed."
        elif tool in {"hls4ml.generate_config", "hls4ml.generate_hls4ml_config"}:
            summary = "Generated hls4ml config." if result.get("status") == "success" else "hls4ml config generation failed."
            if result.get("config_path"):
                artifacts.append({"type": "hls4ml_config", "path": result["config_path"]})
        elif tool in {"hls4ml.convert", "hls4ml.convert_with_hls4ml"}:
            summary = "Converted model to an hls4ml HLS project." if result.get("status") == "success" else "hls4ml conversion failed."
            if result.get("hls_project_dir"):
                artifacts.append({"type": "hls_project", "path": result["hls_project_dir"]})
            if result.get("log_path"):
                artifacts.append({"type": "hls4ml_log", "path": result["log_path"]})
            reference = result.get("reference_data") or {}
            for key in ("input_path", "output_path", "manifest_path"):
                if reference.get(key):
                    artifacts.append({"type": "reference_data", "path": reference[key], "role": key})
            if reference.get("status") == "error":
                warnings.append({"message": "Reference data generation failed.", "error": reference.get("error")})
        elif tool in {"hls4ml.run_csim", "hls4ml.run_hls4ml_csim"}:
            summary = "hls4ml csim completed." if result.get("status") == "success" else "hls4ml csim failed."
            if result.get("log_path"):
                artifacts.append({"type": "hls4ml_log", "path": result["log_path"]})
        elif tool == "hls4ml.inspect_model":
            summary = "Inspected model structure." if result.get("status") == "success" else "Model inspection failed."

        if result.get("status") == "error":
            status = "failed"
        specialist_result = SpecialistResult(
            specialist_name=self.name,
            todo_id=envelope.todo_id,
            status=status,
            summary=summary,
            observations=observations,
            artifacts=artifacts,
            errors=errors,
            warnings=warnings,
            suggested_todos=self._suggested_todos(tool, result),
        )
        return self._finalize_result(envelope, specialist_result)

    def _select_tool(self, envelope: ContextEnvelope) -> str:
        title = envelope.task_summary.get("todo_title") or ""
        scoped = envelope.scoped_state
        if "Inspect" in title:
            return "hls4ml.inspect_model"
        if "config" in title:
            return scoped.get("assigned_tool") or "hls4ml.generate_config"
        if "Convert" in title:
            return scoped.get("assigned_tool") or "hls4ml.convert"
        return scoped.get("assigned_tool") or "hls4ml.check_support"

    def _arguments_for_tool(self, tool: str, envelope: ContextEnvelope) -> dict[str, Any]:
        scoped = envelope.scoped_state
        task = scoped.get("task") or {}
        if tool == "hls4ml.inspect_model":
            return {"model_path": scoped.get("model_path"), "frontend": scoped.get("frontend") or "onnx"}
        if tool in {"hls4ml.check_support", "hls4ml.check_hls4ml_support"}:
            return {"task": task}
        if tool in {"hls4ml.generate_config", "hls4ml.generate_hls4ml_config"}:
            args = {
                "model_path": scoped.get("model_path"),
                "frontend": scoped.get("frontend") or "onnx",
                "backend": scoped.get("backend") or "Vivado",
                "part": scoped.get("part") or "xc7z020clg400-1",
                "clock_period": scoped.get("clock_period") or 5,
                "precision": scoped.get("precision") or "fixed<16,6>",
                "reuse_factor": scoped.get("reuse_factor") or 1,
                "strategy": scoped.get("strategy") or "Latency",
                "output_dir": scoped.get("run_dir"),
            }
            if scoped.get("io_type"):
                args["io_type"] = scoped["io_type"]
            if scoped.get("layer_overrides"):
                args["layer_overrides"] = scoped["layer_overrides"]
            if scoped.get("model_overrides"):
                args["model_overrides"] = scoped["model_overrides"]
            return args
        if tool in {"hls4ml.run_csim", "hls4ml.run_hls4ml_csim"}:
            return {"hls_project_dir": scoped.get("hls_project_dir")}
        return {
            "model_path": scoped.get("model_path"),
            "frontend": scoped.get("frontend") or "onnx",
            "config_path": scoped.get("hls4ml_config_path"),
            "output_dir": f"{scoped.get('run_dir')}/hls_project",
            "reference_data": task.get("reference_data") or {},
        }

    def _compress_result(self, result: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in result.items()
            if key not in {"stdout", "stderr", "raw_log", "content"}
        }

    def _suggested_todos(self, tool: str, result: dict[str, Any]) -> list[dict[str, Any]]:
        if tool in {"hls4ml.check_support", "hls4ml.check_hls4ml_support"} and result.get("status") == "unsupported":
            return [
                {"title": "Try graph rewrite", "assigned_specialist": None},
                {"title": "Generate fallback HLS template", "assigned_specialist": None},
            ]
        if tool in {"hls4ml.check_support", "hls4ml.check_hls4ml_support"} and result.get("status") == "partially_supported":
            return [
                {"title": "Try graph rewrite", "assigned_specialist": None},
                {"title": "Generate unsupported report", "assigned_specialist": None},
            ]
        if tool in {"hls4ml.check_support", "hls4ml.check_hls4ml_support"} and result.get("status") == "not_recommended":
            return [{"title": "Generate unsupported report", "assigned_specialist": None}]
        if tool in {"hls4ml.convert", "hls4ml.convert_with_hls4ml"} and result.get("status") == "success":
            return [{"title": "Run Vivado HLS synthesis", "assigned_specialist": "VivadoSpecialist"}]
        return []
