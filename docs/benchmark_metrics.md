# Benchmark Metrics

本项目新增 `agent-quality-benchmark`，目标不是给模型跑通用 NLP 分数，而是量化 Agent 工程贡献：

- Tool/path selection accuracy：是否正确选择 `fallback_template_path`、`hls4ml_path`、`existing_hls_project_path`、`llm_candidate_path`、`unsupported_path`，以及是否调用对应工具链。
- Task success rate：按 `operator_fallback`、`model_hls4ml`、`unsupported_recovery`、`toolchain_recovery` 分桶统计。
- Unsupported honesty rate：不支持的模型/算子是否标为 `partial_success` 或 `unsupported`，并避免伪造 latency/resource/verification。
- Repair success rate：csim、转换、报告解析或 LLM candidate 失败后，是否通过 repair/replan 修复。
- Trace completeness：plan、todo、tool call、specialist result、artifact、error stage、summary 是否齐全。
- RAG evidence hit / pollution rate：是否命中相关 HLS 历史经验，是否混入不相关任务经验。
- Latency / cost：p50/p95 runtime、平均 tool calls/run、LLM calls/run、tokens/run。
- LLM Agent harness：plan generated/accepted/rejected、JSON repair、guard rejection、candidate generation/repair、selected skill 是否可追踪。

硬件指标只作为二级证据使用：真实 MNIST run 成功时可以展示 Vivado report，但 benchmark 的主结论应来自 Agent 行为指标。

## 运行方式

分析已有 runs：

```powershell
$env:PYTHONPATH='src'
python -m dl_op_to_hls.cli benchmark `
  --runs mnist_recognition_mlp_234d539d `
  --rag-eval-file benchmarks\rag_eval_labels.json `
  --rag-top-k 5 `
  --output runs\benchmarks\mnist_agent_quality_eval.json `
  --quiet
```

运行 MNIST-first benchmark suite：

```powershell
$env:PYTHONPATH='src'
python -m dl_op_to_hls.cli benchmark `
  --run-suite `
  --suite-file benchmarks\mnist_agent_quality_suite.json `
  --rag-eval-file benchmarks\rag_eval_labels.json `
  --output runs\benchmarks\mnist_agent_quality_suite.json `
  --quiet
```

运行更难的 LLM-first harness suite：

```powershell
$env:PYTHONPATH='src'
python -m dl_op_to_hls.cli benchmark `
  --run-suite `
  --suite-file benchmarks\llm_agent_harness_suite.json `
  --rag-eval-file benchmarks\rag_eval_labels.json `
  --output runs\benchmarks\llm_agent_harness_suite.json `
  --quiet
