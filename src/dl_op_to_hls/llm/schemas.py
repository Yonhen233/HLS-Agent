from __future__ import annotations

from typing import Any


TASK_INTERPRETATION_SCHEMA: dict[str, Any] = {
    "title": "TaskInterpretationSchema",
    "type": "object",
    "required": ["task", "assumptions", "reason_summary"],
    "properties": {
        "task": {
            "type": "object",
            "required": ["task_type", "name", "target", "objective"],
            "properties": {
                "task_type": {"type": "string", "enum": ["model", "operator", "hls_project"]},
                "name": {"type": "string"},
                "op_type": {"type": "string"},
                "model_path": {"type": "string"},
                "frontend": {"type": "string"},
                "hls_project_dir": {"type": "string"},
                "top_function": {"type": "string"},
                "input_shape": {"type": "array"},
                "weight_shape": {"type": "array"},
                "output_shape": {"type": "array"},
                "dtype": {"type": "string"},
                "group": {"type": "integer"},
                "target": {
                    "type": "object",
                    "required": ["backend", "part", "clock_period"],
                    "properties": {
                        "backend": {"type": "string"},
                        "part": {"type": "string"},
                        "clock_period": {"type": "number"},
                    },
                },
                "objective": {"type": "string", "enum": ["standard", "latency", "throughput", "resource", "balanced", "performance"]},
            },
        },
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "reason_summary": {"type": "string"},
    },
    "examples": [
        {
            "task": {
                "task_type": "operator",
                "name": "dense_12x20",
                "op_type": "Dense",
                "input_shape": [12],
                "output_shape": [20],
                "dtype": "ap_fixed<12,4>",
                "target": {"backend": "VivadoHLS", "part": "xc7z020clg400-1", "clock_period": 10},
                "objective": "latency",
            },
            "assumptions": ["Shapes are static at synthesis time."],
            "reason_summary": "Normalized a static Dense deployment request.",
        }
    ],
}

TODO_PLAN_SCHEMA: dict[str, Any] = {
    "title": "TodoPlan",
    "type": "object",
    "required": ["selected_skill", "skill_usage", "todos", "reason_summary"],
    "properties": {
        "selected_skill": {"type": "string"},
        "skill_usage": {"type": "string", "enum": ["strict", "adapted"]},
        "reason_summary": {"type": "string"},
        "todos": {
            "type": "array",
            "minItems": 1,
            "maxItems": 8,
            "items": {
                "type": "object",
                "required": ["title", "assigned_tool", "assigned_specialist", "dependencies", "inputs"],
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "assigned_tool": {"type": ["string", "null"]},
                    "assigned_specialist": {"type": ["string", "null"]},
                    "dependencies": {"type": "array", "items": {"type": "string"}},
                    "inputs": {"type": "object"},
                },
            },
        },
    },
    "examples": [
        {
            "selected_skill": "llm_candidate_operator_flow",
            "skill_usage": "adapted",
            "reason_summary": "Generate, verify, synthesize, and report one static operator candidate.",
            "todos": [
                {
                    "title": "Generate candidate",
                    "assigned_tool": "llm.generate_candidate",
                    "assigned_specialist": "VerificationSpecialist",
                    "dependencies": [],
                    "inputs": {},
                }
            ],
        }
    ],
}

REACT_DECISION_SCHEMA: dict[str, Any] = {
    "title": "MainAgentReActDecision",
    "type": "object",
    "required": ["reason_summary", "decision"],
    "properties": {
        "reason_summary": {"type": "string"},
        "decision": {
            "type": "string",
            "enum": [
                "delegate_to_specialist",
                "direct_tool_only_when_no_specialist",
                "request_replan",
                "mark_blocked",
                "mark_failed",
            ],
        },
        "action": {"type": "object"},
        "expected_observation": {"type": "string"},
        "fallback_if_failed": {"type": "string"},
    },
    "examples": [
        {
            "reason_summary": "This todo is assigned to VivadoSpecialist, so Main Agent must delegate instead of calling vivado tools.",
            "decision": "delegate_to_specialist",
            "action": {"specialist_name": "VivadoSpecialist"},
            "expected_observation": "SpecialistResult with metrics or structured error.",
        },
        {
            "reason_summary": "This atomic todo has no specialist route and can use the direct validation tool.",
            "decision": "direct_tool_only_when_no_specialist",
            "action": {"tool_name": "task.validate_schema", "arguments": {}},
            "expected_observation": "Validated task schema.",
        },
    ],
}

SPECIALIST_REACT_DECISION_SCHEMA: dict[str, Any] = {
    "title": "SpecialistLocalReActDecision",
    "type": "object",
    "required": ["reason_summary", "decision"],
    "properties": {
        "reason_summary": {"type": "string"},
        "decision": {"type": "string", "enum": ["call_tool", "mark_blocked", "mark_failed", "finish_with_result"]},
        "action": {"type": "object"},
        "expected_observation": {"type": "string"},
    },
}

