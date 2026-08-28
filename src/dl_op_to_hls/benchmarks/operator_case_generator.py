from __future__ import annotations

import math
import random
import re
from dataclasses import asdict, dataclass
from typing import Any


FIXED_RE = re.compile(r"(?:ap_)?fixed\s*<\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*([A-Z_]+))?(?:\s*,\s*([A-Z_]+))?", re.I)
INPUT_FAMILIES = (
    "zeros",
    "ones",
    "alternating",
    "random_small",
    "near_limits",
    "overflow_pressure",
    "sparse",
    "symmetric",
    "impulse",
    "near_boundary",
)


@dataclass(frozen=True)
class FixedPointSpec:
    total_bits: int
    integer_bits: int
    rounding_mode: str = "AP_TRN"
    overflow_mode: str = "AP_WRAP"

    @property
    def fractional_bits(self) -> int:
        return self.total_bits - self.integer_bits

    @property
    def step(self) -> float:
        return 2.0 ** (-self.fractional_bits)

    @property
    def minimum(self) -> float:
        return -(2.0 ** (self.integer_bits - 1))

    @property
    def maximum(self) -> float:
        return (2.0 ** (self.integer_bits - 1)) - self.step

    @classmethod
    def parse(cls, value: str) -> "FixedPointSpec":
        match = FIXED_RE.search(value)
        if not match:
            raise ValueError(f"Unsupported fixed-point dtype: {value}")
        total, integer, rounding, overflow = match.groups()
        spec = cls(int(total), int(integer), rounding or "AP_TRN", overflow or "AP_WRAP")
        if spec.total_bits < 2 or spec.integer_bits < 1 or spec.integer_bits > spec.total_bits:
            raise ValueError(f"Invalid fixed-point dtype: {value}")
        return spec

    def quantize(self, value: float) -> tuple[float, bool, bool]:
        scaled = value / self.step
        integer = round(scaled) if self.rounding_mode == "AP_RND" else math.floor(scaled)
        minimum_int = -(2 ** (self.total_bits - 1))
        maximum_int = (2 ** (self.total_bits - 1)) - 1
        overflowed = integer < minimum_int or integer > maximum_int
        saturated = False
        if overflowed and self.overflow_mode == "AP_SAT":
            integer = min(maximum_int, max(minimum_int, integer))
            saturated = True
        elif overflowed:
            span = 2**self.total_bits
            integer = ((integer - minimum_int) % span) + minimum_int
        return integer * self.step, overflowed, saturated


def generate_operator_cases() -> list[dict[str, Any]]:
    """Generate a layered pairwise matrix; each row is an independent numeric case."""

    dtypes = ("ap_fixed<8,3>", "ap_fixed<12,4>", "ap_fixed<16,6>")
    cases: list[dict[str, Any]] = []
    family_index = 0

    def add(operator: str, shape: Any, dtype: str, params: dict[str, Any] | None = None) -> None:
        nonlocal family_index
        for offset in (0, 5):
            family = INPUT_FAMILIES[(family_index + offset) % len(INPUT_FAMILIES)]
            case_id = f"{operator.lower()}_{len(cases) + 1:03d}"
            cases.append(
                {
                    "case_id": case_id,
                    "operator": operator,
                    "shape": shape,
                    "dtype": dtype,
                    "input_family": family,
                    "seed": 1000 + len(cases),
                    "rounding_mode": "AP_TRN",
                    "overflow_mode": "AP_WRAP",
                    "accumulator_dtype": _accumulator_dtype(dtype),
                    "golden_mode": "python_math_and_bit_accurate",
                    "tolerance": FixedPointSpec.parse(dtype).step,
                    "expected_outcome": "reference_ready",
                    "objective": ("latency", "resource", "balanced")[len(cases) % 3],
                    "target_part": "xc7z020clg400-1",
                    "clock_period": (5, 10)[len(cases) % 2],
                    "params": params or {},
                    "evidence_class": "unit",
                }
            )
        family_index += 1

    for shape in ([8, 8], [16, 32], [32, 16], [32, 64]):
        for dtype in dtypes:
            add("Dense", shape, dtype)
    for shape in ([4, 4, 4], [8, 8, 8], [16, 16, 16], [8, 16, 4]):
        for dtype in dtypes:
            add("MatMul", shape, dtype)
    for operator in ("ReLU", "Add", "ScaleShift"):
        for length in (16, 64, 256):
            for dtype in dtypes:
                add(operator, [length], dtype, {"scale": 1.5, "shift": -0.25} if operator == "ScaleShift" else {})
    conv_specs = (
        {"input_shape": [6, 6, 1], "kernel": [3, 3], "output_channels": 2, "stride": [1, 1], "padding": "valid", "layout": "NHWC", "groups": 1},
        {"input_shape": [8, 8, 3], "kernel": [3, 3], "output_channels": 4, "stride": [1, 1], "padding": "same", "layout": "NHWC", "groups": 1},
        {"input_shape": [16, 16, 4], "kernel": [3, 3], "output_channels": 8, "stride": [1, 1], "padding": "same", "layout": "NHWC", "groups": 1},
    )
    for spec in conv_specs:
        for dtype in dtypes:
            add("Conv2D", spec["input_shape"], dtype, spec)
    return cases