```

真实 LLM / Vivado benchmark 需要提前设置真实 API、hls4ml、Vivado 环境变量。不要把 API key 写进仓库文件：

```powershell
$env:PYTHONPATH='src'
$env:DL_OP_TO_HLS_LLM_API_KEY='<set-locally>'
$env:DL_OP_TO_HLS_LLM_ENABLED='1'
$env:DL_OP_TO_HLS_LLM_PROVIDER='openai-compatible'
$env:DL_OP_TO_HLS_LLM_BASE_URL='https://api.deepseek.com'
$env:DL_OP_TO_HLS_LLM_MODEL='deepseek-v4-pro'
```

长程评测建议使用 `--quiet`，只落盘 JSON/Markdown 报告，不持续把完整结果打印给用户。

## 核心指标

| 指标 | 含义 | 为什么能体现贡献 |
|---|---|---|
| `selected_path_valid_rate` | run 是否落在已定义合法 Agent path | 防止 Agent 进入未定义路径 |
| `agent_runtime.session_run_rate` | run 是否绑定 durable session | 验证 LLM Agent 会话主路径 |
| `agent_runtime.checkpoint_count_total` | Todo 边界和结束 checkpoint 数 | 验证中断恢复基础 |
| `agent_runtime.delegation_completion_rate` | request/result correlation 闭环率 | 验证 Main/Sub Agent 通信 |
| `agent_runtime.duplicate_tool_call_count_total` | 排除幂等 retry 后的重复调用 | 发现无效循环和 token/tool 浪费 |
| `avg_recorded_tokens_per_run` | provider usage 或 runtime 记录 token | 约束真实 LLM 成本 |
| `toolchain_selection_accuracy` | path 对应工具链是否被实际调用 | 衡量 tool/path selection，不看硬件好坏 |
| `task_success_rate_by_category` | 各任务桶成功率 | 区分 fallback、hls4ml、unsupported、toolchain recovery |
| `llm_harness.plan_acceptance_rate` | LLM plan 被 guard/skill policy 接受的比例 | 衡量 planner 输出是否能进入可执行 DAG |
| `llm_harness.json_repair_success_rate` | LLM JSON/schema 修复成功率 | 衡量结构化输出 harness，而不是裸聊天效果 |
| `llm_harness.guard_rejection_run_rate` | 出现 guard/specialist mismatch 拒绝的 run 比例 | 衡量 tool/specialist 边界是否被违反 |
| `llm_harness.candidate_generation_event_count_total` | 真实调用 LLM candidate generator 并通过 sandbox 的次数 | 衡量 LLM 生成代码路径是否真的接入 |
| `llm_harness.candidate_repair_todo_count_total` | LLM candidate 失败后的修复 todo 数 | 衡量 repair/replan 的可观测性 |
| `unsupported_honesty_rate` | unsupported case 是否诚实停止 | 防止伪造综合或验证结果 |
| `repair_success_rate` | 失败后 repair/replan 成功比例 | 衡量长程任务恢复能力 |
| `trace_completeness_avg` | plan/todo/tool/specialist/artifact/error/summary 完整率 | 衡量可追踪性和可复盘性 |
| `rag_evidence_hit_rate` | RAG 是否召回相关经验 | 衡量历史经验是否真正可用 |
| `rag_pollution_rate` | RAG 是否混入明显不相关经验 | 衡量 RAG hygiene |
| `semantic_rag.embedding_retrieval_rate` | RAG Tool 中实际进入 embedding recall 的比例 | 防止配置写了 semantic 但运行仍只走 FTS |
| `semantic_rag.cross_encoder_rerank_rate` | 实际执行 cross-encoder rerank 的比例 | 验证两阶段检索链路 |
| `semantic_rag.lexical_fallback_rate` | 模型缺失或故障时 lexical fallback 比例 | 发现模型部署或推理退化 |
| `runtime_s.p50 / runtime_s.p95` | run 耗时分位数 | 衡量端到端长程任务开销 |
| `avg_tool_calls_per_run` | 平均工具调用数 | 衡量编排成本 |
| `avg_llm_calls_per_run` | 平均 LLM 调用数 | 衡量 LLM 成本和节流压力 |
| `avg_estimated_tokens_per_run` | Specialist context token 估算 | 衡量上下文预算压力 |
| `vivado_metric_runs` | 成功解析真实 report 的 run 列表 | 仅作为真实工具链二级证据 |

## RAG 评估指标

RAG 评估通过 `--rag-eval-file` 提供标签。支持两种标签：

1. `relevant_source_ids`：严格 IR 标注，用于计算标准 Recall@K / Precision@K / MRR / nDCG。
2. `relevant_terms`、`required_terms`、`irrelevant_terms`：轻量标签，用于历史 runs source_id 不稳定时评估 term coverage 和 pollution。

输出指标：

| 指标 | 定义 |
|---|---|
| `precision_at_k` | Top-K 中相关结果占比 |
| `recall_at_k` | Top-K 覆盖相关 source id 的比例；没有 source id 标签时为 `null` |
| `hit_at_k` | Top-K 是否至少命中一个相关结果 |
| `mrr` | 第一个相关结果排名的倒数 |
| `ndcg_at_k` | 排名质量；没有 source id 标签时为 `null` |
| `relevant_term_coverage_at_k` | Top-K 文本覆盖 relevant terms 的比例 |
| `pollution_at_k` | Top-K 中包含 irrelevant terms 的结果占比 |
| `embedding_recall_usage_rate` | Top-K 结果中来自 embedding recall 的比例 |
| `cross_encoder_rerank_usage_rate` | Top-K 结果中经过 cross encoder 的比例 |
| `semantic_score_avg` | Top-K 平均 embedding cosine score |
| `cross_encoder_score_avg` | Top-K 平均校准后 reranker score |
| `rerank_mean_position_gain` | 结果从 pre-rerank 到 final rank 的平均名次提升 |

真实模型专项探针使用 `semantic-rag-benchmark`，同时检查 embedding 持久化、两阶段路径、相关 Top-1、Corrective RAG、实体污染门禁和 backend fallback。领域质量仍应以人工标注 query-document 集的 Recall@K、nDCG 和 hard-negative pollution 为准，不能只依赖该探针。

## 当前评测口径

当前真实跑通的主路径是 MNIST recognition MLP，因此正式展示应优先报告 `examples/mnist_recognition_mlp.json` 的 Agent 指标。Dense/MatMul/ResNet/ScaleShift 等 case 可以作为 mock contract、LLM harness 或边界回归，不应包装成主硬件 benchmark。

如果 `mnist_agent_quality_suite` 出现 1.0，不应直接解读为 Agent 泛化能力很强。它更像 smoke/contract 回归，样例少且多数是确定性路径。`llm_agent_harness_suite` 补充了 LLM-first planner、selected skill、fallback/existing/unsupported path、LLM candidate generation、强制 verification failure repair 等更接近 Agent 岗位面试关注的 harness 指标。

注意：runtime 受外部 LLM API 和 Vivado 环境波动影响；正式评测需要 `--repeat` 多次运行并报告 p50/p95。

## 面试表述建议

可以说：

> 我没有只用“demo 能跑”证明贡献，而是把 Agent 工程贡献量化为 path/toolchain selection、分桶成功率、unsupported honesty、repair success、trace completeness、RAG evidence hit/pollution、runtime p50/p95 和 LLM/tool/token 成本。硬件 report 只作为 MNIST 真实链路跑通的辅助证据。

不要过度声称：

> “硬件资源优化是 benchmark 主结论。”

更严谨的说法：

> “当前主评测是 MNIST recognition 的 Agent 行为质量；真实 Vivado latency/resource 只用于证明链路不是纯 mock。”
