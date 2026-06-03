# 开发日志（Development Log）

维护约定：
- 从 **2026-06-01** 起，所有后续 bug 修复都追加到本文件，不新建分散日志。
- 每次记录必须包含：时间、测试动作、问题根因、修复方案、未修复原因。

---

## 2026-06-04 06:33:44 +08:00：更换 Paratera DeepSeek 配置后的真实链路复核
### 1. 本次测试做了什么
执行与验证：
- 继续在独立目录 `D:\hls_agent\standalone_work\dl-op-to-hls-agent` 开发，未修改旧 `D:\hls_agent` 脚本。
- 先运行全量单元测试：
  - `python -m pytest -q`
- 尝试使用新的 OpenAI-compatible LLM 配置运行真实 LLM + hls4ml + Vivado Demo0-Demo6：
  - Base URL：Paratera LLM endpoint。
  - Model：`DeepSeekv4pro`。
  - 真实 hls4ml：`DL_OP_TO_HLS_MOCK_HLS4ML=0`。
  - 真实 Vivado HLS：`DL_OP_TO_HLS_MOCK_VIVADO=0`。
  - Vivado HLS 路径：`D:\Xilinx\Vivado\2018.3\bin\vivado_hls.bat`。
  - strict runtime。
  - specialist LLM decider enabled。
- 因真实 LLM 调用被安全审批器阻止，转而运行不出网的真实 hls4ml + Vivado Demo0-Demo6：
  - `DL_OP_TO_HLS_RUNTIME_MODE=strict`
  - `DL_OP_TO_HLS_OPTIMIZATION_FALLBACK_MODE=demo`

### 2. 当前测试结果
已通过：
- 全量测试通过：
  - `python -m pytest -q`
- 非 LLM 的真实 hls4ml + Vivado Demo0-Demo6 跑完：
  - Demo0：`dense_16x32_af6abf3c_05`，`success`，`fallback_template_path`，`report.status=success`。
  - Demo1：`matmul_16x16_resource_9ac8e2e8_08`，`success`，`fallback_template_path`，`report.status=success`。
  - Demo2：`mnist_mlp_demo_4ff92a59_07`，`partial_success`，`unsupported_path`，`report.status=missing`，`HLS4MLConversionError`。
  - Demo3：`mnist_tiny_cnn_188af60c_06`，`partial_success`，`unsupported_path`，`report.status=missing`，`HLS4MLConversionError`。
  - Demo4：`mnist_qkeras_cnn_a7e2cdc5_04`，`partial_success`，`unsupported_path`，`report.status=missing`。
  - Demo5：`tiny_residual_block_ad48a995_04`，`partial_success`，`unsupported_path`，`report.status=missing`。
  - Demo6：`resnet18_boundary_demo_cd40d797_06`，`partial_success`，`unsupported_path`，`report.status=missing`。

真实 LLM + Vivado Demo0-Demo6：
- 本轮未运行成功。
- 原因：Codex 外部执行审批器拒绝向新的外部 LLM endpoint 发送本地 demo / 工程上下文。
- 处理：没有绕过审批器，也没有用 mock 冒充真实 LLM 结果。
- 后续：需要用户在了解“会向外部 LLM endpoint 发送本地任务与工程上下文”的风险后，明确批准继续执行。

### 3. 发现的问题与根因
1) 真实外部 LLM 调用涉及工作区上下文外发
- 现象：真实 LLM Demo0-Demo6 命令被审批器拒绝。
- 根因：`run-llm` 会把任务摘要、specialist context、RAG/memory 摘要等发送到 OpenAI-compatible endpoint；这属于本地项目上下文外发。
- 风险：即使用户提供了 API key，仍需要明确确认对外发送上下文的安全边界。

2) 本地真实 Vivado 路径稳定
- 现象：Demo0/Demo1 均完成真实 Vivado csynth 和 report parse。
- 根因：fallback template 生成的 HLS C++/TCL 能被 Vivado HLS 2018.3 执行。
- 结论：本地 EDA toolchain 不再是当前阻塞点。

3) 模型类 Demo 仍处于明确边界处理
- 现象：Demo2/Demo3 真实 hls4ml 仍进入 unsupported path，并记录 `HLS4MLConversionError`。
- 根因：当前 hls4ml 真实转换链路仍不能完整覆盖这些 ONNX 图中的边界算子。
- 结论：这是当前模型支持范围问题，不应通过 mock 或静默 fallback 伪装成 hls4ml 主路径成功。

### 4. 已修复内容（含修复方式）
- 本轮没有修改代码。
- 本轮确认了上一轮状态语义修复仍然有效：
  - Demo0/Demo1 真实 Vivado 成功后最终状态为 `success`。
  - hls4ml support warning 不再错误污染 fallback_template 路径最终状态。
- 本轮新增开发日志记录，明确区分：
  - 已完成的本地真实 hls4ml + Vivado 验证。
  - 未完成的外部 LLM 真实验证。

### 5. 未修复 / 待继续验证
- 真实 LLM + Vivado Demo0-Demo6 尚未完成。
  - 需要用户明确批准向 Paratera LLM endpoint 发送本地任务/工程上下文后继续执行。
- Demo2/Demo3 的模型图 rewrite / 静态消除能力仍需继续增强：
  - Demo2：继续验证 `Gemm -> MatMul + Add` 后是否能进入 hls4ml convert。
  - Demo3：继续实现或强化 `Shape` / flatten / reshape 静态消除。

---

## 2026-06-03 10:32:37 +08:00：Specialist 本地 ReAct 工具契约修复、真实 Vivado 状态语义修复
### 1. 本次测试做了什么
执行与验证：
- 继续在独立目录 `D:\hls_agent\standalone_work\dl-op-to-hls-agent` 开发，未修改旧 `D:\hls_agent` 脚本。
- 针对上一轮真实 DeepSeek + Vivado 暴露的 Demo2 / Demo3 失败继续排查：
  - Demo2 rewritten model 重试时，`HLS4MLSpecialist` 的 local ReAct 输出空/坏 arguments，覆盖了 ContextEnvelope 生成的 canonical `task` 参数，触发 `KeyError: 'task'`。
  - Demo3 inspect todo 中，local ReAct 选择了不匹配当前 todo 的动作，触发 `Specialist ReAct decision violated the local action/tool schema`。
- 运行聚焦测试：
  - `python -m pytest tests/test_specialist_react.py tests/test_specialists.py -q`
  - `python -m pytest tests/test_runtime_hybrid.py tests/test_specialist_react.py tests/test_specialists.py -q`
- 运行全量测试：
  - `python -m pytest -q`
- 运行非 LLM 的真实 hls4ml + Vivado Demo0-Demo6：
  - `DL_OP_TO_HLS_MOCK_HLS4ML=0`
  - `DL_OP_TO_HLS_MOCK_VIVADO=0`
  - `DL_OP_TO_HLS_VIVADO_HLS_PATH=D:\Xilinx\Vivado\2018.3\bin\vivado_hls.bat`
  - `DL_OP_TO_HLS_RUNTIME_MODE=strict`
  - `DL_OP_TO_HLS_OPTIMIZATION_FALLBACK_MODE=demo`
- 尝试运行真实 DeepSeek + Vivado Demo0-Demo6：
  - DeepSeek OpenAI-compatible。
  - strict runtime。
  - specialist LLM decider enabled。

### 2. 当前测试结果
已通过：
- 聚焦测试通过：
  - `tests/test_specialist_react.py`
  - `tests/test_specialists.py`
  - `tests/test_runtime_hybrid.py`
- 全量测试通过：
  - `python -m pytest -q`
- 非 LLM 真实 hls4ml + Vivado Demo0-Demo6 跑完：
  - Demo0：`dense_16x32_af6abf3c_03`，真实 Vivado csynth/report 成功，但修复前状态为 `partial_success`。
  - Demo1：`matmul_16x16_resource_9ac8e2e8_06`，真实 Vivado csynth/report 成功，但修复前状态为 `partial_success`。
  - Demo2：`mnist_mlp_demo_4ff92a59_06`，`partial_success`，`unsupported_path`，真实 hls4ml 仍报告 `HLS4MLConversionError`。
  - Demo3：`mnist_tiny_cnn_188af60c_05`，`partial_success`，`unsupported_path`，真实 hls4ml 仍报告 `HLS4MLConversionError`。
  - Demo4：`mnist_qkeras_cnn_a7e2cdc5_03`，`partial_success`，`unsupported_path`。
  - Demo5：`tiny_residual_block_ad48a995_03`，`partial_success`，`unsupported_path`。
  - Demo6：`resnet18_boundary_demo_cd40d797_05`，`partial_success`，`unsupported_path`。
- 状态语义修复后，重新运行真实 Vivado Demo0/Demo1：
  - Demo0：`dense_16x32_af6abf3c_04`，`success`，`fallback_template_path`，`report.status=success`。
  - Demo1：`matmul_16x16_resource_9ac8e2e8_07`，`success`，`fallback_template_path`，`report.status=success`。

真实 DeepSeek + Vivado Demo0-Demo6：
- 本轮未能启动。
- 原因：Codex 当前会话的外部执行审批器因 usage limit 拒绝联网/API执行请求：
  - `You've hit your usage limit...`
- 处理：没有绕过审批器，也没有用 mock 冒充真实 DeepSeek 结果。
- 后续：额度恢复后，需要用相同 strict 配置重新运行 Demo0-Demo6，重点观察 Demo2/Demo3 是否从 `InvalidTaskError` 转为正常 graph rewrite / unsupported 边界处理。

