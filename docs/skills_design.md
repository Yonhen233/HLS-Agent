# Skills Design

## Role of Skills
Skills are explicit playbooks extracted from legacy deterministic flows.
They are:
- workflow priors for LLM planning,
- constraints for allowed tools/specialists,
- reusable policy surfaces,
- and baseline references for no-LLM operation.

Skills are **not** hardcoded runtime state machines.

## File Layout
- Skill files: `skills/*.yaml`
- Loader and policy: `src/dl_op_to_hls/skills/`

## Data Contract
Each skill includes:
- `intent`, `trigger`, `recommended_todos`
- `allowed_tools`, `allowed_specialists`
- `failure_policy`, `verification_policy`, `memory_policy`

`recommended_todos` is advisory, not a fixed mandatory sequence.

## LLM Integration
`SkillPromptContextBuilder` builds compressed summaries for planner prompts.
`SkillPolicy` validates LLM plan outputs against selected skills.
