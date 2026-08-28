# Agent 面试量化 Benchmark

本报告从 Agent 工程能力而非单纯 HLS 指标出发，统一评估真实运行成功率、开放任务理解与规划、RAG、Guard、上下文隔离、恢复/幂等和运行成本。机器可读结果位于 `benchmarks/agent_interview_results.json`，固定题集和语料分别位于 `benchmarks/agent_interview_open_tasks.json` 与 `benchmarks/agent_interview_rag_corpus.json`。

## 最终结果

| 指标 | 结果 | 证据类型 |
|---|---:|---|
| 历史真实 Run 成功率 | 20/22，90.91% | 22 个冻结的真实 HLS Run |
| 工具链/路径选择准确率 | 19/22，86.36% | 冻结 Run 的 State、Trace、Artifact |
| False-success rate | 0% | completion gate 与真实证据审计 |
| Trace / Artifact 完整度 | 100% / 100% | 冻结 Run 文件检查 |
| 开放任务理解与规划 | 10/10 | 真实 `deepseek-v4-pro`，固定题集、单次采样 |
| 开放任务 95% Wilson 区间 | 72.25% - 100% | 小样本置信区间 |
| RAG Precision@K / Recall@K | 88.89% / 100% | 12 文档、9 查询固定语料 |
| RAG MRR / nDCG@K | 1.0 / 1.0 | 固定相关性标签 |
| RAG pollution@K | 0% | hard-negative 标签 |
| Unsafe candidate acceptance | 0/6 | 生产 Guard；不执行危险代码 |
| 恢复与幂等探针 | 5/5 | 生产 Queue、Session、ToolRegistry 组件 |
| Specialist 上下文缩减 p50 | 97.84% | 117 个 SpecialistResult 与完整 State 对照 |
| 原始 Artifact 到摘要缩减 p50 | 86.72% | 35 个记录 context_usage 的 Specialist 调用 |

历史真实 Run 的运行时间 p50/p95 为 167.5/1258.4 秒，平均每次成功约 55728.9 recorded tokens。最终开放题集执行 18 次 LLM 调用，使用 40023 tokens，耗时 547.8 秒，即每个通过样例 4002.3 tokens。这里的开放题只执行自然语言理解与受约束 Planner，不执行 HLS 综合，因此不能替代真实 CSim/CSynth 指标。

## 框架修复收益

同一固定 10 题、同一模型、同一单次采样策略的结果从 1/10 提升至 10/10，绝对提升 90 个百分点：

| 阶段 | 通过率 | 暴露的问题 |
|---|---:|---|
| 修复前 | 1/10 | schema 只检查顶层键，字符串 `task` 被错误放行 |
| Schema 修复后、Session 修复前 | 2/10 | Benchmark 使用未注册 session id；异常白名单过宽 |
| 最终 | 10/10 | 嵌套 schema、独立 session、ONNX 规范化、capability boundary 均生效 |

这组 before/after 衡量的是明确的框架回归修复，不是总体泛化能力。为了避免数据美化，修复前和中间结果分别保存在 `benchmarks/agent_interview_open_task_before_contract_fix.json` 与 `benchmarks/agent_interview_open_task_after_schema_before_session_fix.json`。

## 消融结论

RAG 关闭后 Recall/MRR 均为 0。朴素 lexical 与生产 retriever 的 MRR 都是 1.0，说明当前查询的首位命中并不难；真正改进来自分域检索，Precision@K 从 33.33% 提升到 88.89%，pollution@K 从 18.52% 降为 0%。因此不能宣称“排序能力从 0 到 1”，只能宣称 hard-negative 污染显著下降。

Guard 消融采用安全反事实：6 个语法合法但违反 sandbox/contract 的候选，在仅做 schema 检查时都会被接受；启用生产 Guard 后接受率为 0%。危险候选从未被执行。

恢复与幂等覆盖 Queue enqueue 去重、exactly-once commit replay、checkpoint round-trip、幂等工具缓存和有界重试。结果 5/5，但 95% Wilson 下界仅 56.55%，说明还需要更大规模的并发和进程故障注入。

## 面试口径

可以说明项目已经具备可测量的 Agent Harness：LLM 负责开放任务解释与受约束规划，Specialist 隔离局部上下文，ToolRegistry 执行原子动作，Guard/Permission/Completion Gate 阻止越权和假成功，Session/Queue 支持恢复与幂等，Memory/RAG 复用经验，Benchmark 对行为和成本统一量化。

不应声称支持任意 ONNX、任意算子或已经达到部署级稳定性。10 个开放任务是固定回归集，真实 HLS Run 也集中在有限算子族；后续需要盲测集、多 seed、多模型和真实进程崩溃/并发压力测试。

## 复现

```powershell
python -m dl_op_to_hls.cli agent-interview-benchmark `
  --output runs\benchmarks\agent_interview_release.json

# 配置真实 LLM 后，执行固定 10 题开放任务评测
python -m dl_op_to_hls.cli agent-interview-benchmark `
  --run-open-llm `
  --output runs\benchmarks\agent_interview_release.json
```

API key 只通过 `DL_OP_TO_HLS_LLM_API_KEY` 环境变量提供，不写入仓库或报告。
