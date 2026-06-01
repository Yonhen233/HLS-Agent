# Demo Script

This script is designed for interview demos in a mock-tool environment.
All commands below should work without real `hls4ml` or real `Vivado HLS`.

## 0. Warm-up

```bash
dl-op-to-hls specialists-list
```

What to show:
1. The system has clear specialist boundaries.
2. Main agent orchestration vs specialist local execution.

Likely question:
1. Why specialist layer?

Suggested answer:
1. It isolates domain context and keeps Main Agent context compact and stable.

## 1. Stable fallback operator demo

```bash
dl-op-to-hls run examples/dense_operator.json --mock-tools
```

What to show:
1. `fallback_template_path` selected.
2. Generated files: `.h/.cpp/testbench.cpp/run_hls.tcl`.
3. `todos.json`, `trace.jsonl`, `artifacts.json`, `summary.md`, `suggestions.md`.

Likely question:
1. Why not always use hls4ml?

Suggested answer:
1. Operator JSON path is intentionally routed to deterministic fallback templates in P0.

## 2. hls4ml model demo (tiny CNN)

```bash
dl-op-to-hls run examples/mnist_tiny_cnn.json --mock-tools
```

What to show:
1. `hls4ml_path` selected.
2. HLS4ML specialist + Vivado specialist trace events.
3. Report parsing and optimization suggestions.

Likely question:
1. Is this real synthesis?

Suggested answer:
1. Default interview flow uses mocks for stability; real adapters are available when toolchains exist.

## 3. Boundary / unsupported judgment demo

```bash
dl-op-to-hls run examples/resnet18_boundary.json --mock-tools
```

What to show:
1. `not_recommended` support status.
2. `unsupported_report.md` generated.
3. No full `vivado.run_csynth` attempt for this boundary demo.

Likely question:
1. Why skip synthesis?

Suggested answer:
1. This MVP prioritizes safe and explicit boundary handling over overpromising full-model closure.

## 4. Memory and RAG retrieval demo

Run after several demos:

```bash
dl-op-to-hls memory-search "Dense high DSP reuse factor"
dl-op-to-hls rag-search "Dense high DSP reuse factor"
```

What to show:
1. Historical experiences are retrievable.
2. SQLite is source of truth, RAG is retrieval layer.
