# DL-Operator-to-HLS Agent 工作流图

本文档用于面试时快速展示系统结构。图中的重点是 Agent Harness，而不是硬件指标。

## 1. 总体架构

```mermaid
flowchart TD
    U["User task"] --> A["MainAgent"]
    A --> R{"Runtime"}
    R --> P["Plan / Todo"]
    P --> S["Specialist Router"]
    S --> H["HLS4ML Specialist"]
    S --> V["Vivado Specialist"]
    S --> Q["Verification Specialist"]
    S --> O["Optimization Specialist"]
    S --> M["Memory Specialist"]
    H --> T["ToolRegistry"]
    V --> T
    Q --> T
    O --> T
    M --> T
    T --> G["PermissionGate"]
    G --> X["HLS tools / parsers / reports"]
    X --> E["ArtifactManager"]
    X --> L["TraceWriter"]
    E --> Z["Summary + benchmark evidence"]
    L --> Z
```

## 2. LLM-first Harness

```mermaid
flowchart TD
    A["Task"] --> B["Retrieve memory and skill context"]
    B --> C["LLM proposes plan"]
    C --> D{"Schema and guard pass?"}
    D -- "no" --> E["JSON repair / plan repair"]
    E --> C
    D -- "yes" --> F["Create todo list"]
    F --> G["Execute todo with specialists"]
    G --> H{"Tool or verification failure?"}
    H -- "yes" --> I["Repair / replan / unsupported recovery"]
    I --> G
    H -- "no" --> J["Finalize summary"]
    J --> K["Trace + artifacts + metrics"]
```

## 3. Path Selection

```mermaid
flowchart TD
    T["Input task"] --> C{"Task type"}
    C -- "Supported model, e.g. MNIST" --> H["hls4ml_path"]
    C -- "Templateable op" --> F["fallback_template_path"]
    C -- "Existing project" --> E["existing_project_path"]
    C -- "Small generated kernel" --> L["llm_candidate_path"]
    C -- "Unsupported model/op" --> U["unsupported_path"]
    H --> HS["inspect model -> config -> convert -> csim/report"]
    F --> FS["select template -> generate code/testbench -> verify/report"]
    E --> ES["reuse project -> run/parse report -> recover if needed"]
    L --> LS["generate candidate -> sandbox -> csim -> repair/report"]
    U --> US["write honest unsupported report"]
```

## 4. Specialist Context

```mermaid
flowchart LR
    S["AgentState"] --> B["ContextBuilder"]
    B --> C["ContextEnvelope"]
    C --> C1["scoped_state"]
    C --> C2["artifact_refs"]
    C --> C3["retrieved_memory_refs"]
    C --> C4["constraints"]
    C --> C5["allowed_tools"]
    C --> C6["token budget"]
    C --> SP["Specialist"]
    SP --> R["SpecialistResult"]
```

## 5. Tool Call Safety

```mermaid
sequenceDiagram
    participant Sp as Specialist
    participant Tr as ToolRegistry
    participant Pg as PermissionGate
    participant Tool as Registered Tool
    participant Trace as TraceWriter

    Sp->>Tr: call(tool_name, args)
    Tr->>Pg: check tool/path/command permission
    Pg-->>Tr: allow or deny
    Tr->>Trace: PreToolUse
    Tr->>Tool: execute
    Tool-->>Tr: result or error
    Tr->>Trace: PostToolUse or ToolFailed
    Tr-->>Sp: ToolResult
```

## 6. Repair Loop

```mermaid
flowchart TD
    A["Execute todo"] --> B{"Failure stage"}
    B -- "hls4ml convert" --> C["adjust config or mark unsupported"]
    B -- "csim failed" --> D["repair candidate/testbench"]
    B -- "report missing" --> E["parse log or write recovery report"]
    B -- "LLM invalid JSON" --> F["repair structured output"]
    B -- "toolchain missing" --> G["toolchain recovery"]
    C --> H["Replan todo"]
    D --> H
    E --> H
    F --> H
    G --> H
    H --> I["Retry or partial_success"]
```

## 7. Trace Completeness

```mermaid
flowchart LR
    A["Run"] --> B["Plan"]
    B --> C["Todo"]
    C --> D["Tool call"]
    D --> E["Specialist result"]
    E --> F["Artifact"]
    E --> G["Error stage when failed"]
    F --> H["Summary"]
    G --> H
```

## 8. RAG Evidence Control

```mermaid
flowchart TD
    Q["Query"] --> A["Token / anchor scoring"]
    A --> B{"Failure-like query?"}
    B -- "yes" --> F["Allow failure cases"]
    B -- "no" --> N["Suppress failure-only memories"]
    F --> R["Ranked evidence"]
    N --> R
    R --> M{"Relevant to task?"}
    M -- "yes" --> Hit["Hit"]
    M -- "no" --> Pollute["Pollution"]
```

## 9. Benchmark Harness

```mermaid
flowchart TD
    S["Suite JSON"] --> R["Run cases"]
    R --> C["Collect run metrics"]
    C --> P["Path selection accuracy"]
    C --> T["Task success by bucket"]
    C --> U["Unsupported honesty"]
    C --> Re["Repair success"]
    C --> Tr["Trace completeness"]
    C --> G["RAG hit / pollution"]
    C --> L["Latency / cost"]
    P --> Report["Markdown + JSON report"]
    T --> Report
    U --> Report
    Re --> Report
    Tr --> Report
    G --> Report
    L --> Report
```

## 10. 面试讲解顺序

```mermaid
flowchart LR
    A["Problem: old scripts are not agents"] --> B["Agent architecture"]
    B --> C["Controlled tool use"]
    C --> D["Specialist context isolation"]
    D --> E["Repair and unsupported honesty"]
    E --> F["RAG evidence control"]
    F --> G["Agent benchmark metrics"]
    G --> H["Limitations and next steps"]
```
