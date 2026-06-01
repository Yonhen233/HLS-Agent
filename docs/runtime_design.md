# Runtime Design

## Why Hybrid
The runtime uses a **Todo-driven Plan-Execute-ReAct hybrid** model:

- Pure ReAct is weak for long HLS pipelines with known stages.
- Pure Plan-Execute is weak when tool outputs force path switches.
- Hybrid keeps global structure while allowing local reaction.

## Runtime Modes
- `run`: deterministic baseline runtime.
- `run-llm`: LLM-first runtime (no silent fallback).
- `run-nl`: natural-language task input, LLM-first only.

## Outer Loop
1. Initialize state/context.
2. Retrieve initial memory.
3. Build plan (deterministic or skill-guided LLM plan).
4. Execute todos.
5. Reflect and update todo graph.
6. Finalize summary/suggestions/memory artifacts.

## Inner ReAct
Each todo execution records:
- reason summary,
- action type (`tool` / `specialist`),
- observation summary,
- decision summary.

This preserves explainability without storing hidden chain-of-thought.

## Reflection and Branching
Typical branch cases:
- hls4ml unsupported -> graph rewrite/fallback/unsupported report.
- Vivado not found -> synthesis skipped, continue as partial success.
- candidate verification failed -> repair or reject path.

## Partial Success
`partial_success` is first-class:
- artifacts generated but synthesis skipped,
- report missing but log summary available,
- boundary unsupported path completed with actionable report.
