# DL-Operator-to-HLS Agent 面试梳理报告

## 1. 项目一句话

这个项目不是单纯的 HLS 脚本集合，而是一个面向深度学习算子/模型到 HLS 工程转换的 LLM Agent Harness：它把任务理解、路径选择、工具调用、专家协作、RAG 经验召回、错误恢复、工件追踪和评测指标串成一条可审计的自动化流水线。

面试表达可以压缩为：

> 我把一个传统 DL-to-HLS 工具链，改造成了可评测的 Agent 系统。它不是只跑 hls4ml，而是会先判断任务属于 `hls4ml_path`、`fallback_template_path`、`existing_project_path`、`unsupported_path` 或 `llm_candidate_path`，再通过受权限约束的工具注册表执行，并用 trace、artifact manifest、specialist result 和 benchmark harness 证明 Agent 是否真的做对了。

## 2. 面试主线

建议用这条线讲项目：

1. 传统工具链问题：脚本能跑，但缺少任务分流、失败恢复、证据链、长期经验和统一评测。
2. Agent 化改造目标：让系统能规划、选路、调用工具、观察结果、修复错误、记录过程。
3. 核心架构：`MainAgent` + runtime + todo + specialists + tool registry + memory/RAG + artifacts/trace。
4. 关键难点：HLS 工具链不稳定、模型支持边界复杂、LLM 可能幻觉、评测不能只看硬件指标。
5. 评测重点：Agent 指标，包括路径选择准确率、任务成功率、unsupported 诚实率、repair 成功率、trace 完整度、RAG 命中/污染率、latency/cost。
6. 面试亮点：这套工程展示的是互联网大厂 Agent 岗位关心的 Harness 设计，而不只是 FPGA/HLS 专项能力。

## 3. 代码地图

| 层次 | 关键文件 | 作用 |
| --- | --- | --- |
| Agent 入口 | `src/dl_op_to_hls/main_agent/agent.py` | `MainAgent` 外部入口，加载配置、工具、runtime。 |
| 传统 Plan-Execute-ReAct runtime | `src/dl_op_to_hls/main_agent/runtime.py` | 初始化状态、规划 todo、执行工具/专家、最终汇总。 |
| LLM-first runtime | `src/dl_op_to_hls/main_agent/llm_runtime.py` | 由 LLM 生成 plan/todo/replan，并通过 guard 修正不安全或无效决策。 |
| 状态模型 | `src/dl_op_to_hls/main_agent/state.py` | 保存 run 的 plan、todo、path、artifacts、errors、memory、LLM decisions。 |
| Todo 模型 | `src/dl_op_to_hls/main_agent/todo.py` | 定义 todo 状态、依赖和 specialist/tool 输入输出。 |
| 工具注册 | `src/dl_op_to_hls/core/tool_registry.py` | 统一工具调用、权限检查、trace 事件、失败封装。 |
| 权限控制 | `src/dl_op_to_hls/core/permissions.py` | 控制路径、命令和工具参数，避免 Agent 任意读写或执行。 |
| 工件管理 | `src/dl_op_to_hls/core/artifacts.py` | 注册文件、sha256、manifest，并写入 trace。 |
| Trace | `src/dl_op_to_hls/core/trace.py` | JSONL 事件流，形成可审计执行证据。 |
| Specialist 上下文 | `src/dl_op_to_hls/specialists/context.py` | 构造 scoped context，限制专家可见信息和工具列表。 |
| Specialist 路由 | `src/dl_op_to_hls/specialists/router.py` | 根据 todo 指定或能力匹配路由专家。 |
| HLS4ML 适配 | `src/dl_op_to_hls/adapters/hls4ml_adapter.py` | 检查模型支持、生成 config、转换、csim。 |
| Vivado 适配 | `src/dl_op_to_hls/adapters/vivado_hls_adapter.py` | 创建工程、csim/csynth、解析报告和日志。 |
| Candidate 沙箱 | `src/dl_op_to_hls/core/candidate_sandbox.py` | 扫描 LLM 生成代码，禁止危险调用和明显不合规接口。 |
| Memory/RAG | `src/dl_op_to_hls/memory/*`, `src/dl_op_to_hls/rag/*` | 存储经验、召回案例、控制 failure memory 污染。 |
| 评测 Harness | `src/dl_op_to_hls/benchmarks/agent_quality_benchmark.py` | 计算 Agent 指标、RAG 指标、LLM harness 指标。 |

