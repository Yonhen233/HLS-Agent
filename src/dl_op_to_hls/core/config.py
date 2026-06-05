from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_PERMISSIONS = {
    "filesystem": {
        "allowed_read_dirs": [".", "./examples", "./models", "./runs"],
        "allowed_write_dirs": ["./runs"],
        "denied_dirs": ["/", "/etc", "~/.ssh", "~/.aws"],
    },
    "commands": {
        "allow": ["vivado_hls", "vitis-run", "vitis", "pytest"],
        "ask": ["python"],
        "deny": ["rm", "rm -rf", "curl", "wget", "ssh", "scp", "sudo"],
    },
}


def _simple_yaml_load(text: str) -> dict[str, Any]:
    try:
        import yaml  # type: ignore

        loaded = yaml.safe_load(text)
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        pass

    result: dict[str, Any] = {}
    section_stack: list[tuple[int, dict[str, Any] | list[Any]]] = [(-1, result)]
    current_key: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        while section_stack and indent <= section_stack[-1][0]:
            section_stack.pop()
        container = section_stack[-1][1]
        if stripped.startswith("- "):
            value = stripped[2:].strip().strip('"').strip("'")
            if isinstance(container, list):
                container.append(value)
            elif current_key and isinstance(container, dict):
                target = container.setdefault(current_key, [])
                if isinstance(target, list):
                    target.append(value)
            continue
        if ":" in stripped:
            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip()
            current_key = key
            if not value:
                next_container: dict[str, Any] = {}
                if isinstance(container, dict):
                    container[key] = next_container
                section_stack.append((indent, next_container))
            else:
                parsed: Any = value.strip('"').strip("'")
                if parsed.lower() in {"true", "false"}:
                    parsed = parsed.lower() == "true"
                elif parsed.isdigit():
                    parsed = int(parsed)
                if isinstance(container, dict):
                    container[key] = parsed
    return result


