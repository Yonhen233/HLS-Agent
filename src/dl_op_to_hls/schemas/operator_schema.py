from __future__ import annotations

import re

from ..core.errors import AgentRuntimeError, build_error
from ..core.design_objectives import normalize_objective_mode


def normalize_operator_task(task: dict) -> dict:
    _validate_operator_contract(task)
    normalized = dict(task)
    normalized.setdefault("name", f"{task.get('op_type', 'operator').lower()}_demo")
    optimization = dict(task.get("optimization", {}))
    normalized["objective"] = normalize_objective_mode(
        optimization.get("objective", task.get("objective", "latency")),
        default="latency",
    )
    if "objective" in optimization:
        optimization["objective"] = normalized["objective"]
    normalized["optimization"] = optimization
    return normalized


def _validate_operator_contract(task: dict) -> None:
    dtype = task.get("dtype")
    if dtype is not None:
        match = re.fullmatch(r"ap_fixed\s*<\s*(\d+)\s*,\s*(\d+)\s*>", str(dtype))
        if not match or int(match.group(1)) <= int(match.group(2)) or int(match.group(2)) <= 0:
            raise AgentRuntimeError(
                build_error(
                    "InvalidTaskError",
                    "dtype must use ap_fixed<total_bits,integer_bits> with total_bits > integer_bits > 0.",
                    recoverable=False,
                    source="schemas.operator_schema",
                    details={"dtype": dtype},
                )
            )

    for field in ("input_shape", "weight_shape", "output_shape"):
        shape = task.get(field)
        if shape is None:
            continue
        if not isinstance(shape, list) or not shape or any(not isinstance(value, int) for value in shape):
            raise AgentRuntimeError(
                build_error(
                    "UnsupportedOperatorError",
                    f"{field} must be a non-empty static integer shape.",
                    recoverable=False,
                    source="schemas.operator_schema",
                    details={field: shape},
                )
            )
        if any(value <= 0 for value in shape):
            raise AgentRuntimeError(
                build_error(
                    "InvalidTaskError",
                    f"{field} dimensions must be positive.",
                    recoverable=False,
                    source="schemas.operator_schema",
                    details={field: shape},
                )
            )

    if task.get("op_type") == "MatMul":
        lhs = task.get("input_shape")
        rhs = task.get("weight_shape")
        output = task.get("output_shape")
        if lhs and rhs and output and (
            len(lhs) != 2 or len(rhs) != 2 or len(output) != 2
            or lhs[1] != rhs[0] or output != [lhs[0], rhs[1]]
        ):
            raise AgentRuntimeError(
                build_error(
                    "InvalidTaskError",
                    "MatMul shapes must satisfy [M,K] x [K,N] -> [M,N].",
                    recoverable=False,
                    source="schemas.operator_schema",
                    details={"input_shape": lhs, "weight_shape": rhs, "output_shape": output},
                )
            )
