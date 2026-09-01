from __future__ import annotations

import os
from dataclasses import dataclass


VALID_INPUT_CONTEXT_MODES = {"full", "scoped"}
VALID_RESULT_CONTEXT_MODES = {"raw", "compressed"}


@dataclass(frozen=True)
class ContextModeConfig:
    """Orthogonal context modes used by the context-ablation benchmark.

    Production defaults remain scoped input plus compressed specialist results.
    """

    input_context_mode: str = "scoped"
    result_context_mode: str = "compressed"

    @classmethod
    def from_env(cls) -> "ContextModeConfig":
        config = cls(
            input_context_mode=os.environ.get("DL_OP_TO_HLS_INPUT_CONTEXT_MODE", "scoped").strip().lower(),
            result_context_mode=os.environ.get("DL_OP_TO_HLS_RESULT_CONTEXT_MODE", "compressed").strip().lower(),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.input_context_mode not in VALID_INPUT_CONTEXT_MODES:
            raise ValueError(f"Invalid input_context_mode: {self.input_context_mode}")
        if self.result_context_mode not in VALID_RESULT_CONTEXT_MODES:
            raise ValueError(f"Invalid result_context_mode: {self.result_context_mode}")

    def to_dict(self) -> dict[str, str]:
        return {
            "input_context_mode": self.input_context_mode,
            "result_context_mode": self.result_context_mode,
        }
