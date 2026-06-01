# Reality Check

## What Is Real Today
- Real local Vivado binary path can be configured via `DL_OP_TO_HLS_VIVADO_HLS_PATH`.
- hls4ml adapter supports real package detection and real conversion path attempts.
- Deterministic runtime is production-safe baseline for environments without LLM API.

## What Is Controlled/Mixed
- LLM-first runtime requires API key and policy checks.
- Candidate generation is guarded and must pass verification.
- Some flows still use lightweight adapters where toolchain integration depth depends on environment.

## Practical Usage
- Use `run` for deterministic regression and baseline behavior.
- Use `run-llm` to validate LLM-first orchestration behavior explicitly.
