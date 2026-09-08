"""core layer implementation for permissions.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .errors import build_error


class PermissionGate:
    """Coordinate PermissionGate within the permissions boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    def __init__(self, config: dict[str, Any], workspace_root: str | Path):
        """Implement the internal __init__ helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            config: Value supplied by the caller and validated by the surrounding schema.
            workspace_root: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        self.config = config
        self.workspace_root = Path(workspace_root).resolve()

    def _resolve(self, path: str) -> Path:
        """Implement the internal _resolve helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            path: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = (self.workspace_root / candidate).resolve()
        else:
            candidate = candidate.resolve()
        return candidate

    def _normalized_dir(self, path: str) -> Path:
        """Implement the internal _normalized_dir helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            path: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        raw = str(path).strip()
        if os.name == "nt" and raw in {"/", "/etc"}:
            return Path("__non_matching_unix_only__")
        return self._resolve(path)

    def _is_within(self, path: Path, directory: Path) -> bool:
        """Implement the internal _is_within helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            path: Value supplied by the caller and validated by the surrounding schema.
            directory: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        try:
            path.relative_to(directory)
            return True
        except ValueError:
            return False

    def _decision(self, decision: str, reason: str) -> dict[str, str]:
        """Implement the internal _decision helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            decision: Value supplied by the caller and validated by the surrounding schema.
            reason: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        return {"decision": decision, "reason": reason}

    def check_read_path(self, path: str) -> dict[str, str]:
        """Execute check_read_path at the permissions boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            path: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
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
        """Execute check_write_path at the permissions boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            path: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
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
        """Execute check_command at the permissions boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            command: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
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
                return self._decision("ask", f"Command {command[0]} requires explicit session approval.")
        return self._decision("deny", f"Command {command[0]} is not allow-listed.")

    def check_url(self, value: str) -> dict[str, str]:
        """Execute check_url at the permissions boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            value: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        parsed = urlparse(value)
        network = self.config.get("network", {})
        if parsed.scheme not in set(network.get("allowed_schemes", ["https"])):
            return self._decision("deny", f"URL scheme {parsed.scheme or '<empty>'} is not allowed.")
        host = (parsed.hostname or "").lower()
        denied = {str(item).lower() for item in network.get("denied_domains", [])}
        allowed = {str(item).lower() for item in network.get("allowed_domains", [])}
        if any(host == item or host.endswith(f".{item}") for item in denied):
            return self._decision("deny", f"Network domain {host} is denied by policy.")
        if not allowed:
            return self._decision("deny", "Network access is disabled because no domains are allow-listed.")
        if not any(host == item or host.endswith(f".{item}") for item in allowed):
            return self._decision("deny", f"Network domain {host} is not allow-listed.")
        return self._decision("allow", f"Network domain {host} is allow-listed.")

    def check_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        *,
        tool_spec=None,
        principal: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        """Execute check_tool at the permissions boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            tool_name: Value supplied by the caller and validated by the surrounding schema.
            args: Value supplied by the caller and validated by the surrounding schema.
            tool_spec: Value supplied by the caller and validated by the surrounding schema.
            principal: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        limits = self.config.get("limits", {})
        encoded_size = len(json.dumps(args, ensure_ascii=False, default=str).encode("utf-8"))
        if encoded_size > int(limits.get("max_tool_argument_bytes", 1_000_000)):
            return self._decision("deny", "Tool arguments exceed the configured resource limit.")

        required = set(getattr(tool_spec, "required_capabilities", None) or [])
        granted = set((principal or {}).get("capabilities", []))
        if required and principal is not None and not required.issubset(granted):
            missing = sorted(required - granted)
            return self._decision("deny", f"Principal lacks required capabilities: {', '.join(missing)}")

        schema = getattr(tool_spec, "input_schema", None) or {}
        for key_path, value, annotation in self._walk_values(args, schema):
            key = key_path[-1].lower() if key_path else ""
            permission_type = annotation or self._infer_permission_type(key, value)
            decision: dict[str, str] | None = None
            if permission_type == "read_path" and isinstance(value, str):
                decision = self.check_read_path(value)
            elif permission_type == "write_path" and isinstance(value, str):
                decision = self.check_write_path(value)
            elif permission_type == "command" and isinstance(value, list):
                decision = self.check_command([str(item) for item in value])
            elif permission_type == "url" and isinstance(value, str):
                decision = self.check_url(value)
            if decision and decision["decision"] != "allow":
                return decision

        risk_level = str(getattr(tool_spec, "risk_level", "low"))
        ask_levels = set(self.config.get("approvals", {}).get("risk_levels", ["critical"]))
        if risk_level in ask_levels:
            return self._decision("ask", f"Tool {tool_name} has {risk_level} risk and requires approval.")
        return self._decision("allow", f"Tool {tool_name} is allowed by policy.")

    def _walk_values(
        self,
        value: Any,
        schema: dict[str, Any] | None,
        path: tuple[str, ...] = (),
    ):
        """Implement the internal _walk_values helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            value: Value supplied by the caller and validated by the surrounding schema.
            schema: Value supplied by the caller and validated by the surrounding schema.
            path: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        schema = schema or {}
        annotation = schema.get("x-permission")
        if annotation:
            yield path, value, str(annotation)
            return
        if isinstance(value, dict):
            properties = schema.get("properties", {}) if isinstance(schema.get("properties"), dict) else {}
            additional = schema.get("additionalProperties", {})
            if path and not properties and not isinstance(additional, dict):
                return
            if path and not properties and isinstance(additional, dict) and not additional:
                # Generic state/task blobs are data, not direct filesystem capabilities.
                # Their handler must declare x-permission on actionable nested fields.
                return
            for key, item in value.items():
                child_schema = properties.get(key, additional if isinstance(additional, dict) else {})
                yield from self._walk_values(item, child_schema, (*path, str(key)))
        elif isinstance(value, list):
            item_schema = schema.get("items", {}) if isinstance(schema.get("items"), dict) else {}
            if annotation == "command":
                yield path, value, annotation
            else:
                yield path, value, None
                for index, item in enumerate(value):
                    yield from self._walk_values(item, item_schema, (*path, str(index)))
        else:
            yield path, value, None

    @staticmethod
    def _infer_permission_type(key: str, value: Any) -> str | None:
        """Implement the internal _infer_permission_type helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            key: Value supplied by the caller and validated by the surrounding schema.
            value: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        if key in {"command", "argv"} and isinstance(value, list):
            return "command"
        if key in {"url", "uri", "endpoint", "base_url", "webhook"} and isinstance(value, str):
            return "url"
        if not isinstance(value, str):
            return None
        if key in {"output_dir", "work_dir", "report_dir", "destination", "target_path", "output_path"}:
            return "write_path"
        if key == "path" or key.endswith("_path") or key.endswith("_dir") or key in {"source", "file", "filename"}:
            return "read_path"
        return None

    def denied_error(self, source: str, reason: str) -> dict[str, Any]:
        """Execute denied_error at the permissions boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            source: Value supplied by the caller and validated by the surrounding schema.
            reason: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        return build_error(
            "PermissionDeniedError",
            reason,
            recoverable=True,
            source=source,
            suggested_action="Adjust permissions.yaml or choose a workspace path inside runs/.",
        ).to_dict()
