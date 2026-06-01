# 开发日志（Development Log）

维护约定：
- 从 **2026-06-01** 起，所有后续 bug 修复都追加到本文件，不新建分散日志。
- 每次记录必须包含：时间、测试动作、问题根因、修复方案、未修复原因。

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

