# 深度学习算子转 HLS Agent

英文名：`DL-Operator-to-HLS-Agent`

命令行名：`dl-op-to-hls`

这是一个面向 FPGA HLS 工作流的 Agent 工程原型：用户输入深度学习算子、小模型或已有 HLS 工程任务，系统通过 Agent 编排 hls4ml 风格工具、Vivado HLS 风格工具、fallback HLS 模板、RAG Memory、SQLite 元数据和 Specialist Sub-agent，生成 HLS 工程、运行/模拟综合流程、解析报告，并给出可追踪的优化建议。

本项目的重点不是“支持任意模型”，而是展示一套可面试演示、可调试、可扩展的 Agent 工程架构。

## 项目边界

- 本项目是深度学习算子/小模型到 HLS 的 Agent 原型。
- 不生成 bitstream。
- 不做上板验证。
- 不承诺支持任意 PyTorch/ONNX/QONNX/QKeras 模型。
- LLM 生成的 HLS 代码必须经过验证，不能直接作为最终实现。
- SQLite 是结构化事实源；RAG 只是检索层，不替代数据库。
- `run` 是确定性基线流程；`run-llm` 是 LLM-first Agent 流程，不会在 LLM 不可用时静默退回确定性 planner。

## 核心架构

```text
User Task
  ↓
Main Agent
  - 全局任务理解
  - TodoList 管理
  - Specialist 调度
  - 状态合并
  - Trace / Artifact / Memory / Summary
  ↓
Todo-driven Plan-Execute-ReAct Runtime
  - 外层：Plan → TodoList → Execute → Reflect → Finalize
  - 内层：Main Agent ReAct 或 Specialist Local ReAct
  ↓
Specialist Sub-agents
  - HLS4MLSpecialist
  - VivadoSpecialist
  - VerificationSpecialist
  - OptimizationSpecialist
  - MemorySpecialist
  ↓
ToolRegistry / MCP-style Tools
  - hls4ml tools
  - Vivado HLS tools
  - fallback templates
  - report parser
  - memory / RAG / DB tools
  ↓
Artifacts + SQLite + RAG
```

## 为什么这是 Agent 工程项目

本项目不只是脚本串联。它包含：

- Tool Registry：所有工具统一注册、调用、追踪。
- Permission Gate：限制文件读写和命令执行，避免工具越权。
- Hook / Trace：每次运行生成 `trace.jsonl`，记录 Run、Todo、Tool、Specialist、LLM 事件。
- AgentState：运行状态可序列化，失败也保存。
- Artifact Manager：所有生成文件登记到 manifest。
- Structured Error：失败以结构化错误返回，支持 partial success。
- Context Compression：原始长日志和报告保存为 artifact，Agent 只接收摘要。
- Memory Layer：短期记忆、长期 episodic/semantic memory、skills/playbooks。
- RAG Memory：从 summary、suggestions、compressed context、memory facts 检索历史经验。
- Todo Board：每个任务拆成可观察、可恢复、可追踪的 TodoItem。
- Plan-Execute-ReAct Hybrid：全局规划与局部 ReAct 决策结合。
- Specialist Sub-agent：领域任务隔离，避免 Main Agent 污染上下文。

## 两层 ReAct 设计

### Main Agent ReAct

Main Agent 不直接看到 Specialist 的私有底层工具。它只允许以下高层动作：

```text
delegate_to_specialist
direct_tool_only_when_no_specialist
request_replan
mark_blocked
mark_failed
```

这能防止 Main Agent 绕过 Specialist，直接拼接 `hls4ml.*` 或 `vivado.*` 工具参数。

### Specialist Local ReAct

每个 Specialist 内部有自己的局部 ReAct decider，输入被限制为：

```text
ContextEnvelope
allowed_tools
recent specialist observations
candidate arguments
```

输出只允许：

```text
call_tool
mark_blocked
mark_failed
finish_with_result
```

Specialist 只能调用自己的 `allowed_tools`，并且只能返回压缩后的 `SpecialistResult`，不能直接修改完整 `AgentState` 或长期 memory。

## Specialist 分工

- `HLS4MLSpecialist`：模型检查、hls4ml 支持判断、配置生成、模型转换。
- `VivadoSpecialist`：Vivado HLS project 创建、csim/csynth、报告解析。
- `VerificationSpecialist`：fallback/LLM candidate 的 testbench、csim、验证。
- `OptimizationSpecialist`：结合 report、objective、RAG/memory 生成优化建议。
- `MemorySpecialist`：压缩上下文、抽取 memory candidate、长期记忆提升、RAG 索引。

