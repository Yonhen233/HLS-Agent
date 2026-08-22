from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SandboxPolicy:
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
        self.workspace_root = Path(workspace_root).resolve()
        self.policy = policy or SandboxPolicy()
        if backend not in {"docker", "podman"}:
            raise ValueError("Sandbox backend must be docker or podman.")
        self.backend = backend

    def build_command(self, command: list[str], run_dir: str | Path, env: dict[str, str] | None = None) -> list[str]:
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
        return {
            "backend": self.backend,
            "command": self.build_command(command, run_dir, env),
            "timeout_seconds": self.policy.timeout_seconds,
            "network": self.policy.network,
            "read_only_root": True,
        }
