# Demo Models

This directory stores small demo model artifacts for the `dl-op-to-hls` interview demos.

- `models/generated/` is the target output directory for helper scripts in `scripts/`.
- Scripts generate structure-only demo models for toolchain validation.
- The scripts do not train models and do not target accuracy benchmarks.
- For ONNX CNN demos, layout conversion and cleanup may still be required in real flows.
- QKeras demos are optional and skip gracefully when `tensorflow` or `qkeras` is unavailable.
- `resnet18` remains a boundary demo, not a P0 support target.
