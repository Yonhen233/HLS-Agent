# 仓库结构与代码导览

本文是面向代码阅读、面试讲解和后续维护的仓库地图。项目的主线不是“调用一个转换脚本”，而是一个带有状态、规划、工具治理、Specialist 隔离、证据门禁和可恢复执行能力的 HLS Agent Harness。

## 1. 先看什么

建议按下面顺序阅读：

1. `README.md`：从用户角度理解项目边界、运行方式和真实工具链。
2. `src/dl_op_to_hls/cli.py`：命令行入口，展示用户请求如何进入系统。
3. `src/dl_op_to_hls/main_agent/agent.py` 和 `main_agent/runtime.py`：Main Agent 如何规划、调度和恢复任务。
4. `src/dl_op_to_hls/core/tool_registry.py`、`core/permissions.py`、`core/trace.py`：工具网关、权限和可观测性。
5. `src/dl_op_to_hls/specialists/`：局部上下文隔离和领域执行。
6. `src/dl_op_to_hls/adapters/`、`mcp/`：真实 hls4ml/Vivado 工具与 MCP 的接入边界。
7. `src/dl_op_to_hls/core/tool_evidence.py`、`core/release_governance.py`、`tools/functional_verification.py`：为什么 Agent 不能仅凭 LLM 文本宣布成功。
8. `tests/`：从单元测试、契约测试到真实工具探针的验证方式。

## 2. 运行主链路

```text
CLI / Chat
  -> Task Interpreter / Planner
  -> AgentState + Todo DAG
  -> Main Agent Runtime
  -> SpecialistRouter
  -> ContextEnvelope
  -> Specialist local ReAct 或 atomic Tool
  -> ToolRegistry / PermissionGate / MCP Proxy
  -> Artifact + Trace + SQLite
  -> CSim / CSynth / Report Parser
  -> Evidence Gate
  -> Finalizer / MemorySpecialist / RAG
```

`AgentState` 是一次运行的工作状态；`trace.jsonl` 是事实记录；SQLite 保存结构化元数据；artifact 保存原始报告、代码和日志；RAG 只承担检索，不替代数据库事实。

## 3. 顶层目录

| 路径 | 内容 | 面试讲解重点 |
|---|---|---|
| `src/dl_op_to_hls/` | 主 Python 包 | Agent Harness 的实现主体 |
| `src/dl_op_to_hls/core/` | 通用运行时基础设施 | 状态、权限、预算、Trace、证据、恢复 |
| `src/dl_op_to_hls/main_agent/` | Main Agent 编排器 | Plan-Execute-ReAct、Todo DAG、Replan |
| `src/dl_op_to_hls/specialists/` | Specialist 子 Agent | 上下文隔离、领域工具白名单、压缩返回 |
| `src/dl_op_to_hls/llm/` | LLM 客户端与协议 | Planner、ReAct、Reflector、结构化输出校验 |
| `src/dl_op_to_hls/mcp/` | MCP 客户端、代理、服务端 | stdio/Streamable HTTP、工具发现和转发 |
| `src/dl_op_to_hls/adapters/` | hls4ml、Vivado 和 LLM 适配器 | 外部工具隔离与真实命令调用 |
| `src/dl_op_to_hls/tools/` | 原子工具 | 代码生成、验证、报告解析、建议 |
| `src/dl_op_to_hls/memory/` | 分层记忆 | 短期记忆、长期经验、技能提炼 |
| `src/dl_op_to_hls/rag/` | RAG 索引和检索 | 结构化过滤、向量召回、RRF、精排 |
| `src/dl_op_to_hls/skills/` | Skill SDK | Skill schema、选择、策略和 prompt 上下文 |
| `src/dl_op_to_hls/db/` | SQLite 持久化 | 实验、工具调用、失败、记忆和队列元数据 |
| `src/dl_op_to_hls/schemas/` | 输入输出 schema | 任务、算子、模型、报告、工具契约 |
| `src/dl_op_to_hls/benchmarks/` | Agent 评测 | 成功率、恢复、上下文、RAG 和算子能力 |
| `examples/` | 用户可运行的任务描述 | Demo 输入，不把实验代码硬编码进 Agent |
| `scripts/` | 训练、模型导出和真实工具探针 | 离线准备和端到端验证 |
| `tests/` | 自动化验证 | 契约、回归、mock 和真实环境探针 |
| `docs/` | 面向用户和开发者的设计文档 | 架构、MCP、Memory、上下文和评测 |
| `docs/internal/` | 内部开发审计记录 | 历史问题、真实测试和修复证据 |
| `runs/` | 本地运行产物 | 默认忽略，不应提交到 Git |