### 3. 发现的问题与根因
1) Specialist local ReAct 仍能破坏工具输入契约
- 现象：Demo2 rewritten model 重试时，`hls4ml.check_support` 被调用时缺少 `task`，报 `KeyError: 'task'`。
- 根因：`HLS4MLSpecialist.handle()` 先从 ContextEnvelope 构造了 canonical args，但随后允许 LLM action 的 `arguments` 整体覆盖 canonical args。
- 风险：即使 Main Agent 正确隔离了 ContextEnvelope，sub-agent 内部仍可能把结构化 tool input 退化成自由拼参。

2) Specialist local ReAct 仍能偏离当前 Todo 的 assigned_tool
- 现象：Demo3 的 inspect todo 被 local ReAct 判为 schema violation。
- 根因：guard 只检查工具是否在 specialist allowed_tools 内，没有强制“当前 todo 的 preferred_tool 必须被执行”。
- 风险：HLS4MLSpecialist 可见多个 hls4ml tool，LLM 可能在 inspect/config/check/convert 间跳转，导致 TodoList 的依赖语义被破坏。

3) 成功的 fallback 路径被早期 hls4ml warning 错误降级为 partial_success
- 现象：Demo0/Demo1 真实 Vivado csynth 和 report parse 都成功，但最终状态仍是 `partial_success`。
- 根因：`update_status_from_todos()` 看到任意 `completed_with_warning` 就把 run 置为 partial，没有区分“主路径不适合但替代路径成功”和“最终目标未完成”。
- 风险：演示和评估中会低估 fallback_template 路径的真实完成度。

### 4. 已修复内容（含修复方式）
- 收紧 Specialist local ReAct 契约：
  - 如果 Todo 有 `assigned_tool` / preferred tool，local ReAct 可以决定 `call_tool`、`mark_blocked`、`mark_failed`。
  - 但不允许改选其它 tool。
  - 不允许用 LLM action arguments 覆盖 ContextEnvelope 生成的 canonical arguments。
  - 如果 LLM 返回 `finish_with_result`，guard 会修复为调用 required tool。
  - 如果 LLM 返回 wrong tool，guard 会修复为 preferred tool。
  - 如果 canonical args 缺失，则标记 `mark_blocked`，不强行调用工具。
- 增加回归测试：
  - local ReAct 返回 wrong tool 时自动修复到 preferred tool。
  - local ReAct 返回 bad args 时保留 canonical arguments。
  - HLS4MLSpecialist 在 LLM 返回空 arguments 时仍使用 ContextEnvelope 中的 canonical `task`。
- 修复 fallback 路径状态聚合：
  - 当 `state.report.status == success` 且 selected path 为 `fallback_template_path` / `hls4ml_path` / `existing_hls_project_path` / `llm_candidate_path`，并且没有真实 error / blocked / meaningful skipped 时，最终 run 状态为 `success`。
  - 早期 hls4ml support warning 仍保留在 Todo Execution Summary 中，但不再污染最终 run status。
- 增加回归测试：
  - `test_runtime_fallback_success_not_downgraded_by_hls4ml_warning`。

### 5. 未修复 / 待继续验证
- 真实 DeepSeek + Vivado Demo0-Demo6 尚未完成本轮复测。
  - 原因不是项目代码，而是当前 Codex 会话 usage limit 阻止联网/API执行。
  - 需要额度恢复后继续跑。
- Demo2/Demo3 的真实 hls4ml 模型支持边界仍存在：
  - Demo2 的 ONNX `Gemm` rewrite 已有实现，但仍需真实 DeepSeek strict loop 复测确认完整链路。
  - Demo3 的 `Shape` / reshape / flatten 静态消除仍是后续重点。
- MatMul Demo1 真实 Vivado report 显示 timing 未满足：
  - `target_ns=8.0`
  - `estimated_ns=9.634`
  - synthesis 本身成功，因此 run status 为 success；优化建议应继续提示 timing/resource trade-off。

---

## 2026-06-02 15:32:42 +08:00：Agent 框架契约收紧、真实 Graph Rewrite、上下文预算与沙箱补强
### 1. 本次测试做了什么
执行与验证：
- 继续在独立目录 `D:\hls_agent\standalone_work\dl-op-to-hls-agent` 开发，未修改旧 `D:\hls_agent` 脚本。
- 复查外部评审提出的 5 类架构问题：
  - ContextEnvelope token budget 只有声明、没有真实预算控制。
  - Specialist Sub-agent 串行执行，是否需要 Multi-Agent Coordinator。
  - Skill YAML 仍主要手工维护，是否需要自动提炼。
  - LLM candidate 只有目录权限约束，缺少 HLS C++ 静态安全扫描。
  - strict/demo/production 模式和 fallback 策略主要靠环境变量，契约不够显式。
- 针对 Demo2 既往失败继续排查：
  - 真实 hls4ml 遇到 ONNX `Gemm` 报 `Unsupported operation type: Gemm`。
  - LLM reflection 曾提出未注册工具/专家，如 `onnx_graph_rewrite`、`GraphRewriteSpecialist`。
- 运行新增/聚焦测试：
  - `python -m pytest tests/test_demo_examples_schema.py tests/test_llm_reflection_guard.py tests/test_token_budget.py tests/test_candidate_sandbox.py tests/test_runtime_config.py -q`
- 运行全量测试：
  - `python -m pytest -q`
- 尝试启动真实 DeepSeek + Vivado Demo0-Demo6 批量复测：
  - DeepSeek OpenAI-compatible。
  - `DL_OP_TO_HLS_MOCK_HLS4ML=0`
  - `DL_OP_TO_HLS_MOCK_VIVADO=0`
  - `DL_OP_TO_HLS_VIVADO_HLS_PATH=D:\Xilinx\Vivado\2018.3\bin\vivado_hls.bat`
  - `DL_OP_TO_HLS_RUNTIME_MODE=strict`
  - `DL_OP_TO_HLS_OPTIMIZATION_FALLBACK_MODE=strict`
  - `DL_OP_TO_HLS_SPECIALIST_LLM_DECIDER_ENABLED=1`

### 2. 当前测试结果
已通过：
- 聚焦测试通过：`18 passed`。
- 全量测试通过：`python -m pytest -q`，全部通过。
- 新增 ONNX Gemm rewrite 单元测试通过：
  - 构造真实 ONNX `Gemm(transB=1)` 图。
  - `graph_rewrite.rewrite` 生成 rewritten ONNX。
  - rewritten graph 中不再包含 `Gemm`，包含 `MatMul` 和 `Add`。

真实 Demo0-Demo6 复测状态：
- 本轮批量真实运行未能启动。
- 原因：Codex 提权审批器因当前 usage limit 拒绝联网 API/Vivado 执行请求：
  - `You've hit your usage limit...`
- 处理：按照安全规则，没有绕过审批器继续执行同等网络/API命令，也没有改用 mock 冒充真实结果。
- 后续：额度恢复后可直接用本轮同等 strict 配置重跑 Demo0-Demo6。

### 3. 发现的问题与根因
1) ContextEnvelope token budget 之前只是“声明式”
- 现象：`max_context_tokens=3000` 存在，但 ContextBuilder 没有实际估算/截断。
- 根因：context isolation 已经做了 artifact ref 隔离，但没有把 budget 变成执行约束。
- 风险：RAG / memory 摘要积累后，Main Agent 或 Specialist prompt 仍可能越界。

2) Demo2 的 Gemm 问题不是简单“LLM 基模不行”
- 现象：真实 hls4ml 对当前 MNIST MLP ONNX 的 `Gemm` 不支持。
- 根因：`graph_rewrite.rewrite` 之前只返回建议，`implemented=False`，没有真的改写 ONNX。
- 风险：LLM 会尝试凭空提出 `onnx_graph_rewrite` 等不存在工具，说明框架没有把可用能力边界喂清楚并强校验。

3) LLM reflection 新增 todo 缺少二次 ToolRegistry / Specialist allowlist 校验
- 现象：LLM reflection 可以提出未知 tool / unknown specialist。
- 根因：planner 阶段有 guard，但 reflect 阶段新增 todo 进入 TodoList 前缺少同等级别 guard。
- 风险：后续执行阶段才爆 PermissionDenied / KeyError，问题定位太晚。

4) Candidate 代码缺少 HLS C++ 静态沙箱
- 现象：已有 `LLMGuard.validate_candidate_files` 限制 candidate 目录，但不扫描 C++ 内容。
- 根因：路径隔离与代码安全扫描没有分层。
- 风险：LLM candidate 可能包含 `system()`、危险 include、进程/网络 API 等不适合 HLS 验证环境的内容。

5) runtime mode / fallback 策略配置不够集中
- 现象：strict/demo 切换分散在多个环境变量中。
- 根因：缺少统一 `runtime.yaml` 作为声明式配置源。
- 风险：开发期 strict 与 demo 展示期 fallback 语义混淆。

### 4. 已修复内容（含修复方式）
- 新增 `core/token_budget.py`
  - 实现轻量 token 估算：默认 `1 token ~= 4 chars`。
  - ContextBuilder 构造 ContextEnvelope 后立即执行预算检查。
  - 超预算时优先截断 RAG / retrieved memory，再截断 state summary / notes，最后裁剪 artifact refs。
  - SpecialistResult `context_usage` 新增：
    - `estimated_input_tokens`
    - `estimated_output_tokens`
    - `max_context_tokens`
    - `context_truncated`
