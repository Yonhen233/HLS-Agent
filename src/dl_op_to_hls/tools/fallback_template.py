from __future__ import annotations

from pathlib import Path
from string import Template
from typing import Any

from ..core.errors import build_error, error_result


def _load_template(template_dir: Path, name: str) -> Template:
    return Template((template_dir / name).read_text(encoding="utf-8"))


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _shape_value(values: list[int] | None, index: int, default: int) -> int:
    if not values or len(values) <= index:
        return default
    return int(values[index])


def _render_testbench(op_type: str, task: dict[str, Any], template_dir: Path) -> str:
    top_function = task["name"]
    header_name = f"{top_function}.h"
    dtype = task.get("dtype", "ap_fixed<16,6>")
    if op_type == "Dense":
        input_dim = _shape_value(task.get("input_shape"), 0, 16)
        output_dim = _shape_value(task.get("output_shape"), 0, 32)
        setup = "\n".join(
            [
                f"  data_t input[{input_dim}] = {{0}};",
                f"  data_t weights[{output_dim}][{input_dim}] = {{0}};",
                f"  data_t bias[{output_dim}] = {{0}};",
                f"  data_t output[{output_dim}] = {{0}};",
                f"  for (int i = 0; i < {input_dim}; ++i) input[i] = (data_t)(i % 4);",
                f"  {top_function}(input, weights, bias, output);",
            ]
        )
    elif op_type == "MatMul":
        rows = _shape_value(task.get("input_shape"), 0, 4)
        inner = _shape_value(task.get("input_shape"), 1, 4)
        cols = _shape_value(task.get("output_shape"), 1, 4)
        setup = "\n".join(
            [
                f"  data_t lhs[{rows}][{inner}] = {{0}};",
                f"  data_t rhs[{inner}][{cols}] = {{0}};",
                f"  data_t output[{rows}][{cols}] = {{0}};",
                f"  {top_function}(lhs, rhs, output);",
            ]
        )
    elif op_type == "ReLU":
        width = _shape_value(task.get("input_shape"), 0, 16)
        setup = "\n".join(
            [
                f"  data_t input[{width}] = {{0}};",
                f"  data_t output[{width}] = {{0}};",
                f"  for (int i = 0; i < {width}; ++i) input[i] = (i % 2 == 0) ? (data_t)i : (data_t)(-i);",
                f"  {top_function}(input, output);",
            ]
        )
    else:
        width = _shape_value(task.get("input_shape"), 0, 16)
        setup = "\n".join(
            [
                f"  data_t lhs[{width}] = {{0}};",
                f"  data_t rhs[{width}] = {{0}};",
                f"  data_t output[{width}] = {{0}};",
                f"  {top_function}(lhs, rhs, output);",
            ]
        )
    return _load_template(template_dir, "testbench.cpp.j2").safe_substitute(
        top_function=top_function,
        header_name=header_name,
        dtype=dtype,
        setup_block=setup,
        output_comment=f"Smoke testbench for {op_type}",
    )


def render_fallback_operator(task: dict[str, Any], output_dir: str) -> dict[str, Any]:
    template_dir = Path(__file__).resolve().parents[1] / "templates" / "fallback"
    op_type = str(task.get("op_type", "")).strip()
    top_function = task["name"]
    dtype = task.get("dtype", "ap_fixed<16,6>")
    generated_dir = Path(output_dir)
    generated_dir.mkdir(parents=True, exist_ok=True)
    template_map = {
        "Dense": ("dense.h.j2", "dense.cpp.j2"),
        "MatMul": ("matmul.h.j2", "matmul.cpp.j2"),
        "ReLU": ("relu.h.j2", "relu.cpp.j2"),
        "Add": ("add.h.j2", "add.cpp.j2"),
    }
    if op_type not in template_map:
        return error_result(
            build_error(
                "UnsupportedOperatorError",
                f"No fallback template for operator {op_type}.",
                recoverable=True,
                source="fallback.generate_operator_hls",
                suggested_action="Use graph rewrite or LLM candidate generation.",
            )
        )

    header_template_name, cpp_template_name = template_map[op_type]
    context = {
        "guard": f"{top_function.upper()}_H",
        "top_function": top_function,
        "dtype": dtype,
        "input_dim": _shape_value(task.get("input_shape"), 0, 16),
        "output_dim": _shape_value(task.get("output_shape"), 0, 32),
        "lhs_rows": _shape_value(task.get("input_shape"), 0, 4),
        "lhs_cols": _shape_value(task.get("input_shape"), 1, 4),
        "rhs_cols": _shape_value(task.get("output_shape"), 1, 4),
        "reuse_factor": int(task.get("optimization", {}).get("reuse_factor", 1)),
        "pipeline_ii": int(task.get("optimization", {}).get("pipeline_ii", 1)),
        "project_name": top_function,
        "part": task.get("target", {}).get("part", "xc7z020clg400-1"),
        "clock_period": task.get("target", {}).get("clock_period", 5),
        "cpp_name": f"{top_function}.cpp",
        "testbench_name": "testbench.cpp",
    }
    header_text = _load_template(template_dir, header_template_name).safe_substitute(context)
    cpp_text = _load_template(template_dir, cpp_template_name).safe_substitute(context)
    tb_text = _render_testbench(op_type, task, template_dir)
    tcl_text = _load_template(template_dir, "run_hls.tcl.j2").safe_substitute(context)

    header_path = generated_dir / f"{top_function}.h"
    cpp_path = generated_dir / f"{top_function}.cpp"
    tb_path = generated_dir / "testbench.cpp"
    tcl_path = generated_dir / "run_hls.tcl"
    for path, text in (
        (header_path, header_text),
        (cpp_path, cpp_text),
        (tb_path, tb_text),
        (tcl_path, tcl_text),
    ):
        _write_file(path, text)
    return {
        "status": "success",
        "source": "fallback_template",
        "generated_files": [str(header_path), str(cpp_path), str(tb_path), str(tcl_path)],
    }


def generate_operator_hls(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    task = arguments["task"]
    output_dir = arguments["output_dir"]
    result = render_fallback_operator(task, output_dir)
    artifact_manager = context.get("artifact_manager")
    if artifact_manager and result.get("status") == "success":
        file_types = {
            ".h": "hls_header",
            ".cpp": "hls_cpp",
            ".tcl": "tcl",
        }
        for file_path in result["generated_files"]:
            suffix = Path(file_path).suffix
            artifact_type = "testbench" if Path(file_path).name == "testbench.cpp" else file_types.get(suffix, "hls_cpp")
            artifact_manager.register_file(file_path, artifact_type)
    return result


def generate_testbench(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    task = arguments["task"]
    output_dir = Path(arguments["output_dir"])
    template_dir = Path(__file__).resolve().parents[1] / "templates" / "fallback"
    tb_text = _render_testbench(task.get("op_type", "operator"), task, template_dir)
    tb_path = output_dir / "testbench.cpp"
    _write_file(tb_path, tb_text)
    artifact_manager = context.get("artifact_manager")
    if artifact_manager:
        artifact_manager.register_file(tb_path, "testbench")
    return {"status": "success", "testbench_path": str(tb_path)}