## 4. 核心源码文件

### 4.1 `core/`：Harness 基础设施

| 文件 | 作用 |
|---|---|
| `agent_messages.py` | Main Agent、Specialist 和工具之间的结构化消息 |
| `artifacts.py` | artifact 注册、哈希和 manifest |
| `budgets.py` | 运行级时间、调用次数和 token 预算 |
| `candidate_sandbox.py` | LLM 生成 HLS C/C++ 的静态安全检查 |
| `config.py` | 工作区和运行配置加载 |
| `context.py` | 长日志和报告的结构化压缩 |
| `context_modes.py` | 上下文模式和发送策略 |
| `context_pack.py` | 将文件、摘要和引用打包成受控上下文 |
| `context_window.py` | token 估算、截断和窗口预算 |
| `credential_broker.py` | 统一读取和脱敏外部凭据 |
| `design_objectives.py` | performance/resource/latency/throughput 等目标定义 |
| `durable_queue.py` | 可恢复任务队列和长任务状态 |
| `errors.py` | 结构化错误类型和错误序列化 |
| `execution_sandbox.py` | 命令执行边界和进程管理 |
| `goal_contract.py` | 运行目标、完成条件和终止契约 |
| `hooks.py` | 生命周期 hook 分发 |
| `json_schema.py` | JSON 输入输出的校验辅助 |
| `memory_hygiene.py` | 记忆索引前的脱敏和内容清理 |
| `observability.py` | 运行指标、事件和调试观测 |
| `permissions.py` | 文件、命令和工具权限门禁 |
| `progress.py` | 长任务进度和阶段事件 |
| `release_governance.py` | 版本发布前的证据与质量检查 |
| `scheduler.py` | Todo 依赖和可执行项调度 |
| `sessions.py` | CLI 多轮会话持久化 |
| `token_budget.py` | token 估算和 API 预算控制 |
| `tool_evidence.py` | 工具输出的证据级别和完成门禁 |
| `tool_registry.py` | 全部本地工具的统一注册和调用入口 |
| `trace.py` | 唯一运行事实源 `trace.jsonl` |
| `trace_tools.py` | 对 Trace 的 bounded、权限约束查询 |
| `workspace_context.py` | 工作区文件清单、符号索引和增量读取 |

### 4.2 `main_agent/`：全局编排

| 文件 | 作用 |
|---|---|
| `agent.py` | Main Agent 外观、依赖组装和运行入口 |
| `executor.py` | 执行 Todo、调用 Specialist、合并结果 |
| `finalizer.py` | 生成 summary、suggestions 和最终状态 |
| `llm_runtime.py` | LLM-first runtime 的规划、反思和恢复 |
| `planner.py` | 将任务转成计划和 Todo DAG |
| `reflector.py` | 根据观察结果更新 Todo 和路径 |
| `runtime.py` | Plan-Execute-ReAct Hybrid 主循环 |
| `state.py` | AgentState 数据结构和 checkpoint 序列化 |
| `status.py` | conversion/synthesis/verification 等状态语义 |
| `todo.py` | TodoItem、依赖、状态迁移和历史 |
| `workflow.py` | 兼容的确定性工作流入口 |

### 4.3 `specialists/`：领域隔离

| 文件 | 作用 |
|---|---|
| `base.py` | Specialist 抽象接口和统一 guard |
| `context.py` | ContextEnvelope 和按 Specialist 裁剪上下文 |
| `result.py` | SpecialistResult 结构化返回 |
| `router.py` | 按 Todo、工具和 Skill 选择 Specialist |
| `react.py` | Specialist 局部 ReAct decision schema |
| `hls4ml_specialist.py` | 模型检查、配置和 hls4ml 转换 |
| `vivado_specialist.py` | Vivado HLS 工程、CSim、CSynth 和报告 |
| `verification_specialist.py` | Golden CSim、reference compare 和 candidate 验证 |
| `optimization_specialist.py` | 基于报告和经验生成优化建议 |
| `memory_specialist.py` | 短期上下文压缩、经验提炼和长期提升 |
| `codegen_specialist.py` | LLM HLS candidate 生成和 repair |

