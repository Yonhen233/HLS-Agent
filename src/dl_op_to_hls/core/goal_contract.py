from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


SUCCESS_PATHS = {
    "fallback_template_path",
    "hls4ml_path",
    "existing_hls_project_path",
    "llm_candidate_path",
}


@dataclass(frozen=True)
class GoalRequirement:
    requirement_id: str
    description: str
    verifier: str
    required: bool = True
    plan_required: bool = True
    accepted_tools: tuple[str, ...] = ()
    evidence_types: tuple[str, ...] = ()
    parameters: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["accepted_tools"] = list(self.accepted_tools)
        payload["evidence_types"] = list(self.evidence_types)
        return payload


class GoalContractBuilder:
    """Compile a task into deterministic acceptance criteria.

    The LLM may propose a plan, but it cannot weaken these requirements. Tasks
    may add requirements through ``acceptance_criteria``; the built-in contract
    remains the minimum for an HLS run to claim success.
    """

    def build(self, task: dict[str, Any]) -> dict[str, Any]:
        task_type = str(task.get("task_type") or "")
        implementation_tools = {
            "model": (
                "hls4ml.convert",
                "hls4ml.convert_with_hls4ml",
                "llm.generate_candidate",
                "llm.generate_hls_candidate",
                "report.write_unsupported",
            ),
            "operator": (
                "fallback.generate_operator_hls",
                "llm.generate_candidate",
                "llm.generate_hls_candidate",
                "report.write_unsupported",
            ),
            "hls_project": ("task.prepare_existing_project", "report.write_unsupported"),
        }.get(task_type, ("report.write_unsupported",))

        requirements = [
            GoalRequirement(
                "task.validated",
                "The normalized task schema was validated.",
                "tool_succeeded",
                accepted_tools=("task.validate_schema",),
                evidence_types=("tool_receipt",),
            ),
            GoalRequirement(
                "implementation.resolved",
                "A concrete implementation path or an honest unsupported boundary was produced.",
                "implementation_or_boundary",
                accepted_tools=implementation_tools,
                evidence_types=("selected_path", "artifact", "tool_receipt"),
            ),
            GoalRequirement(
                "implementation.verified",
                "Generated or existing HLS behavior was checked against an executable reference.",
                "functional_verification_or_boundary",
                accepted_tools=(
                    "vivado.run_csim",
                    "vivado.run_csynth",
                    "verify_candidate.run",
                    "verify.run_csim",
                    "verify.compare_reference",
                    "report.write_unsupported",
                ),
                evidence_types=("verification", "tool_receipt"),
            ),
            GoalRequirement(
                "report.produced",
                "A current-run synthesis report or unsupported report was produced.",
                "report_or_boundary",
                accepted_tools=(
                    "vivado.run_csynth",
                    "vivado.parse_report",
                    "vivado.parse_csynth_report",
                    "report.write_unsupported",
                ),
                evidence_types=("report", "artifact", "tool_receipt"),
            ),
            GoalRequirement(
                "implementation.timing",
                "The implementation met the requested clock target, or the task ended at an honest unsupported boundary.",
                "timing_or_boundary",
                plan_required=False,
                evidence_types=("report",),
            ),
            GoalRequirement(
                "run.summarized",
                "The run has an evidence-grounded final summary.",
                "artifact_exists",
                plan_required=False,
                accepted_tools=("summary.write_summary",),
                evidence_types=("summary",),
                parameters={"artifact_keys": ["summary"]},
            ),
            GoalRequirement(
                "run.no_unresolved_errors",
                "No unresolved execution error remains when success is claimed.",
                "no_unresolved_errors",
                plan_required=False,
                evidence_types=("state",),
            ),
        ]

        for index, item in enumerate(task.get("acceptance_criteria") or [], start=1):
            if not isinstance(item, dict):
                continue
            requirement_id = str(item.get("id") or f"custom.{index}")
            requirements.append(
                GoalRequirement(
                    requirement_id=requirement_id,
                    description=str(item.get("description") or requirement_id),
                    verifier=str(item.get("verifier") or "artifact_exists"),
                    required=bool(item.get("required", True)),
                    plan_required=bool(item.get("plan_required", True)),
                    accepted_tools=tuple(str(value) for value in item.get("accepted_tools") or []),
                    evidence_types=tuple(str(value) for value in item.get("evidence_types") or []),
                    parameters=dict(item.get("parameters") or {}),
                )
            )

        return {
            "version": "1.0",
            "task_type": task_type,
            "task_name": task.get("name"),
            "success_policy": "all_required_requirements",
            "requirements": [item.to_dict() for item in requirements],
        }