## Memory 分层

```text
L0 Runtime State
  AgentState / state.json / current todo / tool results
  注意：L0 是运行状态，不是真正 memory。

L1 Short-term Memory
  当前 run 的压缩上下文、近期决策、错误摘要。

L2 Long-term Episodic Memory
  历史 run、实现、综合结果、失败案例，存入 SQLite。

L3 Long-term Semantic Memory
  从多次 run 中总结出的事实和经验，存入 memory_facts + RAG。

L4 Skills / Playbooks
  可复用流程：hls4ml path、fallback path、Vivado synthesis、unsupported path 等。
```

## 运行模式

### 确定性基线流程

```powershell
$env:PYTHONPATH="src"
python -m dl_op_to_hls.cli run examples/dense_operator.json
```

### LLM-first Agent 流程

```powershell
$env:PYTHONPATH="src"
$env:DL_OP_TO_HLS_LLM_ENABLED="1"
$env:DL_OP_TO_HLS_LLM_PROVIDER="openai-compatible"
$env:DL_OP_TO_HLS_LLM_BASE_URL="https://your-openai-compatible-endpoint/v1"
$env:DL_OP_TO_HLS_LLM_MODEL="your-model"
$env:DL_OP_TO_HLS_LLM_API_KEY="<your-api-key>"
python -m dl_op_to_hls.cli run-llm examples/dense_operator.json
```

### Demo / strict 优化建议模式

默认 `demo` 模式允许在 LLM 不可用时使用规则建议，便于演示：

```powershell
$env:DL_OP_TO_HLS_OPTIMIZATION_FALLBACK_MODE="demo"
```

开发排错时建议使用 `strict`，LLM 失败就暴露为结构化错误：

```powershell
$env:DL_OP_TO_HLS_OPTIMIZATION_FALLBACK_MODE="strict"
```

## hls4ml 与 Vivado HLS 配置

hls4ml 是 Python 库；安装后可走真实 hls4ml path。Vivado HLS 通过命令行调用。

```powershell
$env:DL_OP_TO_HLS_VIVADO_HLS_PATH="D:\Xilinx\Vivado\2018.3\bin\vivado_hls.bat"
```

如需强制演示环境使用 mock 工具：

```powershell
$env:DL_OP_TO_HLS_MOCK_HLS4ML="1"
$env:DL_OP_TO_HLS_MOCK_VIVADO="1"
python -m dl_op_to_hls.cli run examples/dense_operator.json --mock-tools
```

## Demo 任务

| Demo | 文件 | 类型 | 目标路径 | 作用 |
|---|---|---|---|---|
| Demo 0 | `examples/dense_operator.json` | operator | fallback_template | 最稳演示，展示 Agent 工程闭环 |
| Demo 1 | `examples/matmul_resource.json` | operator | fallback_template | 展示 latency/resource trade-off |
| Demo 2 | `examples/mnist_mlp_hls4ml.json` | model | hls4ml | 展示 hls4ml 主路径 |
| Demo 3 | `examples/mnist_tiny_cnn.json` | model | hls4ml | 展示经典 CNN |
| Demo 4 | `examples/mnist_qonnx_cnn.json` | model | hls4ml / qonnx | 展示 Torch/QONNX FPGA-aware 量化路径 |
| Demo 5 | `examples/tiny_residual_block.json` | model | partial / rewrite / boundary | 展示 residual block 边界处理 |
| Demo 6 | `examples/resnet18_boundary.json` | model | unsupported_report | 展示 Agent 不盲目承诺 |

递进运行：

```powershell
$env:PYTHONPATH="src"
python -m dl_op_to_hls.cli run examples/dense_operator.json --mock-tools
python -m dl_op_to_hls.cli run examples/matmul_resource.json --mock-tools
python -m dl_op_to_hls.cli run examples/mnist_mlp_hls4ml.json --mock-tools
python -m dl_op_to_hls.cli run examples/mnist_tiny_cnn.json --mock-tools
python -m dl_op_to_hls.cli run examples/mnist_qonnx_cnn.json --mock-tools
python -m dl_op_to_hls.cli run examples/tiny_residual_block.json --mock-tools
python -m dl_op_to_hls.cli run examples/resnet18_boundary.json --mock-tools
```

每次 run 会生成：