## 4. 架构分层

项目可以分为五层：

1. **任务解释层**：把自然语言或结构化任务转成 objective、constraints、expected path。
2. **Agent runtime 层**：负责规划、todo 执行、失败 replan、最终总结。
3. **专家协作层**：HLS4ML、Vivado、Verification、Optimization、Memory 等 specialist 分工。
4. **工具链适配层**：对接 hls4ml、Vivado/Vitis、fallback template、LLM candidate、报告解析。
5. **证据与评测层**：trace、artifact、benchmark、RAG evidence、latency/cost 指标。

这个分层的价值是：面试官如果问「你到底做了 Agent 什么」，可以明确回答不是把 prompt 包在脚本外面，而是实现了可控工具调用、上下文隔离、错误恢复和可量化评测。

## 5. MainAgent 和 Runtime

`MainAgent` 是外部入口，负责配置和 runtime 选择。更重要的逻辑在 runtime：

- `PlanExecuteReactRuntime`：偏确定性，适合已有工具链和 mock/real 混合评测。
- `LLMFirstRuntime`：偏 Agent 岗位展示，LLM 先生成 plan/todo，再经过 schema、guard、tool allowlist 和 repair 约束。

runtime 的典型流程：

1. 初始化 `AgentState`，创建 run id、artifact manager、trace writer。
2. 召回初始 memory/RAG。
3. 生成 plan 和 todo。
4. 按依赖执行 todo。
5. 对工具失败、报告缺失、LLM candidate 失败等场景进行 repair/replan。
6. 写 summary、artifact manifest、trace，并返回最终状态。

可强调的工程点：

- 不是让 LLM 自由发挥，而是把它放在 schema、permission、tool allowlist 和 trace 之内。
- `AgentState` 是单 run 的事实来源，trace 是执行证据，artifact manifest 是文件证据。
- LLM-first 与传统 runtime 并存，可以做 A/B 和消融对比。

## 6. 路径选择逻辑

Agent 需要选择的不是硬件参数，而是任务路径：

| Path | 典型任务 | 成功标准 |
| --- | --- | --- |
| `hls4ml_path` | MNIST MLP/CNN 这类当前真实跑通的模型转换 | 生成 config、转换 HLS project、至少完成可用的报告/工件。 |
| `fallback_template_path` | Dense、matmul、relu、add 等可模板化算子 | 选择正确 template，生成 HLS 代码、testbench、报告。 |
| `existing_project_path` | 用户已有 HLS 工程，需要解析/综合/恢复 | 不重新发明工程，优先复用现有 project 并解析报告。 |
| `unsupported_path` | ResNet18、复杂残差、未支持模型/算子 | 诚实返回 `partial_success` 或 `unsupported`，不能伪造 latency/resource。 |
| `llm_candidate_path` | 可让 LLM 生成候选 HLS kernel 的小算子 | 通过 sandbox、csim/report，失败后能 repair 或降级。 |

面试回答要点：

- Path selection 是 Agent 指标，不是 HLS 指标。
- 对 unsupported 的诚实比「强行成功」更重要，因为 Agent 不能伪造工具链结果。
- 当前真实主线以 MNIST 为主，这是合理的：评测要围绕真实跑通链路，再用 mock/negative case 覆盖边界。

## 7. Specialist 设计

Specialist 不是为了概念复杂化，而是为了解决两个问题：