- 新增 `core/candidate_sandbox.py`
  - 对 LLM candidate HLS C++ 做 pattern-based 静态扫描。
  - 拒绝：
    - `system()`
    - `popen()`
    - process spawn API
    - `#include <fstream>` / `<filesystem>` / `<windows.h>` / `<unistd.h>` 等危险 include
    - socket/network include
    - inline asm
  - `llm/candidate_generator.py` 写文件前先扫描，违规则返回 `PermissionDeniedError`，不写 candidate 文件。
- 新增 `runtime.yaml`
  - 集中声明：
    - `runtime.mode: strict | demo | production`
    - `runtime.llm.fallback: error`
    - `runtime.optimization.fallback: demo | strict`
    - `runtime.specialist.llm_decider_enabled`
  - `core/config.py` 读取 runtime.yaml，并保留环境变量 override。
- `graph_rewrite.rewrite` 从建议升级为真实 ONNX rewrite 工具
  - 对安全模式 `Gemm(alpha=1,beta=1,transA=0)` 执行自动改写。
  - 支持 `transB=1` 时转置常量 initializer。
  - 输出 rewritten ONNX 到 `runs/<run_id>/rewritten/*_gemm_rewritten.onnx`。
  - 注册 rewritten model artifact。
  - 遇到非平凡 Gemm 参数时返回结构化“不可安全改写”，不强行改变语义。
- Runtime 接入 rewritten model
  - `Try graph rewrite` 成功后更新：
    - `state.task["original_model_path"]`
    - `state.task["model_path"]`
    - `state.artifacts["rewritten_model"]`
  - rewrite 成功后重新追加 `Check hls4ml support`，再进入 config/convert。
  - rewrite 未实现或不安全时才进入 unsupported report。
- LLM reflection 新增 todo guard
  - `LLMFirstRuntime._validate_reflection_todo()` 校验：
    - assigned_tool 必须存在于 ToolRegistry。
    - assigned_specialist 必须存在于 SpecialistRouter。
    - specialist-private tool 必须委派给对应 specialist。
    - assigned_tool 必须在 assigned_specialist.allowed_tools 内。
  - 被拒绝的 reflection todo 写入 `LLMReflectionTodoRejected` trace，并记录脱敏结构化错误。
- 优化建议 strict schema 继续收紧
  - 支持 DeepSeek 可能返回的 `justification` / `rationale` 字段映射到 `reason`。
  - 占位标题但 reason 具体时规范化为 `Optimization action`。
  - 纯占位/空建议 strict 模式下仍失败，不再静默规则兜底。

### 5. 新增或更新的测试
- `test_graph_rewrite_rewrites_onnx_gemm_to_matmul_add`
- `test_llm_reflection_rejects_unknown_tool_and_specialist`
- `test_llm_reflection_rejects_specialist_tool_mismatch`
- `test_token_budget_*`
- `test_candidate_sandbox_*`
- `test_runtime_config_*`
- `test_llm_react_fills_delegate_specialist_from_todo`
- `test_llm_optimizer_strict_mode_accepts_justification_field`

测试结果：
- 聚焦测试：通过。
- 全量测试：通过。

### 6. 未修复完成的问题及原因
1) Multi-Agent Coordinator 并行调度暂未进入主线
- 原因：当前 artifact manifest、SQLite、Todo 状态、Vivado 工作目录 merge 都是共享状态；贸然并行会引入竞态，降低 demo bug 信号质量。
- 策略：作为后续 feature flag 实验模式实现，例如 `runtime.coordinator.parallel_enabled=true`；默认 production/strict 仍保持串行、可追踪、可复现。

2) Skill 自动提炼暂未写入 YAML 自动生成流程
- 原因：当前 MemoryManager 已能抽取/promote memory candidates，但自动写 skill YAML 会改变可执行能力集合，必须先增加 review/approval gate，避免 Agent 自行扩大权限。
- 策略：后续实现 `skills/candidates/*.yaml`，先作为候选 skill，不自动启用；通过人工批准或 tests 后再移入 `skills/*.yaml`。

3) Demo3 Shape/Reshape/Flatten 静态消除未完成
- 原因：本轮优先修复 Demo2 已知 `Gemm -> MatMul + Add` 的真实 rewrite；Shape/Reshape/Flatten 需要更多 ONNX shape/value_info 语义处理。
- 策略：后续补 `static_shape_elimination`，并用真实 Tiny CNN ONNX 单元图测试。

4) Demo4 QKeras/H5 真实前端仍未完成
- 原因：当前环境缺 `qkeras` / `tensorflow`，adapter 只能结构化 unsupported。
- 策略：后续增加 Keras/QKeras frontend adapter，或提供先导出为 hls4ml 支持输入格式的转换脚本。

5) 真实 DeepSeek + Vivado Demo0-Demo6 未完成
- 原因：Codex 当前外部命令审批因 usage limit 拒绝联网真实运行。
- 策略：额度恢复后继续执行 strict 真实复测；不使用 mock 替代真实结果。

---

## 2026-06-02 10:32:02 +08:00：真实/Mock 边界体检、严格验证修补、DeepSeek Demo0 真实复测
### 1. 本次测试做了什么
执行与验证：
- 使用独立目录：`D:\hls_agent\standalone_work\dl-op-to-hls-agent`。
- 检查用户指出的潜在问题：
  - `adapters/` 是否只有 `__init__.py`。
  - `cli:main` 是否缺失。
  - `verify_candidate` 是否写死 mock 报告。
  - `hls4ml.run_csim` 是否仍然无条件 mock 成功。
  - Permission / Hook / Trace 等基础设施是否存在。
- 使用 DeepSeek OpenAI-compatible 配置进行真实 Demo0 复测：
  - `DL_OP_TO_HLS_LLM_PROVIDER=openai-compatible`
  - `DL_OP_TO_HLS_LLM_BASE_URL=https://api.deepseek.com`
  - `DL_OP_TO_HLS_LLM_MODEL=deepseek-v4-pro`
  - `DL_OP_TO_HLS_LLM_API_KEY=<redacted>`
  - `DL_OP_TO_HLS_MOCK_HLS4ML=0`
  - `DL_OP_TO_HLS_MOCK_VIVADO=0`
  - `DL_OP_TO_HLS_VIVADO_HLS_PATH=D:\Xilinx\Vivado\2018.3\bin\vivado_hls.bat`
  - `DL_OP_TO_HLS_OPTIMIZATION_FALLBACK_MODE=strict`
- 运行聚焦测试：
  - `python -m pytest tests/test_fallback_templates.py -vv`
  - `python -m pytest tests/test_hls4ml_mcp.py tests/test_specialists.py -q`
  - `python -m pytest tests/test_llm_optimizer_fallback.py tests/test_fallback_templates.py tests/test_hls4ml_mcp.py tests/test_specialists.py -q`
- 运行全量测试：
  - `python -m pytest -q`

### 2. 当前复测结果
已确认不是问题的项：
- `src/dl_op_to_hls/adapters/` 并非只有 `__init__.py`，当前已存在：
  - `hls4ml_adapter.py`
  - `vivado_hls_adapter.py`
  - `legacy_vivado_env.py`
  - `llm_adapter.py`
  - `senior_agent_adapter.py`
- CLI 入口存在：
  - `src/dl_op_to_hls/cli.py`
  - `pyproject.toml` 中注册：`dl-op-to-hls = "dl_op_to_hls.cli:main"`。
- Permission / Hook / Trace / Artifact / DB / RAG 等基础设施存在，且本轮 pytest 仍全量通过。

已确认确实存在的问题：
- `verify_candidate.run` 之前会写死 `MOCK_REPORT` 并返回 `status=verified`。
- `hls4ml.run_csim` 之前无论真实/非真实模式都会写入 `Mock hls4ml csim completed successfully.`。
- Demo JSON 中 `demo.mock_tools=true` 会污染 LLM plan/summary，使真实运行也被描述成 mock demo。
- Demo0 真实运行虽然完成，但 `suggestions.md` 出现了泛化占位输出：`Suggestion` / `Suggestion`。这不是 mock，但属于 LLM 输出质量 guard 不足。

Demo0 真实复测结果：
- run_id：`dense_16x32_115c1f11_07`
- 运行状态：`success`
- selected_path：`fallback_template_path`
- DeepSeek LLM plan/react 成功；Main Agent 使用 `delegate_to_specialist` 调度 VivadoSpecialist / OptimizationSpecialist / MemorySpecialist。
- VivadoSpecialist 真实调用 `vivado_hls.bat` 完成 synthesis/report parsing。
- 真实报告指标：
  - Latency：269 / 269 cycles
  - II：269 / 269
  - DSP：16
  - BRAM：0
  - LUT：549
  - FF：732
  - Timing estimated：4.304 ns
  - Timing met：true
- summary 已包含：
  - `Todo Execution Summary`
  - `Specialist Execution Summary`
  - `Context Isolation`
  - `Memory Summary`

依赖状态：
- `hls4ml`：已安装。
- `onnx`：已安装。
- `qkeras`：未安装。
- `tensorflow`：未安装。
- 因此 Demo4 的真实 QKeras/H5 分支当前预期应结构化 unsupported，而不是伪造成功。

### 3. 发现的问题与根因
1) `verify_candidate` 将 mock 结果伪装为 verified
- 现象：无论候选代码是否真实通过 csim/csynth，工具都会写固定 csynth.rpt 并返回 `verified`。
- 根因：P0 mock 验证接口未与真实模式隔离。
- 风险：LLM candidate 可能未经真实 testbench/Vivado 验证就进入可复用 implementation 记忆。

