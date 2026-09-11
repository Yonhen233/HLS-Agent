"""skills layer implementation for extractor.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


class LegacyWorkflowExtractor:
    """Coordinate LegacyWorkflowExtractor within the extractor boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    def __init__(self, project_root: str | Path = "."):
        """Implement the internal __init__ helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            project_root: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        self.project_root = Path(project_root)

    def inspect_legacy_planner(self) -> dict[str, Any]:
        """Execute inspect_legacy_planner at the extractor boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Returns:
            The structured value promised by the function signature.
        """
        planner_path = self.project_root / "src" / "dl_op_to_hls" / "main_agent" / "planner.py"
        text = planner_path.read_text(encoding="utf-8") if planner_path.exists() else ""
        task_type_branches = re.findall(r'if task_type == "([^"]+)"', text)
        return {"path": str(planner_path), "task_type_branches": task_type_branches}

    def inspect_legacy_reflector(self) -> dict[str, Any]:
        """Execute inspect_legacy_reflector at the extractor boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Returns:
            The structured value promised by the function signature.
        """
        runtime_path = self.project_root / "src" / "dl_op_to_hls" / "main_agent" / "runtime.py"
        text = runtime_path.read_text(encoding="utf-8") if runtime_path.exists() else ""
        patterns = [
            "hls4ml_status\") == \"unsupported\"",
            "hls4ml_status\") == \"partially_supported\"",
            "VivadoNotFoundError",
            "VerificationFailedError",
        ]
        branches = [pattern for pattern in patterns if pattern in text]
        return {"path": str(runtime_path), "failure_branches": branches}

    def inspect_legacy_suggestions(self) -> dict[str, Any]:
        """Execute inspect_legacy_suggestions at the extractor boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Returns:
            The structured value promised by the function signature.
        """
        suggest_path = self.project_root / "src" / "dl_op_to_hls" / "tools" / "suggest_optimization.py"
        text = suggest_path.read_text(encoding="utf-8") if suggest_path.exists() else ""
        rules = []
        for token in ["latency", "resource", "timing", "reuse_factor", "pipeline", "DSP", "LUT"]:
            if token.lower() in text.lower():
                rules.append(token)
        return {"path": str(suggest_path), "rule_tokens": rules}

    def generate_skill_skeletons(self) -> list[dict[str, Any]]:
        """Execute generate_skill_skeletons at the extractor boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Returns:
            The structured value promised by the function signature.
        """
        planner = self.inspect_legacy_planner()
        reflector = self.inspect_legacy_reflector()
        suggestions = self.inspect_legacy_suggestions()
        skills = [
            {
                "name": "legacy_operator_flow",
                "description": "Extracted skeleton from deterministic operator planner/runtime path.",
                "intent": "operator_to_hls_fallback",
                "trigger": {"task_type": "operator"},
                "preconditions": ["task_schema_valid"],
                "recommended_todos": [
                    {"title": "Validate task schema", "assigned_tool": "task.validate_schema"},
                    {"title": "Check hls4ml support", "assigned_tool": "hls4ml.check_support"},
                    {"title": "Generate fallback HLS template", "assigned_tool": "fallback.generate_operator_hls"},
                    {"title": "Run Vivado HLS synthesis", "assigned_tool": "vivado.run_csynth"},
                    {"title": "Parse synthesis report", "assigned_tool": "vivado.parse_report"},
                    {"title": "Generate optimization suggestions", "assigned_tool": "suggestion.suggest_optimization"},
                ],
                "allowed_tools": [
                    "task.validate_schema",
                    "hls4ml.check_support",
                    "fallback.generate_operator_hls",
                    "vivado.run_csynth",
                    "vivado.parse_report",
                    "suggestion.suggest_optimization",
                ],
                "allowed_specialists": [
                    "HLS4MLSpecialist",
                    "VivadoSpecialist",
                    "OptimizationSpecialist",
                ],
                "required_artifacts": ["summary_md", "state_json", "trace_jsonl"],
                "failure_policy": {
                    "legacy_reflector_tokens": reflector.get("failure_branches", []),
                },
                "verification_policy": {"generated_code_requires_verification": True},
                "memory_policy": {"promote_metrics": True},
                "tags": ["legacy", "extracted"],
                "source": "legacy_extractor",
            },
            {
                "name": "legacy_model_flow",
                "description": "Extracted skeleton from deterministic model planner/runtime path.",
                "intent": "model_to_hls_hls4ml",
                "trigger": {"task_type": "model"},
                "preconditions": ["task_schema_valid"],
                "recommended_todos": [
                    {"title": "Validate task schema", "assigned_tool": "task.validate_schema"},
                    {"title": "Inspect model structure", "assigned_tool": "hls4ml.inspect_model"},
                    {"title": "Check hls4ml support", "assigned_tool": "hls4ml.check_support"},
                    {"title": "Generate hls4ml config", "assigned_tool": "hls4ml.generate_config"},
                    {"title": "Convert with hls4ml", "assigned_tool": "hls4ml.convert"},
                    {"title": "Run Vivado HLS synthesis", "assigned_tool": "vivado.run_csynth"},
                ],
                "allowed_tools": [
                    "task.validate_schema",
                    "hls4ml.inspect_model",
                    "hls4ml.check_support",
                    "hls4ml.generate_config",
                    "hls4ml.convert",
                    "vivado.run_csynth",
                ],
                "allowed_specialists": ["HLS4MLSpecialist", "VivadoSpecialist"],
                "required_artifacts": ["hls4ml_config", "hls_project", "summary_md", "trace_jsonl"],
                "failure_policy": {"legacy_planner_branches": planner.get("task_type_branches", [])},
                "verification_policy": {"hls4ml_generated_project_requires_report_validation": True},
                "memory_policy": {"promote_metrics": True, "promote_conversion_warnings": True},
                "tags": ["legacy", "extracted"],
                "source": "legacy_extractor",
            },
            {
                "name": "legacy_optimization_flow",
                "description": "Extracted suggestion rule tokens for optimization playbook.",
                "intent": "optimization_guidance",
                "trigger": {"task_type": ["model", "operator", "hls_project"]},
                "preconditions": ["report_or_failure_available"],
                "recommended_todos": [
                    {"title": "Generate optimization suggestions", "assigned_tool": "suggestion.suggest_optimization"}
                ],
                "allowed_tools": ["suggestion.suggest_optimization", "memory.retrieve_optimization_rules"],
                "allowed_specialists": ["OptimizationSpecialist"],
                "required_artifacts": ["suggestions"],
                "failure_policy": {},
                "verification_policy": {},
                "memory_policy": {"promote_failures": True, "promote_metrics": True},
                "tags": suggestions.get("rule_tokens", []),
                "source": "legacy_extractor",
            },
        ]
        # Extracted playbooks are drafts: add the guidance layer, but never
        # silently publish them as executable approved skills.
        for skill in skills:
            skill["status"] = "candidate"
            skill.setdefault("purpose", skill.get("description", ""))
            skill.setdefault(
                "procedure",
                [
                    str(todo.get("title") or todo.get("assigned_tool") or "Inspect the next bounded step.")
                    for todo in skill.get("recommended_todos", [])[:8]
                ],
            )
            skill.setdefault(
                "decision_rules",
                [
                    "Treat extracted steps as starting guidance and re-check the current task contract.",
                    "Do not claim success without the artifacts and verification evidence required by the skill.",
                ],
            )
            skill.setdefault(
                "pitfalls",
                [
                    "Do not copy legacy behavior blindly when current tool or permission contracts differ.",
                    "Do not turn a candidate playbook into an approved skill without review and regression tests.",
                ],
            )
            skill.setdefault(
                "verification_guidance",
                [
                    "Validate the extracted document against the Skill schema and runtime allowlists.",
                    "Run the relevant tool, artifact, and failure-path regression tests before approval.",
                ],
            )
            skill.setdefault(
                "examples",
                [{"scenario": "legacy flow extracted", "expected_outcome": "candidate skill awaits review"}],
            )
        return skills

    def write_skill_yaml(self, skeleton: dict[str, Any], path: str | Path) -> None:
        """Execute write_skill_yaml at the extractor boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            skeleton: Value supplied by the caller and validated by the surrounding schema.
            path: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(skeleton, indent=2, ensure_ascii=False), encoding="utf-8")

    def write_legacy_workflow_map(self, output_path: str | Path) -> Path:
        """Execute write_legacy_workflow_map at the extractor boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            output_path: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        planner = self.inspect_legacy_planner()
        reflector = self.inspect_legacy_reflector()
        suggestions = self.inspect_legacy_suggestions()
        content = ["# Legacy Workflow Map", "", "## planner.py task branches"]
        planner_items = planner.get("task_type_branches", [])
        if planner_items:
            content.extend(f"- `{item}`" for item in planner_items)
        else:
            content.append("- (none found)")

        content.extend(["", "## runtime.py / reflect branches"])
        reflector_items = reflector.get("failure_branches", [])
        if reflector_items:
            content.extend(f"- `{item}`" for item in reflector_items)
        else:
            content.append("- (none found)")

        content.extend(["", "## suggest_optimization.py rule tokens"])
        suggestion_items = suggestions.get("rule_tokens", [])
        if suggestion_items:
            content.extend(f"- `{item}`" for item in suggestion_items)
        else:
            content.append("- (none found)")

        content.extend(
            [
                "",
                "## Skill Mapping",
                "- `operator_fallback_flow`: deterministic operator fallback + Vivado path.",
                "- `hls4ml_model_flow`: deterministic model path with hls4ml tools.",
                "- `existing_hls_project_flow`: deterministic existing HLS project synthesis path.",
                "- `unsupported_boundary_flow`: partial/unsupported boundary handling.",
                "- `latency_optimization_flow` and `resource_optimization_flow`: extracted from suggest_optimization rules.",
                "- `llm_candidate_verification_flow`: existing candidate + verify flow.",
                "- `memory_promotion_flow`: finalize memory compression and promotion.",
            ]
        )
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(content) + "\n", encoding="utf-8")
        return target
