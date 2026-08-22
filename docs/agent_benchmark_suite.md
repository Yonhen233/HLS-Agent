# Agent 能力 Benchmark 设计

本 benchmark 的目标不是证明某个 HLS 算子一定能在所有 FPGA 工具链上综合成功，而是量化评估 `DL-Operator-to-HLS-Agent` 的 Agent 工程能力，尤其适合用于 Agent 实习岗位面试展示。

它关注的问题是：

- Main Agent 是否能选择正确路径，而不是盲目承诺。
- Todo / ReAct / Specialist / ToolRegistry 是否按契约运行。
- 真实失败或 unsupported 边界是否能被结构化记录。
- artifacts、trace、state、memory 是否完整。
- RAG 是否能召回相关经验，同时避免明显污染。
- Vivado 不存在或模型不支持时，系统是否保持可解释的 partial success。
- 长程任务的 repair/replan 是否有效，LLM/tool/token 成本是否可量化。

## Benchmark 层次

当前实现分为两层。

第一层是 run-level metrics，由 `collect_run_metrics()` 从已有 run 目录读取：

- `status_counts`：success / partial_success / failed 分布。
- `selected_path_counts`：fallback、hls4ml、unsupported、existing_project 等路径分布。
- `selected_path_valid_rate`：是否只落在明确支持的 Agent path。
- `toolchain_selection_accuracy`：当前 path 是否调用了对应工具链。
- `task_success_rate_by_category`：按 `operator_fallback`、`model_hls4ml`、`unsupported_recovery`、`toolchain_recovery` 分桶统计成功率。
- `runtime_s`：从 trace 时间戳估算 min / p50 / p95 / max。
- `llm_decision_count_total`：LLM ReAct 决策次数。
- `tool_call_count_total`、`avg_tool_calls_per_run`：ToolRegistry 工具调用成本。
- `llm_call_count_total`、`avg_llm_calls_per_run`：LLM 调用成本。
- `avg_estimated_tokens_per_run`：Specialist context token 估算。
- `specialist_event_count_total`：Specialist 生命周期事件数量。
- `artifact_completeness_avg`：关键 artifacts 完整率。
- `trace_completeness_avg`：plan、todo、tool call、specialist result、artifact、error stage、summary 完整率。
- `rag_evidence_hit_rate` / `rag_pollution_rate`：相关经验命中与不相关经验污染比例。
- `unsupported_honesty_rate`：unsupported path 是否保持 `partial_success`/`unsupported`，是否避免编造综合或验证结果。
- `repair_success_rate`：失败后 repair/replan 是否让 run 收敛到 success/partial_success。
- `llm_harness`：LLM plan 接受率、JSON repair 成功率、guard rejection、candidate generation/repair 计数。
- `vivado_metric_runs`：成功解析 latency / II / DSP / BRAM / LUT / FF / timing 的 run；这是二级硬件证据，不是主评测指标。

第二层是 capability-suite checks，由 `benchmarks/agent_capability_suite.json` 定义每个 case 的期望契约：

- 期望状态，例如 `success` 或 `partial_success`。
- 期望路径，例如 `fallback_template_path`、`hls4ml_path`、`unsupported_path`。
- 必须出现的 trace events，例如 `TodoCreated`、`SpecialistSelected`、`SpecialistResultMerged`。
- 必须参与的 Specialist，例如 `VivadoSpecialist`、`OptimizationSpecialist`、`MemorySpecialist`。
- 禁止出现的错误，例如 `PermissionDeniedError`。
- 是否必须调用与 path 匹配的工具链。
- 是否必须具备完整 trace。
- unsupported case 是否禁止出现伪造 latency / resource / verification。
- repair case 是否要求修复成功。
- 是否必须具备 Vivado synthesis metrics；该项只用于真实链路佐证。

## 当前 Suite 覆盖

`benchmarks/mnist_agent_quality_suite.json` 是当前推荐的主评测 suite，因为真实跑通的主路径是 MNIST recognition：

- Primary：`examples/mnist_recognition_mlp.json`，真实 hls4ml/Vivado 链路，报告 Agent 指标并保留 Vivado report 作为二级证据。
- LLM：同一 MNIST 任务可走 `runner: llm`，使用 OpenAI-compatible DeepSeek 配置评估 path selection、toolchain selection 和 trace。
- Bucket smoke：保留少量 fallback、unsupported、toolchain recovery case，用于分桶成功率，不把它们包装成硬件 benchmark。

`benchmarks/llm_agent_harness_suite.json` 是更难的 LLM-first 面试展示 suite：

- Primary：仍保留 `examples/mnist_recognition_mlp.json` 的真实 hls4ml/Vivado 链路。
- Path diversity：Dense fallback、existing HLS project、ResNet18 unsupported honesty 都由 LLM planner 选择 skill/path。
- LLM candidate：ScaleShift 走 `llm_candidate_path`，要求真实 LLM 生成 candidate、通过 sandbox、再由 verification/Vivado 工具链验证。
- Repair/recovery：强制 candidate verification failure，要求 Agent 生成 repair todo，耗尽预算后诚实落到 unsupported，而不是伪造 report。

