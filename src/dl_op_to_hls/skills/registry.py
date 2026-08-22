from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..core.errors import AgentRuntimeError, build_error
from .skill import Skill
from .schema import SkillValidator, evaluate_conditions


class SkillRegistry:
    def __init__(self, skills_dir: str | Path = "skills"):
        self.skills_dir = Path(skills_dir)
        self._skills: dict[str, Skill] = {}
        self._versions: dict[str, dict[str, Skill]] = {}
        self._validation_reports: list[dict[str, Any]] = []
        self.validator = SkillValidator()
        self._pinned_versions: dict[str, str] = {}

    def load_all(self) -> None:
        self._skills = {}
        self._versions = {}
        self._validation_reports = []
        if not self.skills_dir.exists():
            return
        for path in sorted(self.skills_dir.glob("*.yaml")) + sorted(self.skills_dir.glob("*.yml")):
            payload = self._load_skill_file(path)
            report = self.validator.validate_document(payload)
            self._validation_reports.append({**report.to_dict(), "path": str(path)})
            if not report.valid:
                raise AgentRuntimeError(
                    build_error(
                        "InvalidTaskError",
                        f"Invalid skill {path.name}: {'; '.join(report.errors)}",
                        recoverable=False,
                        source="skills.registry.validate",
                        details={"path": str(path), "report": report.to_dict()},
                    )
                )
            skill = Skill.from_dict(payload, source=str(path))
            versions = self._versions.setdefault(skill.name, {})
            if skill.version in versions:
                raise AgentRuntimeError(
                    build_error(
                        "InvalidTaskError",
                        f"Duplicate skill name/version detected: {skill.name}@{skill.version}",
                        recoverable=False,
                        source="skills.registry.load_all",
                        details={"path": str(path)},
                    )
                )
            versions[skill.version] = skill
        for name, versions in self._versions.items():
            approved = [item for item in versions.values() if item.status == "approved"]
            active = approved or [item for item in versions.values() if item.status != "deprecated"] or list(versions.values())
            self._skills[name] = sorted(active, key=lambda item: self._version_key(item.version), reverse=True)[0]
        self._validate_dependencies()

    def list_skills(self) -> list[Skill]:
        return list(self._skills.values())

    def get(self, name: str, version: str | None = None) -> Skill:
        version = version or self._pinned_versions.get(name)
        if version is not None:
            if name not in self._versions or version not in self._versions[name]:
                raise KeyError(f"{name}@{version}")
            return self._versions[name][version]
        if name not in self._skills:
            raise KeyError(name)
        return self._skills[name]

    def pin_release_manifest(self, manifest: dict[str, Any]) -> None:
        self._pinned_versions = {
            key.split(":", 1)[1]: str(value["selected_version"])
            for key, value in manifest.items()
            if key.startswith("skill:") and key != "skill:approved-skills" and value.get("selected_version")
        }

    def validation_reports(self) -> list[dict[str, Any]]:
        return list(self._validation_reports)

    def transition(self, name: str, target_status: str, version: str | None = None) -> Skill:
        if target_status not in {"approved", "deprecated"}:
            raise ValueError("Skills may only be promoted to approved or transitioned to deprecated.")
        skill = self.get(name, version)
        allowed = {
            "candidate": {"approved", "deprecated"},
            "approved": {"deprecated"},
            "deprecated": set(),
        }
        if target_status == skill.status:
            return skill
        if target_status not in allowed.get(skill.status, set()):
            raise ValueError(f"Invalid skill lifecycle transition: {skill.status} -> {target_status}")
        path = Path(skill.source)
        payload = self._load_skill_file(path)
        payload["status"] = target_status
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)
        self.load_all()
        return self.get(name, skill.version)

    def find_candidates(self, task: dict[str, Any]) -> list[Skill]:
        candidates: list[tuple[int, Skill]] = []
        for skill in self._skills.values():
            if skill.status != "approved":
                continue
            score = self._match_score(skill, task)
            if score > 0:
                candidates.append((score, skill))
        candidates.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in candidates]

    def to_prompt_context(self, task: dict[str, Any]) -> dict[str, Any]:
        candidates = self.find_candidates(task)
        return {
            "available_skills": [skill.to_prompt_summary() for skill in candidates[:5]],
            "total_loaded_skills": len(self._skills),
        }

    def _load_skill_file(self, path: Path) -> dict[str, Any]:
        raw = path.read_text(encoding="utf-8")
        parsed: Any = None
        parse_error: str | None = None
        try:
            import yaml  # type: ignore

            parsed = yaml.safe_load(raw)
        except Exception as exc:
            parse_error = str(exc)
        if parsed is None:
            try:
                parsed = json.loads(raw)
            except Exception as exc:
                raise AgentRuntimeError(
                    build_error(
                        "InvalidTaskError",
                        f"Failed to parse skill file {path.name}: {parse_error or str(exc)}",
                        recoverable=False,
                        source="skills.registry.load_file",
                        details={"path": str(path)},
                    )
                ) from exc
        if not isinstance(parsed, dict):
            raise AgentRuntimeError(
                build_error(
                    "InvalidTaskError",
                    f"Skill file {path.name} must contain an object.",
                    recoverable=False,
                    source="skills.registry.load_file",
                    details={"path": str(path)},
                )
            )
        return parsed

    def _match_score(self, skill: Skill, task: dict[str, Any]) -> int:
        trigger = skill.trigger
        if not trigger:
            return 1
        score = 0
        llm_candidate_cfg = task.get("llm_candidate") if isinstance(task.get("llm_candidate"), dict) else {}
        if llm_candidate_cfg.get("required") and skill.name == "llm_candidate_verification_flow":
            score += 10
        if llm_candidate_cfg.get("required") and "optimization" in skill.tags:
            score -= 3
        task_type = task.get("task_type")
        trigger_task_type = trigger.get("task_type")
        if trigger_task_type:
            if isinstance(trigger_task_type, list):
                if task_type not in trigger_task_type:
                    return 0
                score += 1
            elif task_type != trigger_task_type:
                return 0
            else:
                score += 3
        frontends = trigger.get("frontends")
        if frontends:
            if task.get("frontend") in frontends:
                score += 2
            else:
                return 0
        op_types = trigger.get("op_types")
        if op_types:
            if task.get("op_type") in op_types:
                score += 2
            else:
                return 0
        conditions = trigger.get("conditions", [])
        if conditions:
            if not evaluate_conditions(conditions, task):
                return 0
            score += 1
            if skill.name == "unsupported_boundary_flow":
                score += 10
        if not score:
            score = 1
        return score

    def _validate_dependencies(self) -> None:
        for skill in [item for versions in self._versions.values() for item in versions.values()]:
            for dependency in skill.dependencies:
                name = str(dependency.get("name") or "")
                if name not in self._versions:
                    raise AgentRuntimeError(
                        build_error(
                            "InvalidTaskError",
                            f"Skill {skill.name} depends on missing skill {name}",
                            recoverable=False,
                            source="skills.registry.dependencies",
                        )
                    )

    @staticmethod
    def _version_key(value: str) -> tuple[int, int, int, str]:
        core, _, suffix = value.partition("-")
        parts = [int(item) for item in core.split(".")]
        while len(parts) < 3:
            parts.append(0)
        return parts[0], parts[1], parts[2], suffix
