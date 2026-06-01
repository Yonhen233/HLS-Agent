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
        result = client.complete_json(
            system_prompt=prompts.TASK_INTERPRETER_SYSTEM_PROMPT,
            user_prompt=input_data,
            schema=TASK_INTERPRETATION_SCHEMA,
            temperature=0.0,
        )
        emit_llm_event(client.context, "LLMTaskInterpreted", {"run_id": client.context.get("run_id"), "input_mode": "natural_language"})
        return result
