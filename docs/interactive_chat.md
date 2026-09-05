# 交互式连续对话

项目提供 `dl-op-to-hls chat` 作为连续多轮 Agent 入口。它复用现有的 `SessionManager`、`LLMFirstRuntime`、`AgentState`、Todo、Memory、Trace 和 checkpoint，不会另写一套执行逻辑。

## 启动

```powershell
cd D:\hls_agent\standalone_work\dl-op-to-hls-agent
$env:PYTHONPATH = "src"
$env:DL_OP_TO_HLS_LLM_ENABLED = "1"
$env:DL_OP_TO_HLS_LLM_PROVIDER = "openai-compatible"
$env:DL_OP_TO_HLS_LLM_BASE_URL = "https://your-endpoint/v1"
$env:DL_OP_TO_HLS_LLM_MODEL = "your-model"
$env:DL_OP_TO_HLS_LLM_API_KEY = "your-api-key"
dl-op-to-hls chat
```

启动后可连续输入普通文本：

```text
> 把这个 Dense 算子转换成 HLS，优先优化 latency
> 在不明显增加 latency 的情况下继续降低 DSP
> 查看当前结果
```

后续请求会携带当前 session 的压缩摘要、最近消息和上一轮任务，由 `LLMTaskInterpreter` 生成完整结构化任务，再进入 Planner、Todo、Specialist 和 Tool 流程。

## 会话恢复

退出后 session 会保存在 SQLite。可以查看并恢复：

```powershell
dl-op-to-hls session-list
dl-op-to-hls chat --session-id <session_id>
dl-op-to-hls session-show <session_id>
dl-op-to-hls session-resume <session_id>
```

`/status` 或 `/session` 查看当前会话，`/help` 查看命令，`/exit` 或 `/quit` 退出。

## 上下文与错误边界

聊天终端只输出 session、run、状态、Todo 进度、selected path 和最近错误。完整状态仍保存到 `runs/<run_id>/state.json`，原始工具材料保存为 artifacts，调用过程保存到 `trace.jsonl`。较旧对话会由 `SessionManager` 压缩，LLM Runtime 继续使用已有 context budget、权限和完成门禁。

单轮 API 或 Agent 错误会记录到该轮状态并返回错误摘要，聊天循环仍等待下一条输入；这不等于把失败伪装成成功。
