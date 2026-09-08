# DL-to-HLS Agent

面向 FPGA 高层次综合的 Coding Agent Harness：将深度学习算子、小型模型或已有 HLS 工程转换为可验证、可综合、可追踪的 HLS 实现。

项目不是简单地让 LLM 输出一段 C++。它围绕真实工程闭环组织工作：理解目标、规划步骤、生成候选实现、编写 Golden Testbench、调用 Vivado HLS、解析时延与资源报告、失败修复、沉淀经验，并要求每个成功结论都能追溯到工具产物。

> 当前边界：生成并验证 HLS 工程，不生成 bitstream，不做上板验证，也不承诺支持任意神经网络。

## 能解决什么问题

用户可以输入：

- 一个算子描述，例如 Dense、MatMul、ReLU、Add、ScaleShift 或受支持的静态 Conv2D。
- 一个 ONNX/QONNX 小模型。
- 一个已有 HLS C++ 工程。
- 一段自然语言需求，例如“把这个 Dense 算子转成 HLS，在资源预算内优先降低 II”。

Agent 会根据任务和目标选择执行路径：

```text
用户需求
  -> LLM Planner 生成 Todo DAG
  -> Main Agent 调度 Specialist
  -> 复用已验证实现，或生成新的 LLM Candidate
  -> Candidate Sandbox 静态检查
  -> Golden CSim 功能验证
  -> Vivado HLS CSynth
  -> 报告解析与证据门禁
  -> 优化建议、Trace、Artifact 和长期经验
```

只有满足相应证据条件时，状态才会提升为 `functional_verified` 或 `deployment_ready_candidate`。LLM 不能只凭文字宣称任务完成。

## 快速开始

### 1. 安装

```powershell
git clone https://github.com/Yonhen233/HLS-Agent.git
cd HLS-Agent
python -m pip install -e .
```

可选依赖：

```powershell
python -m pip install -e ".[real-toolchain]"
python -m pip install -e ".[rag]"
```

### 2. 配置 LLM

项目支持 OpenAI-compatible API。密钥只通过环境变量传入，不要写进仓库：

```powershell
$env:DL_OP_TO_HLS_LLM_ENABLED="1"
$env:DL_OP_TO_HLS_LLM_PROVIDER="openai-compatible"
$env:DL_OP_TO_HLS_LLM_BASE_URL="https://your-endpoint/v1"
$env:DL_OP_TO_HLS_LLM_MODEL="your-model"
$env:DL_OP_TO_HLS_LLM_API_KEY="<your-api-key>"
```

### 3. 运行一个任务

```powershell
dl-op-to-hls agent-run examples\dense_operator.json --real-tools
```

`run`、`run-llm` 和 `agent-run` 进入同一套持久化 LLM Agent Runtime；`run-baseline` 仅用于确定性对照实验。

### 4. 连续对话

```powershell
dl-op-to-hls chat --real-tools
```

示例：

```text
> 把 Dense 16x32 转成 HLS，优先优化资源
> 保持功能验证通过，再尝试降低 DSP
> /status
> /exit
```

会话退出后可继续：

```powershell
dl-op-to-hls chat --session-id <session_id> --real-tools
```

## 接入真实 Vivado HLS

Vivado HLS 2018.3 示例配置：

```powershell
$env:DL_OP_TO_HLS_HLS_TOOLCHAIN="vivado_hls"
$env:DL_OP_TO_HLS_VIVADO_HLS_PATH="D:\Xilinx\Vivado\2018.3\bin\vivado_hls.bat"
$env:DL_OP_TO_HLS_MOCK_HLS4ML="0"
$env:DL_OP_TO_HLS_MOCK_VIVADO="0"
```

Vivado 本身不原生支持 MCP。项目通过 Adapter 将其命令行和 TCL 自动化流程封装为标准 MCP Tools：

```text
VivadoSpecialist
  -> Tool Registry / Permission Gate / Trace
  -> MCP Client
  -> JSON-RPC over stdio
  -> Vivado MCP Server
  -> VivadoHLSAdapter
  -> vivado_hls.bat -f run_hls.tcl
```

MCP Server 基于官方 Python MCP SDK，支持：