class PlanCoverageValidator:
    ENABLING_TOOL_REQUIREMENTS = {
        "hls4ml.inspect_model": ["implementation.resolved"],
        "hls4ml.check_support": ["implementation.resolved"],
        "hls4ml.check_hls4ml_support": ["implementation.resolved"],
        "hls4ml.generate_config": ["implementation.resolved"],
        "hls4ml.generate_hls4ml_config": ["implementation.resolved"],
        "graph_rewrite.rewrite": ["implementation.resolved"],
        "fallback.generate_testbench": ["implementation.verified"],
        "vivado.create_project": ["implementation.verified", "report.produced"],
        "vivado.create_vivado_project": ["implementation.verified", "report.produced"],
        "vivado.parse_log": ["report.produced"],
    }

    def validate(self, contract: dict[str, Any], todos: list[Any]) -> dict[str, Any]:
        tools = {
            str(item.get("assigned_tool"))
            for item in todos
            if isinstance(item, dict) and item.get("assigned_tool")
        }
        missing: list[dict[str, Any]] = []
        covered: list[str] = []
        for requirement in contract.get("requirements", []):
            if not requirement.get("required", True) or not requirement.get("plan_required", True):
                continue
            accepted = set(requirement.get("accepted_tools") or [])
            if accepted and tools.intersection(accepted):
                covered.append(str(requirement["requirement_id"]))
            elif accepted:
                missing.append(
                    {
                        "requirement_id": requirement["requirement_id"],
                        "description": requirement.get("description"),
                        "accepted_tools": sorted(accepted),
                    }
                )
            else:
                missing.append(
                    {
                        "requirement_id": requirement["requirement_id"],
                        "description": requirement.get("description"),
                        "accepted_tools": [],
                        "reason": "plan_required requirement has no accepted_tools mapping",
                    }
                )
        return {
            "status": "valid" if not missing else "incomplete",
            "covered_requirements": covered,
            "missing_requirements": missing,
            "planned_tools": sorted(tools),
        }

    def repair_with_skill(self, plan: dict[str, Any], skill: Any, contract: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        repaired = {**plan, "todos": [dict(item) for item in plan.get("todos", []) if isinstance(item, dict)]}
        before = self.validate(contract, repaired["todos"])
        if before["status"] == "valid" or skill is None:
            return repaired, {"repaired": False, "before": before, "after": before, "added_tools": []}

        existing_tools = {item.get("assigned_tool") for item in repaired["todos"]}
        added_tools: list[str] = []
        for item in getattr(skill, "recommended_todos", []) or []:
            if not isinstance(item, dict):
                continue
            tool_name = item.get("assigned_tool")
            if not tool_name or tool_name in existing_tools:
                continue
            repaired["todos"].append(dict(item))
            existing_tools.add(tool_name)
            added_tools.append(str(tool_name))
            if self.validate(contract, repaired["todos"])["status"] == "valid":
                break
        after = self.validate(contract, repaired["todos"])
        return repaired, {"repaired": bool(added_tools), "before": before, "after": after, "added_tools": added_tools}

    def requirement_ids_for_tool(self, contract: dict[str, Any], tool_name: str | None) -> list[str]:
        if not tool_name:
            return []
        direct = [
            str(item["requirement_id"])
            for item in contract.get("requirements", [])
            if tool_name in set(item.get("accepted_tools") or [])
        ]
        return list(dict.fromkeys(direct + self.ENABLING_TOOL_REQUIREMENTS.get(tool_name, [])))


class CompletionGate:
    """Independent final status gate; LLM assertions are never accepted as proof."""

    OPTIONAL_ERROR_SOURCES = (
        "suggestion.",
        "memory.",
        "rag.",
        "db.",
        "parameter_advisor.",
    )

    def evaluate(self, state: Any, contract: dict[str, Any], receipts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        receipts = list(receipts or [])
        checks = [self._evaluate_requirement(state, item, receipts) for item in contract.get("requirements", [])]
        required_failures = [item for item in checks if item["required"] and item["status"] != "satisfied"]
        unsupported = getattr(state, "selected_path", None) == "unsupported_path"
        critical_receipts = [
            item
            for item in receipts
            if str(item.get("tool_name") or "").startswith(("hls4ml.", "vivado.", "verify."))
            or item.get("tool_name") == "verify_candidate.run"
        ]
        mock_only = bool(critical_receipts) and not any(
            item.get("valid") and not item.get("mock_evidence") for item in critical_receipts
        )
        evidence_level = "mock" if mock_only else "real" if critical_receipts else "unverified"
        honest_boundary = unsupported and any(
            item["requirement_id"] == "implementation.resolved" and item["status"] == "satisfied" for item in checks
        )
        passed = not required_failures and not unsupported
        previous_status = str(getattr(state, "status", "initialized"))
        blocking_errors, warning_errors = self._classify_errors(getattr(state, "errors", []) or [])
        if passed:
            recommended_status = "success"
            stop_reason = (
                "acceptance_contract_satisfied_in_mock_harness"
                if evidence_level == "mock"
                else "acceptance_contract_satisfied"
            )
        elif honest_boundary:
            recommended_status = "partial_success"
            stop_reason = "honest_unsupported_boundary"
        elif previous_status == "failed":
            recommended_status = "failed"
            stop_reason = "required_evidence_missing_after_failure"
        else:
            recommended_status = "partial_success"
            stop_reason = "required_evidence_missing"
        return {
            "evaluated": True,
            "passed": passed,
            "honest_boundary": honest_boundary,
            "previous_status": previous_status,
            "recommended_status": recommended_status,
            "stop_reason": stop_reason,
            "false_success_prevented": previous_status == "success" and not passed,
            "evidence_level": evidence_level,
            "production_ready": passed and evidence_level == "real",
            "mock_results_cannot_support_production_claims": evidence_level == "mock",
            "blocking_errors": blocking_errors,
            "warnings": warning_errors,
            "requirements": checks,
            "missing_required": [item["requirement_id"] for item in required_failures],
        }

    def apply(self, state: Any, contract: dict[str, Any], receipts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        result = self.evaluate(state, contract, receipts)
        if getattr(state, "status", None) != "interrupted":
            state.status = result["recommended_status"]
        state.completion = result
        return result

    def _evaluate_requirement(self, state: Any, requirement: dict[str, Any], receipts: list[dict[str, Any]]) -> dict[str, Any]:
        verifier = str(requirement.get("verifier") or "")
        parameters = requirement.get("parameters") or {}
        accepted_tools = set(requirement.get("accepted_tools") or [])
        evidence: list[Any] = []
        satisfied = False
        selected_path = getattr(state, "selected_path", None)
        artifacts = getattr(state, "artifacts", {}) or {}

        if verifier == "tool_succeeded":
            matched = [item for item in receipts if item.get("tool_name") in accepted_tools and item.get("valid")]
            if not matched:
                matched = [
                    {"todo_id": item.id, "tool_name": item.assigned_tool}
                    for item in getattr(state, "todos", [])
                    if item.assigned_tool in accepted_tools and item.status == "completed"
                ]
            satisfied = bool(matched)
            evidence = matched
        elif verifier == "implementation_or_boundary":
            if selected_path == "unsupported_path":
                boundary = artifacts.get("unsupported_report") or self._completed_tool(state, "report.write_unsupported")
                satisfied = bool(boundary)
                evidence = [boundary] if boundary else []
            else:
                project_dir = getattr(state, "hls_project_dir", None)
                satisfied = selected_path in SUCCESS_PATHS and bool(project_dir or self._completed_any_tool(state, accepted_tools))
                evidence = [selected_path, project_dir]
        elif verifier == "functional_verification_or_boundary":
            if selected_path == "unsupported_path":
                satisfied = bool(artifacts.get("unsupported_report") or self._completed_tool(state, "report.write_unsupported"))
                evidence = ["not_applicable_for_honest_boundary"] if satisfied else []
            else:
                from ..main_agent.status import is_functionally_verified

                verification = getattr(state, "verification", None)
                satisfied = is_functionally_verified(verification)
                evidence = [verification] if verification else []
        elif verifier == "report_or_boundary":
            if selected_path == "unsupported_path":
                boundary = artifacts.get("unsupported_report") or self._completed_tool(state, "report.write_unsupported")
                satisfied = bool(boundary)
                evidence = [boundary] if boundary else []
            else:
                report = getattr(state, "report", None) or {}
                satisfied = report.get("status") == "success"
                evidence = [report] if report else []
        elif verifier == "timing_or_boundary":
            if selected_path == "unsupported_path":
                satisfied = bool(artifacts.get("unsupported_report") or self._completed_tool(state, "report.write_unsupported"))
                evidence = ["not_applicable_for_honest_boundary"] if satisfied else []
            else:
                report = getattr(state, "report", None) or {}
                timing = report.get("timing") if isinstance(report.get("timing"), dict) else {}
                satisfied = timing.get("met") is True
                evidence = [timing] if timing else []
        elif verifier == "artifact_exists":
            keys = [str(item) for item in parameters.get("artifact_keys") or requirement.get("evidence_types") or []]
            paths = [artifacts.get(key) for key in keys if artifacts.get(key)]
            existing = [path for path in paths if Path(str(path)).exists()]
            satisfied = bool(existing) and len(existing) == len(paths) and len(paths) == len(keys)
            evidence = existing
        elif verifier == "no_unresolved_errors":
            errors = getattr(state, "errors", []) or []
            blocking, warnings = self._classify_errors(errors)
            satisfied = not blocking
            evidence = {"blocking": blocking, "warnings": warnings}
        elif verifier == "state_path_equals":
            field_name = str(parameters.get("field") or "")
            satisfied = getattr(state, field_name, None) == parameters.get("value")
            evidence = [getattr(state, field_name, None)]

        return {
            "requirement_id": str(requirement.get("requirement_id")),
            "description": requirement.get("description"),
            "required": bool(requirement.get("required", True)),
            "status": "satisfied" if satisfied else "missing",
            "verifier": verifier,
            "evidence": evidence,
        }

    @classmethod
    def _classify_errors(cls, errors: list[Any]) -> tuple[list[Any], list[Any]]:
        """Separate required-path failures from non-contract auxiliary warnings."""
        blocking: list[Any] = []
        warnings: list[Any] = []
        for item in errors:
            if not isinstance(item, dict):
                blocking.append(item)
                continue
            source = str(item.get("source") or "")
            if source.startswith(cls.OPTIONAL_ERROR_SOURCES):
                warnings.append(item)
            else:
                blocking.append(item)
        return blocking, warnings

    @staticmethod
    def _completed_tool(state: Any, tool_name: str) -> Any:
        for item in getattr(state, "todos", []):
            if item.assigned_tool == tool_name and item.status in {"completed", "completed_with_warning"}:
                return item.outputs or {"todo_id": item.id}
        return None

    @classmethod
    def _completed_any_tool(cls, state: Any, tool_names: set[str]) -> Any:
        for tool_name in tool_names:
            completed = cls._completed_tool(state, tool_name)
            if completed:
                return completed
        return None