1. 不同任务需要不同上下文，例如 HLS4ML 不需要看到完整 Vivado 日志。
2. 不同专家只能调用不同工具，降低 LLM 越权和幻觉工具调用概率。

| Specialist | 职责 | 典型工具 |
| --- | --- | --- |
| `HLS4MLSpecialist` | 模型检查、config、转换、csim | `hls4ml.inspect_model`, `hls4ml.check_support`, `hls4ml.convert` |
| `VivadoSpecialist` | HLS 工程创建、csim/csynth、报告解析 | `vivado.create_project`, `vivado.run_csim`, `vivado.parse_report` |
| `VerificationSpecialist` | testbench、候选验证、unsupported report | `fallback.generate_testbench`, `verify_candidate.run`, `report.write_unsupported` |
| `OptimizationSpecialist` | 召回经验、参数建议、优化建议 | `rag.retrieve_experience`, `suggestion.suggest_optimization` |
| `MemorySpecialist` | 经验抽取、压缩、保存、索引 | `memory.extract_candidates`, `memory.save`, `rag.index` |

`ContextEnvelope` 是 specialist 协作的关键结构，它包含 run/todo 信息、scoped state、artifact refs、retrieved memory refs、constraints、allowed tools 和 token budget。这个设计可以转化为面试语言：

> 我没有把全局状态原样塞给每个专家，而是给每个 specialist 构造最小必要上下文，同时用 allowed_tools 限制它能做什么，这样既省 token，又降低越权和错误工具调用。

## 8. Tool Registry 与权限

`ToolRegistry.call()` 是 Agent 执行外部动作的入口。它做几件关键事：

- 检查工具是否注册。
- 调用 `PermissionGate` 验证路径、命令和工具参数。
- 发出 `PreToolUse`、`PostToolUse`、`ToolFailed` trace 事件。
- 捕获异常并转为结构化失败。
- 对输入输出做 hash，方便审计但避免 trace 过大。

这部分非常适合回答 Agent 安全问题：

> 我把 LLM 和外部世界之间的边界放在 ToolRegistry 和 PermissionGate。LLM 只能产生意图，真正落地必须经过注册工具、路径白名单和 trace 记录。

## 9. Trace、Artifact、Error

这三者构成可审计闭环：

| 组件 | 解决的问题 |
| --- | --- |
| Trace | 证明每一步发生了什么，包括 plan、todo、tool call、specialist result、error stage、summary。 |
| Artifact | 证明产物是什么，包括路径、类型、sha256、manifest。 |
| Structured Error | 证明失败在哪里，而不是只返回一段日志。 |

错误类型覆盖：

- 任务/支持边界：`InvalidTaskError`, `UnsupportedOperatorError`
- hls4ml：`HLS4MLNotInstalledError`, `HLS4MLConversionError`
- Vivado：`VivadoNotFoundError`, `VivadoSynthesisError`
- 报告：`ReportMissingError`, `ReportParseError`
- 安全：`PermissionDeniedError`
- RAG/DB/LLM：`RagIndexError`, `DatabaseError`, `LLMGenerationError`
- 验证：`VerificationFailedError`

面试要点：结构化错误是 repair/replan 的前提。没有错误 stage，Agent 只能「重新试一次」；有错误 stage，才能定向修复。

## 10. Memory 与 RAG

Memory/RAG 的设计目标不是「塞更多上下文」，而是「召回相关 HLS case，避免污染当前任务」。

关键机制：

- 按 domain 索引：optimization、parameter、failure、episodic 等。
- token overlap、anchor、strong anchor 混合打分。
- failure memory gated retrieval：只有 query 明确像失败恢复任务时，才召回 failure case。
- RAG benchmark 统计 hit rate、precision、recall、MRR、NDCG、pollution rate。

面试可讲：

> 我把 RAG 当成 Agent 决策证据，而不是 prompt 填充物。评测时不只看有没有召回，还看有没有把不相关经验污染进当前任务。

