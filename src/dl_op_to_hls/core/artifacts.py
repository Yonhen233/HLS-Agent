from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .permissions import PermissionGate


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class ArtifactManager:
    run_id: str
    run_dir: Path
    permission_gate: PermissionGate
    hooks: Any | None = None
    artifacts: list[dict[str, Any]] = field(default_factory=list)

    def ensure_dir(self, relative_dir: str) -> Path:
        directory = self.run_dir / relative_dir
        decision = self.permission_gate.check_write_path(str(directory))
        if decision["decision"] != "allow":
            raise PermissionError(decision["reason"])
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def _emit(self, event: str, payload: dict[str, Any]) -> None:
        if self.hooks:
            self.hooks.emit(event, {"run_id": self.run_id, **payload})

    def register_file(self, path: str | Path, artifact_type: str) -> dict[str, Any]:
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
        return self.write_text(relative_path, json.dumps(payload, indent=2, ensure_ascii=False, default=str), artifact_type)

    def save_manifest(self) -> Path:
        manifest_path = (self.run_dir / "artifacts.json").resolve()
        manifest = {"run_id": self.run_id, "artifacts": self.artifacts}
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        return manifest_path