- 标准 stdio 与 Streamable HTTP。
- `tools/list` 动态发现。
- 输入和输出 JSON Schema。
- Progress 与 Cancellation 通知。
- 结构化错误和结果。
- stderr 隔离与协议 stdout 保护。
- 客户端和服务端双层权限检查。
- 非幂等综合调用禁止在传输故障后盲目重放。

本地 EDA 推荐 stdio：

```powershell
$env:DL_OP_TO_HLS_MCP_TRANSPORT="stdio"
dl-op-to-hls agent-run examples\dense_operator.json --real-tools
```

也可以单独启动本机 Streamable HTTP Server：

```powershell
dl-op-to-hls serve-hls4ml --transport streamable-http --host 127.0.0.1 --port 8000
dl-op-to-hls serve-vivado-hls --transport streamable-http --host 127.0.0.1 --port 8001
```

未配置 OAuth 时，HTTP 服务只能监听 loopback。公网部署必须配置 OAuth 2.1、HTTPS 和受保护资源元数据。

## Agent 架构

### Todo-driven Plan-Execute-ReAct

外层使用 Plan-Execute 管理长流程：

```text
Plan -> Todo DAG -> Execute -> Reflect/Replan -> Finalize
```

局部异常通过 ReAct 处理：

```text
Reason -> Tool Call -> Observation -> Decision
```

当工具和参数已经由 Planner 明确确定时，Runtime 不会重复调用 LLM 再做一次相同选择；只有参数缺失、工具结果异常、需要修复或改变路径时，才触发局部 ReAct。这兼顾了 Agent 决策能力、调用成本和行为稳定性。

### 中心调度式 Multi-Agent

Main Agent 拥有全局状态、Todo DAG 和最终决策权。领域任务被委派给 Specialist：

| Specialist | 职责 |
|---|---|
| CodegenSpecialist | 生成或修复 HLS Candidate |
| HLS4MLSpecialist | 模型检查、配置与可选 hls4ml 转换 |
| VivadoSpecialist | CSim、CSynth、日志及报告解析 |
| VerificationSpecialist | Golden Testbench、参考输出比对和验证状态 |
| OptimizationSpecialist | 根据目标、报告和历史经验提出优化建议 |
| MemorySpecialist | 抽取有证据的经验并写入长期记忆 |

Main Agent 为每次委派构建受 Token Budget 限制的 `ContextEnvelope`。Specialist 只能看到当前任务所需的摘要、Artifact 引用、相关经验和允许工具，不能读取完整 AgentState，也不能越过 Tool Registry。

### Skill、Tool 与 MCP

- Skill 描述某类任务“应该如何做”，包含触发条件、步骤、允许工具和成功标准。
- Tool 执行一个原子动作，例如生成候选、运行 CSim 或解析报告。
- MCP 标准化进程间的工具发现和调用，不负责 Planner、Memory 或 Agent 决策。
- Tool Registry 是统一网关，负责 Schema、权限、重试、缓存、预算、Trace 和证据后置条件。

## 长任务与恢复

三个机制分别工作在不同层次：

- SQLite WAL：可靠存储底座，改善并发读写与崩溃恢复。
- Durable Queue：管理任务领取、租约、去重、重试和完成提交。
- Incremental Checkpoint：在 Planner 和 Todo 边界保存 AgentState、Todo、预算和证据状态。

进程中断后，Agent 从最近有效 Checkpoint 恢复未完成 Todo；这不表示能从 Vivado 进程内部的某个综合百分比继续，而是避免重新执行已经有有效证据的前置阶段。

## 经验复用

SQLite 是 source of truth，RAG 是检索层。只有具备相应真实证据的实现、失败和优化经验才能进入高置信长期记忆。

检索链路为：

```text
任务域过滤
  -> BM25 + Embedding 召回
  -> RRF 融合
  -> Cross-Encoder 精排
  -> 证据门禁与来源去重
  -> Top-K 经验摘要
```

累计语料包含 16,062 个历史片段和对应 Embedding。方法级真实经验评测包含 105 条 leave-one-source-out 查询；在生产检索配置下取得 `Hit@5=92.38%`、`MRR=90.48%`、`Recall@5=11.82%`。Recall 较低的主要原因是每条方法查询可能对应大量相关历史来源，而 Top-5 最多返回 5 条；因此 Hit 与 MRR 更适合衡量运行时是否及时找到可用经验。该数据集属于单人规则化弱标注，不等同于独立双人标注的开放域 Gold Set。

