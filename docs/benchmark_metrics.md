# Benchmark Metrics

本项目新增 `agent-quality-benchmark`，目标不是给模型跑通用 NLP 分数，而是量化 Agent 工程贡献：

- Agent 是否按正确路径执行。
- LLM 决策是否带来无效调用。
- Tool / Specialist / Trace 是否完整可观测。
- RAG 是否召回相关经验，是否出现跨任务污染。
- unsupported path 是否被正确标记为 `partial_success`。
- 真实 Vivado HLS report 是否被解析为 latency/resource/timing 指标。

## 运行方式

分析已有 runs：

```powershell
$env:PYTHONPATH='src'
python -m dl_op_to_hls.cli benchmark `
  --runs dense_16x32_af6abf3c_10 matmul_16x16_resource_9ac8e2e8_13 resnet18_boundary_demo_cd40d797_13 resnet18_boundary_demo_cd40d797_15 `
  --compare resnet18_boundary_demo_cd40d797_13 resnet18_boundary_demo_cd40d797_15 `
  --rag-eval-file benchmarks\rag_eval_labels.json `
  --rag-top-k 5 `
  --output runs\benchmarks\agent_quality_benchmark_demo.json
```

运行新的 benchmark suite：

```powershell
$env:PYTHONPATH='src'
python -m dl_op_to_hls.cli benchmark --run-suite --runner deterministic --mock-tools --repeat 3
```

真实 LLM / Vivado benchmark 可以使用 `--runner llm`，并提前设置真实 API、hls4ml、Vivado 环境变量。

## 核心指标

| 指标 | 含义 | 为什么能体现贡献 |
|---|---|---|
| `runtime_s` | 从 `trace.jsonl` 首个事件到最后事件的耗时 | 衡量 workflow / LLM 调用 / toolchain 综合耗时 |
| `llm_decision_count` | `state.llm_decisions` 数量 | 衡量 LLM 参与程度和无效决策是否减少 |
| `tool_call_count` | `PreToolUse` 事件数量 | 衡量 ToolRegistry 编排复杂度 |
| `specialist_event_count` | Specialist 相关 trace 事件数量 | 证明 sub-agent 层真实执行 |
| `artifact_completeness.rate` | 必需 run artifacts 的生成比例 | 衡量工程闭环与可复现性 |
| `rag_pollution_rate` | RAG 结果含二手污染或跨任务污染的 run 比例 | 衡量 RAG hygiene 改进 |
| `unsupported_semantics_pass_rate` | unsupported 状态和建议语义正确比例 | 衡量 Agent 是否诚实表达边界 |
| `vivado_metric_runs` | 成功解析真实 report 的 run 列表 | 证明真实 HLS 工具链接入 |
| `latency / dsp / lut / ff / timing_met` | Vivado csynth report 指标 | 展示 Agent 能产生 EDA 可用结果 |

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

## 当前真实观测结果

基于已有真实 runs 的一次 benchmark：

- Demo0 Dense：真实 Vivado report 成功，latency 269 cycles，DSP 16，LUT 549，timing met。
- Demo1 MatMul：真实 Vivado report 成功，latency 2052 cycles，DSP 16，LUT 624。
- Demo6 before/after：
  - `resnet18_boundary_demo_cd40d797_13` -> `resnet18_boundary_demo_cd40d797_15`
  - runtime: 184s -> 74s，单次观测下降 59.78%。
  - RAG pollution: true -> false。
  - unsupported status: `success` -> `partial_success`。
  - unsupported metric suggestion error: true -> false。

注意：runtime 受外部 LLM API 和 Vivado 环境波动影响，适合表述为 observed improvement；若要写成严格 benchmark，需要 `--repeat` 多次运行并报告 median/p95。

## 面试表述建议

可以说：

> 我没有只用“demo 能跑”证明贡献，而是把 Agent 工程贡献量化为 runtime、LLM decision count、tool call count、artifact completeness、RAG pollution rate、unsupported semantics pass rate、Vivado metric extraction 等指标。真实复测中，ResNet boundary 的 RAG 污染被消除，unsupported 状态从误导性的 success 修正为 partial_success，无 report 场景不再生成错误优化建议，并在一次真实运行中观察到 runtime 从 184s 降到 74s。

不要过度声称：

> “整体性能提升 60%。”

更严谨的说法：

> “在 ResNet boundary 真实 run 上观察到 59.78% 的耗时下降，主要来自跳过无效 LLM optimization 和确定性 memory playbook；由于 LLM API latency 有波动，后续用 repeat median/p95 做正式评测。”