2) `hls4ml.run_csim` 真实模式下仍写 mock 成功日志
- 现象：真实工具环境下仍输出 `Mock hls4ml csim completed successfully.`。
- 根因：adapter 没有区分 `mock_mode=True/False`。
- 风险：真实 hls4ml csim 状态被错误标记为 success。

3) Specialist local ReAct 可能重复调用 LLM，导致长流程卡顿
- 现象：上轮真实 Demo0 卡在 OptimizationSpecialist。
- 根因：Main Agent 已经做了 LLM ReAct 决策，Specialist 内部 local ReAct 又默认使用 LLM decider。
- 修复策略：Specialist local ReAct 默认使用确定性 schema guard；只有显式设置 `DL_OP_TO_HLS_SPECIALIST_LLM_DECIDER_ENABLED=1` 时才启用 LLM。

4) Demo JSON 的 `mock_tools=true` 会误导 LLM
- 现象：真实 Demo0 summary 的 LLM reasoning 提到了 mock Vivado。
- 根因：任务 JSON 中的 demo 元数据仍写着 mock_tools true。
- 修复策略：Demo0-Demo6 的 `mock_tools` 改为 `false`，描述改成真实优先，`--mock-tools` 仅用于离线冒烟测试。

5) Optimization suggestions 缺少质量 guard
- 现象：DeepSeek 返回的 suggestions 被规范化成 `Suggestion` / `Suggestion`，系统仍写入 summary。
- 根因：schema 只检查字段存在，没有检查内容是否为空壳/占位。
- 修复策略：新增 placeholder suggestion guard；strict 模式下空建议/占位建议返回 `LLMGenerationError`，demo 模式下才允许回退到规则建议。

### 4. 已修复内容（含修复方式）
- `verify_candidate.run`
  - 新增显式 `mock` / `real` 模式判断。
  - mock 模式才允许写 fixture report。
  - real 模式要求 candidate dir 存在、testbench 存在，并通过 Vivado adapter 创建项目、运行 Tcl、解析 report 后才返回 `verified`。
  - 缺 testbench / Vivado 失败 / report 缺失 / report 解析失败都会返回 structured error。
- `hls4ml.run_csim`
  - mock 模式保留原有 demo 行为并标记 `mode=mock`。
  - real 模式不再写假成功日志。
  - 缺项目目录、缺 hls4ml/onnx、缺 `build_prj.tcl` 或直接 csim 未启用时返回结构化错误。
- `MainAgent.create_run_context`
  - 注入 `hls4ml_adapter`、`vivado_adapter`。
  - 显式设置 `specialist_llm_decider_enabled=False`。
- `BaseSpecialist`
  - local ReAct 默认走确定性 decider。
  - 只有 `DL_OP_TO_HLS_SPECIALIST_LLM_DECIDER_ENABLED=1` 才调用 Specialist 内部 LLM decider。
- `PermissionGate`
  - `check_tool` 增加 `candidate_dir`、`testbench_path`、`report_dir` 检查。
- `VerificationSpecialist`
  - 描述从 mock csim/csynth 改为 explicit mock or real Vivado-backed verification。
- Demo JSON
  - Demo0-Demo6 的 `demo.mock_tools` 改为 `false`。
  - 描述改成真实优先，mock 仅用于 offline smoke test。
- `suggest_optimization`
  - 新增占位建议识别。
  - strict 模式下拒绝 `Suggestion` / 空 reason / 空建议。

### 5. 新增或更新的测试
- `test_verify_candidate_mock_success`
  - 显式传 `mode=mock`。
- `test_verify_candidate_real_mode_requires_testbench`
  - 验证真实模式下没有 testbench 不能返回 verified。
- `test_hls4ml_run_csim_real_mode_does_not_mock_success`
  - 验证真实模式不会写 mock 成功。
- `test_llm_optimizer_strict_mode_rejects_placeholder_suggestions`
  - 验证 strict 模式拒绝占位建议。

测试结果：
- 聚焦测试通过：
  - fallback / hls4ml / specialists / optimizer tests 全部通过。
- 全量测试通过：
  - `python -m pytest -q` 通过。

### 6. 未修复完成的问题及原因
1) Demo1-Demo6 本轮未能继续真实运行
- 原因：批量真实命令需要联网调用 DeepSeek API 并调用 Vivado HLS，Codex 提权系统返回 usage limit，拒绝继续执行：
  - `You've hit your usage limit...`
- 处理：按照安全规则，未绕过提权限制继续执行同等网络/Vivado命令。
- 后续：额度恢复后继续运行 Demo1-Demo6，或用户可在本机 PowerShell 中直接运行同等命令。

2) Demo0 在新增 suggestions guard 后尚未重新真实复测
- 原因：同样受 usage limit 限制，不能继续调用 DeepSeek API。
- 已完成的验证：pytest 已覆盖 placeholder suggestion strict rejection。
- 后续：额度恢复后需要重新运行 Demo0，确认 DeepSeek 在 strict guard 下能返回高质量建议；如果不能，应继续优化 optimizer prompt 或将该阶段标为结构化失败。

3) Demo2/Demo3 真实 hls4ml 图支持问题仍可能存在
- 既往结果显示 MNIST MLP 可能包含 Gemm，Tiny CNN 可能包含 Shape/reshape/flatten 类节点。
- 当前已有 graph rewrite suggestion，但并未真正完成 ONNX graph rewrite。
- 后续：实现真实 Gemm -> MatMul + Add、静态 Shape/Reshape/Flatten 消除，不能只靠 fallback。

4) Demo4 QKeras/H5 真实链路未完成
- 当前 `qkeras` / `tensorflow` 未安装，adapter 只做结构化 unsupported。
- 后续：补 Keras/QKeras frontend 分支，或提供从 QKeras/H5 到 hls4ml 支持输入的真实转换路径。

---

## 2026-06-01 20:31:40 +08:00：修复后真实 LLM Demo0 复测结果
### 1. 本次测试做了什么
执行与验证：
- 使用独立目录：`D:\hls_agent\standalone_work\dl-op-to-hls-agent`。
- 使用真实 LLM API、真实 Vivado HLS 路径、非 mock 工具配置复测 Demo0：
  - `python -m dl_op_to_hls.cli run-llm examples/dense_operator.json`
  - `DL_OP_TO_HLS_MOCK_HLS4ML=0`
  - `DL_OP_TO_HLS_MOCK_VIVADO=0`
  - `DL_OP_TO_HLS_OPTIMIZATION_FALLBACK_MODE=strict`
- 本次命令外层 15 分钟超时，后台 Python 进程继续运行；后续确认其长时间停留在 OptimizationSpecialist 阶段，因此已停止该孤儿进程，避免继续消耗 API。

### 2. 当前复测结果
本轮 run_id：
- `dense_16x32_115c1f11_06`

已经验证通过的链路：
- Main Agent ReAct 不再卡在缺失 `decision`，trace 中已出现合法决策：
  - `direct_tool_only_when_no_specialist`
  - `delegate_to_specialist`
- Fallback HLS template 已生成成功：
  - `generated/dense_16x32.h`
  - `generated/dense_16x32.cpp`
  - `generated/testbench.cpp`
  - `generated/run_hls.tcl`
- VivadoSpecialist 已被正确委派并执行成功：
  - `vivado.create_project` success
  - `vivado.run_csynth` success
  - `vivado.parse_report` success
- Vivado report artifact 已生成：
  - `runs/dense_16x32_115c1f11_06/vivado_hls/vivado_hls/solution1/syn/report/dense_16x32_csynth.rpt`
- `Parse synthesis report` todo 也通过 `VivadoSpecialist` 完成。

未完成的链路：
- 执行到 `Generate optimization suggestions` / `OptimizationSpecialist` 后，trace 停在 `SpecialistStarted`，没有后续 tool event。
- 外层命令超时后后台进程仍存在，说明该阶段可能卡在 Specialist local ReAct 的 LLM 调用、API 等待或 optimizer LLM 调用上。

### 3. 发现的问题与根因
1) 之前的 `decision` 缺失问题已明显改善
- 证据：trace 中 Main Agent 多次返回合法 `decision`，并成功委派 VivadoSpecialist。
- 结论：schema enum、prompt 示例、strict JSON repair 对主 ReAct 契约有效。

2) 新瓶颈转移到 OptimizationSpecialist 阶段
- 现象：trace 最后事件为 `SpecialistStarted` for `OptimizationSpecialist`，之后无 `PreToolUse` / `SpecialistFinished`。
- 初步根因：OptimizationSpecialist 内部 local ReAct 也会调用 LLM decider；在当前真实 API/限速环境下可能等待过长或挂起。
- 下一步修复方向：为 Specialist local ReAct 增加 per-call timeout、超时结构化错误、以及针对 OptimizationSpecialist 的“必须先发出 local_react trace 再调用 LLM”可观测性。

3) run-llm 长流程缺少全局 wall-clock budget
- 现象：外层 shell 超时后子进程仍继续运行。
- 初步根因：当前 runtime 没有统一 run-level deadline / cancellation propagation。
- 下一步修复方向：增加 `DL_OP_TO_HLS_RUN_TIMEOUT_SEC` 或 runtime deadline，在 LLM/tool/specialist 层统一检查并返回 structured timeout error。

### 4. 已修复内容（含修复方式）
- 本次为真实复测与定位，未修改业务代码。
- 停止了超时后残留的 Python 进程，避免继续消耗 API。

