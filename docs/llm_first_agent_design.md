# LLM-first Agent Design

## Objective
This project now supports an **LLM-first, tool-grounded, policy-constrained** runtime for HLS workflows.

## Runtime Modes
- `run`: deterministic baseline runtime (legacy-compatible).
- `run-llm`: forces LLM-first runtime.
- `run-nl`: natural-language input, always LLM-first.

`run-llm` does **not** silently fall back to the deterministic planner when LLM is unavailable.

## Core Flow
1. Interpret task (JSON or natural language).
2. Build skill context from `skills/*.yaml`.
3. LLM planner generates TodoPlan (`selected_skill`, `skill_usage`, todos).
4. Guards + SkillPolicy validate plan.
5. ReAct loop executes todo items through ToolRegistry/Specialists.
6. Reflection updates todo graph on failures/branches.
7. Finalization writes summary/suggestions/memory artifacts.

## Why Keep ToolRegistry and PermissionGate
- LLM decides, but tools execute atomic actions.
- PermissionGate blocks unsafe paths/commands/tools.
- Verification remains mandatory for generated HLS candidates.

## Chain-of-thought Policy
The system logs only concise decision summaries (`reason_summary`, `decision`) in trace/state, not hidden chain-of-thought.
