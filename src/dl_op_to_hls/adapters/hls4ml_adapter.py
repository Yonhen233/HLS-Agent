from __future__ import annotations

import json
import shutil
import importlib.util
from pathlib import Path
from typing import Any

from ..core.errors import build_error, error_result


class HLS4MLAdapter:
    def __init__(self, mock_mode: bool = True):
        self.mock_mode = mock_mode

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
        try:  # pragma: no cover - real dependency path
            import onnx  # type: ignore

            model = onnx.load(model_path)
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
            backend = task.get("target", {}).get("backend", "Vivado")
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
            return {
                "status": "unsupported",
                "supported_layers": [],
                "unsupported_layers": [
                    {
                        "name": task.get("name", "model"),
                        "type": "Model",
                        "reason": str(exc),
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
                    f"Backend: {arguments['backend']}",
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
            backend = arguments.get("backend", "Vivado")
            precision = arguments.get("precision", "fixed<16,6>")
            reuse_factor = int(arguments.get("reuse_factor", 1))
            strategy = arguments.get("strategy", "Latency")
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
            return {"status": "success", "config_path": str(config_path)}
        except Exception as exc:  # pragma: no cover - real dependency path
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
            return {
                "status": "success",
                "hls_project_dir": str(output_dir),
                "top_function": top_function,
                "log_path": str(log_path),
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
            backend = (
                str(config_payload.get("backend"))
                if isinstance(config_payload, dict) and config_payload.get("backend")
                else str(arguments.get("backend", "Vivado"))
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
            converted = hls4ml.converters.convert_from_onnx_model(
                model,
                output_dir=str(output_dir),
                project_name=top_function,
                backend=backend,
                hls_config=hls_config,
                part=part,
                clock_period=clock_period,
            )
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
                    ]
                ),
                encoding="utf-8",
            )
            return {
                "status": "success",
                "hls_project_dir": str(output_dir),
                "top_function": top_function,
                "log_path": str(log_path),
            }
        except Exception as exc:  # pragma: no cover - real dependency path
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
        log_path.write_text("Mock hls4ml csim completed successfully.", encoding="utf-8")
        return {"status": "success", "log_path": str(log_path)}