## 11. LLM Candidate 与 Guard

`llm_candidate_path` 用于小算子候选生成。风险点是 LLM 可能写出危险代码、错误接口、伪造报告或无法综合。项目用几层防护：

1. candidate sandbox 扫描 OS/process/file/network/asm 等危险模式。
2. 检查 HLS 接口契约，例如非字节对齐 `m_axi`、过大的 mutable complete partition。
3. 工具执行必须走 registry 和 permission。
4. 如果 candidate、csim 或报告失败，runtime 会 repair/replan。
5. 如果无法证明成功，降级为 unsupported/partial，不伪造硬件结果。

这个点适合互联网 Agent 岗位：

> LLM 生成不是终点，验证和失败恢复才是 harness 的核心。

## 12. 评测 Harness

评测重点已经从硬件结果转成 Agent 行为：

| 指标 | 含义 |
| --- | --- |
| Tool/path selection accuracy | 是否选对 `fallback_template_path`、`hls4ml_path`、`existing_project_path`、`unsupported_path`、`llm_candidate_path`，并调用正确工具链。 |
| Task success rate | 按 operator_fallback、model_hls4ml、unsupported_recovery、toolchain_recovery、llm_candidate 分桶统计成功率。 |
| Unsupported honesty rate | 不支持模型/算子是否诚实标为 partial/unsupported，是否避免伪造 latency/resource/verification。 |
| Repair success rate | csim、转换、报告解析、LLM candidate 失败后是否能 repair/replan。 |
| Trace completeness | 每个 run 是否有 plan、todo、tool call、specialist result、artifact、error stage、summary。 |
| RAG evidence hit/pollution | 是否召回相关 HLS case，是否混入不相关经验。 |
| Latency/cost | p50/p95 runtime、tool calls/run、LLM calls/run、tokens/run。 |

当前 LLM harness 的最新修复版报告位于：

- `runs/benchmarks/llm_agent_harness_eval_fixed_20260706_131346.md`
- `runs/benchmarks/llm_agent_harness_eval_fixed_20260706_131346.json`

报告显示 6 个 LLM-first case 全部通过，其中 4 个 success、2 个 partial_success。需要注意：分数高不代表系统已经覆盖真实复杂 HLS 全域，而是说明当前 suite 的 contract 测试通过。面试时要主动说明这个限制，反而更可信。

## 13. 为什么之前指标看起来太好

原因主要有三类：

1. **样例偏 contract 化**：很多 case 验证的是 Agent 是否走对路径、是否有 trace/artifact，而不是真实硬件 Pareto 最优。
2. **MNIST 是当前真实闭环主线**：真实跑通模型主要是 MNIST，因此 hls4ml case 天然更稳定。
3. **负例数量有限**：unsupported、candidate failure、toolchain missing 等有覆盖，但还不够接近工业长尾。

补充方向：

- 增加 LLM plan 被拒、JSON repair、多轮 replan 的 case。
- 增加近似相似但应选不同 path 的 hard negative。
- 增加 RAG 污染样例，例如 CIFAR 经验误召回到 MNIST，Vivado failure 误召回到 hls4ml config。
- 增加 fake-report trap，检查 Agent 是否拒绝伪造 latency/resource。
- 增加 timeout、missing artifact、partial trace case。

## 14. 代表性 Bug 复盘