def validate_case_schema(case: dict[str, Any]) -> list[str]:
    required = {
        "case_id", "operator", "shape", "dtype", "input_family", "seed", "rounding_mode",
        "overflow_mode", "golden_mode", "tolerance", "expected_outcome", "objective",
        "target_part", "clock_period", "evidence_class",
    }
    errors = [f"missing {key}" for key in sorted(required.difference(case))]
    if case.get("input_family") not in INPUT_FAMILIES:
        errors.append("unsupported input_family")
    try:
        FixedPointSpec.parse(str(case.get("dtype")))
    except ValueError as exc:
        errors.append(str(exc))
    if case.get("operator") == "Conv2D":
        params = case.get("params") or {}
        if params.get("layout") != "NHWC":
            errors.append("Conv2D requires NHWC layout")
        if int(params.get("groups", 1)) != 1:
            errors.append("Conv2D groups must equal 1")
        if not all(isinstance(value, int) and value > 0 for value in case.get("shape") or []):
            errors.append("Conv2D shape must be static positive integers")
    return errors


def evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    errors = validate_case_schema(case)
    if errors:
        return {"case_id": case.get("case_id"), "passed": False, "errors": errors, "evidence_class": "unit"}
    spec = FixedPointSpec.parse(case["dtype"])
    rng = random.Random(int(case["seed"]))
    inputs = _make_inputs(_input_count(case), case["input_family"], spec, rng)
    quantized_inputs, input_overflow, input_saturation = _quantize_many(inputs, spec)
    math_output, bit_output, arithmetic_overflow, arithmetic_saturation = _run_operator(case, quantized_inputs, spec, rng)
    errors_abs = [abs(a - b) for a, b in zip(math_output, bit_output)]
    tolerance = float(case["tolerance"])
    return {
        "case_id": case["case_id"],
        "operator": case["operator"],
        "passed": bool(bit_output) and all(math.isfinite(value) for value in bit_output),
        "reference_status": "ready",
        "max_abs_error": max(errors_abs, default=0.0),
        "mean_abs_error": sum(errors_abs) / len(errors_abs) if errors_abs else 0.0,
        "mismatch_count": sum(error > tolerance for error in errors_abs),
        "saturation_count": input_saturation + arithmetic_saturation,
        "overflow_count": input_overflow + arithmetic_overflow,
        "output_count": len(bit_output),
        "evidence_class": "unit",
    }


def suite_payload() -> dict[str, Any]:
    cases = generate_operator_cases()
    return {
        "schema_version": "1.0",
        "suite_name": "operator_functional_suite",
        "description": "Layer-1 independent mathematical and bit-accurate golden cases; not real HLS evidence.",
        "case_count": len(cases),
        "evidence_class": "unit",
        "cases": cases,
    }


def _accumulator_dtype(dtype: str) -> str:
    spec = FixedPointSpec.parse(dtype)
    return f"ap_fixed<{min(32, spec.total_bits + 8)},{min(16, spec.integer_bits + 4)}>"


def _input_count(case: dict[str, Any]) -> int:
    shape = case["shape"]
    if case["operator"] == "Dense":
        return int(shape[0])
    if case["operator"] == "MatMul":
        rows, shared, cols = shape
        return rows * shared + shared * cols
    count = 1
    for value in shape:
        count *= int(value)
    return count


