# Context Isolation

## Why Context Gets Too Long

A single HLS run can produce model metadata, generated C++ and headers, testbenches, TCL scripts, Vivado logs, csynth reports, summaries, suggestions, trace files, and historical memory retrieval results. Passing all of this into the Main Agent would make decisions harder to inspect and easier to contaminate with raw noise.

## ContextEnvelope

ContextEnvelope is the scoped input passed from the Main Agent to a specialist. It contains:

- Current run id and Todo id.
- Task summary.
- Specialist-specific state slice.
- Artifact references.
- Top-k retrieved memory summaries.
- Constraints and allowed tools.
- A max context token budget.

The envelope does not contain full AgentState, full trace, raw logs, raw reports, full HLS code, or the full memory database.

## Artifact References

Raw materials are saved as artifacts. Specialists receive paths and metadata, then read only what their domain needs. The Main Agent receives compressed outputs such as metrics, summary strings, structured errors, artifact refs, and context_usage.

## SpecialistResult Compression

SpecialistResult is the return boundary. It carries compressed observations and context_usage so the Main Agent can merge results without ingesting raw files.

The result can include:

- Summaries.
- Latency/resource/timing metrics.
- Structured errors.
- Warnings.
- Artifact refs.
- Suggested todos.
- Memory candidates.

The result cannot include raw Vivado logs, raw csynth reports, full generated code, full stdout/stderr, or full specialist internal trace.

## Merge Rules

Main Agent merges only bounded fields:

- Summary and status.
- Metrics.
- Artifact refs.
- Structured errors and warnings.
- Suggested todos.
- Memory candidates.
- context_usage.

Raw artifacts remain under `runs/<run_id>/...`.

## context_usage

Each specialist records `context_usage` with raw artifact bytes read, summary bytes returned, and compression ratio. This makes context isolation visible in trace and summary output.
