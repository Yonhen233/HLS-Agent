# Senior Agent Review

## 1. 整体流程

仓库里师兄的主流程集中在 `orchestrator.py` 与 `HLSVerificationEnv` 一类脚本里，目标是围绕 C/C++ 到 HLS 的生成、验证、诊断和修复形成闭环。它更偏研究型 orchestration，而不是面向当前任务书的轻量产品化包结构。

## 2. 输入输出格式

现有代码主要围绕代码字符串、testbench 字符串、工作目录和多阶段日志字典运转，不是我们现在要求的标准化任务 JSON。适合复用到 adapter 层，不适合原样作为 CLI 契约。

## 3. HLS C++ 生成方式

师兄代码更偏“分析-修复-验证”链路，本身不专注于深度学习算子模板化生成。对当前项目来说，更适合保留验证侧能力，而由新项目自己提供 fallback templates。

## 4. TCL 生成方式

`hls_verification_env.py` 中 `create_project_tcl()` 与 `_build_stage_tcl()` 已经具备很好的可复用价值：

- 自动生成 `open_project / add_files / set_top / open_solution / create_clock`
- 区分 `csim / csynth / cosim`
- 支持 testbench 与附属文件

这部分非常适合封装到 `vivado_hls_adapter.py`。

## 5. Vivado HLS 调用方式

`HLSVerificationEnv` 内部已经处理：

- `vivado_hls` 路径解析
- Windows 下 `vivado_hls.bat` 兼容
- 独立 workspace 创建
- subprocess 执行与超时
- cosim watchdog

这是当前仓库里最值得直接桥接复用的模块。

## 6. stdout/stderr 捕获

师兄代码将 stdout/stderr 分流到实时日志文件，再合并写回阶段日志，适合我们保留到 real adapter 路径中。

## 7. report 解析方式

现有仓库对日志证据抓取做得比较强，`project_log_evidence.py` 能抽取错误上下文。当前 P0 里我们只保留轻量 report parser，把更复杂的日志证据抽取作为后续增强点。

## 8. 错误处理方式

师兄代码错误处理覆盖面广，尤其是：

- 超时
- watchdog 中止
- 编码回退
- synthesis / cosim 失败证据收集

这说明适配层应优先吸收其“运行与证据”能力，而不是重新发明一套 subprocess 管理逻辑。

## 9. 可直接复用于 Vivado HLS MCP 的代码

最值得复用的是 `HLSVerificationEnv`：

- `create_project_tcl`
- `run_with_existing_tcl`
- 阶段化 TCL 生成
- 日志与 timeout 管理

辅助复用点：

- `project_log_evidence.py`
- 设计文件 / 证据抽取逻辑

## 10. 需要重构的地方

- 现有脚本缺少标准 package/CLI/pyproject 结构
- 输入格式不是任务书要求的三类 JSON
- 数据落盘缺少统一 artifact/state/trace/SQLite/RAG 契约
- 工具调用没有统一 ToolRegistry 和 PermissionGate

## 结论

新项目应当：

- 新建独立 `src/dl_op_to_hls` 包结构
- 把师兄现有验证能力下沉为 `senior_agent_adapter.py` 和 `vivado_hls_adapter.py`
- 不直接搬运整套 orchestrator
- 保留其强项：Vivado HLS 路径解析、TCL 生成、阶段执行、日志处理