def _make_inputs(count: int, family: str, spec: FixedPointSpec, rng: random.Random) -> list[float]:
    small = min(0.75, spec.maximum / 4)
    if family == "zeros":
        return [0.0] * count
    if family == "ones":
        return [1.0] * count
    if family == "alternating":
        return [small if index % 2 == 0 else -small for index in range(count)]
    if family == "random_small":
        return [rng.uniform(-small, small) for _ in range(count)]
    if family == "near_limits":
        return [spec.maximum - spec.step if index % 2 == 0 else spec.minimum + spec.step for index in range(count)]
    if family == "overflow_pressure":
        return [spec.maximum * 1.5 if index % 2 == 0 else spec.minimum * 1.5 for index in range(count)]
    if family == "sparse":
        return [rng.uniform(-small, small) if index % 7 == 0 else 0.0 for index in range(count)]
    if family == "symmetric":
        half = [rng.uniform(0, small) for _ in range((count + 1) // 2)]
        return (half + [-value for value in half])[:count]
    if family == "impulse":
        values = [0.0] * count
        values[count // 2] = 1.0
        return values
    return [spec.step * (0.49 if index % 2 == 0 else 0.51) for index in range(count)]


def _quantize_many(values: list[float], spec: FixedPointSpec) -> tuple[list[float], int, int]:
    output: list[float] = []
    overflow_count = saturation_count = 0
    for value in values:
        quantized, overflowed, saturated = spec.quantize(value)
        output.append(quantized)
        overflow_count += int(overflowed)
        saturation_count += int(saturated)
    return output, overflow_count, saturation_count


def _run_operator(case: dict[str, Any], values: list[float], spec: FixedPointSpec, rng: random.Random) -> tuple[list[float], list[float], int, int]:
    operator = case["operator"]
    shape = case["shape"]
    overflow_count = saturation_count = 0

    def q(value: float) -> float:
        nonlocal overflow_count, saturation_count
        quantized, overflowed, saturated = spec.quantize(value)
        overflow_count += int(overflowed)
        saturation_count += int(saturated)
        return quantized

    if operator in {"ReLU", "Add", "ScaleShift"}:
        if operator == "ReLU":
            math_output = [max(0.0, value) for value in values]
        elif operator == "Add":
            rhs = list(reversed(values))
            math_output = [left + right for left, right in zip(values, rhs)]
        else:
            scale = float((case.get("params") or {}).get("scale", 1.5))
            shift = float((case.get("params") or {}).get("shift", -0.25))
            math_output = [value * scale + shift for value in values]
        return math_output, [q(value) for value in math_output], overflow_count, saturation_count

    if operator == "Dense":
        input_dim, output_dim = shape
        weights = [q(rng.uniform(-0.5, 0.5)) for _ in range(input_dim * output_dim)]
        bias = [q(rng.uniform(-0.25, 0.25)) for _ in range(output_dim)]
        math_output = [bias[out] + sum(values[index] * weights[index * output_dim + out] for index in range(input_dim)) for out in range(output_dim)]
        bit_output = []
        for out in range(output_dim):
            acc = bias[out]
            for index in range(input_dim):
                acc = q(acc + q(values[index] * weights[index * output_dim + out]))
            bit_output.append(acc)
        return math_output, bit_output, overflow_count, saturation_count

    if operator == "MatMul":
        rows, shared, cols = shape
        left = values[: rows * shared]
        right = values[rows * shared :]
        math_output = [sum(left[row * shared + k] * right[k * cols + col] for k in range(shared)) for row in range(rows) for col in range(cols)]
        bit_output = []
        for row in range(rows):
            for col in range(cols):
                acc = 0.0
                for k in range(shared):
                    acc = q(acc + q(left[row * shared + k] * right[k * cols + col]))
                bit_output.append(acc)
        return math_output, bit_output, overflow_count, saturation_count

    if operator == "Conv2D":
        params = case["params"]
        height, width, channels = shape
        kernel_h, kernel_w = params["kernel"]
        output_channels = int(params["output_channels"])
        padding = params["padding"]
        pad_h = kernel_h // 2 if padding == "same" else 0
        pad_w = kernel_w // 2 if padding == "same" else 0
        out_h = height if padding == "same" else height - kernel_h + 1
        out_w = width if padding == "same" else width - kernel_w + 1
        weights = [q(rng.uniform(-0.35, 0.35)) for _ in range(kernel_h * kernel_w * channels * output_channels)]
        bias = [q(rng.uniform(-0.2, 0.2)) for _ in range(output_channels)]
        math_output: list[float] = []
        bit_output: list[float] = []
        for oy in range(out_h):
            for ox in range(out_w):
                for oc in range(output_channels):
                    terms: list[float] = []
                    for ky in range(kernel_h):
                        iy = oy + ky - pad_h
                        for kx in range(kernel_w):
                            ix = ox + kx - pad_w
                            for ic in range(channels):
                                sample = values[(iy * width + ix) * channels + ic] if 0 <= iy < height and 0 <= ix < width else 0.0
                                weight = weights[((ky * kernel_w + kx) * channels + ic) * output_channels + oc]
                                terms.append(sample * weight)
                    math_output.append(bias[oc] + sum(terms))
                    acc = bias[oc]
                    for term in terms:
                        acc = q(acc + q(term))
                    bit_output.append(acc)
        return math_output, bit_output, overflow_count, saturation_count
    raise ValueError(f"Unsupported operator: {operator}")


def case_to_dict(case: Any) -> dict[str, Any]:
    return asdict(case) if hasattr(case, "__dataclass_fields__") else dict(case)