```text
runs/<run_id>/state.json
runs/<run_id>/todos.json
runs/<run_id>/trace.jsonl
runs/<run_id>/artifacts.json
runs/<run_id>/summary.md
runs/<run_id>/suggestions.md
runs/<run_id>/memory/*.json
runs/<run_id>/specialists/*/summary.json
```

## 常用命令

```powershell
$env:PYTHONPATH="src"

python -m dl_op_to_hls.cli llm-status
python -m dl_op_to_hls.cli report runs/<run_id>
python -m dl_op_to_hls.cli suggest runs/<run_id>
python -m dl_op_to_hls.cli rag-search "Dense reuse factor DSP"
python -m dl_op_to_hls.cli memory-search "Dense high DSP reuse factor"
python -m dl_op_to_hls.cli db-list-runs
python -m dl_op_to_hls.cli skills-list
python -m dl_op_to_hls.cli specialists-list
python -m dl_op_to_hls.cli specialist-show VivadoSpecialist
```

## Benchmark / Quantitative Evaluation

The project includes an Agent-quality benchmark for measuring workflow and RAG improvements:

```powershell
$env:PYTHONPATH="src"
python -m dl_op_to_hls.cli benchmark `
  --runs dense_16x32_af6abf3c_10 matmul_16x16_resource_9ac8e2e8_13 resnet18_boundary_demo_cd40d797_13 resnet18_boundary_demo_cd40d797_15 `
  --compare resnet18_boundary_demo_cd40d797_13 resnet18_boundary_demo_cd40d797_15 `
  --rag-eval-file benchmarks\rag_eval_labels.json `
  --rag-top-k 5 `
  --output runs\benchmarks\agent_quality_benchmark_demo.json
```

Metrics include runtime, LLM decision count, tool calls, specialist events, artifact completeness, RAG pollution rate, unsupported semantics pass rate, Vivado report metrics, Precision@K, Recall@K, Hit@K, MRR, nDCG@K, relevant-term coverage, and pollution@K.

See `docs/benchmark_metrics.md` for metric definitions and interview-ready interpretation.

## 测试

```powershell
$env:PYTHONPATH="src"
python -m pytest -q
```

当前测试覆盖：

- ToolRegistry / PermissionGate / Hook / Trace
- TodoList / Hybrid Runtime
- Memory / RAG / SQLite
- hls4ml / Vivado HLS MCP-style adapters
- fallback templates / report parser
- Main Agent / Specialist Sub-agent
- Main Agent ReAct 与 Specialist Local ReAct 契约
- Demo0-Demo6 mock-flow 验收

## 目录结构

```text
src/dl_op_to_hls/
  main_agent/        Main Agent、runtime、todo、planner、executor、reflector
  specialists/       Specialist Sub-agent、ContextEnvelope、SpecialistResult
  core/              ToolRegistry、permissions、hooks、trace、artifacts、errors
  adapters/          hls4ml / Vivado HLS adapter
  tools/             fallback、report parser、suggestion、verification
  memory/            MemoryManager、policy、short-term/episodic/semantic/skills
  rag/               chunker、indexer、retriever
  db/                SQLite schema 与 repository
  llm/               LLM client、planner、react、guards、schemas、prompts

examples/            Demo0-Demo6 输入任务
models/              示例模型或生成模型目录
scripts/             示例模型生成脚本
docs/                架构、运行时、memory、specialist、开发日志
tests/               pytest 测试
runs/                本地运行产物，默认不进入 git
```

## 重要文档

- `docs/runtime_design.md`
- `docs/memory_design.md`
- `docs/todo_design.md`
- `docs/specialist_agents.md`
- `docs/context_isolation.md`
- `docs/llm_first_agent_design.md`
- `docs/llm_guardrails.md`
- `docs/development_log.md`

## 当前限制与未来工作

当前限制：

- hls4ml 对 ONNX/QONNX/QKeras 的真实支持取决于本地库版本和模型图结构。
- Vivado HLS 真实综合取决于本机安装、license、环境变量和 Windows batch 调用。
- boundary demo 设计目标是展示“安全拒绝/边界处理”，不是 full synthesis success。
- LLM API 有速率限制时需要配置请求节流。

未来工作：

- 增强 graph rewrite，例如 Gemm → MatMul + Add、Shape/Flatten 静态消除。
- 增强真实 hls4ml custom layer suggestion。
- 增加 precision/reuse factor sweep。
- 将 MCP-style in-process tools 升级为真实 MCP server/client。
- 引入更系统的 benchmark report 和 experiment comparison。
