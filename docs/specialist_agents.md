# Specialist Sub-agent Layer

## Why Specialist Sub-agents

The project now uses specialist sub-agents to isolate domain work from the Main Agent. HLS workflows produce large and noisy material: Vivado logs, csynth reports, HLS C++ files, testbenches, hls4ml conversion logs, trace files, and historical memories. The Main Agent owns the run, but it should not carry all of that raw material in its working context.

Specialists solve this by handling local domain execution and returning a compressed, structured result.

## Specialist vs Tool

A tool is an atomic action, such as `vivado.run_csynth` or `hls4ml.check_support`.

A specialist is a scoped executor for a domain. It receives a TodoItem and a ContextEnvelope, then calls only its allowed tools through ToolRegistry. It can coordinate a few related tool calls, compress observations, and return a SpecialistResult.

## Specialist vs Main Agent

Main Agent responsibilities:

- Own AgentState and TodoList.
- Select paths such as hls4ml, fallback template, LLM candidate, or existing project.
- Build ContextEnvelope objects.
- Route TodoItems to specialists.
- Merge SpecialistResult objects.
- Decide dynamic Todo changes and final run status.
- Write final summary, suggestions, artifacts, and memory.

Specialist responsibilities:

- Handle one local TodoItem.
- Use only scoped context.
- Call allowed tools through ToolRegistry.
- Return summaries, metrics, errors, artifact refs, suggested todos, memory candidates, and context_usage.

Specialists do not own global state, directly edit TodoList, or decide final run status.

## Why This Is Not a Multi-agent Chat System

The goal is not free-form conversation between agents. The project uses specialists for context isolation and domain-specific execution. Each specialist receives an input envelope and returns a structured result. The Main Agent remains the single global decision maker.

## Specialists

HLS4MLSpecialist handles model inspection, support checks, hls4ml config generation, conversion, and lightweight hls4ml warnings.

VivadoSpecialist handles project creation, csim/csynth, report parsing, log parsing, and recoverable Vivado errors such as `VivadoNotFoundError`.

VerificationSpecialist handles candidate verification through mock csim/csynth-compatible tools and returns implementation memory candidates when verification succeeds.

OptimizationSpecialist reads current metrics and scoped memory summaries, then generates suggestions through the optimization tool.

MemorySpecialist compresses run context, extracts memory candidates, promotes long-term memories, and indexes reusable material through the memory/RAG layer.

## SpecialistResult

Every specialist returns SpecialistResult with:

- `status`
- `summary`
- `observations`
- `metrics`
- `artifacts`
- `errors`
- `warnings`
- `suggested_todos`
- `memory_candidates`
- `context_usage`

The result intentionally excludes raw logs, raw reports, full HLS code, full stdout/stderr, and internal trace detail.

## ToolRegistry Use

Specialists never call adapters directly. They call tools through ToolRegistry. ToolRegistry still applies PermissionGate, hooks, trace, and database tool-call metadata. Each specialist also checks that the requested tool is inside its allowed tool list before invoking it.
