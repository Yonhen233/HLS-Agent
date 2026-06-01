from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .errors import build_error


class PermissionGate:
    def __init__(self, config: dict[str, Any], workspace_root: str | Path):
        self.config = config
        self.workspace_root = Path(workspace_root).resolve()

    def _resolve(self, path: str) -> Path:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = (self.workspace_root / candidate).resolve()
        else:
            candidate = candidate.resolve()
        return candidate

    def _normalized_dir(self, path: str) -> Path:
        raw = str(path).strip()
        if os.name == "nt" and raw in {"/", "/etc"}:
            return Path("__non_matching_unix_only__")
        return self._resolve(path)

    def _is_within(self, path: Path, directory: Path) -> bool:
        try:
            path.relative_to(directory)
            return True
        except ValueError:
            return False

    def _decision(self, decision: str, reason: str) -> dict[str, str]:
        return {"decision": decision, "reason": reason}

    def check_read_path(self, path: str) -> dict[str, str]:
        resolved = self._resolve(path)
        denied = [self._normalized_dir(item) for item in self.config.get("filesystem", {}).get("denied_dirs", [])]
        for item in denied:
            if self._is_within(resolved, item):
                return self._decision("deny", f"Path is inside denied directory: {item}")
        allowed = [self._normalized_dir(item) for item in self.config.get("filesystem", {}).get("allowed_read_dirs", ["."])]
        for item in allowed:
            if self._is_within(resolved, item):
                return self._decision("allow", "Path is inside allowed read directory.")
        return self._decision("deny", "Path is outside allowed read directories.")

    def check_write_path(self, path: str) -> dict[str, str]:
        resolved = self._resolve(path)
        denied = [self._normalized_dir(item) for item in self.config.get("filesystem", {}).get("denied_dirs", [])]
        for item in denied:
            if self._is_within(resolved, item):
                return self._decision("deny", f"Path is inside denied directory: {item}")
        allowed = [self._normalized_dir(item) for item in self.config.get("filesystem", {}).get("allowed_write_dirs", [])]
        for item in allowed:
            if self._is_within(resolved, item):
                return self._decision("allow", "Path is inside allowed write directory.")
        return self._decision("deny", "Path is outside allowed write directories.")

    def check_command(self, command: list[str]) -> dict[str, str]:
        if not command:
            return self._decision("deny", "Empty command is not allowed.")
        normalized = " ".join(command).strip().lower()
        commands_cfg = self.config.get("commands", {})
        for denied in commands_cfg.get("deny", []):
            if normalized == denied.lower() or normalized.startswith(f"{denied.lower()} "):
                return self._decision("deny", f"Command {command[0]} is denied by policy.")
        for allowed in commands_cfg.get("allow", []):
            if normalized == allowed.lower() or normalized.startswith(f"{allowed.lower()} "):
                return self._decision("allow", f"Command {command[0]} is allowed by policy.")
        for ask in commands_cfg.get("ask", []):
            if normalized == ask.lower() or normalized.startswith(f"{ask.lower()} "):
                return self._decision("deny", f"Command {command[0]} requires approval and is denied in P0.")
        return self._decision("deny", f"Command {command[0]} is not allow-listed.")

    def check_tool(self, tool_name: str, args: dict[str, Any]) -> dict[str, str]:
        for key in ("path", "report_path", "log_path", "config_path", "output_dir", "work_dir", "hls_project_dir"):
            value = args.get(key)
            if not value:
                continue
            decision = self.check_write_path(value) if key in {"output_dir", "work_dir"} else self.check_read_path(value)
            if decision["decision"] != "allow":
                return decision
        command = args.get("command")
        if isinstance(command, list):
            decision = self.check_command([str(item) for item in command])
            if decision["decision"] != "allow":
                return decision
        return self._decision("allow", f"Tool {tool_name} is allowed by policy.")

    def denied_error(self, source: str, reason: str) -> dict[str, Any]:
        return build_error(
            "PermissionDeniedError",
            reason,
            recoverable=True,
            source=source,
            suggested_action="Adjust permissions.yaml or choose a workspace path inside runs/.",
        ).to_dict()