### 5. 未修复完成的问题及原因
1) Demo0 run-llm 尚未完整成功
- 原因：虽然已通过 Main Agent ReAct、fallback generation、Vivado synthesis/report parsing，但卡在 OptimizationSpecialist 阶段。

2) 本次没有 push 到 GitHub
- 原因：用户要求“如果成功则 push”；本轮复测未完整成功，因此不推送新的日志/状态提交，避免把未完成验证误标为通过。
---

## 2026-06-01 15:11:00 +08:00：LLM 契约层、Skill 工具边界、hls4ml stdout 与 QKeras/H5 前端修补
### 1. 本次测试做了什么
执行与验证：
- 修补 Main Agent ReAct schema：增加 `title`、`decision enum` 和强示例。
- 增强 `REACT_SYSTEM_PROMPT`：明确只能输出严格 JSON，`decision` 必须来自 `allowed_actions`。
- 新增严格 JSON repair 回合：第一次 LLM JSON 缺字段/格式错误时，只允许修复 JSON 结构和缺失必填字段，不允许改变任务语义。
- 新增脱敏 LLM debug artifact：repair 失败时写入 `runs/<run_id>/llm_debug/*.json`，并对 API key/token/secret 做脱敏。
- 收紧 planner capability exposure：planner 的 `direct_tools` 现在按候选 skill contract 过滤，同时显式提供 `skill_tool_contracts`。
- 对齐 `hls4ml_model_flow` allowlist：加入 `graph_rewrite.rewrite`、`report.write_unsupported`、`summary.write_summary`，避免 failure policy 允许但 skill policy 拒绝。
- 修复 LLM candidate 工具命名不一致：同时识别 `llm.generate_candidate` 和旧别名 `llm.generate_hls_candidate`。
- 增加 QKeras/H5 frontend 分支：`.h5/.hdf5` 不再被当成 ONNX ModelProto 解析，而是返回结构化 unsupported / conversion error。
- 捕获真实 hls4ml 部分 stdout：在 `config_from_onnx_model` / `convert_from_onnx_model` 调用处 redirect stdout 到 log artifact，避免污染 CLI JSON。
- 增强 graph rewrite 检测：支持检测 ONNX `Gemm`、`Shape/Reshape/Flatten` 并给出明确 rewrite suggestion，但不假装已完成真实图重写。

运行测试：
- Focused：`python -m pytest tests/test_llm_client_config.py tests/test_llm_todo_plan_schema.py tests/test_skill_policy.py tests/test_hls4ml_mcp.py tests/test_demo_examples_schema.py tests/test_llm_react_decision_guard.py -q`，结果：27 passed。
- Full：`python -m pytest -q`，结果：158 passed。

### 2. 发现的问题与根因
1) LLM ReAct 缺 `decision` 不应只靠 prompt 期待模型遵守
- 根因：OpenAI-compatible 模型可能返回近似 JSON，但不稳定遵守必填字段。
- 修复策略：schema enum + 强示例 + strict JSON repair + 失败 artifact，而不是静默 deterministic fallback。

2) Boundary planner 违反 skill allowlist 是 tool contract 不一致问题
- 根因：`hls4ml_model_flow` 的 failure_policy 提到 graph rewrite / unsupported report，但 allowed_tools 中没有这些工具；planner 也能看到比当前 skill 更多的 direct tools。
- 修复策略：对齐 skill allowlist，并把 planner 可见 direct tools 限制到候选 skill contracts。

3) Demo4 的 QKeras/H5 不应走 ONNX parser
- 根因：adapter 没有 frontend 分支，导致 `.h5` 被 ONNX parser 解析并报 `Error parsing onnx.ModelProto`。
- 修复策略：识别 `keras/qkeras/h5` frontend，返回明确结构化 unsupported/转换错误，指向专门 H5 frontend 后续实现。

4) 真实 hls4ml stdout 污染 CLI JSON
- 根因：第三方库直接打印 stdout，CLI 同时输出 JSON state。
- 修复策略：在 adapter 真实调用点捕获 stdout 并写入日志 artifact。

### 3. 已修复内容（含修复方式）
修复文件：
- `src/dl_op_to_hls/llm/schemas.py`
- `src/dl_op_to_hls/llm/prompts.py`
- `src/dl_op_to_hls/llm/client.py`
- `src/dl_op_to_hls/llm/planner.py`
- `src/dl_op_to_hls/llm/guards.py`
- `src/dl_op_to_hls/skills/policy.py`
- `skills/hls4ml_model_flow.yaml`
- `src/dl_op_to_hls/adapters/hls4ml_adapter.py`
- `src/dl_op_to_hls/tools/graph_rewrite.py`
- `tests/test_llm_client_config.py`
- `tests/test_llm_todo_plan_schema.py`
- `tests/test_hls4ml_mcp.py`
- `tests/test_demo_examples_schema.py`

关键修复点：
- `REACT_DECISION_SCHEMA.decision` 增加 enum：`delegate_to_specialist`、`direct_tool_only_when_no_specialist`、`request_replan`、`mark_blocked`、`mark_failed`。
- `SPECIALIST_REACT_DECISION_SCHEMA.decision` 增加 enum：`call_tool`、`mark_blocked`、`mark_failed`、`finish_with_result`。
- `LLMClient.complete_json()` 支持一次 strict repair，修复失败写脱敏 debug artifact。
- Planner payload 新增 `skill_tool_contracts`，并过滤掉候选 skill 外的 direct tools。
- HLS4MLAdapter 对 `.h5/.hdf5/qkeras/keras` 做前端识别，不再误走 ONNX parse。
- Graph rewrite 明确返回 `implemented: false`，避免把建议误表示成已完成转换。

### 4. 当前结果
- 本地 mock/单元/集成测试全部通过：158 passed。
- 已修复框架侧最直接的 LLM schema 缺字段问题，并增加可调试 artifact。
- 已修复 skill contract 与 planner capability exposure 的主要不一致点。
- 已修复 QKeras/H5 输入链路误报 ONNX parse 的问题。
- 已部分修复 hls4ml stdout 污染 CLI JSON 的问题。

### 5. 未修复完成的问题及原因
1) 未完成真实 API Demo0 复测
- 原因：尝试运行真实 API + Vivado Demo0 探针时，当前 Codex 环境提示使用额度限制，无法继续发起该外部执行。

2) Gemm/Shape 仍只是 rewrite suggestion，不是真实 ONNX 图重写
- 原因：真实 ONNX graph rewrite 需要安全地重写 initializer、shape metadata 和下游节点，不能在本轮用字符串级伪转换冒充完成。

3) hls4ml stdout 捕获可能还不覆盖所有第三方打印点
- 原因：已覆盖 adapter 中主要真实调用点，但其他库内部异步/底层输出仍需后续真实复测确认。

4) Boundary demo 仍需真实 LLM 复测
- 原因：本轮已修 prompt/contract/allowlist，但受额度限制未能重新运行真实 `run-llm` 验证。
---

## 2026-06-01 14:48:53 +08:00：真实 LLM API 与真实 Vivado/HLS 工具链 Demo0-Demo6 全量验证
### 1. 本次测试做了什么
执行与验证：
- 使用独立目录：`D:\hls_agent\standalone_work\dl-op-to-hls-agent`。
- 先执行真实 LLM-first 验证：`python -m dl_op_to_hls.cli run-llm <demo>`。
- LLM API 配置为 OpenAI-compatible endpoint，模型为 `mimo-v2.5-pro`；API Key 只通过环境变量注入，未写入仓库文件或日志。
- LLM 限速配置：`DL_OP_TO_HLS_LLM_RATE_BYTES_PER_MINUTE=10000`、`DL_OP_TO_HLS_LLM_MIN_REQUEST_INTERVAL_SEC=12`、`DL_OP_TO_HLS_LLM_MIN_RETRY_429_SECONDS=30`。
- Vivado HLS 配置：`DL_OP_TO_HLS_VIVADO_HLS_PATH=D:\Xilinx\Vivado\2018.3\bin\vivado_hls.bat`。
- 关闭 mock：`DL_OP_TO_HLS_MOCK_HLS4ML=0`、`DL_OP_TO_HLS_MOCK_VIVADO=0`。
- 开发期严格模式：`DL_OP_TO_HLS_OPTIMIZATION_FALLBACK_MODE=strict`。
- 随后执行真实工具链基线验证：`python -m dl_op_to_hls.cli run <demo>`，用于确认 hls4ml/Vivado adapter 的真实行为。

### 2. 真实 LLM API 验证结果（run-llm）
| Demo | 文件 | run_id | status | 主要结果 |
|---|---|---|---|---|
| Demo 0 | `examples/dense_operator.json` | `dense_16x32_115c1f11_04` | `failed` | Main Agent ReAct 响应缺少 `decision` 字段 |
| Demo 1 | `examples/matmul_resource.json` | `matmul_16x16_resource_b0ad01f2_03` | `failed` | Main Agent ReAct 响应缺少 `decision` 字段 |
| Demo 2 | `examples/mnist_mlp_hls4ml.json` | `mnist_mlp_demo_88b12719_06` | `failed` | Main Agent ReAct 响应缺少 `decision` 字段 |
| Demo 3 | `examples/mnist_tiny_cnn.json` | `mnist_tiny_cnn_6bbae346_06` | `failed` | Main Agent ReAct 响应缺少 `decision` 字段 |
| Demo 4 | `examples/mnist_qkeras_cnn.json` | `mnist_qkeras_cnn_4c10f7fa_04` | `failed` | Main Agent ReAct 响应缺少 `decision` 字段 |
| Demo 5 | `examples/tiny_residual_block.json` | `tiny_residual_block_b66fa9b1_05` | `failed` | LLM planner 生成了 selected skill allowlist 外的工具 |
| Demo 6 | `examples/resnet18_boundary.json` | `resnet18_boundary_demo_16dc6e00_04` | `failed` | LLM planner 生成了 selected skill allowlist 外的工具 |

