# Skills Design

## Design Goal

Skill is a versioned, declarative playbook rather than a bag of tools or a hidden
workflow state machine. It has two deliberately separate layers:

1. **Execution contract**: machine-readable permissions, prerequisites, tool and
   Specialist allowlists, verification requirements, failure policy, memory policy,
   budgets, concurrency and required artifacts. The runtime enforces this layer.
2. **Execution guidance**: concise natural-language purpose, procedure, decision
   rules, pitfalls, verification guidance and examples. The Planner and the local
   Specialist ReAct decider use this layer to understand what to do and why.

The first layer prevents unsafe or semantically invalid actions. The second layer
improves decisions without pretending that prose is an authorization mechanism.
Skills are **not** hardcoded runtime state machines: `recommended_todos` are
starting suggestions, while the LLM may adapt them only within the contract and
the Main Agent's plan, goal and evidence guards.

## File Layout

- Published skills: `skills/*.yaml` (currently JSON-compatible YAML documents)
- Data model and prompt projection: `src/dl_op_to_hls/skills/skill.py`
- Schema linter: `src/dl_op_to_hls/skills/schema.py`
- Loading, version selection and integrity checks: `src/dl_op_to_hls/skills/registry.py`
- Planner capability projection: `src/dl_op_to_hls/skills/prompt_context.py`
- Runtime allowlist and verification checks: `src/dl_op_to_hls/skills/policy.py`

## Ideal Skill Contract

Every shipped Skill contains the following groups:

```yaml
name: operator_fallback_flow
version: 1.1.0
status: approved
description: Short trigger-facing description
intent: operator_to_hls_fallback
trigger: {task_type: operator}
preconditions: [task_schema_valid]

# Human-readable playbook guidance
purpose: What outcome this playbook is for
procedure: [ordered but adaptable execution steps]
decision_rules: [branch conditions and invariants]
pitfalls: [common incorrect actions]
verification_guidance: [evidence required before claiming success]
examples: [{scenario: ..., expected_outcome: ...}]

# Machine-enforced contract
recommended_todos: [{title: ..., assigned_tool: ..., dependencies: [...]}]
allowed_tools: [fallback.generate_operator_hls]
allowed_specialists: [CodegenSpecialist, VivadoSpecialist]
required_artifacts: [hls_cpp, testbench, vivado_report]
failure_policy: {}
verification_policy: {}
memory_policy: {}
context_policy: {}
budget_policy: {}
concurrency_policy: {}
permissions: {}
```

The guidance fields are validated for shape and non-empty content. Their truth is
not accepted as evidence: reports, CSim/reference comparison, and artifacts still
come from tools and evidence gates.

## How A Run Uses A Skill

`SkillRegistry` loads and validates all documents, chooses an approved version,
and ranks candidates from task triggers. This is progressive disclosure: the
Planner first receives a bounded catalog preview (`to_catalog_summary`) containing
enough purpose, trigger, short guidance and capability information to select a
Skill; after selection, the runtime retains the full contract and projects only
the current Specialist's guidance into its `ContextEnvelope`. Tool schemas and
raw artifact contents are requested only at their execution boundary. The Planner
returns a selected Skill and a Todo plan; `SkillPolicy` and `LLMGuard` reject tool,
Specialist, dependency, budget or verification violations.

When a Todo is delegated, `ContextBuilder` projects only the selected Skill's
guidance relevant to that Specialist into `ContextEnvelope.scoped_state.skill_guidance`.
It does not copy the complete AgentState, raw logs, full code, or other roles'
allowlists. The Specialist can use the guidance to make a local decision, but can
only call `allowed_tools` and must return a structured `SpecialistResult`.

## Ten Current Skills

- `hls4ml_model_flow`: inspect, check support, configure and convert supported models.
- `operator_fallback_flow`: explicitly selected local operator-template generation.
- `llm_candidate_verification_flow`: candidate generation followed by independent functional and synthesis verification.
- `vivado_synthesis_flow`: isolated Vivado HLS execution and real report parsing.
- `report_parse_flow`: conversion of reports/logs into structured facts.
- `latency_optimization_flow`: latency and II optimization from measured metrics.
- `resource_optimization_flow`: resource-budget optimization with trade-off evidence.
- `existing_hls_project_flow`: safe evaluation of a user-provided HLS project.
- `unsupported_boundary_flow`: honest terminal boundary when semantics or evidence are insufficient.
- `memory_promotion_flow`: bounded trace/evidence review and controlled long-term memory promotion.

## Lifecycle And Safety

Published files are `approved`; generated or automatically extracted playbooks
must remain `candidate` until reviewed and tested. A Skill may suggest a new Todo,
but it cannot grant itself a new tool, bypass PermissionGate, write long-term
memory, or turn a candidate implementation into verified output. Version changes
must pass schema, runtime contract and regression tests before approval.
