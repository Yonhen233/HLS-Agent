# Demo Examples

This document describes the 7 interview-oriented demos for `dl-op-to-hls`.

## Demo Matrix

| Demo | File | Type | Expected Path | Real hls4ml required | Real Vivado required |
|---|---|---|---|---|---|
| Demo 0 | `examples/dense_operator.json` | operator | fallback template | No | No |
| Demo 1 | `examples/matmul_resource.json` | operator | fallback template | No | No |
| Demo 2 | `examples/mnist_mlp_hls4ml.json` | model | hls4ml | No (mock by default) | No (mock by default) |
| Demo 3 | `examples/mnist_tiny_cnn.json` | model | hls4ml | No (mock by default) | No (mock by default) |
| Demo 4 | `examples/mnist_qonnx_cnn.json` | model | hls4ml / qonnx frontend | No (mock by default) | No (mock by default) |
| Demo 5 | `examples/tiny_residual_block.json` | model | partial support boundary | No | No |
| Demo 6 | `examples/resnet18_boundary.json` | model | unsupported/not-recommended report | No | No |

## Demo 0: Dense fallback

- Input JSON: `examples/dense_operator.json`
- Expected path: `fallback_template_path`
- Expected outputs:
  - generated `dense_16x32.h/.cpp`
  - generated `testbench.cpp`
  - generated `run_hls.tcl`
  - normal run artifacts (`state.json`, `todos.json`, `trace.jsonl`, `summary.md`, `suggestions.md`)
- Interview focus: deterministic fallback, artifact tracking, trace visibility.

## Demo 1: MatMul resource-oriented fallback

- Input JSON: `examples/matmul_resource.json`
- Expected path: `fallback_template_path`
- Expected behavior: mock report shows lower DSP and higher latency profile.
- Interview focus: resource/latency trade-off explanation from report + suggestions.

## Demo 2: MNIST MLP hls4ml path

- Input JSON: `examples/mnist_mlp_hls4ml.json`
- Expected path: `hls4ml_path`
- Expected behavior: hls4ml support check -> config -> conversion -> mock Vivado synth.
- Interview focus: specialist orchestration across hls4ml + Vivado + optimization.

## Demo 3: MNIST Tiny CNN hls4ml path

- Input JSON: `examples/mnist_tiny_cnn.json`
- Expected path: `hls4ml_path`
- Expected behavior: 14x14 downsampled MNIST-like CNN enters the ONNX layer-list adapter, hls4ml conversion, Vivado synthesis, and report parsing.
- Interview focus: classic CNN path, report parsing, optimization suggestions.

## Demo 4: Torch/QONNX quantized CNN resource path

- Input JSON: `examples/mnist_qonnx_cnn.json`
- Expected path: `hls4ml_path` (frontend = `qonnx`)
- Expected behavior: Torch-generated 14x14 ONNX/QONNX-style CNN with statically rounded weights enters the ONNX/QONNX layer-list adapter and then hls4ml.
- Interview focus: PyTorch-compatible quantization path, static shape/layout cleanup, and resource-oriented precision.

## Demo 5: Tiny residual block boundary

- Input JSON: `examples/tiny_residual_block.json`
- Expected path: `unsupported_path` (after partial support judgment)
- Expected behavior:
  - hls4ml returns `partially_supported`
  - graph rewrite todo appears
  - unsupported/boundary report is generated
- Interview focus: boundary handling without false promises.

## Demo 6: ResNet-18 boundary / unsupported

- Input JSON: `examples/resnet18_boundary.json`
- Expected path: `unsupported_path`
- Expected behavior:
  - hls4ml returns `not_recommended`
  - `unsupported_report.md` generated
  - full synthesis is skipped
- Interview focus: safe refusal and actionable alternatives.
