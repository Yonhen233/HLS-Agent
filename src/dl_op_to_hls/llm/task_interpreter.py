from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import prompts
from .schemas import TASK_INTERPRETATION_SCHEMA
from .trace import emit_llm_event


class LLMTaskInterpreter:
    def interpret(self, input_data: str | dict[str, Any], client) -> dict[str, Any]:
        if isinstance(input_data, dict):
            payload = {"task": input_data, "assumptions": [], "reason_summary": "Task input was already structured JSON."}
            emit_llm_event(client.context, "LLMTaskInterpreted", {"run_id": client.context.get("run_id"), "input_mode": "json"})
            return payload
        candidate_path = Path(input_data)
        if candidate_path.exists() and candidate_path.is_file():
            parsed = json.loads(candidate_path.read_text(encoding="utf-8"))
            payload = {"task": parsed, "assumptions": [], "reason_summary": "Loaded JSON task from file path."}
            emit_llm_event(client.context, "LLMTaskInterpreted", {"run_id": client.context.get("run_id"), "input_mode": "json_file"})
            return payload
        session_context = client.context.get("session_context") if isinstance(client.context, dict) else None
        user_payload: Any = input_data
        if session_context and (session_context.get("summary") or session_context.get("last_task")):
            user_payload = json.dumps(
                {
                    "current_user_request": input_data,
                    "previous_task": session_context.get("last_task"),
                    "conversation_summary": session_context.get("summary", ""),
                    "recent_messages": session_context.get("recent_messages", [])[-6:],
                    "instruction": "Interpret the current request in context and return a complete normalized task, not a delta.",
                },
                ensure_ascii=False,
            )
        result = client.complete_json(
            system_prompt=prompts.resolve_prompt(client.context, "task_interpreter"),
            user_prompt=user_payload,
            schema=TASK_INTERPRETATION_SCHEMA,
            temperature=0.0,
        )
        result = self._canonicalize_task_fields(result)
        emit_llm_event(client.context, "LLMTaskInterpreted", {"run_id": client.context.get("run_id"), "input_mode": "natural_language"})
        return result

    @staticmethod
    def _canonicalize_task_fields(result: dict[str, Any]) -> dict[str, Any]:
        """Normalize common model aliases without changing the requested workload."""
        normalized = dict(result)
        task = normalized.get("task")
        if not isinstance(task, dict):
            return normalized
        task = dict(task)
        source = task.get("source") if isinstance(task.get("source"), dict) else {}
        source_format = str(source.get("format") or "").lower()
        source_path = source.get("path")
        model_path = task.get("model_path") or source_path
        suffix = Path(str(model_path or "")).suffix.lower()
        model_frontends = {".onnx": "onnx", ".h5": "keras", ".keras": "keras"}
        frontend = source_format or model_frontends.get(suffix)
        if frontend in {"onnx", "qonnx", "keras", "qkeras"} and model_path:
            task["task_type"] = "model"
            task["model_path"] = str(model_path)
            task["frontend"] = frontend
            task.pop("hls_project_dir", None)
            task.pop("top_function", None)
            task.pop("source", None)
            constraints = task.get("constraints") if isinstance(task.get("constraints"), dict) else {}
            if constraints.get("stability") and constraints.get("maintainability"):
                task["objective"] = "standard"
            assumptions = list(normalized.get("assumptions") or [])
            note = f"Canonicalized {frontend} source fields into the model task contract."
            if note not in assumptions:
                assumptions.append(note)
            normalized["assumptions"] = assumptions
        normalized["task"] = task
        return normalized