## 上下文管理

- Main Agent 只维护全局摘要、Todo、关键决策和结构化结果。
- Specialist 通过 ContextEnvelope 接收裁剪后的局部上下文。
- 原始日志、报告和 HLS C++ 作为 Artifact 保存，不直接注入 LLM。
- 历史经验按任务域和 Top-K 检索，不加载完整 Memory DB。
- Workspace 使用增量文件清单、符号索引和按需行读取。

在配对上下文消融实验中，真实 API Prompt Token 中位数由 `53,078` 降至 `24,269`，减少 `54.28%`。该指标衡量发送给模型的 Prompt Token，不等价于离线 Envelope 字节压缩率；实验没有证明墙钟时间稳定下降。

## 证据与可观测性

每次运行会生成：

```text
runs/<run_id>/
  state.json
  todos.json
  trace.jsonl
  artifacts.json
  report.json
  summary.md
  suggestions.md
  memory/
  specialists/
```

Trace 记录 Planner、Todo 状态迁移、Specialist 路由、Decision Ledger、工具调用、Artifact、Evidence Receipt 和结构化异常。它用于还原执行链路；Session Runtime 使用 Checkpoint 实际执行恢复。

## 示例与演示

| 示例 | 输入 | 主要展示内容 |
|---|---|---|
| `dense_operator.json` | Dense 算子 | LLM Candidate、Golden CSim、CSynth 闭环 |
| `matmul_resource.json` | MatMul 算子 | 资源目标与复用权衡 |
| `mnist_mlp_hls4ml.json` | ONNX MLP | 模型输入与可选 hls4ml 路径 |
| `mnist_tiny_cnn.json` | 小型 CNN | Conv/Pool 模型边界 |
| `mnist_qonnx_cnn.json` | Torch/QONNX | FPGA-aware 量化模型输入 |
| `tiny_residual_block.json` | Residual Block | Rewrite 与能力边界 |
| `resnet18_boundary.json` | ResNet18 边界 | 安全拒绝而不是盲目承诺 |
| `mnist_recognition_mlp.json` | 训练权重 MNIST | Python/ONNX 与 HLS 识别结果比对 |

查看结果：

```powershell
dl-op-to-hls report runs\<run_id>
dl-op-to-hls suggest runs\<run_id>
dl-op-to-hls rag-search "Dense reuse factor DSP"
dl-op-to-hls session-list
dl-op-to-hls specialists-list
```

## 测试与评测

```powershell
python -m pytest -q
```

当前测试覆盖 Tool Registry、Permission Gate、Todo/Replan、Specialist、MCP stdio/HTTP、Context、Memory/RAG、Candidate Sandbox、功能验证、报告解析、会话恢复和 Bad Case。Mock、Fixture、Real CSim、Real CSynth 与真实 LLM 证据分开统计。

常用评测入口：

```powershell
dl-op-to-hls experience-content-benchmark --output runs\benchmarks\experience_content.json
dl-op-to-hls bad-case-benchmark --output runs\benchmarks\bad_case.json
```

详细指标口径见：

- [仓库结构与代码导览](docs/repository_guide.md)
- [Agent 架构](docs/mature_llm_agent_architecture.md)
- [MCP 设计](docs/mcp_tools.md)
- [Benchmark 指标](docs/benchmark_metrics.md)
- [上下文消融](docs/context_ablation_final_report.md)
- [RAG 设计](docs/rag_design.md)
- [交互式 CLI](docs/interactive_chat.md)

## 项目边界与后续工作

- 当前 LLM-first Conv2D 只支持有限的静态图契约，不是完整 ONNX Compiler。
- 真实综合依赖本地 Vivado/Vitis 安装、License 和目标器件支持。
- Golden CSim 证明当前测试向量下的功能一致性，不等于对任意输入完成形式化验证。
- `deployment_ready_candidate` 表示具备继续进入 RTL/部署验证的候选，不表示已经生成 bitstream 或完成上板。
- MCP Tasks 目前仍属于实验能力，长任务暂由项目的 Durable Queue 和 Checkpoint 管理。
- 下一阶段重点是扩大独立人工标注评测、增加更多真实模型验证，并接入 bitstream 与上板测试链路。

## License

本仓库用于学习、研究和工程能力展示。使用 AMD/Xilinx、模型与数据集相关组件时，请遵循各自许可证。
