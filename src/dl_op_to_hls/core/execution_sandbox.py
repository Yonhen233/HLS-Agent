"""core layer implementation for execution_sandbox.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SandboxPolicy:
    """Coordinate SandboxPolicy within the execution_sandbox boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    image: str = "dl-op-to-hls-runner:locked"
    cpus: float = 2.0
    memory_mb: int = 4096
    pids_limit: int = 256
    timeout_seconds: int = 900
    network: str = "none"
    env_allowlist: tuple[str, ...] = ("PATH", "PYTHONPATH", "XILINX_VIVADO", "XILINX_HLS")
    extra_readonly_mounts: tuple[str, ...] = field(default_factory=tuple)


class ContainerSandbox:
    """Builds a least-privilege Docker/Podman invocation for untrusted candidates."""

    def __init__(self, workspace_root: str | Path, policy: SandboxPolicy | None = None, *, backend: str = "docker"):
        """Implement the internal __init__ helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            workspace_root: Value supplied by the caller and validated by the surrounding schema.
            policy: Value supplied by the caller and validated by the surrounding schema.
            backend: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        self.workspace_root = Path(workspace_root).resolve()
        self.policy = policy or SandboxPolicy()
        if backend not in {"docker", "podman"}:
            raise ValueError("Sandbox backend must be docker or podman.")
        self.backend = backend

    def build_command(self, command: list[str], run_dir: str | Path, env: dict[str, str] | None = None) -> list[str]:
        """Execute build_command at the execution_sandbox boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            command: Value supplied by the caller and validated by the surrounding schema.
            run_dir: Value supplied by the caller and validated by the surrounding schema.
            env: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        target = Path(run_dir).resolve()
        try:
            target.relative_to(self.workspace_root)
        except ValueError as exc:
            raise PermissionError("Sandbox write directory must be inside the workspace.") from exc
        if not command or any("\x00" in item for item in command):
            raise ValueError("Invalid sandbox command.")
        policy = self.policy
        args = [
            self.backend, "run", "--rm", "--read-only", "--cap-drop=ALL", "--security-opt", "no-new-privileges",
            "--network", policy.network, "--cpus", str(policy.cpus), "--memory", f"{policy.memory_mb}m",
            "--pids-limit", str(policy.pids_limit), "--tmpfs", "/tmp:rw,noexec,nosuid,size=512m",
            "--mount", f"type=bind,src={self.workspace_root},dst=/workspace,readonly",
            "--mount", f"type=bind,src={target},dst=/run",
            "--workdir", "/run",
        ]
        for mount in policy.extra_readonly_mounts:
            source = Path(mount).resolve()
            args.extend(["--mount", f"type=bind,src={source},dst=/opt/readonly/{source.name},readonly"])
        supplied = env or {}
        for name in policy.env_allowlist:
            value = supplied.get(name, os.environ.get(name))
            if value is not None:
                args.extend(["--env", f"{name}={value}"])
        forbidden = {name for name in supplied if name not in policy.env_allowlist}
        if forbidden:
            raise PermissionError(f"Sandbox environment contains non-allowlisted keys: {sorted(forbidden)}")
        return [*args, policy.image, *command]

    def plan(self, command: list[str], run_dir: str | Path, env: dict[str, str] | None = None) -> dict[str, Any]:
        """Execute plan at the execution_sandbox boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            command: Value supplied by the caller and validated by the surrounding schema.
            run_dir: Value supplied by the caller and validated by the surrounding schema.
            env: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        return {
            "backend": self.backend,
            "command": self.build_command(command, run_dir, env),
            "timeout_seconds": self.policy.timeout_seconds,
            "network": self.policy.network,
            "read_only_root": True,
        }