如果旧 suite 各项指标都是 1.0，主要说明 smoke/contract case 太少、太稳定；不能证明 LLM Agent 泛化。LLM harness suite 才更接近互联网大厂关心的 planner/guard/tool-use/repair 可观测性。

`benchmarks/agent_capability_suite.json` 仍是回归 suite，当前包含 12 个 case：

- `operator_fallback`：Dense、MatMul、ReLU、Add，测试 fallback template、Vivado specialist、优化建议和 memory promotion。
- `existing_project`：已有 HLS 工程路径，测试已有工程综合与 artifact 管理。
- `model_hls4ml`：MNIST MLP、Tiny CNN、Torch/QONNX quantized CNN 路径，测试 hls4ml specialist 主路径。
- `unsupported_recovery`：自定义不支持算子、residual block、ResNet18 boundary，测试诚实 unsupported report。
- `toolchain_recovery`：强制 Vivado 路径缺失，测试 `VivadoNotFoundError` 是否被结构化处理。

这组 case 是“能力契约回归集”，不是大规模泛化集。它适合证明框架关键机制稳定工作，也适合防止后续修改破坏已有 Agent 契约。正式展示时优先用 MNIST-first suite。

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
$env:DL_OP_TO_HLS_LLM_API_KEY='<set-locally>'
$env:DL_OP_TO_HLS_LLM_ENABLED='1'
$env:DL_OP_TO_HLS_LLM_PROVIDER='openai-compatible'
$env:DL_OP_TO_HLS_LLM_BASE_URL='https://api.deepseek.com'
$env:DL_OP_TO_HLS_LLM_MODEL='deepseek-v4-pro'
python -m dl_op_to_hls.cli benchmark `
  --run-suite `
  --suite-file benchmarks\mnist_agent_quality_suite.json `
  --rag-eval-file benchmarks\rag_eval_labels.json `
  --rag-top-k 5 `
  --output runs\benchmarks\mnist_agent_quality_suite.json `
  --quiet
```

LLM-first harness suite：

```powershell
$env:PYTHONPATH='src'
$env:DL_OP_TO_HLS_LLM_API_KEY='<set-locally>'
$env:DL_OP_TO_HLS_LLM_ENABLED='1'
$env:DL_OP_TO_HLS_LLM_PROVIDER='openai-compatible'
$env:DL_OP_TO_HLS_LLM_BASE_URL='https://api.deepseek.com'
$env:DL_OP_TO_HLS_LLM_MODEL='deepseek-v4-pro'
python -m dl_op_to_hls.cli benchmark `
  --run-suite `
  --suite-file benchmarks\llm_agent_harness_suite.json `
  --rag-eval-file benchmarks\rag_eval_labels.json `
  --rag-top-k 5 `
  --output runs\benchmarks\llm_agent_harness_suite.json `
  --quiet
```

只对已有 run 复评：

```powershell
$env:PYTHONPATH='src'
python -m dl_op_to_hls.cli benchmark `
  --runs <run_id_1> <run_id_2> `
  --suite-file benchmarks\mnist_agent_quality_suite.json `
  --rag-eval-file benchmarks\rag_eval_labels.json `
  --output runs\benchmarks\mnist_agent_quality_eval.json `
  --quiet
```

长程评测时建议保持静默：使用 `--quiet` 只写 `json` 和同名 `md` 报告，不在终端持续刷完整 payload。

输出文件会包含：

- `metrics`：每个 run 的基础指标。
- `aggregate`：整体聚合指标。
- `rag_eval`：RAG 检索评估。
- `suite_eval`：case 级契约评分。

## 如何解释 1.0 分

如果 suite pass_rate 为 1.0，只能说明：

- 当前明确设计的 Agent 契约 case 全部通过。
- MNIST 主路径、fallback、hls4ml、unsupported、toolchain recovery、artifact/trace/memory 等关键路径未回归。
- 它是稳定的回归基线。

不能说明：

- Agent 已经能处理所有模型。
- LLM planning 泛化已经满分。
- RAG 在开放域中没有污染。
- Vivado / hls4ml 真实工具链没有兼容问题。
- 硬件 latency/resource 已经优化到最好。

更强的下一步 benchmark 应包含：

- 30 到 50 个 hard-negative case。
- 多种真实模型导出格式：ONNX、QONNX、Keras/QKeras、手写 C++。
- repeat 运行，报告 median、p95、失败率。
- LLM-first suite，单独统计 JSON 合规率、tool selection accuracy、repair success rate。
- RAG curated corpus，标注更完整的 relevance labels。
- 真实 Vivado suite 与 mock contract suite 分开报告。

## 面试展示口径

可以把本 benchmark 描述为：

> 我没有只做 demo，而是把 Agent 工程拆成可量化契约：path/toolchain selection、分桶成功率、repair、trace/artifact 完整性、RAG 命中/污染、unsupported 诚实性和 toolchain failure recovery。当前主评测以真实跑通的 MNIST recognition 为中心，硬件 report 只作为链路证据。

这能体现的能力包括：

- 能把模糊 Agent 需求拆成可测试契约。
- 能区分 demo 成功、工具链成功、Agent 框架成功。
- 能主动暴露失败边界，而不是用 fallback 掩盖。
- 能用真实运行日志反推评估指标和修复方向。