结论：
- API 实际被调用，限速后未再观察到 429 作为主失败原因。
- 失败集中在 LLM 输出契约：Demo0-Demo4 是 `REACT_DECISION_SCHEMA` 缺 `decision`；Demo5-Demo6 是 planner 违反 SkillPolicy allowlist。
- 因为当前是开发期严格模式，系统没有把这些错误静默 fallback 到确定性流程，这是符合“暴露问题并修 Agent”的目标的。
- 这些失败发生在 Vivado 调用之前，因此 run-llm 这轮没有完成真实 Vivado 综合验证。

### 3. 真实 hls4ml/Vivado 工具链基线验证结果（run，非 mock）
| Demo | 文件 | run_id | status | selected_path | report_status | 主要结果 |
|---|---|---|---|---|---|---|
| Demo 0 | `examples/dense_operator.json` | `dense_16x32_115c1f11_05` | `partial_success` | `fallback_template_path` | `success` | fallback HLS + Vivado work dir/report 生成成功 |
| Demo 1 | `examples/matmul_resource.json` | `matmul_16x16_resource_b0ad01f2_04` | `partial_success` | `fallback_template_path` | `success` | matmul fallback + Vivado work dir/report 生成成功 |
| Demo 2 | `examples/mnist_mlp_hls4ml.json` | `mnist_mlp_demo_88b12719_07` | `partial_success` | `unsupported_path` | `missing` | 真实 hls4ml 报 `Unsupported operation type: Gemm` |
| Demo 3 | `examples/mnist_tiny_cnn.json` | `mnist_tiny_cnn_6bbae346_07` | `partial_success` | `unsupported_path` | `missing` | 真实 hls4ml 报 `Unsupported operation type: Shape` |
| Demo 4 | `examples/mnist_qkeras_cnn.json` | `mnist_qkeras_cnn_4c10f7fa_05` | `partial_success` | `unsupported_path` | `missing` | h5/QKeras 输入被当前 ONNX parser 链路解析失败 |
| Demo 5 | `examples/tiny_residual_block.json` | `tiny_residual_block_b66fa9b1_06` | `partial_success` | `unsupported_path` | `missing` | residual boundary 按预期进入 unsupported 路径 |
| Demo 6 | `examples/resnet18_boundary.json` | `resnet18_boundary_demo_16dc6e00_05` | `partial_success` | `unsupported_path` | `missing` | ResNet18 boundary 按预期进入 unsupported 路径 |

补充现象：
- Demo2/Demo3 的 CLI stdout 被真实 hls4ml 打印的 `Output layers` / `Topology` 污染，导致外层 PowerShell `ConvertFrom-Json` 解析失败；但 run 目录中的 `state.json` 和 `summary.md` 正常生成。
- Demo0/Demo1 的 `vivado_work_dir` 已生成，说明本机 Vivado HLS bat 路径可被 adapter 调用。

### 4. 发现的问题与根因
1) LLM ReAct 输出缺少 `decision`
- 根因：当前 prompt/schema 约束还不足以让该 OpenAI-compatible 模型稳定返回严格 JSON 字段；客户端严格校验后正确报错。
- 下一步修复方向：加强 `REACT_SYSTEM_PROMPT` 的字段示例，增加 schema title/enum 提示，并在 error details 中保留脱敏后的 raw LLM payload，便于调试。

2) Boundary demo 的 LLM planner 违反 skill allowlist
- 根因：planner 会提出 `graph_rewrite.rewrite`、`report.write_unsupported`、`summary.write_summary` 等工具，但当前 selected skill allowlist 未覆盖这些工具或工具名注册不一致。
- 下一步修复方向：统一 skill YAML、ToolRegistry 注册名和 planner layered capability view；不应通过放宽 guard 解决。

3) Demo2/Demo3 真实 hls4ml 不支持当前 ONNX 图
- 根因：MNIST MLP 包含 `Gemm`；Tiny CNN 包含 `Shape`，当前 hls4ml 转换链路不支持。
- 下一步修复方向：实现 graph rewrite：`Gemm -> MatMul + Add`，并对 `Shape`/reshape/flatten 做静态消除。

4) Demo4 QKeras/H5 输入链路不匹配
- 根因：当前 adapter 的真实模型解析链路按 ONNX ModelProto 解析，不能直接解析 `.h5`。
- 下一步修复方向：增加 QKeras/H5 frontend 分支，或先导出为 hls4ml 支持的 Keras/QKeras 输入格式。

5) 真实 hls4ml stdout 污染 CLI JSON 输出
- 根因：底层库直接向 stdout 打印，CLI 同时输出 JSON state，导致调用方无法直接 `ConvertFrom-Json`。
- 下一步修复方向：adapter 捕获/重定向第三方 stdout 到 log artifact，CLI stdout 只输出 JSON。

### 5. 已修复内容（含修复方式）
- 本次主要是全量真实验证与问题定位，未改动业务代码。
- 新增/更新开发日志，记录真实 API、真实 Vivado、真实 hls4ml 的验证结果与后续修复方向。

### 6. 未修复完成的问题及原因
1) run-llm Demo0-Demo6 尚未真实跑通
- 原因：LLM 输出契约和 SkillPolicy allowlist 暴露真实问题；开发期不应静默 fallback。

2) Demo2-Demo4 尚未真实 hls4ml full success
- 原因：当前模型图和 frontend 与 hls4ml 支持范围不完全匹配，需要 graph rewrite / frontend 分支改造。

3) CLI JSON 输出仍可能被第三方 stdout 污染
- 原因：真实 hls4ml 库直接打印 stdout，需要后续在 adapter 层捕获。
---

## 2026-06-01 13:57:09 +08:00：中文 README、Demo0-Demo6 递进验收与 GitHub 发布准备
### 1. 本次测试做了什么
执行与验证：
- 将 `README.md` 重写为较详细中文版本，覆盖项目边界、Agent 架构、两层 ReAct、Specialist、Memory、运行模式、Demo 路线、环境变量、测试和目录结构。
- 使用独立目录运行：`D:\hls_agent\standalone_work\dl-op-to-hls-agent`。
- 按 Demo0 → Demo6 递进运行稳定演示验收命令：`python -m dl_op_to_hls.cli run <example> --mock-tools`。
- 运行时显式设置：`PYTHONPATH=src`、`DL_OP_TO_HLS_OPTIMIZATION_FALLBACK_MODE=demo`。
- 生成本轮 Demo 摘要：`runs/demo0_6_progressive_summary_20260601.json`。

### 2. Demo0-Demo6 递进结果
| Demo | 文件 | run_id | status | selected_path | report_status | 说明 |
|---|---|---|---|---|---|---|
| Demo 0 | `examples/dense_operator.json` | `dense_16x32_115c1f11_03` | `partial_success` | `fallback_template_path` | `success` | fallback template 工程闭环可用 |
| Demo 1 | `examples/matmul_resource.json` | `matmul_16x16_resource_b0ad01f2_02` | `partial_success` | `fallback_template_path` | `success` | matmul resource trade-off 演示可用 |
| Demo 2 | `examples/mnist_mlp_hls4ml.json` | `mnist_mlp_demo_88b12719_05` | `success` | `hls4ml_path` | `success` | hls4ml 主路径演示可用 |
| Demo 3 | `examples/mnist_tiny_cnn.json` | `mnist_tiny_cnn_6bbae346_05` | `success` | `hls4ml_path` | `success` | tiny CNN 主路径演示可用 |
| Demo 4 | `examples/mnist_qkeras_cnn.json` | `mnist_qkeras_cnn_4c10f7fa_03` | `success` | `hls4ml_path` | `success` | qkeras/量化演示路径在 mock-tool 验收中可用 |
| Demo 5 | `examples/tiny_residual_block.json` | `tiny_residual_block_b66fa9b1_04` | `partial_success` | `unsupported_path` | `missing` | residual boundary 按预期进入边界/unsupported 路径 |
| Demo 6 | `examples/resnet18_boundary.json` | `resnet18_boundary_demo_16dc6e00_03` | `partial_success` | `unsupported_path` | `missing` | ResNet18 boundary 按预期不盲目承诺 full synthesis |

### 3. 发现的问题与根因
1) 直接运行 `python -m dl_op_to_hls.cli ...` 会找不到包
- 根因：当前独立目录尚未 editable install，Python 默认搜索路径不包含 `src`。
- 处理：本轮命令显式设置 `PYTHONPATH=src`；README 中也写明该运行方式。
2) Demo 验收需要区分 mock-tool 与真实工具
- 根因：Demo0-Demo6 的演示验收目标是稳定展示 Agent 工程闭环；真实 hls4ml/Vivado 环境会受到本机依赖、license、模型图和 API 限速影响。
- 处理：本轮明确使用 `--mock-tools`，并在 README 和本日志中标注，不把它伪装成真实 Vivado 综合。
3) GitHub 发布前需要确认不泄露 API Key
- 根因：历史对话中出现过 API Key，但不能写入仓库。
- 处理：上传前用 `rg` 检查仓库文件，未发现真实 API Key；代码中只保留环境变量读取方式。

### 4. 已修复内容（含修复方式）
修复文件：
- `README.md`
- `docs/development_log.md`

