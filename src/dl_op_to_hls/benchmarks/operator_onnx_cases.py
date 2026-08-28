from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..adapters.hls4ml_adapter import HLS4MLAdapter
from .operator_suite_specs import all_suite_payloads


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _save_model(path: Path, nodes: list[Any], inputs: list[Any], outputs: list[Any], initializers: list[Any] | None = None, *, opset: int = 13) -> None:
    from onnx import helper, save  # type: ignore

    graph = helper.make_graph(nodes, path.stem, inputs, outputs, initializer=initializers or [])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", opset)])
    save(model, str(path))


def _tensor(name: str, shape: list[int | str | None], data_type: int | None = None) -> Any:
    from onnx import TensorProto, helper  # type: ignore

    return helper.make_tensor_value_info(name, data_type or TensorProto.FLOAT, shape)


def _array(name: str, values: Any, dtype: Any = None) -> Any:
    import numpy as np  # type: ignore
    from onnx import numpy_helper  # type: ignore

    return numpy_helper.from_array(np.asarray(values, dtype=dtype or np.float32), name=name)


def _dense_nodes(*, relu: bool = False, matmul_add: bool = False, trans_a: int = 0, alpha: float = 1.0) -> tuple[list[Any], list[Any]]:
    import numpy as np  # type: ignore
    from onnx import helper  # type: ignore

    if matmul_add:
        nodes = [
            helper.make_node("MatMul", ["input", "weight"], ["mm"], name="matmul"),
            helper.make_node("Add", ["mm", "bias"], ["dense_out"], name="bias_add"),
        ]
        initializers = [_array("weight", np.ones((4, 3))), _array("bias", np.zeros(3))]
    else:
        nodes = [
            helper.make_node(
                "Gemm", ["input", "weight", "bias"], ["dense_out"], name="gemm", transB=1, transA=trans_a, alpha=alpha
            )
        ]
        initializers = [_array("weight", np.ones((3, 4))), _array("bias", np.zeros(3))]
    if relu:
        nodes.append(helper.make_node("Relu", ["dense_out"], ["output"], name="relu"))
    return nodes, initializers