| # | 问题 | 根因 | 修复/经验 |
| --- | --- | --- | --- |
| 1 | LLM candidate repair 后仍失败 | unsupported recovery todo 没有被正确转成报告写入流程 | 在 LLM runtime 中加入 unsupported recovery todo coercion。 |
| 2 | Verification specialist 无法写 unsupported report | tool allowlist 缺少 `report.write_unsupported` | 补齐 skill allowlist，避免专家想做但无权限。 |
| 3 | LLM 计划 JSON 不稳定 | LLM 输出可能有格式噪声 | 加 schema validation 和 JSON repair 指标。 |
| 4 | 指标过高 | suite 偏简单且 deterministic mock 多 | 增加 LLM-first hard cases 和负例说明。 |
| 5 | unsupported 可能被误判 success | 只看 summary 容易误导 | 增加 unsupported honesty rate 和 fake metric 检查。 |
| 6 | RAG 可能污染当前任务 | failure memory 与普通优化经验混召回 | failure-query gating 和 pollution benchmark。 |
| 7 | trace 过大 | 全量日志写入上下文/trace | 使用 hash、artifact ref 和 scoped context。 |
| 8 | specialist 越权调用工具 | 只靠 prompt 约束不可靠 | BaseSpecialist 强制检查 envelope 和 specialist allowlist。 |
| 9 | 已有工程被错误重建 | path selection 没区分 existing_project | 增加 existing project case 和 path accuracy。 |
| 10 | 报告缺失时无法定位 | 异常只有字符串 | 引入 `ReportMissingError`、error stage 和 repair 指标。 |
| 11 | hls4ml 不支持复杂模型时幻觉成功 | LLM 容易补充看似合理数字 | unsupported report 要求不生成 latency/resource/verification 假结果。 |
| 12 | candidate 代码安全风险 | LLM 可生成系统调用或文件访问 | CandidateSandbox 做静态扫描与接口契约检查。 |
| 13 | 工具链缺失导致整 run 失败 | Vivado/hls4ml 环境不稳定 | 用 recovery path 返回可解释 partial_success。 |
| 14 | todo 依赖状态过硬 | warning/skipped 可能阻断后续合理流程 | Todo dependency OK 集合区分 done/warning/skipped。 |
| 15 | benchmark 只看硬件指标 | 不适合 Agent 岗位展示 | 转为 Agent harness 指标，保留 latency/cost 作为运行成本。 |

## 15. 可用于简历的表述

可以写成：

> 设计并实现 DL Operator-to-HLS 的 LLM Agent Harness，支持 hls4ml、fallback template、existing project、unsupported recovery 与 LLM candidate 多路径调度；通过 ToolRegistry/PermissionGate 实现受控工具调用，通过 specialist scoped context 降低 token 与越权风险，通过 trace/artifact manifest/structured error 构建可审计执行链路；构建 Agent 质量评测集，覆盖路径选择准确率、unsupported honesty、repair success、trace completeness、RAG hit/pollution、latency/cost 等指标。

如果要更贴互联网 Agent：

> 将传统 EDA/HLS 脚本改造成可评测的 LLM Agent 系统，重点解决 plan validation、tool use safety、multi-step repair、RAG evidence control 与 benchmark harness 设计问题。

## 16. 风险与不足

需要主动承认：

- 真实完整跑通链路目前以 MNIST 为主，复杂 CNN/ResNet 更多是 boundary/unsupported/honesty case。
- hls4ml/Vivado 的真实环境依赖强，部分 case 使用 mock 或 contract evaluation。
- 当前指标高说明 harness contract 工作良好，不等价于工业级全模型支持。
- LLM candidate 适合小算子探索，不应承诺自动生成复杂神经网络 HLS 工程。
- RAG 已有 hit/pollution 指标，但还可以继续扩展更强的 hard negative set。

这种坦诚不减分，反而说明你知道 Agent 评测与 demo 的边界。

## 17. 面试收束话术

推荐收束：

> 这个项目最有价值的地方不是我手写了几个 HLS 模板，而是我把一个传统工程工具链拆成了 Agent 可以安全操作、可以失败恢复、可以被评测的系统。大厂 Agent 岗位通常不只关心模型能不能回答，而是关心它怎么规划、怎么调用工具、怎么防幻觉、怎么从失败中恢复、怎么证明自己做过什么。这个项目正好围绕这些问题做了工程化实现和 benchmark。
