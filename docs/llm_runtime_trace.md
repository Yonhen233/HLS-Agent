# LLM Runtime Trace

## LLM Events
- `LLMCallStarted`
- `LLMCallFinished`
- `LLMCallFailed`
- `LLMTaskInterpreted`
- `LLMSkillContextBuilt`
- `LLMPlanGenerated`
- `LLMPlanRejected`
- `LLMPlanAccepted`
- `LLMReActDecision`
- `LLMReflectionDecision`
- `LLMOptimizationGenerated`
- `LLMCandidateGenerated`
- `LLMGuardRejected`

## Event Payload Principles
- Include: run id, prompt type, model, decision summary, selected skill.
- Exclude: hidden chain-of-thought and full raw artifacts.

## Trace Usage
Use `dl-op-to-hls llm-trace runs/<run_id>` to inspect only LLM-related trace lines.
