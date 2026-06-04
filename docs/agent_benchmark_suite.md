# Agent 能力 Benchmark 设计

本 benchmark 的目标不是证明某个 HLS 算子一定能在所有 FPGA 工具链上综合成功，而是量化评估 `DL-Operator-to-HLS-Agent` 的 Agent 工程能力，尤其适合用于 Agent 实习岗位面试展示。

它关注的问题是：

- Main Agent 是否能选择正确路径，而不是盲目承诺。
- Todo / ReAct / Specialist / ToolRegistry 是否按契约运行。
- 真实失败或 unsupported 边界是否能被结构化记录。
- artifacts、trace、state、memory 是否完整。
- RAG 是否能召回相关经验，同时避免明显污染。
- Vivado 不存在或模型不支持时，系统是否保持可解释的 partial success。

## Benchmark 层次

当前实现分为两层。

第一层是 run-level metrics，由 `collect_run_metrics()` 从已有 run 目录读取：

- `status_counts`：success / partial_success / failed 分布。
- `selected_path_counts`：fallback、hls4ml、unsupported、existing_project 等路径分布。
- `runtime_s`：从 trace 时间戳估算 min / median / max。
- `llm_decision_count_total`：LLM ReAct 决策次数。
- `tool_call_count_total`：ToolRegistry 工具调用次数。
- `specialist_event_count_total`：Specialist 生命周期事件数量。
- `artifact_completeness_avg`：关键 artifacts 完整率。
- `rag_pollution_rate`：明显不相关经验被召回的比例。
- `unsupported_semantics_pass_rate`：unsupported path 是否保持 partial_success、是否避免编造综合指标。
- `vivado_metric_runs`：成功解析 latency / II / DSP / BRAM / LUT / FF / timing 的 run。

第二层是 capability-suite checks，由 `benchmarks/agent_capability_suite.json` 定义每个 case 的期望契约：

- 期望状态，例如 `success` 或 `partial_success`。
- 期望路径，例如 `fallback_template_path`、`hls4ml_path`、`unsupported_path`。
- 必须出现的 trace events，例如 `TodoCreated`、`SpecialistSelected`、`SpecialistResultMerged`。
- 必须参与的 Specialist，例如 `VivadoSpecialist`、`OptimizationSpecialist`、`MemorySpecialist`。
- 禁止出现的错误，例如 `PermissionDeniedError`。
- 是否必须具备 Vivado synthesis metrics。
- unsupported case 是否禁止出现伪造 latency / DSP 建议。

## 当前 Suite 覆盖

`benchmarks/agent_capability_suite.json` 当前包含 12 个 case：

- `operator_fallback`：Dense、MatMul、ReLU、Add，测试 fallback template、Vivado specialist、优化建议和 memory promotion。
- `existing_project`：已有 HLS 工程路径，测试已有工程综合与 artifact 管理。
- `model_hls4ml`：MNIST MLP、Tiny CNN、QKeras mock 路径，测试 hls4ml specialist 主路径。
- `unsupported_recovery`：自定义不支持算子、residual block、ResNet18 boundary，测试诚实 unsupported report。
- `toolchain_recovery`：强制 Vivado 路径缺失，测试 `VivadoNotFoundError` 是否被结构化处理。

这组 case 是“能力契约回归集”，不是大规模泛化集。它适合证明框架关键机制稳定工作，也适合防止后续修改破坏已有 Agent 契约。

## RAG 评估指标

`benchmarks/rag_eval_labels.json` 配合 benchmark 输出常见信息检索指标：

- `precision_at_k`：top-k 中相关结果比例。
- `recall_at_k`：标注相关 source 是否被召回。
- `hit_at_k`：top-k 是否至少命中一个相关结果。
- `mrr`：第一个相关结果的倒数排名。
- `ndcg_at_k`：考虑排名位置的相关性指标。
- `relevant_term_coverage_at_k`：查询关键术语覆盖率。
- `pollution_at_k`：明显不相关术语污染比例。

RAG 评估目前是小样本标注，主要用于发现污染和回归，不应包装成通用检索 benchmark。

## 运行方式

在项目根目录运行：

```powershell
$env:PYTHONPATH='src'
python -m dl_op_to_hls.cli benchmark `
  --run-suite `
  --suite-file benchmarks\agent_capability_suite.json `
  --rag-eval-file benchmarks\rag_eval_labels.json `
  --rag-top-k 5 `
  --output runs\benchmarks\agent_capability_suite_smoke.json
```

只对已有 run 复评：

```powershell
$env:PYTHONPATH='src'
python -m dl_op_to_hls.cli benchmark `
  --runs <run_id_1> <run_id_2> `
  --suite-file benchmarks\agent_capability_suite.json `
  --rag-eval-file benchmarks\rag_eval_labels.json `
  --output runs\benchmarks\agent_capability_suite_eval.json
```

输出文件会包含：

- `metrics`：每个 run 的基础指标。
- `aggregate`：整体聚合指标。
- `rag_eval`：RAG 检索评估。
- `suite_eval`：case 级契约评分。

## 如何解释 1.0 分

如果 suite pass_rate 为 1.0，只能说明：

- 当前 12 个明确设计的 Agent 契约 case 全部通过。
- 这些 case 覆盖了 fallback、hls4ml mock、unsupported、toolchain recovery、artifact/trace/memory 等关键路径。
- 它是稳定的回归基线。

不能说明：

- Agent 已经能处理所有模型。
- LLM planning 泛化已经满分。
- RAG 在开放域中没有污染。
- Vivado / hls4ml 真实工具链没有兼容问题。

更强的下一步 benchmark 应包含：

- 30 到 50 个 hard-negative case。
- 多种真实模型导出格式：ONNX、Keras、QKeras、手写 C++。
- repeat 运行，报告 median、p95、失败率。
- LLM-first suite，单独统计 JSON 合规率、tool selection accuracy、repair success rate。
- RAG curated corpus，标注更完整的 relevance labels。
- 真实 Vivado suite 与 mock contract suite 分开报告。

## 面试展示口径

可以把本 benchmark 描述为：

> 我没有只做 demo，而是把 Agent 工程拆成可量化契约：规划路径、工具路由、specialist 隔离、trace/artifact 完整性、RAG 召回、unsupported 诚实性和 toolchain failure recovery。然后用一个可复现 suite 进行回归评估，保证每次框架改动都有指标反馈。

这能体现的能力包括：

- 能把模糊 Agent 需求拆成可测试契约。
- 能区分 demo 成功、工具链成功、Agent 框架成功。
- 能主动暴露失败边界，而不是用 fallback 掩盖。
- 能用真实运行日志反推评估指标和修复方向。