REFLECTION_DECISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["reason_summary", "decision", "todo_status", "run_status", "new_todos", "memory_candidates"],
    "properties": {
        "reason_summary": {"type": "string"},
        "decision": {"type": "string"},
        "todo_status": {"type": "string"},
        "run_status": {"type": "string"},
        "new_todos": {"type": "array"},
        "memory_candidates": {"type": "array"},
    },
}

OPTIMIZATION_SUGGESTION_SCHEMA: dict[str, Any] = {
    "title": "OptimizationSuggestionSchema",
    "type": "object",
    "required": ["summary", "suggestions", "memory_used"],
    "properties": {
        "summary": {"type": "string"},
        "suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["title", "reason", "expected_tradeoff", "confidence"],
                "properties": {
                    "title": {"type": "string"},
                    "reason": {"type": "string"},
                    "expected_tradeoff": {"type": "string"},
                    "confidence": {"type": "number"},
                },
            },
        },
        "memory_used": {"type": "array"},
    },
}

CANDIDATE_GENERATION_SCHEMA: dict[str, Any] = {
    "title": "CandidateGenerationSchema",
    "type": "object",
    "required": ["candidate_name", "files", "assumptions", "requires_verification"],
    "properties": {
        "candidate_name": {"type": "string"},
        "files": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["relative_path", "content"],
                "properties": {
                    "relative_path": {
                        "type": "string",
                        "description": "Relative path under candidate/, for example candidate/scale_shift_llm.cpp.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Complete file content; no placeholders.",
                    },
                    "role": {
                        "type": "string",
                        "enum": ["hls_header", "hls_cpp", "testbench", "tcl", "note"],
                    },
                },
            },
        },
        "assumptions": {"type": "array"},
        "requires_verification": {"type": "boolean"},
    },
    "examples": [
        {
            "candidate_name": "scale_shift_llm",
            "files": [
                {
                    "relative_path": "candidate/scale_shift_llm.h",
                    "role": "hls_header",
                    "content": "#ifndef SCALE_SHIFT_LLM_H\n#define SCALE_SHIFT_LLM_H\n#include \"ap_fixed.h\"\ntypedef ap_fixed<16,6> data_t;\nvoid scale_shift_llm(data_t input[16], data_t output[16]);\n#endif\n",
                },
                {
                    "relative_path": "candidate/scale_shift_llm.cpp",
                    "role": "hls_cpp",
                    "content": "#include \"scale_shift_llm.h\"\nvoid scale_shift_llm(data_t input[16], data_t output[16]) {\n  for (int i = 0; i < 16; ++i) {\n#pragma HLS PIPELINE II=1\n    output[i] = input[i] * (data_t)2 + (data_t)1;\n  }\n}\n",
                },
                {
                    "relative_path": "candidate/testbench.cpp",
                    "role": "testbench",
                    "content": "#include \"scale_shift_llm.h\"\n#include <cstdio>\nint main() { data_t input[16]; data_t output[16]; int failed = 0; for (int i = 0; i < 16; ++i) { input[i] = (data_t)(i - 8); } scale_shift_llm(input, output); for (int i = 0; i < 16; ++i) { data_t expected = input[i] * (data_t)2 + (data_t)1; double diff = (double)(output[i] - expected); if (diff < 0) diff = -diff; if (diff > 0.001) { std::printf(\"GOLDEN_CHECK_FAILED %d\\n\", i); failed = 1; } } if (failed) return 1; std::printf(\"GOLDEN_CHECK_PASSED\\n\"); return 0; }\n",
                },
            ],
            "assumptions": ["Static shape [16]."],
            "requires_verification": True,
        }
    ],
}


def validate_required(payload: dict[str, Any], schema: dict[str, Any]) -> None:
    """Validate the JSON-schema subset used by Agent control-plane contracts."""

    def validate(value: Any, node: dict[str, Any], path: str) -> None:
        expected = node.get("type")
        allowed_types = expected if isinstance(expected, list) else [expected] if expected else []
        type_checks = {
            "object": lambda item: isinstance(item, dict),
            "array": lambda item: isinstance(item, list),
            "string": lambda item: isinstance(item, str),
            "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
            "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
            "boolean": lambda item: isinstance(item, bool),
            "null": lambda item: item is None,
        }
        if allowed_types and not any(type_checks[item](value) for item in allowed_types if item in type_checks):
            raise ValueError(f"Invalid type at {path}: expected {allowed_types}, got {type(value).__name__}")
        if "enum" in node and value not in node["enum"]:
            raise ValueError(f"Invalid enum at {path}: {value!r} not in {node['enum']}")
        if isinstance(value, dict):
            for key in node.get("required", []):
                if key not in value:
                    raise ValueError(f"Missing required key: {path}.{key}")
            properties = node.get("properties", {})
            for key, child in properties.items():
                if key in value:
                    validate(value[key], child, f"{path}.{key}")
        if isinstance(value, list) and isinstance(node.get("items"), dict):
            for index, item in enumerate(value):
                validate(item, node["items"], f"{path}[{index}]")

    validate(payload, schema, "$")