关键修复点：
- README 从简短英文说明扩展为中文交付文档。
- README 明确 `run` / `run-llm` 差异、Specialist Local ReAct、strict/demo 优化建议模式、Demo0-Demo6 运行方式。
- development log 继续按“最新在最上面”的顺序追加本次 Demo 验收记录。

### 5. 未修复完成的问题及原因
1) 本轮 Demo 使用 mock-tool 验收，不代表真实 Vivado HLS 综合全通过
- 原因：本次目标是仓库发布前的递进演示验收；真实工具链测试需要单独记录 hls4ml/Vivado 环境、license、模型转换错误和运行耗时。
2) 独立目录尚未安装为 editable package
- 原因：为了避免修改用户全局 Python 环境，本轮使用 `PYTHONPATH=src` 运行；后续可执行 `python -m pip install -e .` 改善 CLI 体验。
---

## 2026-06-01 12:32:30 +08:00：Specialist Local ReAct 与优化建议 strict/demo 模式
### 1. 本次测试做了什么
执行与验证：
- 新增 Specialist local ReAct decider / guard / schema / prompt。
- 将 HLS4MLSpecialist、VivadoSpecialist、VerificationSpecialist、OptimizationSpecialist、MemorySpecialist 的局部工具调用接入 local ReAct 决策。
- 将 `suggestion.suggest_optimization` 的 rule fallback 改成可配置模式：`demo` 允许规则建议，`strict` 下 LLM 不可用或失败即返回 `LLMGenerationError`。
- 新增并运行 focused 回归：`python -m pytest tests/test_specialist_react.py tests/test_specialists.py tests/test_llm_optimizer_fallback.py tests/test_llm_runtime_plan_validation.py tests/test_llm_react_decision_guard.py tests/test_llm_todo_plan_schema.py tests/test_llm_trace_events.py tests/test_llm_runtime_no_silent_legacy_fallback.py -q`，结果：42 passed。
### 2. 发现的问题与根因
1) Specialist 内部仍是固定工具编排
- 根因：虽然 Main Agent 已经不能直接看 specialist 私有 tool，但 specialist 自己的 `handle()` 仍然直接调用工具，没有独立的局部 ReAct action schema。
2) Specialist 越权调用需要在局部层直接暴露
- 根因：如果把越权工具温柔转换成普通失败，会让 guard 契约不够尖锐；开发期应该直接暴露 schema violation。
3) 优化建议仍存在隐式规则 fallback
- 根因：`suggest_optimization` 在无 LLM 或 LLM 异常时默认走 rule fallback，开发期会掩盖 API / prompt / schema 问题。
### 3. 已修复内容（含修复方式）
修复文件：
- `src/dl_op_to_hls/specialists/react.py`
- `src/dl_op_to_hls/specialists/base.py`
- `src/dl_op_to_hls/specialists/hls4ml_specialist.py`
- `src/dl_op_to_hls/specialists/vivado_specialist.py`
- `src/dl_op_to_hls/specialists/verification_specialist.py`
- `src/dl_op_to_hls/specialists/optimization_specialist.py`
- `src/dl_op_to_hls/specialists/memory_specialist.py`
- `src/dl_op_to_hls/llm/schemas.py`
- `src/dl_op_to_hls/llm/prompts.py`
- `src/dl_op_to_hls/llm/optimizer.py`
- `src/dl_op_to_hls/tools/suggest_optimization.py`
- `tests/test_specialist_react.py`
- `tests/test_specialists.py`
- `tests/test_llm_optimizer_fallback.py`

关键修复点：
- 新增 Specialist action schema：`call_tool`、`mark_blocked`、`mark_failed`、`finish_with_result`。
- 新增 `SPECIALIST_REACT_SYSTEM_PROMPT`，和 Main Agent ReAct prompt 分离。
- 新增 `SpecialistReActGuard`，`call_tool` 必须命中当前 specialist 的 `allowed_tools`。
- 新增 `SpecialistReActDecider`，输入限定为 `ContextEnvelope`、`allowed_tools`、recent specialist observations、candidate arguments。
- `BaseSpecialist` 新增 `_local_react_step()`，每个工具调用前记录局部 ReAct 决策。
- 每个 specialist 现在先通过 local ReAct 决策，再通过 ToolRegistry 调工具。
- `suggest_optimization` 新增 `fallback_mode`：默认 `demo`，可通过参数/context/环境变量 `DL_OP_TO_HLS_OPTIMIZATION_FALLBACK_MODE=strict` 切到严格模式。
### 4. 当前结果
- Focused 回归通过：42 passed。
- Main Agent ReAct 与 Specialist ReAct 已分成两套 schema：Main Agent 负责 delegation/direct-tool/replan/block/fail；Specialist 负责局部 call_tool/block/fail/finish。
- strict 模式下，无 LLM 的优化建议不会再自动规则兜底，而是返回结构化 `LLMGenerationError`。
### 5. 未修复完成的问题及原因
1) 尚未运行全量 `pytest`
- 原因：本次先完成架构契约 focused 回归，尚未花更长时间跑全部测试矩阵。
2) Specialist local ReAct 当前支持 LLM decider，但默认仍有 deterministic policy
- 原因：无 API 或测试环境下仍需要可测的本地决策路径；它不是静默兜底，而是显式的局部策略，所有决策都会进入 observations。
---

## 2026-06-01 12:26:23 +08:00｜Main Agent 动作层、分层工具视图与 Specialist 隔离契约加固

### 1. 本次测试做了什么

执行与验证：
- 新增 Main Agent action schema。
- 将 planner 输入从扁平 `available_tools` 改为分层能力视图。
- 收紧 Main Agent ReAct，只允许高层动作。
- 为 specialist 隔离和本地工具调用契约增加测试。
- 运行回归：`python -m pytest tests/test_llm_runtime_plan_validation.py tests/test_llm_react_decision_guard.py tests/test_llm_todo_plan_schema.py tests/test_specialists.py tests/test_llm_trace_events.py tests/test_llm_runtime_no_silent_legacy_fallback.py -q`（36 passed）。

### 2. 已修复内容（含修复方式）

修复文件：
- `src/dl_op_to_hls/llm/actions.py`
- `src/dl_op_to_hls/llm/planner.py`
- `src/dl_op_to_hls/llm/react.py`
- `src/dl_op_to_hls/llm/prompts.py`
- `src/dl_op_to_hls/llm/guards.py`
- `src/dl_op_to_hls/llm/client.py`
- `src/dl_op_to_hls/main_agent/llm_runtime.py`
- `tests/test_llm_todo_plan_schema.py`
- `tests/test_llm_react_decision_guard.py`
- `tests/test_llm_runtime_plan_validation.py`
- `tests/test_specialists.py`

关键修复点：
- 新增 Main Agent action schema：`delegate_to_specialist`、`direct_tool_only_when_no_specialist`、`request_replan`、`mark_blocked`、`mark_failed`。
- Planner 现在接收 layered capability view：
  - `main_agent_actions`
  - `direct_tools`
  - `available_specialists`
- Main Agent planner 不再直接接收 specialist 私有工具列表，例如 `hls4ml.*`、`vivado.*`、`memory.*`、`suggestion.*`。
- Specialist 私有 tool 若未分配对应 specialist，plan validator 会直接拒绝。
- Specialist-owned todo 的 Main Agent ReAct 只允许 `delegate_to_specialist`、`request_replan`、`mark_blocked`、`mark_failed`。
- Atomic todo 的 Main Agent ReAct 只允许 `direct_tool_only_when_no_specialist`、`request_replan`、`mark_blocked`、`mark_failed`。
- JSON normalize 层不再在缺失 `decision` 时自动补 `call_tool`。
- LLM reflection 失败不再调用父类逻辑继续执行，而是明确标记失败。
- 增加 specialist 契约测试，确认每个 specialist：
  - 只接收 `ContextEnvelope`。
  - 只调用自身 `allowed_tools`。
  - 只返回 `SpecialistResult`。
  - 不把 `raw_log`、`stdout`、`stderr` 合入返回结果。

### 3. 剩余架构问题与原因

1) Specialist 内部仍主要是确定性编排
- 原因：当前 specialist 的 `handle()` 内部直接按固定逻辑调用工具，还没有自己的 LLM local ReAct decider。
- 影响：隔离边界已经更清楚，但还不是完整的“Specialist 局部 ReAct”。

2) `suggest_optimization` 中仍存在 rule fallback
- 原因：优化建议工具为了无 LLM/LLM 失败时可输出建议，仍有规则建议兜底。
- 影响：这是工具内部的建议生成兜底，不会绕过 Main Agent/Specialist 的权限边界，但开发期需要在结果中显式标记 `llm_fallback_used`。

3) Deterministic `run` 模式仍存在
- 原因：项目保留 `run` 作为非 LLM 基线流程，`run-llm` 才是 LLM-first Agent 流程。
- 影响：这不是 `run-llm` 的静默 fallback，但文档和 CLI 输出需要继续强调两者不同。

### 4. 下一步建议

- 为 Specialist 增加独立 local ReAct decider：
  - 输入：`ContextEnvelope`、`allowed_tools`、recent specialist observations。
  - 输出：`call_tool`、`mark_blocked`、`mark_failed`、`finish_with_result`。
- 给每个 Specialist 增加 prompt 和 guard，形成 Main Agent ReAct 与 Specialist ReAct 两层不同 schema。
- 把 `suggest_optimization` 的 rule fallback 改为开发期可配置：strict 模式下 LLM 失败即失败，demo 模式下才启用规则建议。