### 4.4 `llm/`：模型交互层

| 文件 | 作用 |
|---|---|
| `client.py` | OpenAI-compatible API 客户端和响应计量 |
| `config.py` | Base URL、模型、超时和限流配置 |
| `planner.py` | LLM Planner 输出 Todo/Skill 计划 |
| `react.py` | Main Agent ReAct action schema |
| `reflector.py` | 失败后的判断和 Replan |
| `optimizer.py` | LLM 优化决策入口 |
| `finalizer.py` | LLM 总结和结构化最终输出 |
| `candidate_generator.py` | 通用 candidate 生成协议 |
| `controller.py` | 多轮 LLM 控制循环 |
| `task_interpreter.py` | 自然语言到标准任务 |
| `actions.py` | Main Agent 合法 action 枚举 |
| `guards.py` | JSON repair、allowlist 和语义不变校验 |
| `schemas.py` | LLM 请求/响应 JSON schema |
| `prompts.py` | system prompt、few-shot 示例和约束 |
| `trace.py` | LLM 调用和 token 使用的 Trace 事件 |

### 4.5 `adapters/`、`mcp/` 和 `mcp_servers/`

| 文件 | 作用 |
|---|---|
| `adapters/hls4ml_adapter.py` | hls4ml 检测、配置、转换和 CSim 适配 |
| `adapters/vivado_hls_adapter.py` | Vivado HLS/Vitis HLS 命令、TCL、日志和报告 |
| `adapters/llm_adapter.py` | 统一 LLM candidate 适配接口 |
| `adapters/senior_agent_adapter.py` | 旧工程能力的隔离桥接，不直接复用旧脚本 |
| `adapters/legacy_vivado_env.py` | 旧 Vivado 环境的兼容封装 |
| `mcp/server.py` | 官方 MCP SDK Server、stdio 和 Streamable HTTP |
| `mcp/client.py` | supervised stdio JSON-RPC 客户端、进度和取消 |
| `mcp/proxy.py` | MCP 工具与本地 Tool Registry 的统一代理 |
| `mcp_servers/hls4ml_server.py` | hls4ml MCP 风格工具集合 |
| `mcp_servers/vivado_hls_server.py` | Vivado HLS MCP 风格工具集合 |

### 4.6 `tools/`、`memory/`、`rag/`、`skills/`、`db/` 和 `schemas/`

| 子目录 | 关键文件 | 作用 |
|---|---|---|
| `tools/` | `fallback_template.py`、`llm_candidate.py`、`verify_candidate.py` | 生成和验证 HLS 实现 |
| `tools/` | `functional_verification.py`、`report_parser.py` | CSim/reference compare 和综合报告解析 |
| `tools/` | `parameter_advisor.py`、`suggest_optimization.py` | 参数建议和优化建议 |
| `tools/` | `graph_rewrite.py`、`summarize.py` | 图改写和结果摘要 |
| `memory/` | `memory_manager.py`、`memory_policy.py` | 记忆写入、提升和证据策略 |
| `memory/` | `short_term.py`、`episodic_memory.py`、`semantic_memory.py` | L1/L2/L3 记忆实现 |
| `memory/` | `skills.py`、`memory_tools.py`、`feedback_governance.py` | Skills 和记忆工具 |
| `rag/` | `indexer.py`、`chunker.py`、`vector_index.py` | 经验切分和向量索引 |
| `rag/` | `retriever.py`、`semantic.py`、`calibration.py` | 结构化过滤、Embedding、RRF、Rerank 和校准 |
| `rag/` | `evidence.py`、`memory.py` | 经验证据和 RAG 记忆接口 |
| `skills/` | `schema.py`、`skill.py`、`registry.py` | Skill 定义与注册 |
| `skills/` | `selector.py`、`policy.py`、`prompt_context.py` | Skill 选择、权限和 prompt 组装 |
| `skills/` | `extractor.py`、`expander.py` | 从历史任务提炼和展开 Skill |
| `db/` | `database.py`、`repositories.py` | SQLite schema、事务和查询仓库 |
| `schemas/` | `task_schema.py`、`operator_schema.py`、`model_schema.py` | 输入任务和模型 schema |
| `schemas/` | `report_schema.py`、`hls_project_schema.py`、`tool_schema.py` | 工具、工程和报告 schema |

