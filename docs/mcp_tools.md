# MCP Server 设计与运行

## 定位

项目使用官方 `mcp` Python SDK 2.x 构建 hls4ml 与 Vivado HLS MCP Server。MCP 只负责标准化工具发现、调用和传输；Tool Registry、Permission Gate、Trace、证据校验与 HLS adapter 仍是 Agent Harness 的领域能力。

```text
Main Agent / Specialist
  -> Tool Registry + Permission / Trace / Evidence
  -> MCP Proxy
  -> MCP stdio 或 Streamable HTTP
  -> Tool Registry + server-side Permission Gate
  -> hls4ml / Vivado HLS adapter
```

这形成两层防护：客户端网关限制 Agent 能调用什么，服务端网关限制 MCP 请求实际能访问哪些路径和命令。

## 标准协议能力

- 官方 SDK 负责 JSON-RPC 消息、生命周期和协议版本兼容。
- 本地传输使用标准 stdio，服务端 stdout 仅承载 MCP 消息；第三方库的普通输出会被 SDK 与协议流隔离。
- 远程/进程外传输使用标准 Streamable HTTP `/mcp` 端点，不使用自定义 REST API。
- `tools/list` 支持游标分页，游标带 HMAC 完整性保护。
- 工具描述同时公开 `inputSchema`、`outputSchema`、annotations 和项目风险元数据。
- `tools/call` 返回兼容文本内容与 `structuredContent`，并设置 `isError`。
- 调用支持 progress notification 和 `notifications/cancelled`。
- 客户端保存 bounded stderr tail，并可将完整 server stderr 写入日志 artifact。
- 非幂等 `tools/call` 不在传输层自动重放；只有 Tool Registry 根据 `idempotent` 声明执行安全重试。
- stdio MCP 子进程默认剥离 LLM API Key，避免 EDA Server 获得不需要的凭据。

官方 SDK Server 同时支持当前协议和握手式 `2025-11-25` 客户端。项目内同步 stdio bridge 使用 `2025-11-25` 握手模式，以适配现有同步 Agent Runtime；外部新客户端可直接使用官方 SDK 支持的当前协议。

## 启动方式

本地 Agent 推荐使用 stdio：

```powershell
$env:DL_OP_TO_HLS_MCP_TRANSPORT="stdio"
dl-op-to-hls agent-run examples\dense_operator.json --real-tools
```

独立启动 stdio Server：

```powershell
dl-op-to-hls serve-hls4ml --transport stdio
dl-op-to-hls serve-vivado-hls --transport stdio
```

启动本机 Streamable HTTP Server：

```powershell
dl-op-to-hls serve-hls4ml --transport streamable-http --host 127.0.0.1 --port 8000
dl-op-to-hls serve-vivado-hls --transport streamable-http --host 127.0.0.1 --port 8001
```

未配置 OAuth 时，HTTP 服务强制只监听 loopback，防止把具有本地文件和 EDA 执行能力的 Server 暴露到网络。跨机器部署必须通过官方 SDK 配置 OAuth 2.1 token verifier、Protected Resource Metadata、HTTPS 和反向代理，不能通过关闭此限制实现。

## 工具

hls4ml Server：

- `hls4ml.inspect_model`
- `hls4ml.check_support`
- `hls4ml.generate_config`
- `hls4ml.convert`
- `hls4ml.run_csim`

Vivado HLS Server：

- `vivado.create_project`
- `vivado.run_csim`
- `vivado.run_csynth`
- `vivado.parse_report`
- `vivado.parse_log`

## 长任务策略

Vivado 综合属于分钟级长任务。当前 Agent Harness 使用 checkpoint、durable queue、超时和取消通知管理生命周期，MCP 调用本身不会在连接异常后盲目重放。MCP `Tasks` 在规范中仍是实验能力，因此当前版本没有虚假声明 `tasks` capability；后续需要跨进程断线续取综合结果时，再把 durable queue 映射为标准 `tasks/get`、`tasks/result` 和 `tasks/cancel`。

## 安全边界

- stdio 适合本机 EDA：不监听端口，继承面更小。
- Streamable HTTP 默认启用 SDK 的 Host/Origin 防护、请求体上限、会话数量和空闲超时。
- 输入路径由 JSON Schema 的 `x-permission` 注解交给 Permission Gate 检查。
- 成功结果必须满足 ToolSpec `output_schema`，并继续经过语义证据门禁。
- 原始日志和大报告保存在 artifacts 中，MCP 返回结构化摘要和引用。

## 规范符合性边界

生产协议路径由官方 SDK 实现，而不是自研 JSON-RPC parser。Resources、Prompts、Sampling、Elicitation 和实验性 MCP Tasks 都是 MCP 的可选能力；本项目作为 HLS Tool Server 只声明实际实现的 Tools capability，不为“看起来完整”而声明空能力。HTTP 公网 OAuth 部署配置依赖部署方身份系统，仓库默认只提供安全的 loopback 服务。