## 2026-06-01 12:13:24 +08:00｜开发期严格模式纠偏：禁止静默 fallback 掩盖 Agent 架构问题

### 1. 本次测试做了什么

执行与验证：
- 重新审查 `LLMFirstRuntime.execute_todo_with_react` 与 `LLMGuard.validate_todo_plan`。
- 增加测试：`test_llm_plan_rejects_tool_specialist_mismatch`。
- 运行回归：`python -m pytest tests/test_llm_runtime_plan_validation.py -q`（3 passed）。

### 2. 关键概念澄清

本项目中有两类容易混淆的 fallback：
- 领域路径 fallback：例如 hls4ml 不支持算子时，进入 `fallback_template_path` 或 `unsupported_path`。这是任务书要求的 HLS 工作流分支。
- Agent 运行时 fallback：例如 LLM 计划非法时，系统自动切回确定性 todo 或直接执行 assigned tool。开发阶段不应该依赖这种兜底，因为它会掩盖 planner、tool scope、specialist isolation 的真实问题。

本次纠偏针对第二类：Agent 运行时静默兜底。

### 3. 发现的问题与根因

1) LLM 获取到了不该直接使用的 tool
- 根因：计划 prompt / guard / specialist scope 三者没有形成闭环约束。LLM 在 Main Agent 层仍能规划底层工具与 specialist 的组合，而不是只看到当前层级允许的动作。

2) Sub-agent 隔离没有完全生效
- 根因：Main Agent 的 ReAct 分支允许对 specialist-owned todo 做 `call_tool`，这让本应由 specialist 内部处理的局部工具决策泄漏到了 Main Agent 层。

3) “优先走 specialist”不是理想最终形态
- 说明：它只是防止 Main Agent 越权执行底层工具的保护。顶尖 Agent 的目标应该是：Main Agent 只做 delegation/merge/reflect；Specialist 内部再做局部 ReAct，并且只能看到自己的 `allowed_tools` 与 `ContextEnvelope`。

4) Guard reject 后回退执行 assigned tool 是错误方向
- 根因：这会把安全/契约错误变成“系统帮忙跑完”，导致开发期看不到真正的 planner 或 prompt 问题。

### 4. 已修复内容（含修复方式）

修复文件：
- `src/dl_op_to_hls/main_agent/llm_runtime.py`
- `src/dl_op_to_hls/llm/guards.py`
- `tests/test_llm_runtime_plan_validation.py`

关键修复点：
- `run-llm` 的计划验证失败后不再静默切到确定性 skill expansion，而是直接返回 `LLMGenerationError`，并带出 `last_plan` 供调试。
- specialist/tool 错配时直接拒绝，记录 `PermissionDeniedError`，不再把 specialist 清空后继续执行。
- ReAct 决策被 guard 拒绝时直接失败并记录结构化错误，不再自动执行 todo 的 assigned tool。
- plan validator 增加检查：`assigned_tool` 必须属于 `assigned_specialist.allowed_tools`。
- 增加测试覆盖 specialist-tool mismatch。

### 5. 当前仍未完成的问题

1) Main Agent 与 Specialist 的 ReAct 层级还需要进一步拆清
- 当前 Main Agent 仍会调用 LLM ReAct 判断每个 todo 的动作。
- 更好的设计是：Main Agent 对 specialist-owned todo 只允许 `delegate_to_specialist`、`mark_blocked`、`request_replan` 等高层动作；底层 `call_tool` 只出现在 Specialist 内部 ReAct。

2) Tool exposure 还需要分层
- 当前 planner 仍可能看到较多底层 tools。
- 下一步应按层级暴露能力：Main Agent 看 specialist/action schema；Specialist 看自己的 scoped tools；ToolRegistry 继续执行原子动作。

3) Specialist 内部 ReAct 还不够完整
- 目前部分 specialist 仍是确定性工具编排。
- 下一步需要让 specialist 在自己的 `ContextEnvelope` 和 `allowed_tools` 内执行局部 ReAct，同时保留可审计 trace。

### 6. 下一步建议

- 引入 Main Agent action schema：`delegate_to_specialist`、`direct_tool_only_when_no_specialist`、`request_replan`、`mark_blocked`、`mark_failed`。
- 将 planner prompt 的 tool 列表改为层级视图：Main Agent 不直接看到 specialist 私有 tool。
- 为每个 Specialist 增加本地 ReAct loop 测试：确保它只接收 `ContextEnvelope`，只调用 `allowed_tools`，只返回 `SpecialistResult`。

---

## 2026-06-01 12:07:04 +08:00｜LLM Agent Demo 全量失败排查与修复

### 1. 本次测试做了什么

工作目录（独立目录）：
- `D:\hls_agent\standalone_work\dl-op-to-hls-agent`

执行与验证：
- 检查运行配置：`python -m dl_op_to_hls.cli llm-status`
- 在真实环境下运行 `run-llm`（非 mock）：
  - hls4ml：已安装（`hls4ml 1.3.0`）
  - Vivado HLS：`D:\Xilinx\Vivado\2018.3\bin\vivado_hls.bat`
  - LLM API：`https://token-plan-sgp.xiaomimimo.com/v1`，模型 `mimo-v2.5-pro`
- 重跑 Demo0~Demo6，并生成汇总：
  - `runs/demo_rerun_after_fixes_final_20260601.json`
- 回归测试：
  - `python -m pytest tests/test_llm_runtime_plan_validation.py -q`（通过）

### 2. 发现的问题与根因

1) 独立目录权限问题（历史目录）
- 现象：`runs/` 目录不可写，导致数据库和运行产物无法创建。
- 根因：旧独立包目录 ACL/权限异常，写入被拒绝。

2) Specialist Todo 被 LLM “call_tool”分支绕开
- 现象：出现 `KeyError: 'model_path'` / `KeyError: 'hls_project_dir'`。
- 根因：带 specialist 的 todo 未强制走 specialist，导致工具入参由自由动作拼接，缺字段。

3) LLM 计划中 specialist 与 tool 错配
- 现象：如 `task.validate_schema` 被分配给 `HLS4MLSpecialist`，触发 `PermissionDeniedError`。
- 根因：计划校验未检查 “assigned_tool 是否在 assigned_specialist.allowed_tools 内”。

4) Guard 拒绝后直接失败
- 现象：一个 ReAct 决策不合法就直接 fail，流程中断。
- 根因：guard reject 没有兜底回退到确定性执行路径。

5) hls4ml convert/config 失败后仍继续 run_csim
- 现象：`hls4ml.run_csim` 缺 `hls_project_dir`，触发失败。
- 根因：context 未提供 `hls_project_dir`，且 specialist 没有“缺项目目录则跳过”的保护。

### 3. 已修复内容（含修复方式）

修复文件：
- `src/dl_op_to_hls/main_agent/llm_runtime.py`
- `src/dl_op_to_hls/main_agent/reflector.py`
- `src/dl_op_to_hls/main_agent/runtime.py`
- `src/dl_op_to_hls/llm/guards.py`
- `src/dl_op_to_hls/specialists/context.py`
- `src/dl_op_to_hls/specialists/hls4ml_specialist.py`

关键修复点：
- 对于命中 specialist 的 todo，优先走 specialist 执行路径，避免参数丢失。
- 增加 specialist-tool 一致性校验，阻止错配计划通过。
- guard 拒绝时回退到 todo 的确定性执行，不直接失败。
- 为 HLS4MLSpecialist 增加 `run_csim` 前置检查：缺 `hls_project_dir` 时标记 `skipped`（可恢复）。
- 将 hls4ml 可恢复失败（如 `HLS4MLConversionError`）转为 `completed_with_warning` 并触发 unsupported/boundary 分支。
- 优化状态汇总逻辑，避免 `initialized` 等异常终态残留。

### 4. 当前结果（修复后）

汇总文件：
- `runs/demo_rerun_after_fixes_final_20260601.json`

结果概览：
- Demo0 `dense_operator.json`：`partial_success`（fallback 路径可用）
- Demo1 `matmul_resource.json`：`partial_success`（fallback 路径可用）
- Demo2 `mnist_mlp_hls4ml.json`：`partial_success`
- Demo3 `mnist_tiny_cnn.json`：`partial_success`
- Demo4 `mnist_qkeras_cnn.json`：`partial_success`
- Demo5 `tiny_residual_block.json`：`partial_success`（boundary 预期）
- Demo6 `resnet18_boundary.json`：`partial_success`（boundary 预期）

### 5. 未完全修复项与原因

1) Demo2 未进入 full hls4ml success
- 原因：模型包含 `Gemm`，当前 hls4ml 转换链路报 `Unsupported operation type: Gemm`。

2) Demo3 未进入 full hls4ml success
- 原因：模型图包含 `Shape`，当前转换链路不支持该 op。

3) Demo4 未进入 full hls4ml/qkeras success
- 原因：`mnist_qkeras_cnn.h5` 与当前 onnx/hls4ml 解析链路不匹配，报 `Error parsing onnx.ModelProto`。

4) Demo6 保持 boundary/unsupported
- 原因：ResNet18 本身按任务书即为“边界/不承诺”演示目标，当前行为符合预期。

### 6. 下一步建议

- 为 Demo2/Demo3 增加稳定 graph rewrite（如 Gemm→MatMul+Add、Shape 消除/静态化）。
- 为 Demo4补齐“QKeras → 可转换 ONNX/hls4ml”导出流程（非占位 h5）。
- 将“boundary/unsupported”路径与“full success”路径分层展示，避免演示期望混淆。

---

