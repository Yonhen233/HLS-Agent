from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.errors import build_error, error_result


def _resolve_model_path(model_path: str, context: dict[str, Any]) -> Path:
    path = Path(model_path)
    if path.is_absolute():
        return path.resolve()
    config = context.get("config")
    workspace_root = getattr(config, "workspace_root", None)
    if workspace_root is not None:
        candidate = (Path(workspace_root) / path).resolve()
        if candidate.exists():
            return candidate
    return path.resolve()


def _rewrite_gemm_to_matmul_add(model_path: Path, context: dict[str, Any]) -> dict[str, Any]:
    try:
        import onnx  # type: ignore
        from onnx import TensorProto, helper, numpy_helper  # type: ignore
    except Exception as exc:
        return error_result(
            build_error(
                "HLS4MLConversionError",
                f"ONNX graph rewrite requires the onnx Python package: {exc}",
                recoverable=True,
                source="graph_rewrite.rewrite",
                suggested_action="Install onnx or provide a model already expressed with hls4ml-supported ops.",
            )
        )

    model = onnx.load(str(model_path))
    graph = model.graph
    initializer_by_name = {item.name: item for item in graph.initializer}
    new_nodes = []
    new_initializers = list(graph.initializer)
    rewrites: list[str] = []
    warnings: list[str] = []
    rewritten = False

    for node in graph.node:
        if node.op_type != "Gemm":
            new_nodes.append(node)
            continue

        attrs = {attr.name: helper.get_attribute_value(attr) for attr in node.attribute}
        alpha = float(attrs.get("alpha", 1.0))
        beta = float(attrs.get("beta", 1.0))
        trans_a = int(attrs.get("transA", 0))
        trans_b = int(attrs.get("transB", 0))
        if trans_a != 0 or alpha != 1.0 or beta != 1.0:
            warnings.append(
                "Skipped Gemm rewrite with non-trivial alpha/beta/transA; rewriting it could change model semantics."
            )
            new_nodes.append(node)
            continue

        if len(node.input) < 2:
            warnings.append("Skipped malformed Gemm node with fewer than two inputs.")
            new_nodes.append(node)
            continue

        a_input = node.input[0]
        b_input = node.input[1]
        matmul_inputs = [a_input, b_input]
        if trans_b:
            initializer = initializer_by_name.get(b_input)
            if initializer is not None:
                transposed_name = f"{b_input}_gemm_transposed"
                array = numpy_helper.to_array(initializer).T
                new_initializer = numpy_helper.from_array(array, name=transposed_name)
                new_initializers.append(new_initializer)
                matmul_inputs[1] = transposed_name
            else:
                transposed_name = f"{node.name or 'gemm'}_B_transposed"
                transpose_node = helper.make_node(
                    "Transpose",
                    inputs=[b_input],
                    outputs=[transposed_name],
                    name=f"{node.name or 'gemm'}_transpose_b",
                    perm=[1, 0],
                )
                new_nodes.append(transpose_node)
                matmul_inputs[1] = transposed_name

        output_name = node.output[0]
        matmul_output = output_name
        has_bias = len(node.input) >= 3 and bool(node.input[2])
        if has_bias:
            matmul_output = f"{output_name}_matmul"
        matmul_node = helper.make_node(
            "MatMul",
            inputs=matmul_inputs,
            outputs=[matmul_output],
            name=f"{node.name or 'gemm'}_matmul",
        )
        new_nodes.append(matmul_node)
        if has_bias:
            add_node = helper.make_node(
                "Add",
                inputs=[matmul_output, node.input[2]],
                outputs=[output_name],
                name=f"{node.name or 'gemm'}_add",
            )
            new_nodes.append(add_node)
            rewrites.append("Gemm -> MatMul + Add")
        else:
            rewrites.append("Gemm -> MatMul")
        rewritten = True

    if not rewritten:
        return {
            "status": "rewrite_suggested",
            "rewrites": ["Gemm -> MatMul + Add"],
            "detected_ops": sorted({node.op_type for node in model.graph.node}),
            "recommendation": "Gemm was detected but no safe automatic rewrite was applied.",
            "implemented": False,
            "warnings": warnings,
        }

    del graph.node[:]
    graph.node.extend(new_nodes)
    del graph.initializer[:]
    graph.initializer.extend(new_initializers)

    try:
        rewritten_model = onnx.shape_inference.infer_shapes(model)
    except Exception:
        rewritten_model = model

    run_dir = Path(context.get("run_dir") or model_path.parent)
    relative_output = Path("rewritten") / f"{model_path.stem}_gemm_rewritten.onnx"
    output_path = (run_dir / relative_output).resolve()
    permission_gate = context.get("permission_gate")
    if permission_gate is not None:
        decision = permission_gate.check_write_path(str(output_path))
        if decision["decision"] != "allow":
            return error_result(
                build_error(
                    "PermissionDeniedError",
                    decision["reason"],
                    recoverable=True,
                    source="graph_rewrite.rewrite",
                    suggested_action="Write rewritten model under the current run directory.",
                    details={"output_path": str(output_path)},
                )
            )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    onnx.save(rewritten_model, str(output_path))
    artifact_manager = context.get("artifact_manager")
    if artifact_manager is not None:
        artifact_manager.register_file(output_path, "rewritten_model")

    return {
        "status": "success",
        "rewrites": sorted(set(rewrites)),
        "detected_ops": sorted({node.op_type for node in rewritten_model.graph.node}),
        "recommendation": "Retry hls4ml support/config/conversion with the rewritten ONNX model.",
        "implemented": True,
        "rewritten_model_path": str(output_path),
        "warnings": warnings,
    }


def rewrite_graph(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    task = arguments.get("task", {})
    op_type = task.get("op_type") or task.get("name") or "unknown"
    rewrites = []
    recommendation = "No rewrite rule matched."
    detected_ops: list[str] = []
    model_path = task.get("model_path")
    resolved_model_path: Path | None = None
    if model_path:
        resolved_model_path = _resolve_model_path(str(model_path), context)
    if resolved_model_path and resolved_model_path.exists() and resolved_model_path.suffix.lower() == ".onnx":
        try:
            import onnx  # type: ignore

            model = onnx.load(str(resolved_model_path))
            detected_ops = sorted({node.op_type for node in model.graph.node})
        except Exception:
            detected_ops = []
    if str(op_type).lower() == "gemm":
        rewrites = ["Gemm -> MatMul + Add"]
        recommendation = "Try MatMul + Add fallback template."
    elif "Gemm" in detected_ops:
        return _rewrite_gemm_to_matmul_add(resolved_model_path, context)
    elif any(op in detected_ops for op in {"Shape", "Reshape", "Flatten"}):
        rewrites = ["Shape/Reshape/Flatten -> static shape elimination"]
        recommendation = "Eliminate static shape operators before hls4ml conversion; keep tensor shapes in metadata."
    elif str(op_type).lower() in {"batchnorm", "batchnormalization"}:
        rewrites = ["BatchNorm inference -> fold into Dense / Conv"]
        recommendation = "Fold BatchNorm parameters before HLS conversion."
    elif str(op_type).lower() in {"flatten", "reshape"}:
        rewrites = ["Flatten / Reshape -> static shape elimination"]
        recommendation = "Remove no-op reshape and retry support check."
    return {
        "status": "rewrite_suggested" if rewrites else "success",
        "rewrites": rewrites,
        "detected_ops": detected_ops,
        "recommendation": recommendation,
        "implemented": False,
    }