## 5. Benchmark、脚本和测试

### 5.1 Benchmark

`src/dl_op_to_hls/benchmarks/` 按评测对象分层：

- `agent_quality_benchmark.py`：端到端运行质量、工具链、状态、Trace、RAG 和证据门禁。
- `agent_interview_benchmark.py`：面试展示所需的恢复、上下文和编排指标。
- `operator_benchmark.py`、`operator_fair_comparison.py`：算子支持与 template/LLM 公平比较。
- `operator_case_generator.py`、`operator_onnx_cases.py`、`operator_suite_specs.py`：正例、反例和 ONNX 用例生成。
- `operator_evidence.py`、`operator_support.py`、`operator_bad_cases.py`：能力边界和证据判定。
- `context_ablation.py`、`context_ablation_aggregate.py`：上下文压缩和消融。
- `historical_rag_benchmark.py`、`experience_content_benchmark.py`、`design_experience_benchmark.py`：真实经验内容召回评测。
- `semantic_rag_benchmark.py`：Embedding/RRF/Rerank 检索评测。
- `bad_case_benchmark.py`、`maturity_benchmark.py`：失败案例与工程成熟度。

### 5.2 `scripts/`

训练和真实工具脚本按用途组织：`train_mnist_recognition_mlp.py`、`train_cifar10_tiny_vgg.py` 负责训练；`make_*_onnx.py` 和 `make_qkeras_mnist_cnn.py` 负责模型导出；`run_real_hls_probe.py`、`run_direct_candidate_csim.py` 和 `run_vitis_fairness_experiments.py` 负责真实 HLS 探针；其余脚本用于 FIFO 优化、架构筛选、结果可视化和演示材料。

### 5.3 `tests/`

测试文件采用“一个能力域一个文件”的组织方式：

- 基础设施：`test_tool_registry.py`、`test_permissions.py`、`test_hooks.py`、`test_trace.py`、`test_artifacts.py`、`test_state.py`、`test_structured_errors.py`。
- Agent runtime：`test_runtime_hybrid.py`、`test_scheduler.py`、`test_todo.py`、`test_session_runtime.py`、`test_sessions.py`、`test_main_agent.py`。
- LLM 契约：`test_llm_*`、`test_agent_messages.py`、`test_specialist_react.py`、`test_prompt_releases.py`。
- Specialist 与 Skill：`test_specialists.py`、`test_skill_*.py`。
- MCP 与真实工具：`test_mcp_transport.py`、`test_hls4ml_mcp.py`、`test_vivado_hls_mcp.py`、`test_real_hls_probe_cli.py`。
- HLS 生成与验证：`test_fallback_templates.py`、`test_candidate_sandbox.py`、`test_functional_verification.py`、`test_report_parser.py`、`test_operator_*.py`。
- Memory/RAG/上下文：`test_memory.py`、`test_memory_governance.py`、`test_rag.py`、`test_context_*.py`、`test_workspace_context.py`、`test_token_budget.py`。
- Demo 与 Benchmark：`test_demo_*.py`、`test_*benchmark.py`、`test_cifar*.py`。

## 6. 面试时的三条主线

1. **控制面**：Main Agent 通过 `AgentState`、Todo DAG、Skill allowlist 和 Replan 管理全局任务。
2. **执行面**：Specialist 只接收 `ContextEnvelope`，通过 `ToolRegistry` 调用有限工具；MCP 负责把外部 HLS 工具变成可发现、可校验、可追踪的工具。
3. **证据面**：原始报告留在 artifact，结构化结果进入 State；只有 Golden CSim、CSynth report、错误和 Trace 等证据满足门禁时，结果才可提升为 verified memory。

## 7. 文档和代码规范

- 每个 Python 文件顶部都有模块 docstring，说明职责、上下游和边界。
- 每个类、函数和方法都有 docstring；内部辅助函数说明其输入、输出和不应承担的职责。
- 代码注释解释“为什么”而不是重复“做了什么”。
- 代码逻辑以 `ToolRegistry`、`PermissionGate`、`Trace` 和 schema 为边界，避免 Specialist 或 LLM 直接修改全局状态。
- 真实 Vivado、hls4ml 和外部 API 结果必须落到 `runs/`，不把本机路径、密钥和大型产物写进源码。