def _conv_prefix(*, group: int = 1) -> tuple[list[Any], list[Any]]:
    import numpy as np  # type: ignore
    from onnx import helper  # type: ignore

    in_channels = 2 if group != 1 else 1
    out_channels = 2
    weights = np.ones((out_channels, in_channels // group, 3, 3), dtype=np.float32)
    node = helper.make_node(
        "Conv", ["input", "conv_w", "conv_b"], ["conv_out"], name="conv", kernel_shape=[3, 3], group=group
    )
    return [node], [_array("conv_w", weights), _array("conv_b", np.zeros(out_channels))]


def _build_positive(case_id: str, path: Path) -> str:
    import numpy as np  # type: ignore
    from onnx import TensorProto, helper  # type: ignore

    expected = ""
    if case_id in {"onnx_pos_01", "onnx_pos_03"}:
        relu = case_id == "onnx_pos_03"
        nodes, init = _dense_nodes(relu=relu)
        _save_model(path, nodes, [_tensor("input", [1, 4])], [_tensor("output" if relu else "dense_out", [1, 3])], init)
        expected = "Gemm -> Dense"
    elif case_id == "onnx_pos_02":
        nodes, init = _dense_nodes(matmul_add=True)
        _save_model(path, nodes, [_tensor("input", [1, 4])], [_tensor("dense_out", [1, 3])], init)
        expected = "Add static bias"
    elif case_id in {"onnx_pos_04", "onnx_pos_05", "onnx_pos_06", "onnx_pos_07", "onnx_pos_08", "onnx_pos_09"}:
        nodes, init = _conv_prefix()
        output_name = "conv_out"
        output_shape = [1, 2, 4, 4]
        if case_id == "onnx_pos_04":
            nodes.append(helper.make_node("Relu", ["conv_out"], ["output"], name="relu"))
            output_name = "output"
            expected = "NCHW Conv"
        elif case_id == "onnx_pos_05":
            init.extend(
                [
                    _array("scale", [1, 1]), _array("bn_bias", [0, 0]),
                    _array("mean", [0, 0]), _array("variance", [1, 1]),
                ]
            )
            nodes.append(helper.make_node("BatchNormalization", ["conv_out", "scale", "bn_bias", "mean", "variance"], ["output"], name="bn"))
            output_name = "output"
            expected = "BatchNormalization"
        elif case_id in {"onnx_pos_06", "onnx_pos_07"}:
            op = "MaxPool" if case_id == "onnx_pos_06" else "AveragePool"
            nodes.append(helper.make_node(op, ["conv_out"], ["output"], name="pool", kernel_shape=[2, 2], strides=[2, 2]))
            output_name, output_shape, expected = "output", [1, 2, 2, 2], op
        elif case_id == "onnx_pos_08":
            nodes.append(helper.make_node("GlobalAveragePool", ["conv_out"], ["output"], name="gap"))
            output_name, output_shape, expected = "output", [1, 2, 1, 1], "GlobalAveragePool"
        elif case_id == "onnx_pos_09":
            init.append(_array("axes", [2, 3], np.int64))
            nodes.append(helper.make_node("ReduceMean", ["conv_out", "axes"], ["output"], name="reduce", keepdims=1))
            output_name, output_shape, expected = "output", [1, 2, 1, 1], "ReduceMean spatial axes"
        _save_model(path, nodes, [_tensor("input", [1, 1, 6, 6])], [_tensor(output_name, output_shape)], init, opset=18 if case_id == "onnx_pos_09" else 13)
    elif case_id == "onnx_pos_10":
        node = helper.make_node("Flatten", ["input"], ["output"], name="flatten", axis=1)
        _save_model(path, [node], [_tensor("input", [1, 2, 2])], [_tensor("output", [1, 4])])
        expected = "Flatten -> static Reshape"
    elif case_id == "onnx_pos_11":
        node = helper.make_node("Reshape", ["input", "shape"], ["output"], name="reshape")
        _save_model(path, [node], [_tensor("input", [1, 2, 2])], [_tensor("output", [1, 4])], [_array("shape", [1, 4], np.int64)])
        expected = "Reshape -> static Reshape"
    elif case_id == "onnx_pos_12":
        nodes = [
            helper.make_node("QuantizeLinear", ["input", "scale", "zero"], ["quantized"], name="quantize"),
            helper.make_node("DequantizeLinear", ["quantized", "scale", "zero"], ["dequantized"], name="dequantize"),
            helper.make_node("Gemm", ["dequantized", "weight", "bias"], ["output"], name="gemm", transB=1),
        ]
        init = [
            _array("scale", [0.125]), _array("zero", [0], np.uint8),
            _array("weight", np.ones((3, 4))), _array("bias", np.zeros(3)),
        ]
        _save_model(path, nodes, [_tensor("input", [1, 4])], [_tensor("output", [1, 3])], init)
        expected = "QuantizeLinear"
    elif case_id == "onnx_pos_13":
        nodes = [
            helper.make_node("Shape", ["input"], ["input_shape"], name="shape"),
            helper.make_node("Gather", ["input_shape", "index"], ["batch"], name="gather", axis=0),
            helper.make_node("Constant", [], ["flat_dim"], name="flat_dim", value=_array("flat_value", [4], np.int64)),
            helper.make_node("Concat", ["batch", "flat_dim"], ["target"], name="concat", axis=0),
            helper.make_node("Reshape", ["input", "target"], ["output"], name="reshape"),
        ]
        _save_model(path, nodes, [_tensor("input", [1, 2, 2])], [_tensor("output", [1, 4])], [_array("index", [0], np.int64)])
        expected = "Gather -> static shape helper eliminated"
    elif case_id == "onnx_pos_14":
        nodes = [
            helper.make_node("Transpose", ["input"], ["nhwc"], name="to_nhwc", perm=[0, 2, 3, 1]),
            helper.make_node("Transpose", ["nhwc"], ["nchw"], name="to_nchw", perm=[0, 3, 1, 2]),
            helper.make_node("Conv", ["nchw", "conv_w"], ["output"], name="conv", kernel_shape=[3, 3]),
        ]
        _save_model(path, nodes, [_tensor("input", [1, 1, 6, 6])], [_tensor("output", [1, 2, 4, 4])], [_array("conv_w", np.ones((2, 1, 3, 3)))])
        expected = "Transpose -> layout metadata only"
    else:  # pragma: no cover - suite manifest controls the identifiers.
        raise KeyError(case_id)
    return expected


def _build_negative(case_id: str, path: Path) -> str:
    import numpy as np  # type: ignore
    from onnx import helper  # type: ignore

    expected = ""
    if case_id == "onnx_neg_01":
        nodes = [
            helper.make_node("MatMul", ["input", "w1"], ["a"], name="branch_a"),
            helper.make_node("MatMul", ["input", "w2"], ["b"], name="branch_b"),
            helper.make_node("Add", ["a", "b"], ["output"], name="residual"),
        ]
        _save_model(path, nodes, [_tensor("input", [1, 4])], [_tensor("output", [1, 3])], [_array("w1", np.ones((4, 3))), _array("w2", np.ones((4, 3)))])
        expected = "Branched/residual"
    elif case_id in {"onnx_neg_02", "onnx_neg_03"}:
        nodes, init = _conv_prefix(group=2)
        _save_model(path, nodes, [_tensor("input", [1, 2, 6, 6])], [_tensor("conv_out", [1, 2, 4, 4])], init)
        expected = "group=2"
    elif case_id == "onnx_neg_04":
        nodes = [helper.make_node("Shape", ["input"], ["shape"]), helper.make_node("Reshape", ["input", "shape"], ["output"])]
        _save_model(path, nodes, [_tensor("input", [1, "dynamic", 2])], [_tensor("output", [1, "dynamic", 2])])
        expected = "dynamic non-batch dimension"
    elif case_id == "onnx_neg_05":
        constant = helper.make_node("Constant", [], ["weight_value"], value=_array("weight_constant", np.ones((4, 3))))
        matmul = helper.make_node("MatMul", ["input", "weight_value"], ["output"])
        _save_model(path, [constant, matmul], [_tensor("input", [1, 4])], [_tensor("output", [1, 3])])
        expected = "static second-input weight initializer"
    elif case_id in {"onnx_neg_06", "onnx_neg_07"}:
        nodes, init = _dense_nodes(trans_a=1 if case_id == "onnx_neg_06" else 0, alpha=2.0 if case_id == "onnx_neg_07" else 1.0)
        _save_model(path, nodes, [_tensor("input", [1, 4])], [_tensor("dense_out", [1, 3])], init)
        expected = "transA" if case_id == "onnx_neg_06" else "non-unit alpha/beta"
    elif case_id == "onnx_neg_08":
        node = helper.make_node("Transpose", ["input"], ["output"], perm=[0, 2, 1])
        _save_model(path, [node], [_tensor("input", [1, 2, 3])], [_tensor("output", [1, 3, 2])])
        expected = "unsupported perm"
    elif case_id == "onnx_neg_09":
        node = helper.make_node("Add", ["lhs", "rhs"], ["output"])
        _save_model(path, [node], [_tensor("lhs", [1, 4]), _tensor("rhs", [1, 4])], [_tensor("output", [1, 4])])
        expected = "expects one model input"
    elif case_id == "onnx_neg_10":
        node = helper.make_node("Shape", ["input"], ["output"])
        _save_model(path, [node], [_tensor("input", [1, None, 4])], [_tensor("output", [3], data_type=7)])
        expected = "dynamic non-batch dimension"
    elif case_id == "onnx_neg_11":
        node = helper.make_node("Loop", ["trip", "condition"], ["output"], name="loop")
        _save_model(path, [node], [_tensor("input", [1, 4])], [_tensor("output", [1, 4])], [_array("trip", 1, np.int64), _array("condition", True, np.bool_)])
        expected = "Unsupported op"
    elif case_id == "onnx_neg_12":
        node = helper.make_node("Relu", ["input"], ["output"], name="custom_relu", domain="com.example")
        _save_model(path, [node], [_tensor("input", [1, 4])], [_tensor("output", [1, 4])])
        expected = "custom-domain nodes"
    else:  # pragma: no cover
        raise KeyError(case_id)
    return expected


def run_operator_onnx_cases(workspace_root: str | Path, output_path: str | Path) -> dict[str, Any]:
    root = Path(workspace_root).resolve()
    manifest_path = root / "benchmarks" / "operator_onnx_graph_suite.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        manifest = all_suite_payloads()["operator_onnx_graph_suite.json"]
    graph_dir = root / "runs" / "operator_onnx_probe" / "graphs"
    graph_dir.mkdir(parents=True, exist_ok=True)
    adapter = HLS4MLAdapter(mock_mode=False)
    results: list[dict[str, Any]] = []

    def execute(case: dict[str, Any], positive: bool, builder: Callable[[str, Path], str]) -> None:
        case_id = str(case["case_id"])
        graph_path = graph_dir / f"{case_id}.onnx"
        expected = builder(case_id, graph_path)
        try:
            import onnx  # type: ignore

            layers, input_layer, output_layer, rewrites = adapter._build_layer_list_from_onnx(onnx.load(str(graph_path)))
            accepted = True
            reason = ""
        except Exception as exc:  # The benchmark records the exact structured boundary reason.
            layers, rewrites, input_layer, output_layer = [], [], None, None
            accepted = False
            reason = str(exc)
        matched = expected.lower() in (" ".join(rewrites) if positive else reason).lower()
        passed = (accepted and matched) if positive else ((not accepted) and matched)
        results.append(
            {
                "case_id": case_id,
                "pattern": case["pattern"],
                "expected": "accepted" if positive else "structured_rejection",
                "passed": passed,
                "accepted": accepted,
                "expected_evidence": expected,
                "reason": reason or None,
                "rewrites": rewrites,
                "layer_classes": [layer.get("class_name") for layer in layers],
                "input_layer": input_layer,
                "output_layer": output_layer,
                "graph_path": str(graph_path.relative_to(root)),
                "evidence_class": "real_onnx_graph_parse",
            }
        )

    for item in manifest["positive_cases"]:
        execute(item, True, _build_positive)
    for item in manifest["negative_cases"]:
        execute(item, False, _build_negative)

    positives = [item for item in results if item["expected"] == "accepted"]
    negatives = [item for item in results if item["expected"] == "structured_rejection"]
    report = {
        "schema_version": "1.0",
        "generated_at": _utc_now(),
        "adapter_role": "static_onnx_contract_extraction_only_not_hls_generation",
        "generation_path": "llm_candidate",
        "case_count": len(results),
        "passed_count": sum(bool(item["passed"]) for item in results),
        "pass_rate": sum(bool(item["passed"]) for item in results) / len(results),
        "positive_acceptance": sum(bool(item["passed"]) for item in positives) / len(positives),
        "negative_rejection": sum(bool(item["passed"]) for item in negatives) / len(negatives),
        "results": results,
    }
    output = Path(output_path)
    if not output.is_absolute():
        output = root / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report
