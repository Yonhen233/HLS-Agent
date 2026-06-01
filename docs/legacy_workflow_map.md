# Legacy Workflow Map

## planner.py branches
- `task_type == "model"`
- `task_type == "operator"`
- fallback branch for `hls_project`

## runtime.py ReAct-like rule branches
- hls4ml support path (`supported`, `unsupported`, `partially_supported`, `not_recommended`)
- fallback template path
- candidate generation and verification retries
- Vivado missing binary (`VivadoNotFoundError`) partial-success branch

## reflector rule branches
- unsupported/partial support -> graph rewrite / fallback / unsupported report
- candidate verification fail -> repair todo or unsupported report
- synthesis skip/failure -> downstream summary behavior

## suggest_optimization.py rule extraction
- latency objective rules
- resource objective rules
- timing failure branch
- RAG hint injection

## Skill Mapping
- `operator_fallback_flow`: deterministic operator fallback + Vivado synthesis/report.
- `hls4ml_model_flow`: model inspect/support/config/convert + Vivado path.
- `existing_hls_project_flow`: existing project synthesis path.
- `unsupported_boundary_flow`: unsupported/not-recommended handling.
- `vivado_synthesis_flow`: synthesis execution policy.
- `report_parse_flow`: report/log parse policy.
- `llm_candidate_verification_flow`: candidate generation + verification loop.
- `latency_optimization_flow`: latency-targeted optimization advice.
- `resource_optimization_flow`: resource-targeted optimization advice.
- `memory_promotion_flow`: finalize memory compression/promotion/indexing.
