# Demo Model Generation

The scripts under `scripts/` are utility generators for demo model structures.
They are intentionally lightweight and do not train models.

## Design Rules

1. Structure-only generation, no training.
2. Graceful skip when dependencies are missing.
3. `--help` supported for each script.
4. Default output goes to `models/generated/`.

## Scripts

### `scripts/make_mnist_mlp_onnx.py`

- Output: `models/generated/mnist_mlp.onnx`
- Structure:
  - `Linear(784 -> 64)`
  - `ReLU`
  - `Linear(64 -> 32)`
  - `ReLU`
  - `Linear(32 -> 10)`
- Notes: no softmax required for this toolchain demo.

### `scripts/make_mnist_tiny_cnn_onnx.py`

- Output: `models/generated/mnist_tiny_cnn.onnx`
- Input: static `1x1x14x14` downsampled MNIST-like tensor for real Vivado HLS demo stability.
- Structure:
  - `Conv2d(1 -> 4, k=3)`
  - `ReLU`
  - `MaxPool2d(2)`
  - `Conv2d(4 -> 8, k=3)`
  - `ReLU`
  - `MaxPool2d(2)`
  - `Flatten`
  - `Linear(... -> 16)`
  - `ReLU`
  - `Linear(16 -> 10)`
- Notes:
  - PyTorch export is naturally NCHW.
  - 14x14 keeps early CNN feature maps below Vivado HLS 2018.3 partition thresholds.
  - Downstream ONNX/hls4ml flows may need layout cleanup or channels-last conversion.

### `scripts/make_mnist_qonnx_cnn.py`

- Output: `models/generated/mnist_qonnx_cnn.onnx`
- Structure: same tiny CNN as Demo 3, exported from Torch with statically rounded weights.
- Notes:
  - this is a QONNX-style toolchain demo artifact, not a training/accuracy benchmark.
  - it uses the same 14x14 downsampled input as Demo 3 for real Vivado HLS repeatability.
  - it keeps the long-term PyTorch -> ONNX/QONNX -> hls4ml path unified.
  - downstream adapter converts NCHW Conv/Pool metadata to hls4ml-compatible channels-last layer-list entries.

### `scripts/make_qkeras_mnist_cnn.py`

- Output: `models/generated/mnist_qkeras_cnn.h5`
- Structure: tiny quantized CNN (QConv2D/QDense/QActivation).
- Notes:
  - if `tensorflow` or `qkeras` is missing, script exits with a clear skip message.
  - this is kept as an optional legacy frontend boundary; Demo 4 now uses Torch/QONNX.

### `scripts/make_tiny_residual_block_onnx.py`

- Output: `models/generated/tiny_residual_block.onnx`
- Structure:
  - `Conv2d`
  - `BatchNorm2d`
  - `ReLU`
  - `Conv2d`
  - `BatchNorm2d`
  - residual `Add`
  - `ReLU`
- Notes: this model is for boundary demonstrations, not guaranteed hls4ml support.

## Example Commands

```bash
python scripts/make_mnist_mlp_onnx.py
python scripts/make_mnist_tiny_cnn_onnx.py
python scripts/make_mnist_qonnx_cnn.py
python scripts/make_qkeras_mnist_cnn.py
python scripts/make_tiny_residual_block_onnx.py
```

## Boundary Reminder

`resnet18_boundary.json` is intentionally a boundary demo.
It is used to demonstrate safe unsupported/not-recommended behavior in the agent, not full P0 synthesis support.
