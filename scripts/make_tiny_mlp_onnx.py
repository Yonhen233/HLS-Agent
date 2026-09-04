from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper


def build_model(seed: int = 7) -> onnx.ModelProto:
    rng = np.random.default_rng(seed)
    input_info = helper.make_tensor_value_info("model_input", TensorProto.FLOAT, [1, 16])
    output_info = helper.make_tensor_value_info("model_output", TensorProto.FLOAT, [1, 4])
    weights_1 = rng.normal(0.0, 0.2, (8, 16)).astype(np.float32)
    bias_1 = rng.normal(0.0, 0.05, (8,)).astype(np.float32)
    weights_2 = rng.normal(0.0, 0.2, (4, 8)).astype(np.float32)
    bias_2 = rng.normal(0.0, 0.05, (4,)).astype(np.float32)
    nodes = [
        helper.make_node("Gemm", ["model_input", "w1", "b1"], ["hidden"], name="dense_1", transB=1),
        helper.make_node("Relu", ["hidden"], ["activated"], name="relu_1"),
        helper.make_node("Gemm", ["activated", "w2", "b2"], ["model_output"], name="dense_2", transB=1),
    ]
    graph = helper.make_graph(
        nodes,
        "tiny_mlp",
        [input_info],
        [output_info],
        [
            numpy_helper.from_array(weights_1, "w1"),
            numpy_helper.from_array(bias_1, "b1"),
            numpy_helper.from_array(weights_2, "w2"),
            numpy_helper.from_array(bias_2, "b2"),
        ],
    )
    model = helper.make_model(graph, producer_name="dl-op-to-hls", opset_imports=[helper.make_operatorsetid("", 13)])
    model.ir_version = 8
    onnx.checker.check_model(model)
    return model


def main() -> None:
    parser = argparse.ArgumentParser(description="Create the real tiny ONNX MLP used by the integration example.")
    parser.add_argument("--output", default="models/mlp.onnx")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    onnx.save(build_model(args.seed), output)


if __name__ == "__main__":
    main()
