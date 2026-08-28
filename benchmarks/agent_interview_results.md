# Agent 面试量化评测

- Interview Ready: `True`
- Frozen run cohort: `22`
- Historical task success: `0.9091`
- False success: `0.0`
- Toolchain selection accuracy: `0.8636`
- Trace / Artifact completeness: `1.0` / `1.0`
- Runtime p50 / p95: `167.5` / `1258.4` seconds
- Tokens per success: `55728.9`

## 开放任务泛化

- Real LLM planning pass: `10/10`
- LLM calls / tokens: `18` / `40023`
- Same-suite framework repair: `90.0` percentage points

## 消融

- RAG MRR: no-memory `0.0`, naive `1.0`, production `1.0`
- RAG nDCG@K: naive `1.0`, production `1.0`
- RAG pollution@K: naive `0.1852`, production `0.0`
- Guard unsafe acceptance: schema-only `1.0`, enabled `0.0`
- Specialist return vs full-state context reduction p50: `0.9784`

## 恢复与幂等

- Production component probes: `5/5`

## Release Gates

- [x] frozen_historical_cohort_present
- [x] historical_false_success_zero
- [x] trace_completeness_at_least_95_percent
- [x] artifact_completeness_at_least_95_percent
- [x] real_llm_open_planning_at_least_80_percent
- [x] rag_mrr_at_least_80_percent
- [x] rag_pollution_at_most_10_percent
- [x] unsafe_candidate_acceptance_zero
- [x] recovery_idempotency_all_pass
- [x] context_isolation_measured

## 口径

- Open-task generalization evaluates real LLM interpretation and guarded planning, not HLS execution.
- Guard ablation is a safe counterfactual and never executes unsafe candidates.
- Context ablation is posthoc over frozen current-run artifacts.
- Samples below 20 are reported with Wilson intervals and are not claimed as population-level stability.
