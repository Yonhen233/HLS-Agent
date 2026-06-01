# LLM Guardrails

## Validation Layers
1. **Schema validation** for LLM outputs.
2. **SkillPolicy** validation against selected skill allowlists.
3. **LLMGuard** validation for plan/action/reflection/candidate safety.
4. **ToolRegistry** centralized tool invocation.
5. **PermissionGate** path/command/tool-level enforcement.

## Blocked Behaviors
- Unknown tool or specialist in TodoPlan.
- Tool call outside allowed skill/specialist tool sets.
- Candidate file writes outside `runs/<run_id>/candidate`.
- Candidate marked `verified` before verification.
- Direct long-term memory mutation without memory tools.
- Direct shell-style actions outside tool layer.

## Candidate Safety
LLM candidate generation is always intermediate:
- `candidate_generated` -> verification -> `verified`/`failed`.
- LLM cannot directly emit `verified` as final status.
