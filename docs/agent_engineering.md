# Agent Engineering

## Tool Registry

所有工具通过 `ToolRegistry.call()` 调用。它负责：

- 权限检查
- `PreToolUse` / `PostToolUse` / `ToolFailed` 事件
- trace hash 记录
- JSON 可序列化约束

## Permission Gate

`PermissionGate` 检查：

- 读路径是否落在允许目录
- 写路径是否落在 `runs/`
- 命令是否命中 allow / ask / deny 列表

P0 中 `ask` 视为 deny，从而避免默认执行高风险命令。

## Hook / Trace

Hook 负责生命周期事件：

- `RunStarted`
- `PreToolUse`
- `PostToolUse`
- `ToolFailed`
- `PermissionDenied`
- `ArtifactCreated`
- `ContextCompressed`
- `RagRetrieved`
- `DbRecordCreated`
- `RunFinished`

Trace 以 `jsonl` 输出，便于逐行调试与后续分析。

## AgentState

`AgentState` 保存：

- 任务与目标
- 规划
- 选定路径
- hls4ml 支持状态
- HLS/Vivado 工作目录
- 报告、建议、RAG 上下文
- 错误与工具结果

## Artifact Manager

每个生成文件都写入 `artifacts.json`，记录：

- type
- absolute path
- sha256
- created_at

## Structured Error

统一错误格式 `AgentError` 支持：

- 错误类型
- message
- recoverable
- source
- suggested_action
- details

这让 graceful failure 和总结输出更一致。

## Context Compression

大日志与原始报告不直接进入 AgentState，只保留压缩摘要与关键指标，避免上下文污染。

## RAG

RAG 只做辅助检索，不覆盖当前结构化 report 事实。它主要复用：

- summary
- suggestions
- compressed logs
- report.json
- docs

## MCP 解耦

MCP 风格适配把 Agent 与具体 EDA 工具解耦。当前 P0 用 in-process registry，后续可替换成真实 MCP client/server。

