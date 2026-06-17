from __future__ import annotations

import json
import shutil
import importlib.util
import contextlib
import io
import os
import re
from pathlib import Path
from typing import Any

from ..core.errors import build_error, error_result
from ..tools.functional_verification import write_onnx_reference_data


class HLS4MLAdapter:
    def __init__(self, mock_mode: bool = True, backend_override: str | None = None):
        self.mock_mode = mock_mode
        self.backend_override = backend_override

    def _installed(self) -> bool:
        return (
            shutil.which("python") is not None
            and importlib.util.find_spec("hls4ml") is not None
            and importlib.util.find_spec("onnx") is not None
        )

    def _is_placeholder_model(self, model_path: str) -> bool:
        path = Path(model_path)
        if not path.exists() or not path.is_file():
            return False
        if path.suffix.lower() != ".onnx":
            return False
        try:
            if path.stat().st_size <= 512:
                preview = path.read_text(encoding="utf-8", errors="ignore").lower()
                if "placeholder" in preview and "onnx" in preview:
                    return True
        except Exception:
            return False
        return False

    def _parse_onnx_config(self, config_path: str | None) -> dict[str, Any]:
        if not config_path:
            return {}
        path = Path(config_path)
        if not path.exists():
            return {}
        raw = path.read_text(encoding="utf-8")
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            pass
        try:
            import yaml  # type: ignore

            parsed = yaml.safe_load(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    def _is_h5_frontend(self, model_path: str, frontend: str | None = None) -> bool:
        return (frontend or "").lower() in {"keras", "qkeras", "h5"} or Path(model_path).suffix.lower() in {".h5", ".hdf5"}

    def _safe_layer_name(self, name: str, fallback: str) -> str:
        value = re.sub(r"[^0-9A-Za-z_]", "_", name or fallback)
        if not value:
            value = fallback
        if value[0].isdigit():
            value = f"n_{value}"
        if value == "input":
            value = "model_input"
        return value

    def _resolve_backend(self, requested_backend: Any = None) -> str:
        backend = self.backend_override or os.environ.get("DL_OP_TO_HLS_HLS4ML_BACKEND") or requested_backend or "Vivado"
        text = str(backend)
        if text.lower() == "vitis":
            return "Vitis"
        if text.lower() == "vivado":
            return "Vivado"
        return text

    def _write_reference_data_for_args(self, model_path: str, output_dir: Path, arguments: dict[str, Any]) -> dict[str, Any]:
        reference_cfg = arguments.get("reference_data") if isinstance(arguments.get("reference_data"), dict) else {}
        return write_onnx_reference_data(
            model_path=model_path,
            project_dir=output_dir,
            num_samples=int(reference_cfg.get("num_samples", arguments.get("reference_num_samples", 2))),
            seed=int(reference_cfg.get("seed", arguments.get("reference_seed", 7))),
            input_data_path=reference_cfg.get("input_path"),
            labels_path=reference_cfg.get("labels_path"),
            classification_min_accuracy=reference_cfg.get("classification_min_accuracy"),
            argmax_match_min=reference_cfg.get("argmax_match_min"),
        )

    def _tensor_shapes(self, model: Any) -> dict[str, list[int]]:
        shapes: dict[str, list[int]] = {}
        for value in [*model.graph.input, *model.graph.value_info, *model.graph.output]:
            dims: list[int] = []
            try:
                for dim in value.type.tensor_type.shape.dim:
                    if dim.HasField("dim_value") and int(dim.dim_value) > 0:
                        dims.append(int(dim.dim_value))
                    else:
                        # hls4ml/Vivado HLS needs static shapes. Batch is fixed to 1 for demo/toolchain conversion.
                        dims.append(1)
            except Exception:
                dims = []
            shapes[value.name] = dims
        return shapes

    def _infer_onnx_shapes(self, model: Any) -> Any:
        try:
            import onnx  # type: ignore

            return onnx.shape_inference.infer_shapes(model)
        except Exception:
            return model

    def _onnx_attrs(self, node: Any) -> dict[str, Any]:
        from onnx import helper  # type: ignore

        return {attr.name: helper.get_attribute_value(attr) for attr in node.attribute}

    def _onnx_layer_list_supported(self, model: Any) -> tuple[bool, list[str], list[str]]:
        ops = [node.op_type for node in model.graph.node]
        supported = {
            "Add",
            "AveragePool",
            "BatchNormalization",
            "Cast",
            "Concat",
            "Constant",
            "ConstantOfShape",
            "Conv",
            "DequantizeLinear",
            "Dropout",
            "Flatten",
            "Gather",
            "Gemm",
            "GlobalAveragePool",
            "Identity",
            "MatMul",
            "MaxPool",
            "QuantizeLinear",
            "Relu",
            "Reshape",
            "Shape",
            "Sigmoid",
            "Slice",
            "Squeeze",
            "Tanh",
            "Transpose",
            "Unsqueeze",
        }
        unsupported = sorted({op for op in ops if op not in supported})
        helper_ops = {
            "Cast",
            "Concat",
            "Constant",
            "ConstantOfShape",
            "Gather",
            "Shape",
            "Slice",
            "Squeeze",
            "Unsqueeze",
        }
        dataflow_ops = {op for op in ops if op not in helper_ops}
        return not unsupported and bool(dataflow_ops), sorted(set(ops)), unsupported

    def _build_layer_list_from_onnx(self, model: Any) -> tuple[list[dict[str, Any]], str, str, list[str]]:
        """Build a small hls4ml layer list for static Torch/ONNX/QONNX demo graphs.

        This is an engineering adapter, not a full ONNX compiler. It supports static
        PyTorch/QONNX-exported MLP/CNN graphs and a few safe rewrites/folds. Branching
        dataflow such as residual Add is rejected with a structured unsupported reason.
        It keeps the hls4ml backend and ModelGraph generation, but avoids hls4ml 1.3.0 ONNX
        parser edge cases around Gemm constants and channels-first Conv nodes.
        """
        from onnx import numpy_helper  # type: ignore
        import numpy as np  # type: ignore

        model = self._infer_onnx_shapes(model)
        initializers = {item.name: numpy_helper.to_array(item) for item in model.graph.initializer}
        shapes = self._tensor_shapes(model)
        graph_inputs = [item.name for item in model.graph.input if item.name not in initializers]
        if len(graph_inputs) != 1:
            raise ValueError(f"Layer-list ONNX adapter expects one model input, found {len(graph_inputs)}.")
        input_name = graph_inputs[0]
        input_shape = shapes.get(input_name)
        if not input_shape or len(input_shape) < 2:
            raise ValueError(f"Input shape for {input_name} is missing or not static.")

        def nhwc(shape: list[int]) -> list[int]:
            return [shape[0], shape[2], shape[3], shape[1]] if len(shape) == 4 else shape

        layer_input_name = "model_input"
        if len(input_shape) == 4:
            layer_input_shape = nhwc(input_shape)[1:]
        else:
            layer_input_shape = input_shape[1:]
        layer_list: list[dict[str, Any]] = [
            {"name": layer_input_name, "class_name": "InputLayer", "input_shape": layer_input_shape}
        ]
        prev = layer_input_name
        rewrites: list[str] = []
        data_owner: dict[str, str] = {input_name: layer_input_name}
        helper_outputs: set[str] = set()
        static_helper_ops = {
            "Shape",
            "Concat",
            "Constant",
            "ConstantOfShape",
            "Gather",
            "Unsqueeze",
            "Squeeze",
            "Slice",
        }

        def _owner_for_data_input(node: Any, index: int = 0) -> str:
            if len(node.input) <= index:
                raise ValueError(f"{node.op_type} node {node.name or node.output[0]} is missing a data input.")
            tensor_name = node.input[index]
            owner = data_owner.get(tensor_name)
            if owner is None:
                raise ValueError(
                    f"{node.op_type} node {node.name or node.output[0]} consumes {tensor_name}, "
                    "which is not on the static sequential data path."
                )
            if owner != prev:
                raise ValueError(
                    f"{node.op_type} node {node.name or node.output[0]} consumes {tensor_name} from {owner}, "
                    f"but the current sequential tail is {prev}. Branched/residual graphs need a real graph compiler."
                )
            return owner

        def _mark_outputs_as_data(node: Any, owner: str) -> None:
            for output in node.output:
                data_owner[output] = owner

        def _mark_outputs_as_helper(node: Any) -> None:
            for output in node.output:
                helper_outputs.add(output)

        def _last_trainable_layer() -> dict[str, Any]:
            for layer in reversed(layer_list):
                if layer.get("class_name") in {"Dense", "Conv2D"}:
                    return layer
            raise ValueError("No Dense/Conv2D layer is available for folding.")

        def _as_channel_vector(array: Any, channels: int, node_label: str) -> Any:
            values = np.asarray(array, dtype=np.float32).reshape(-1)
            if values.size != channels:
                raise ValueError(f"{node_label} expected {channels} channel values, got {values.size}.")
            return values

        def _fold_bias_add(node: Any, data_input: str, bias_input: str) -> None:
            _owner_for_data_input(node, list(node.input).index(data_input))
            layer = _last_trainable_layer()
            if layer.get("name") != prev:
                raise ValueError(
                    f"Add node {node.name or node.output[0]} cannot be safely folded because the current tail is {prev}, "
                    f"not the trainable layer {layer.get('name')}."
                )
            channels = int(layer.get("n_out") or layer.get("n_filt") or 0)
            if channels <= 0:
                raise ValueError(f"Add node {node.name or node.output[0]} cannot infer channel count for bias folding.")
            bias = _as_channel_vector(initializers[bias_input], channels, f"Add node {node.name or node.output[0]}")
            old_bias = layer.get("bias_data")
            if old_bias is None:
                layer["bias_data"] = bias
            else:
                layer["bias_data"] = _as_channel_vector(old_bias, channels, "Existing bias") + bias
            layer["use_bias"] = True
            rewrites.append("Add static bias -> folded into previous Dense/Conv2D")
            _mark_outputs_as_data(node, prev)

        def _fold_batchnorm(node: Any) -> None:
            _owner_for_data_input(node)
            if len(node.input) < 5:
                raise ValueError(f"BatchNormalization node {node.name or node.output[0]} is missing static parameters.")
            missing = [name for name in node.input[1:5] if name not in initializers]
            if missing:
                raise ValueError(f"BatchNormalization node {node.name or node.output[0]} has non-static parameters: {missing}.")
            layer = _last_trainable_layer()
            if layer.get("name") != prev:
                raise ValueError(
                    f"BatchNormalization node {node.name or node.output[0]} cannot be safely folded because the current tail is {prev}, "
                    f"not the trainable layer {layer.get('name')}."
                )
            channels = int(layer.get("n_out") or layer.get("n_filt") or 0)
            scale = _as_channel_vector(initializers[node.input[1]], channels, "BatchNormalization scale")
            beta = _as_channel_vector(initializers[node.input[2]], channels, "BatchNormalization bias")
            mean = _as_channel_vector(initializers[node.input[3]], channels, "BatchNormalization mean")
            variance = _as_channel_vector(initializers[node.input[4]], channels, "BatchNormalization variance")
            epsilon = float(self._onnx_attrs(node).get("epsilon", 1e-5))
            factor = scale / np.sqrt(variance + epsilon)
            old_bias = layer.get("bias_data")
            if old_bias is None:
                old_bias_vec = np.zeros(channels, dtype=np.float32)
            else:
                old_bias_vec = _as_channel_vector(old_bias, channels, "Existing bias")
            if layer.get("class_name") == "Dense":
                layer["weight_data"] = np.asarray(layer["weight_data"], dtype=np.float32) * factor.reshape(1, -1)
            elif layer.get("class_name") == "Conv2D":
                layer["weight_data"] = np.asarray(layer["weight_data"], dtype=np.float32) * factor.reshape(1, 1, 1, -1)
            layer["bias_data"] = (old_bias_vec - mean) * factor + beta
            layer["use_bias"] = True
            rewrites.append("BatchNormalization -> folded into previous Dense/Conv2D")
            _mark_outputs_as_data(node, prev)

        def _add_activation(node: Any, activation: str, name: str) -> None:
            nonlocal prev
            _owner_for_data_input(node)
            layer_list.append({"name": name, "class_name": "Activation", "activation": activation, "inputs": [prev]})
            prev = name
            _mark_outputs_as_data(node, prev)

        for index, node in enumerate(model.graph.node):
            raw_name = node.name or (node.output[0] if node.output else node.op_type)
            name = self._safe_layer_name(raw_name, f"{node.op_type}_{index}")
            if node.op_type in static_helper_ops:
                _mark_outputs_as_helper(node)
                rewrites.append(f"{node.op_type} -> static shape helper eliminated")
                continue
            if node.op_type in {"Identity", "Dropout", "QuantizeLinear", "DequantizeLinear"}:
                owner = _owner_for_data_input(node)
                _mark_outputs_as_data(node, owner)
                rewrites.append(f"{node.op_type} -> data no-op/precision metadata")
                continue
            if node.op_type == "Cast":
                if node.input and node.input[0] in helper_outputs:
                    _mark_outputs_as_helper(node)
                    rewrites.append("Cast -> static shape helper eliminated")
                    continue
                owner = _owner_for_data_input(node)
                _mark_outputs_as_data(node, owner)
                rewrites.append("Cast -> data no-op for static numeric adapter")
                continue
            if node.op_type == "Transpose":
                owner = _owner_for_data_input(node)
                perm = list(self._onnx_attrs(node).get("perm") or [])
                rank = len(shapes.get(node.input[0], []))
                if not perm or perm == list(range(rank)):
                    _mark_outputs_as_data(node, owner)
                    rewrites.append("Transpose -> identity eliminated")
                    continue
                if rank == 4 and perm in ([0, 2, 3, 1], [0, 3, 1, 2]):
                    _mark_outputs_as_data(node, owner)
                    rewrites.append("Transpose -> layout metadata only")
                    continue
                raise ValueError(f"Transpose node {node.name or index} uses unsupported perm={perm}.")
            if node.op_type == "Gemm":
                _owner_for_data_input(node)
                if len(node.input) < 2 or node.input[1] not in initializers:
                    raise ValueError(f"Gemm node {node.name or index} has no static weight initializer.")
                attrs = self._onnx_attrs(node)
                weights = initializers[node.input[1]]
                bias = initializers[node.input[2]] if len(node.input) > 2 and node.input[2] in initializers else None
                if int(attrs.get("transA", 0)) != 0:
                    raise ValueError(f"Gemm node {node.name or index} uses transA; this demo adapter only supports transA=0.")
                if float(attrs.get("alpha", 1.0)) != 1.0 or float(attrs.get("beta", 1.0)) != 1.0:
                    raise ValueError(f"Gemm node {node.name or index} uses non-unit alpha/beta.")
                if int(attrs.get("transB", 0)):
                    weights = weights.T
                layer_list.append(
                    {
                        "name": name,
                        "class_name": "Dense",
                        "inputs": [prev],
                        "weight_data": weights,
                        "bias_data": bias,
                        "n_in": int(weights.shape[0]),
                        "n_out": int(weights.shape[1]),
                        "use_bias": bias is not None,
                    }
                )
                prev = name
                _mark_outputs_as_data(node, prev)
                rewrites.append("Gemm -> Dense layer-list")
                continue
            if node.op_type == "MatMul":
                _owner_for_data_input(node)
                if len(node.input) < 2 or node.input[1] not in initializers:
                    raise ValueError(f"MatMul node {node.name or index} needs a static second-input weight initializer.")
                weights = initializers[node.input[1]]
                if weights.ndim != 2:
                    raise ValueError(f"MatMul node {node.name or index} expects a rank-2 weight matrix.")
                layer_list.append(
                    {
                        "name": name,
                        "class_name": "Dense",
                        "inputs": [prev],
                        "weight_data": weights,
                        "bias_data": None,
                        "n_in": int(weights.shape[0]),
                        "n_out": int(weights.shape[1]),
                        "use_bias": False,
                    }
                )
                prev = name
                _mark_outputs_as_data(node, prev)
                rewrites.append("MatMul static weight -> Dense layer-list")
                continue
            if node.op_type == "Add":
                initializer_inputs = [item for item in node.input if item in initializers]
                data_inputs = [item for item in node.input if item not in initializers]
                if len(initializer_inputs) == 1 and len(data_inputs) == 1:
                    _fold_bias_add(node, data_inputs[0], initializer_inputs[0])
                    continue
                raise ValueError(
                    f"Add node {node.name or index} is not a static bias add. "
                    "Residual/elementwise Add requires graph-level support and is intentionally unsupported here."
                )
            if node.op_type == "BatchNormalization":
                _fold_batchnorm(node)
                continue
            if node.op_type == "Relu":
                _add_activation(node, "ReLU", name)
                continue
            if node.op_type == "Sigmoid":
                _add_activation(node, "sigmoid", name)
                continue
            if node.op_type == "Tanh":
                _add_activation(node, "tanh", name)
                continue
            if node.op_type == "Flatten":
                _owner_for_data_input(node)
                output_shape = shapes.get(node.output[0], [])
                target_shape = output_shape[1:] if len(output_shape) > 1 else [-1]
                layer_list.append({"name": name, "class_name": "Reshape", "inputs": [prev], "target_shape": target_shape})
                prev = name
                _mark_outputs_as_data(node, prev)
                rewrites.append("Flatten -> static Reshape")
                continue
            if node.op_type == "Reshape":
                _owner_for_data_input(node)
                output_shape = shapes.get(node.output[0], [])
                if not output_shape:
                    raise ValueError(f"Reshape node {node.name or index} has no static output shape.")
                layer_list.append({"name": name, "class_name": "Reshape", "inputs": [prev], "target_shape": output_shape[1:]})
                prev = name
                _mark_outputs_as_data(node, prev)
                rewrites.append("Reshape -> static Reshape")
                continue
            if node.op_type == "Conv":
                _owner_for_data_input(node)
                if len(node.input) < 2 or node.input[1] not in initializers:
                    raise ValueError(f"Conv node {node.name or index} has no static weight initializer.")
                attrs = self._onnx_attrs(node)
                groups = int(attrs.get("group", 1))
                if groups != 1:
                    raise ValueError(f"Conv node {node.name or index} uses group={groups}; grouped conv is not supported.")
                weights = initializers[node.input[1]]
                bias = initializers[node.input[2]] if len(node.input) > 2 and node.input[2] in initializers else None
                input_shape_nchw = shapes.get(node.input[0], [])
                output_shape_nchw = shapes.get(node.output[0], [])
                if len(input_shape_nchw) != 4 or len(output_shape_nchw) != 4:
                    raise ValueError(f"Conv node {node.name or index} requires static 4D NCHW shapes.")
                input_shape_nhwc = nhwc(input_shape_nchw)
                output_shape_nhwc = nhwc(output_shape_nchw)
                kernel = list(attrs.get("kernel_shape") or list(weights.shape[2:]))
                pads = list(attrs.get("pads") or [0, 0, 0, 0])
                strides = list(attrs.get("strides") or [1, 1])
                layer_list.append(
                    {
                        "name": name,
                        "inputs": [prev],
                        "class_name": "Conv2D",
                        "data_format": "channels_last",
                        "weight_data": weights.transpose(2, 3, 1, 0),
                        "bias_data": bias,
                        "in_height": int(input_shape_nhwc[1]),
                        "in_width": int(input_shape_nhwc[2]),
                        "n_chan": int(input_shape_nhwc[3]),
                        "n_filt": int(weights.shape[0]),
                        "filt_height": int(kernel[0]),
                        "filt_width": int(kernel[1]),
                        "stride_height": int(strides[0]),
                        "stride_width": int(strides[1]),
                        "dilation": 1,
                        "pad_top": int(pads[0]),
                        "pad_left": int(pads[1]),
                        "pad_bottom": int(pads[2]),
                        "pad_right": int(pads[3]),
                        "out_height": int(output_shape_nhwc[1]),
                        "out_width": int(output_shape_nhwc[2]),
                    }
                )
                prev = name
                _mark_outputs_as_data(node, prev)
                rewrites.append("NCHW Conv -> channels_last Conv2D layer-list")
                continue
            if node.op_type in {"MaxPool", "AveragePool", "GlobalAveragePool"}:
                _owner_for_data_input(node)
                attrs = self._onnx_attrs(node)
                input_shape_nchw = shapes.get(node.input[0], [])
                output_shape_nchw = shapes.get(node.output[0], [])
                if len(input_shape_nchw) != 4 or len(output_shape_nchw) != 4:
                    raise ValueError(f"{node.op_type} node {node.name or index} requires static 4D NCHW shapes.")
                input_shape_nhwc = nhwc(input_shape_nchw)
                output_shape_nhwc = nhwc(output_shape_nchw)
                if node.op_type == "GlobalAveragePool":
                    kernel = [int(input_shape_nhwc[1]), int(input_shape_nhwc[2])]
                    strides = kernel
                    class_name = "AveragePooling2D"
                else:
                    kernel = list(attrs.get("kernel_shape") or [2, 2])
                    strides = list(attrs.get("strides") or kernel)
                    class_name = "MaxPooling2D" if node.op_type == "MaxPool" else "AveragePooling2D"
                pads = list(attrs.get("pads") or [0, 0, 0, 0])
                layer_list.append(
                    {
                        "name": name,
                        "class_name": class_name,
                        "inputs": [prev],
                        "data_format": "channels_last",
                        "n_filt": int(input_shape_nhwc[3]),
                        "in_height": int(input_shape_nhwc[1]),
                        "in_width": int(input_shape_nhwc[2]),
                        "stride_height": int(strides[0]),
                        "stride_width": int(strides[1]),
                        "pool_height": int(kernel[0]),
                        "pool_width": int(kernel[1]),
                        "padding": "valid" if all(int(item) == 0 for item in pads) else "same",
                        "out_height": int(output_shape_nhwc[1]),
                        "out_width": int(output_shape_nhwc[2]),
                        "pad_top": int(pads[0]),
                        "pad_left": int(pads[1]),
                        "pad_bottom": int(pads[2]),
                        "pad_right": int(pads[3]),
                    }
                )
                prev = name
                _mark_outputs_as_data(node, prev)
                rewrites.append(f"NCHW {node.op_type} -> channels_last {class_name} layer-list")
                continue
            raise ValueError(f"Unsupported op for layer-list ONNX adapter: {node.op_type}")

        return layer_list, layer_input_name, prev, sorted(set(rewrites))

    def _write_layer_list_hls_project(
        self,
        *,
        model: Any,
        output_dir: Path,
        project_name: str,
        backend: str,
        hls_config: dict[str, Any],
        part: str,
        clock_period: Any,
    ) -> dict[str, Any]:
        import hls4ml  # type: ignore
        from hls4ml.converters import _check_hls_config, _check_model_config, create_config  # type: ignore
        from hls4ml.model.graph import ModelGraph  # type: ignore

        layer_list, input_layer, output_layer, rewrites = self._build_layer_list_from_onnx(model)
        hls_config = dict(hls_config or {})
        requested_model = dict(hls_config.get("Model", {}))
        requested_reuse = int(requested_model.get("ReuseFactor", 1) or 1)
        layer_name_config = dict(hls_config.get("LayerName", {}))
        for layer in layer_list:
            if layer.get("class_name") != "Conv2D":
                continue
            max_resource_reuse = int(layer["filt_height"]) * int(layer["filt_width"]) * int(layer["n_chan"])
            if requested_reuse > max_resource_reuse:
                layer_config = dict(layer_name_config.get(layer["name"], {}))
                layer_config["ReuseFactor"] = max(1, max_resource_reuse)
                layer_name_config[layer["name"]] = layer_config
                rewrites.append(
                    f"Conv2D {layer['name']} ReuseFactor capped to {max_resource_reuse} for Vivado HLS resource CSim"
                )
        if layer_name_config:
            hls_config["LayerName"] = layer_name_config
        config = create_config(
            output_dir=str(output_dir),
            project_name=project_name,
            backend=backend,
            part=part,
            clock_period=clock_period,
        )
        config["HLSConfig"] = {}
        config["HLSConfig"]["Model"] = _check_model_config(hls_config.get("Model", {}))
        _check_hls_config(config, hls_config)
        model_graph = ModelGraph.from_layer_list(config, layer_list, inputs=[input_layer], outputs=[output_layer])
        model_graph.write()
        return {"rewrites": rewrites, "layer_count": len(layer_list), "backend": backend}

    def _h5_frontend_result(self, task_or_path: dict[str, Any] | str, source: str) -> dict[str, Any]:
        if isinstance(task_or_path, dict):
            model_path = str(task_or_path.get("model_path", ""))
            name = task_or_path.get("name", "model")
        else:
            model_path = str(task_or_path)
            name = Path(model_path).stem or "model"
        if not Path(model_path).exists():
            reason = f"QKeras/Keras H5 model file does not exist: {model_path}"
        else:
            reason = "QKeras/Keras H5 frontend is recognized, but this prototype has not enabled the real H5 conversion branch yet."
        return {
            "status": "unsupported",
            "supported_layers": [],
            "unsupported_layers": [{"name": name, "type": "QKerasH5", "reason": reason}],
            "recommendation": "Export the model through a supported hls4ml Keras/QKeras flow or add a dedicated H5 frontend adapter.",
            "source": source,
        }

    def inspect_model(self, model_path: str, frontend: str) -> dict[str, Any]:
        if self.mock_mode or not self._installed():
            warnings = []
            if not Path(model_path).exists():
                warnings.append("Model file not found; returned mock layer structure for demo flow.")
            return {
                "status": "success",
                "frontend": frontend,
                "layers": [
                    {"name": "dense_1", "type": "Dense", "input_shape": [16], "output_shape": [32]},
                    {"name": "relu_1", "type": "Activation", "input_shape": [32], "output_shape": [32]},
                    {"name": "dense_2", "type": "Dense", "input_shape": [32], "output_shape": [8]},
                ],
                "warnings": warnings,
            }
        if self._is_h5_frontend(model_path, frontend):
            result = self._h5_frontend_result(model_path, "hls4ml.inspect_model")
            return {
                "status": "success" if Path(model_path).exists() else "error",
                "frontend": frontend,
                "layers": [{"name": Path(model_path).stem or "h5_model", "type": "QKerasH5", "input_shape": [], "output_shape": []}],
                "warnings": [result["unsupported_layers"][0]["reason"]],
            }
        try:  # pragma: no cover - real dependency path
            import onnx  # type: ignore

            model = self._infer_onnx_shapes(onnx.load(model_path))
            tensor_shapes: dict[str, list[int | str]] = {}
            for value in [*model.graph.input, *model.graph.value_info, *model.graph.output]:
                dims: list[int | str] = []
                try:
                    for dim in value.type.tensor_type.shape.dim:
                        if dim.HasField("dim_value"):
                            dims.append(int(dim.dim_value))
                        elif dim.HasField("dim_param"):
                            dims.append(dim.dim_param)
                        else:
                            dims.append("?")
                except Exception:
                    dims = []
                tensor_shapes[value.name] = dims
            layers = []
            for node in model.graph.node:
                input_shape: list[int | str] = []
                output_shape: list[int | str] = []
                if node.input:
                    input_shape = tensor_shapes.get(node.input[0], [])
                if node.output:
                    output_shape = tensor_shapes.get(node.output[0], [])
                layers.append(
                    {
                        "name": node.name or node.op_type.lower(),
                        "type": node.op_type,
                        "input_shape": input_shape,
                        "output_shape": output_shape,
                    }
                )
            return {"status": "success", "frontend": frontend, "layers": layers, "warnings": []}
        except Exception as exc:  # pragma: no cover - best effort real path
            return error_result(
                build_error(
                    "HLS4MLConversionError",
                    str(exc),
                    recoverable=True,
                    source="hls4ml.inspect_model",
                )
            )

    def check_support(self, task: dict[str, Any]) -> dict[str, Any]:
        name = str(task.get("name", "")).lower()
        model_path = str(task.get("model_path", "")).lower()
        if task.get("task_type") == "operator":
            return {
                "status": "unsupported",
                "supported_layers": [],
                "unsupported_layers": [
                    {
                        "name": task.get("name", "operator"),
                        "type": task.get("op_type", "Operator"),
                        "reason": "Operator JSON is better handled through fallback templates in P0.",
                    }
                ],
                "recommendation": "Try fallback template or LLM candidate generation.",
            }
        if "tiny_residual_block" in name or "tiny_residual_block" in model_path:
            return {
                "status": "partially_supported",
                "supported_layers": ["Conv2D", "ReLU", "Add"],
                "unsupported_layers": [
                    {
                        "name": "bn_fold_needed",
                        "type": "BatchNorm",
                        "reason": "Can be folded during inference, but graph rewrite is required.",
                    },
                    {
                        "name": "residual_add_layout_sensitive",
                        "type": "ResidualAdd",
                        "reason": "Skip connection support depends on frontend graph and layout.",
                    },
                ],
                "recommendation": "Try graph rewrite and keep the residual block tiny. Consider boundary report if layout conversion is unstable.",
            }
        if "resnet18_boundary" in name or "resnet18" in model_path:
            return {
                "status": "not_recommended",
                "supported_layers": ["Conv2D", "ReLU", "Add"],
                "unsupported_layers": [
                    {
                        "name": "resnet18_full_model",
                        "type": "ModelScale",
                        "reason": "Full ResNet-18 is outside MVP scope due to resource demand and synthesis time.",
                    }
                ],
                "recommendation": "Use tiny residual block or MNIST tiny CNN demo instead.",
            }
        if self.mock_mode:
            if "unsupported" in model_path:
                return {
                    "status": "unsupported",
                    "supported_layers": ["Dense"],
                    "unsupported_layers": [{"name": "custom_op", "type": "CustomOp", "reason": "No hls4ml converter found."}],
                    "recommendation": "Try fallback template or LLM candidate generation.",
                }
            return {
                "status": "supported",
                "supported_layers": ["Dense", "Activation"],
                "unsupported_layers": [],
                "recommendation": "Use hls4ml path.",
            }
        if task.get("task_type") != "model":
            return {
                "status": "unsupported",
                "supported_layers": [],
                "unsupported_layers": [
                    {
                        "name": task.get("name", "operator"),
                        "type": task.get("op_type", "Operator"),
                        "reason": "Only model tasks are checked with real hls4ml support probing.",
                    }
                ],
                "recommendation": "Use fallback template or existing HLS path for this task type.",
            }
        if not self._installed():
            return {
                "status": "unsupported",
                "supported_layers": [],
                "unsupported_layers": [
                    {
                        "name": task.get("name", "model"),
                        "type": "Model",
                        "reason": "hls4ml or onnx Python package is not available in the current environment.",
                    }
                ],
                "recommendation": "Install hls4ml and onnx, or use fallback template path.",
            }
        original_model_path = str(task.get("model_path", ""))
        if self._is_h5_frontend(original_model_path, task.get("frontend")):
            return self._h5_frontend_result(task, "hls4ml.check_support")
        path = Path(original_model_path)
        if not path.exists():
            return {
                "status": "unsupported",
                "supported_layers": [],
                "unsupported_layers": [
                    {
                        "name": task.get("name", "model"),
                        "type": "ModelPath",
                        "reason": f"Model file does not exist: {original_model_path}",
                    }
                ],
                "recommendation": "Provide a valid ONNX model path.",
            }
        if self._is_placeholder_model(original_model_path):
            return {
                "status": "unsupported",
                "supported_layers": [],
                "unsupported_layers": [
                    {
                        "name": task.get("name", "model"),
                        "type": "ModelFile",
                        "reason": "The ONNX file looks like a placeholder text file, not a valid protobuf model.",
                    }
                ],
                "recommendation": "Replace the placeholder with a real ONNX export.",
            }
        try:  # pragma: no cover - real dependency path
            import hls4ml  # type: ignore
            import onnx  # type: ignore

            model = onnx.load(str(path))
            ops = sorted({node.op_type for node in model.graph.node})
            hls4ml_cfg = task.get("hls4ml", {})
            default_precision = hls4ml_cfg.get("precision", "fixed<16,6>")
            default_reuse_factor = int(hls4ml_cfg.get("reuse_factor", 1))
            backend = self._resolve_backend(task.get("target", {}).get("backend", "Vivado"))
            with contextlib.redirect_stdout(io.StringIO()):
                hls4ml.utils.config_from_onnx_model(
                    model,
                    granularity="name",
                    backend=backend,
                    default_precision=default_precision,
                    default_reuse_factor=default_reuse_factor,
                )
            return {
                "status": "supported",
                "supported_layers": ops,
                "unsupported_layers": [],
                "recommendation": "Use hls4ml path.",
            }
        except Exception as exc:  # pragma: no cover - real dependency path
            try:
                import onnx  # type: ignore

                model = onnx.load(str(path))
                supported, ops, unsupported = self._onnx_layer_list_supported(model)
                if supported:
                    # Validate that the narrow parser can actually build a static layer-list.
                    _, _, _, rewrites = self._build_layer_list_from_onnx(model)
                    return {
                        "status": "supported",
                        "supported_layers": ops,
                        "unsupported_layers": [],
                        "recommendation": "Use hls4ml path through the ONNX/QONNX layer-list adapter.",
                        "source": "hls4ml.check_support",
                        "frontend_adapter": "onnx_layer_list",
                        "rewrites": rewrites,
                        "default_parser_error": str(exc),
                    }
                if unsupported:
                    reason = f"Unsupported ops for ONNX/QONNX layer-list adapter: {unsupported}"
                else:
                    reason = str(exc)
            except Exception as layer_exc:
                reason = f"{exc}; ONNX/QONNX layer-list adapter also failed: {layer_exc}"
            return {
                "status": "unsupported",
                "supported_layers": [],
                "unsupported_layers": [
                    {
                        "name": task.get("name", "model"),
                        "type": "Model",
                        "reason": reason,
                    }
                ],
                "recommendation": "Try graph rewrite (e.g., Gemm->MatMul+Add) or fallback template path.",
            }

    def generate_config(self, arguments: dict[str, Any]) -> dict[str, Any]:
        output_dir = Path(arguments["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        config_path = output_dir / "hls4ml_config.yml"
        if self.mock_mode:
            config_text = "\n".join(
                [
                    f"Model: {arguments['model_path']}",
                    f"Frontend: {arguments['frontend']}",
                    f"Backend: {self._resolve_backend(arguments['backend'])}",
                    f"Part: {arguments['part']}",
                    f"ClockPeriod: {arguments['clock_period']}",
                    f"Precision: {arguments['precision']}",
                    f"ReuseFactor: {arguments['reuse_factor']}",
                    f"Strategy: {arguments['strategy']}",
                ]
            )
            config_path.write_text(config_text, encoding="utf-8")
            return {"status": "success", "config_path": str(config_path)}
        if not self._installed():
            return error_result(
                build_error(
                    "HLS4MLNotInstalledError",
                    "hls4ml is not installed.",
                    recoverable=True,
                    source="hls4ml.generate_config",
                    suggested_action="Install hls4ml and onnx, or run fallback template path.",
                )
            )
        model_path = str(arguments.get("model_path", ""))
        if self._is_h5_frontend(model_path, arguments.get("frontend")):
            return error_result(
                build_error(
                    "HLS4MLConversionError",
                    "QKeras/Keras H5 frontend is recognized, but real H5 config generation is not enabled in this prototype.",
                    recoverable=True,
                    source="hls4ml.generate_config",
                    suggested_action="Use a supported hls4ml Keras/QKeras frontend adapter or export a supported model format.",
                    details={"model_path": model_path, "frontend": arguments.get("frontend")},
                )
            )
        if self._is_placeholder_model(model_path):
            return error_result(
                build_error(
                    "HLS4MLConversionError",
                    "Model path points to a placeholder ONNX file.",
                    recoverable=True,
                    source="hls4ml.generate_config",
                    suggested_action="Provide a real ONNX model file.",
                    details={"model_path": model_path},
                )
            )
        try:  # pragma: no cover - real dependency path
            import hls4ml  # type: ignore
            import onnx  # type: ignore

            model = onnx.load(model_path)
            backend = self._resolve_backend(arguments.get("backend", "Vivado"))
            precision = arguments.get("precision", "fixed<16,6>")
            reuse_factor = int(arguments.get("reuse_factor", 1))
            strategy = arguments.get("strategy", "Latency")
            stdout_buffer = io.StringIO()
            with contextlib.redirect_stdout(stdout_buffer):
                generated = hls4ml.utils.config_from_onnx_model(
                    model,
                    granularity="name",
                    backend=backend,
                    default_precision=precision,
                    default_reuse_factor=reuse_factor,
                )
            payload: dict[str, Any] = {
                "model_path": model_path,
                "frontend": arguments.get("frontend", "onnx"),
                "backend": backend,
                "part": arguments.get("part", "xc7z020clg400-1"),
                "clock_period": arguments.get("clock_period", 5),
                "project_name": arguments.get("project_name", "myproject"),
                "hls_config": generated,
            }
            payload.setdefault("hls_config", {})
            if isinstance(payload["hls_config"], dict):
                payload["hls_config"].setdefault("Model", {})
                payload["hls_config"]["Model"]["Precision"] = precision
                payload["hls_config"]["Model"]["ReuseFactor"] = reuse_factor
                payload["hls_config"]["Model"]["Strategy"] = strategy
            config_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            stdout_text = stdout_buffer.getvalue().strip()
            if stdout_text:
                log_dir = output_dir / "logs"
                log_dir.mkdir(parents=True, exist_ok=True)
                (log_dir / "hls4ml_generate_config_stdout.log").write_text(stdout_text, encoding="utf-8")
            return {"status": "success", "config_path": str(config_path)}
        except Exception as exc:  # pragma: no cover - real dependency path
            try:
                import onnx  # type: ignore

                model = onnx.load(model_path)
                supported, _ops, _unsupported = self._onnx_layer_list_supported(model)
                if supported:
                    _, _, _, rewrites = self._build_layer_list_from_onnx(model)
                    precision = arguments.get("precision", "fixed<16,6>")
                    reuse_factor = int(arguments.get("reuse_factor", 1))
                    strategy = arguments.get("strategy", "Latency")
                    payload = {
                        "model_path": model_path,
                        "frontend": arguments.get("frontend", "onnx"),
                        "frontend_adapter": "onnx_layer_list",
                        "backend": self._resolve_backend(arguments.get("backend", "Vivado")),
                        "part": arguments.get("part", "xc7z020clg400-1"),
                        "clock_period": arguments.get("clock_period", 5),
                        "project_name": arguments.get("project_name", "myproject"),
                        "hls_config": {
                            "Model": {
                                "Precision": precision,
                                "ReuseFactor": reuse_factor,
                                "Strategy": strategy,
                            }
                        },
                        "rewrites": rewrites,
                        "default_parser_error": str(exc),
                    }
                    config_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
                    return {"status": "success", "config_path": str(config_path), "frontend_adapter": "onnx_layer_list"}
            except Exception:
                pass
            return error_result(
                build_error(
                    "HLS4MLConversionError",
                    str(exc),
                    recoverable=True,
                    source="hls4ml.generate_config",
                    suggested_action="Inspect ONNX ops and try graph rewrite for unsupported nodes.",
                )
            )

    def convert(self, arguments: dict[str, Any]) -> dict[str, Any]:
        output_dir = Path(arguments["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        if self.mock_mode:
            top_function = "myproject"
            (output_dir / f"{top_function}.cpp").write_text(
                "\n".join(
                    [
                        f"void {top_function}(float input[16], float output[8]) {{",
                        "  for (int i = 0; i < 8; ++i) output[i] = input[i];",
                        "}",
                    ]
                ),
                encoding="utf-8",
            )
            (output_dir / f"{top_function}.h").write_text(
                "\n".join(
                    [
                        f"#ifndef {top_function.upper()}_H",
                        f"#define {top_function.upper()}_H",
                        f"void {top_function}(float input[16], float output[8]);",
                        "#endif",
                    ]
                ),
                encoding="utf-8",
            )
            log_dir = output_dir.parent / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / "hls4ml_convert.log"
            log_path.write_text("Mock hls4ml conversion completed successfully.", encoding="utf-8")
            reference_result = self._write_reference_data_for_args(str(arguments.get("model_path", "")), output_dir, arguments)
            return {
                "status": "success",
                "hls_project_dir": str(output_dir),
                "top_function": top_function,
                "log_path": str(log_path),
                "reference_data": reference_result,
            }
        if not self._installed():
            return error_result(
                build_error(
                    "HLS4MLNotInstalledError",
                    "hls4ml is not installed.",
                    recoverable=True,
                    source="hls4ml.convert",
                    suggested_action="Use fallback template path.",
                )
            )
        model_path = str(arguments.get("model_path", ""))
        if self._is_h5_frontend(model_path, arguments.get("frontend")):
            return error_result(
                build_error(
                    "HLS4MLConversionError",
                    "QKeras/Keras H5 frontend is recognized, but real H5 conversion is not enabled in this prototype.",
                    recoverable=True,
                    source="hls4ml.convert",
                    suggested_action="Use a dedicated Keras/QKeras converter path instead of the ONNX converter.",
                    details={"model_path": model_path, "frontend": arguments.get("frontend")},
                )
            )
        if self._is_placeholder_model(model_path):
            return error_result(
                build_error(
                    "HLS4MLConversionError",
                    "Model path points to a placeholder ONNX file.",
                    recoverable=True,
                    source="hls4ml.convert",
                    suggested_action="Provide a real ONNX model file.",
                    details={"model_path": model_path},
                )
            )
        try:  # pragma: no cover - real dependency path
            import hls4ml  # type: ignore
            import onnx  # type: ignore

            model = onnx.load(model_path)
            config_payload = self._parse_onnx_config(arguments.get("config_path"))
            hls_config = config_payload.get("hls_config") if isinstance(config_payload, dict) else None
            if not isinstance(hls_config, dict):
                hls_config = {
                    "Model": {
                        "Precision": arguments.get("precision", "fixed<16,6>"),
                        "ReuseFactor": int(arguments.get("reuse_factor", 1)),
                        "Strategy": arguments.get("strategy", "Latency"),
                    }
                }
            top_function = str(config_payload.get("project_name") if isinstance(config_payload, dict) else "") or "myproject"
            backend = self._resolve_backend(
                config_payload.get("backend")
                if isinstance(config_payload, dict) and config_payload.get("backend")
                else arguments.get("backend", "Vivado")
            )
            part = (
                config_payload.get("part")
                if isinstance(config_payload, dict) and config_payload.get("part")
                else arguments.get("part", "xc7z020clg400-1")
            )
            clock_period = (
                config_payload.get("clock_period")
                if isinstance(config_payload, dict) and config_payload.get("clock_period") is not None
                else arguments.get("clock_period", 5)
            )
            stdout_buffer = io.StringIO()
            with contextlib.redirect_stdout(stdout_buffer):
                if config_payload.get("frontend_adapter") == "onnx_layer_list":
                    adapter_info = self._write_layer_list_hls_project(
                        model=model,
                        output_dir=output_dir,
                        project_name=top_function,
                        backend=backend,
                        hls_config=hls_config,
                        part=part,
                        clock_period=clock_period,
                    )
                else:
                    converted = hls4ml.converters.convert_from_onnx_model(
                        model,
                        output_dir=str(output_dir),
                        project_name=top_function,
                        backend=backend,
                        hls_config=hls_config,
                        part=part,
                        clock_period=clock_period,
                    )
                    adapter_info = {"frontend_adapter": "hls4ml_onnx_default"}
                    converted.write()
            log_dir = output_dir.parent / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / "hls4ml_convert.log"
            log_path.write_text(
                "\n".join(
                    [
                        "hls4ml real conversion completed successfully.",
                        f"model_path={model_path}",
                        f"project_name={top_function}",
                        f"output_dir={output_dir}",
                        f"backend={backend}",
                        f"frontend_adapter={config_payload.get('frontend_adapter', 'hls4ml_onnx_default')}",
                        f"adapter_info={json.dumps(adapter_info, ensure_ascii=False, default=str)}",
                        "",
                        "Captured stdout:",
                        stdout_buffer.getvalue().strip(),
                    ]
                ),
                encoding="utf-8",
            )
            reference_result = self._write_reference_data_for_args(model_path, output_dir, arguments)
            return {
                "status": "success",
                "hls_project_dir": str(output_dir),
                "top_function": top_function,
                "log_path": str(log_path),
                "reference_data": reference_result,
            }
        except Exception as exc:  # pragma: no cover - real dependency path
            try:
                import onnx  # type: ignore

                model = onnx.load(model_path)
                supported, _ops, _unsupported = self._onnx_layer_list_supported(model)
                if supported:
                    stdout_buffer = io.StringIO()
                    with contextlib.redirect_stdout(stdout_buffer):
                        adapter_info = self._write_layer_list_hls_project(
                            model=model,
                            output_dir=output_dir,
                            project_name=top_function,
                            backend=backend,
                            hls_config=hls_config,
                            part=part,
                            clock_period=clock_period,
                        )
                    log_dir = output_dir.parent / "logs"
                    log_dir.mkdir(parents=True, exist_ok=True)
                    log_path = log_dir / "hls4ml_convert.log"
                    log_path.write_text(
                        "\n".join(
                            [
                                "hls4ml ONNX/QONNX layer-list conversion completed successfully.",
                                f"model_path={model_path}",
                                f"project_name={top_function}",
                                f"default_parser_error={exc}",
                                f"adapter_info={json.dumps(adapter_info, ensure_ascii=False, default=str)}",
                                "",
                                "Captured stdout:",
                                stdout_buffer.getvalue().strip(),
                            ]
                        ),
                        encoding="utf-8",
                    )
                    reference_result = self._write_reference_data_for_args(model_path, output_dir, arguments)
                    return {
                        "status": "success",
                        "hls_project_dir": str(output_dir),
                        "top_function": top_function,
                        "log_path": str(log_path),
                        "frontend_adapter": "onnx_layer_list",
                        "reference_data": reference_result,
                    }
            except Exception as layer_exc:
                exc = RuntimeError(f"{exc}; ONNX/QONNX layer-list adapter failed: {layer_exc}")
            return error_result(
                build_error(
                    "HLS4MLConversionError",
                    str(exc),
                    recoverable=True,
                    source="hls4ml.convert",
                    suggested_action="Try graph rewrite (for example Gemm->MatMul+Add) or fallback template path.",
                )
            )

    def run_csim(self, hls_project_dir: str) -> dict[str, Any]:
        log_dir = Path(hls_project_dir).parent / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "hls4ml_csim.log"
        if self.mock_mode:
            log_path.write_text("Mock hls4ml csim completed successfully.", encoding="utf-8")
            return {"status": "success", "log_path": str(log_path), "mode": "mock"}
        project_dir = Path(hls_project_dir)
        if not project_dir.exists():
            return error_result(
                build_error(
                    "HLS4MLConversionError",
                    "hls4ml project directory does not exist; real csim cannot run.",
                    recoverable=True,
                    source="hls4ml.run_csim",
                    suggested_action="Run hls4ml.convert successfully before requesting csim.",
                    details={"hls_project_dir": hls_project_dir},
                )
            )
        if not self._installed():
            return error_result(
                build_error(
                    "HLS4MLNotInstalledError",
                    "hls4ml and onnx are required for the real hls4ml csim path.",
                    recoverable=True,
                    source="hls4ml.run_csim",
                    suggested_action="Install hls4ml/onnx or use Vivado HLS synthesis on the generated project.",
                )
            )
        build_script = project_dir / "build_prj.tcl"
        if not build_script.exists():
            return error_result(
                build_error(
                    "HLS4MLConversionError",
                    "Real hls4ml csim requires a generated build_prj.tcl; none was found.",
                    recoverable=True,
                    source="hls4ml.run_csim",
                    suggested_action="Use hls4ml.convert to generate a complete project, then run Vivado HLS through vivado.run_csim/run_csynth.",
                    details={"hls_project_dir": hls_project_dir},
                )
            )
        return error_result(
            build_error(
                "HLS4MLConversionError",
                "Direct real hls4ml csim execution is not enabled in this adapter; use VivadoSpecialist for real Tcl execution.",
                recoverable=True,
                source="hls4ml.run_csim",
                suggested_action="Delegate real C simulation/synthesis to VivadoSpecialist with the generated HLS project.",
                details={"build_script": str(build_script), "log_path": str(log_path)},
            )
        )
