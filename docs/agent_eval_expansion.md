# Agent 评测集扩充说明

## 结论

当前仓库的评测资产已经覆盖了较完整的 Agent Harness 组件，但“开放任务泛化”仍偏小：原始套件只有 10 条固定单轮提示词，历史真实 HLS cohort 有 22 次运行。它们适合做回归和面试展示，不足以单独证明模型在新表达、边界条件、提示注入、工具证据和多轮会话上的泛化能力。

本次新增 `benchmarks/agent_interview_open_tasks_v2.json`，包含：

- `dev`：原有 10 条人工编写样例，用于开发期回归。
- `test_semantic_variation`：20 条人工编写的语义变体，覆盖改写、目标歧义、旧报告污染、提前停止、unsupported honesty、提示注入和证据边界。
- 每条变体带 `source_case_id`、`case_family`、`mutation_tags`，因此报告可以按任务族聚合，避免把 30 条样例错误地当成 30 个独立任务族。

生成命令：

```text
dl-op-to-hls generate-agent-eval-suite
```

用新套件运行真实 LLM 规划评测：

```text
dl-op-to-hls agent-interview-benchmark --run-open-llm --open-task-suite benchmarks/agent_interview_open_tasks_v2.json
```

本次检查曾实际发起 30 条 v2 运行，但服务端返回 HTTP 402 `Insufficient Balance`，因此 30 条均未完成第一次 LLM 调用（`llm_calls=0`、`tokens=0`）。这批结果属于运行前配置/额度失败，已经从模型能力统计中排除，不能解释为 0% 成功率。

该命令只评估自然语言理解、技能选择和受保护计划，不会把“计划成功”冒充为 HLS 执行成功。完整报告仍会同时读取冻结的真实运行 cohort、RAG 消融、guard 消融和恢复探针。

## 当前已经跑过的评测

### 真实 Agent/HLS cohort

当前冻结报告中的 22 次真实运行用于检查路径选择、工具链证据、任务完成、trace/artifact 完整性、repair、RAG 污染、运行时和 token 成本。报告显示任务成功率约 90.91%，工具链选择准确率约 86.36%，false success 为 0；但 unsupported honesty 的有效样本不足，不能把该项的漂亮结果当作稳定结论。

### 开放任务 LLM 规划

原始 10 条固定任务已经用真实模型跑过。它主要测 task interpreter、schema repair、skill 选择和拒绝边界，不测完整 HLS 执行。10 条样例的统计区间很宽，且同一套 fixed suite 的 before/after 只能证明回归修复，不能证明总体泛化。

### RAG

固定小语料的 RAG 对比、历史经验 leave-one-run-out、生产语料噪声、hard-negative reranker 校准都已有结果文件。固定 12 文档/9 查询语料适合 smoke test；历史语料更接近生产，但标签来自 verified run metadata 的弱监督，不等价于人工独立相关性标注。

### Harness 机制

已有 context ablation、guard ablation、恢复/幂等探针、bad-case、operator negative cases、ONNX graph cases、template-vs-LLM 对照，以及持久化 trace、权限、canary、SLO 和 feedback quarantine 相关检查。它们更像组件与治理评测，不应和任务 success rate 混成一个数字。

## 建议的正式报告分层

1. **Regression**：10 条 `dev` 基线，每次代码改动都跑。
2. **Robustness**：20 条 `test_semantic_variation`，按 `case_family` 做 family-level bootstrap 或 leave-one-family-out，不能直接按 30 条独立 Bernoulli 样本计算置信区间。
3. **Execution**：真实 MNIST 主路径、真实 CSim/CSynth 和 operator negative cases，单独报告 toolchain evidence 与 artifact completeness。
4. **Retrieval**：固定小语料 smoke、历史 leave-one-run-out、生产噪声集和 hard-negative reranker，分别报告 Precision@K、Recall@K、MRR、nDCG、pollution rate。
5. **Governance**：unsupported honesty、false success、repair、early-stop、tool permission、duplicate/idempotency、trace completeness。
6. **Efficiency**：p50/p95 wall time、tool calls/run、LLM calls/run、input/output/total tokens/run，并按成功与失败分桶。

## 仍然需要补充的真实评测

- **多轮会话集**：同一任务拆成“初始要求 -> 追加约束 -> 撤回约束 -> 中断 -> 恢复”，验证 plan revision、checkpoint、rollback 和旧计划失效。
- **工具状态依赖集**：要求先获取 artifact id，再解析报告；先完成 approval，再执行写操作；重试同一个 idempotency key；模拟 timeout、stale report 和部分提交。
- **人工 RAG relevance 集**：至少 50 个 query，每个 query 标注 1 个正例、2 个 hard negative，并保留 query intent、source freshness 和 evidence level。现有自动标签要作为弱监督，不要冒充人工金标准。
- **独立模型/温度重复**：同一 family 的提示词不变，跨多个 seed 或重复运行，报告 family-level pass@1、pass@k、方差和成本；否则容易把一次偶然成功误认为能力。
- **线上回放集**：脱敏保存真实失败任务、工具错误和用户修订，但反馈必须先经过 quarantine 与人工确认，不能直接回灌 RAG。

## 可借鉴的公开评测范式

- [τ-bench](https://github.com/sierra-research/tau-bench)：模拟用户、领域 API 工具和策略约束，适合借鉴多轮工具调用、业务规则遵守和状态一致性的设计。
- [Apple ToolSandbox](https://github.com/apple/ToolSandbox)：强调有状态工具交互、状态依赖、参数规范化和信息不足时不能臆造，和本项目的工具证据门禁很接近。
- [AgentBench](https://github.com/THUDM/AgentBench)：多环境 Agent 能力评测，适合在 HLS 域内完成稳定性后做横向扩展，不适合作为 HLS 专项指标的替代物。
- [GAIA](https://huggingface.co/gaia-benchmark)：面向通用助手的文件、网页和代码综合任务，可作为通用 Agent 泛化的补充集，但不能替代 HLS toolchain、RAG evidence 和 unsupported honesty 评测。

公开集应当借鉴协议和 failure taxonomy，而不是直接拿总分替代领域评测。对当前项目最有价值的扩充顺序是：先把 `v2` 开放任务真实跑完，再补多轮会话/工具状态依赖集，最后扩大人工标注的 HLS RAG hard-negative 集。
