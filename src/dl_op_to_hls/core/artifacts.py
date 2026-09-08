"""core layer implementation for artifacts.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .permissions import PermissionGate


def _sha256_bytes(data: bytes) -> str:
    """Implement the internal _sha256_bytes helper.

    Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

    Args:
        data: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    return hashlib.sha256(data).hexdigest()


def _utc_now() -> str:
    """Implement the internal _utc_now helper.

    Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

    Returns:
        The structured value promised by the function signature.
    """
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class ArtifactManager:
    """Coordinate ArtifactManager within the artifacts boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    run_id: str
    run_dir: Path
    permission_gate: PermissionGate
    hooks: Any | None = None
    artifacts: list[dict[str, Any]] = field(default_factory=list)

    def ensure_dir(self, relative_dir: str) -> Path:
        """Execute ensure_dir at the artifacts boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            relative_dir: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        directory = self.run_dir / relative_dir
        decision = self.permission_gate.check_write_path(str(directory))
        if decision["decision"] != "allow":
            raise PermissionError(decision["reason"])
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def _emit(self, event: str, payload: dict[str, Any]) -> None:
        """Implement the internal _emit helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            event: Value supplied by the caller and validated by the surrounding schema.
            payload: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        if self.hooks:
            self.hooks.emit(event, {"run_id": self.run_id, **payload})

    def register_file(self, path: str | Path, artifact_type: str) -> dict[str, Any]:
        """Execute register_file at the artifacts boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            path: Value supplied by the caller and validated by the surrounding schema.
            artifact_type: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        resolved = Path(path).resolve()
        data = resolved.read_bytes()
        existing = next((item for item in self.artifacts if item["path"] == str(resolved)), None)
        if existing is not None:
            existing.update(
                {
                    "type": artifact_type,
                    "sha256": _sha256_bytes(data),
                    "created_at": _utc_now(),
                }
            )
            artifact = existing
        else:
            artifact = {
                "artifact_id": f"a{len(self.artifacts) + 1}",
                "type": artifact_type,
                "path": str(resolved),
                "sha256": _sha256_bytes(data),
                "created_at": _utc_now(),
            }
            self.artifacts.append(artifact)
        self._emit("ArtifactCreated", {"path": str(resolved), "artifact_type": artifact_type})
        self.save_manifest()
        return artifact

    def write_text(self, relative_path: str, content: str, artifact_type: str) -> Path:
        """Execute write_text at the artifacts boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            relative_path: Value supplied by the caller and validated by the surrounding schema.
            content: Value supplied by the caller and validated by the surrounding schema.
            artifact_type: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        target = (self.run_dir / relative_path).resolve()
        decision = self.permission_gate.check_write_path(str(target))
        if decision["decision"] != "allow":
            self._emit("PermissionDenied", {"path": str(target), "reason": decision["reason"]})
            raise PermissionError(decision["reason"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        self._emit("FileWritten", {"path": str(target)})
        self.register_file(target, artifact_type)
        return target

    def write_json(self, relative_path: str, payload: dict[str, Any], artifact_type: str) -> Path:
        """Execute write_json at the artifacts boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            relative_path: Value supplied by the caller and validated by the surrounding schema.
            payload: Value supplied by the caller and validated by the surrounding schema.
            artifact_type: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        return self.write_text(relative_path, json.dumps(payload, indent=2, ensure_ascii=False, default=str), artifact_type)

    def save_manifest(self) -> Path:
        """Execute save_manifest at the artifacts boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Returns:
            The structured value promised by the function signature.
        """
        manifest_path = (self.run_dir / "artifacts.json").resolve()
        manifest = {"run_id": self.run_id, "artifacts": self.artifacts}
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        return manifest_path
