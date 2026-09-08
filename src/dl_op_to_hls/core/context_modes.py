"""core layer implementation for context_modes.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

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
        """Execute from_env at the context_modes boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Returns:
            The structured value promised by the function signature.
        """
        config = cls(
            input_context_mode=os.environ.get("DL_OP_TO_HLS_INPUT_CONTEXT_MODE", "scoped").strip().lower(),
            result_context_mode=os.environ.get("DL_OP_TO_HLS_RESULT_CONTEXT_MODE", "compressed").strip().lower(),
        )
        config.validate()
        return config

    def validate(self) -> None:
        """Execute validate at the context_modes boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Returns:
            The structured value promised by the function signature.
        """
        if self.input_context_mode not in VALID_INPUT_CONTEXT_MODES:
            raise ValueError(f"Invalid input_context_mode: {self.input_context_mode}")
        if self.result_context_mode not in VALID_RESULT_CONTEXT_MODES:
            raise ValueError(f"Invalid result_context_mode: {self.result_context_mode}")

    def to_dict(self) -> dict[str, str]:
        """Execute to_dict at the context_modes boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Returns:
            The structured value promised by the function signature.
        """
        return {
            "input_context_mode": self.input_context_mode,
            "result_context_mode": self.result_context_mode,
        }
