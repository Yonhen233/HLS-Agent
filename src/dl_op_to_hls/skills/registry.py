from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..core.errors import AgentRuntimeError, build_error
from .skill import Skill


class SkillRegistry:
    def __init__(self, skills_dir: str | Path = "skills"):
        self.skills_dir = Path(skills_dir)
        self._skills: dict[str, Skill] = {}

    def load_all(self) -> None:
        self._skills = {}
        if not self.skills_dir.exists():
            return
        for path in sorted(self.skills_dir.glob("*.yaml")) + sorted(self.skills_dir.glob("*.yml")):
            payload = self._load_skill_file(path)
            skill = Skill.from_dict(payload, source=str(path))
            if skill.name in self._skills:
                raise AgentRuntimeError(
                    build_error(
                        "InvalidTaskError",
                        f"Duplicate skill name detected: {skill.name}",
                        recoverable=False,
                        source="skills.registry.load_all",
                        details={"path": str(path)},
                    )
                )
            self._skills[skill.name] = skill

    def list_skills(self) -> list[Skill]:
        return list(self._skills.values())

    def get(self, name: str) -> Skill:
        if name not in self._skills:
            raise KeyError(name)
        return self._skills[name]

    def find_candidates(self, task: dict[str, Any]) -> list[Skill]:
        candidates: list[tuple[int, Skill]] = []
        for skill in self._skills.values():
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
            elif task_type != trigger_task_type:
                return 0
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
            score += 1
        if not score:
            score = 1
        return score