@dataclass
class AppConfig:
    workspace_root: Path
    runs_root: Path
    docs_root: Path
    db_path: Path
    permissions_path: Path
    runtime_config_path: Path
    runtime_mode: str = "demo"
    llm_fallback_policy: str = "error"
    optimization_fallback_mode: str = "demo"
    specialist_llm_decider_enabled: bool = False
    mock_hls4ml: bool = True
    mock_vivado: bool = True
    hls_toolchain: str = "vivado_hls"
    hls4ml_backend: str | None = None
    vivado_hls_path: str | None = None
    vitis_hls_path: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, workspace_root: str | Path | None = None) -> "AppConfig":
        root = Path(workspace_root or os.getcwd()).resolve()
        runtime_config_path = root / "runtime.yaml"
        runtime_config = _simple_yaml_load(runtime_config_path.read_text(encoding="utf-8")) if runtime_config_path.exists() else {}
        runtime_section = runtime_config.get("runtime", {}) if isinstance(runtime_config.get("runtime", {}), dict) else {}
        llm_section = runtime_section.get("llm", {}) if isinstance(runtime_section.get("llm", {}), dict) else {}
        optimization_section = runtime_section.get("optimization", {}) if isinstance(runtime_section.get("optimization", {}), dict) else {}
        specialist_section = runtime_section.get("specialist", {}) if isinstance(runtime_section.get("specialist", {}), dict) else {}
        runtime_mode = os.environ.get("DL_OP_TO_HLS_RUNTIME_MODE", runtime_section.get("mode", "demo")).lower()
        if runtime_mode not in {"strict", "demo", "production"}:
            raise ValueError(f"Invalid DL_OP_TO_HLS runtime mode: {runtime_mode}")
        optimization_fallback_mode = os.environ.get(
            "DL_OP_TO_HLS_OPTIMIZATION_FALLBACK_MODE",
            optimization_section.get("fallback", "strict" if runtime_mode in {"strict", "production"} else "demo"),
        ).lower()
        llm_fallback_policy = os.environ.get("DL_OP_TO_HLS_LLM_FALLBACK_POLICY", llm_section.get("fallback", "error")).lower()
        specialist_llm_decider_enabled = os.environ.get("DL_OP_TO_HLS_SPECIALIST_LLM_DECIDER_ENABLED")
        if specialist_llm_decider_enabled is None:
            specialist_llm_decider_enabled_value = bool(specialist_section.get("llm_decider_enabled", False))
        else:
            specialist_llm_decider_enabled_value = specialist_llm_decider_enabled.strip().lower() in {"1", "true", "yes", "on"}
        toolchain_section = runtime_section.get("toolchain", {}) if isinstance(runtime_section.get("toolchain", {}), dict) else {}
        hls_toolchain = _normalize_hls_toolchain(
            os.environ.get("DL_OP_TO_HLS_HLS_TOOLCHAIN")
            or os.environ.get("DL_OP_TO_HLS_HLS_TOOL")
            or toolchain_section.get("hls_toolchain", "vivado_hls")
        )
        hls4ml_backend = os.environ.get("DL_OP_TO_HLS_HLS4ML_BACKEND") or toolchain_section.get("hls4ml_backend")
        if not hls4ml_backend and hls_toolchain == "vitis_hls":
            hls4ml_backend = "Vitis"
        return cls(
            workspace_root=root,
            runs_root=root / "runs",
            docs_root=root / "docs",
            db_path=root / "runs" / "metadata.db",
            permissions_path=root / "permissions.yaml",
            runtime_config_path=runtime_config_path,
            runtime_mode=runtime_mode,
            llm_fallback_policy=llm_fallback_policy,
            optimization_fallback_mode=optimization_fallback_mode,
            specialist_llm_decider_enabled=specialist_llm_decider_enabled_value,
            mock_hls4ml=os.environ.get("DL_OP_TO_HLS_MOCK_HLS4ML", "1") != "0",
            mock_vivado=os.environ.get("DL_OP_TO_HLS_MOCK_VIVADO", "1") != "0",
            hls_toolchain=hls_toolchain,
            hls4ml_backend=hls4ml_backend,
            vivado_hls_path=os.environ.get("DL_OP_TO_HLS_VIVADO_HLS_PATH"),
            vitis_hls_path=os.environ.get("DL_OP_TO_HLS_VITIS_HLS_PATH"),
        )

    def ensure_directories(self) -> None:
        self.runs_root.mkdir(parents=True, exist_ok=True)
        self.docs_root.mkdir(parents=True, exist_ok=True)

    def load_permissions(self) -> dict[str, Any]:
        if not self.permissions_path.exists():
            return DEFAULT_PERMISSIONS
        data = _simple_yaml_load(self.permissions_path.read_text(encoding="utf-8"))
        if not data:
            return DEFAULT_PERMISSIONS
        return data

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_root": str(self.workspace_root),
            "runs_root": str(self.runs_root),
            "docs_root": str(self.docs_root),
            "db_path": str(self.db_path),
            "permissions_path": str(self.permissions_path),
            "runtime_config_path": str(self.runtime_config_path),
            "runtime_mode": self.runtime_mode,
            "llm_fallback_policy": self.llm_fallback_policy,
            "optimization_fallback_mode": self.optimization_fallback_mode,
            "specialist_llm_decider_enabled": self.specialist_llm_decider_enabled,
            "mock_hls4ml": self.mock_hls4ml,
            "mock_vivado": self.mock_vivado,
            "hls_toolchain": self.hls_toolchain,
            "hls4ml_backend": self.hls4ml_backend,
            "vivado_hls_path": self.vivado_hls_path,
            "vitis_hls_path": self.vitis_hls_path,
            "extra": self.extra,
        }

    def write_runtime_config(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")


def _normalize_hls_toolchain(value: Any) -> str:
    text = str(value or "vivado_hls").strip().lower().replace("-", "_")
    aliases = {
        "vivado": "vivado_hls",
        "vivado_hls": "vivado_hls",
        "legacy_vivado": "vivado_hls",
        "vitis": "vitis_hls",
        "vitis_hls": "vitis_hls",
        "vitis_run": "vitis_hls",
        "vitisrun": "vitis_hls",
        "modern_vitis": "vitis_hls",
    }
    if text not in aliases:
        raise ValueError(f"Invalid HLS toolchain: {value}")
    return aliases[text]
