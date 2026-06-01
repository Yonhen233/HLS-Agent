# Architecture

## Goal

项目把深度学习算子/小模型转 HLS 的流程拆成 Agent 编排层和工具执行层：

- Agent 负责任务理解、路径选择、状态管理、上下文压缩、总结与建议
- hls4ml 与 Vivado HLS 通过 MCP 风格工具注册到统一 ToolRegistry
- SQLite 保存结构化结果，RAG 保存轻量经验片段

## Runtime Flow

1. CLI 读取任务 JSON
2. MainAgent 初始化 ToolRegistry / PermissionGate / DB / RAG
3. Workflow 创建 `runs/<run_id>`
4. Hook 写 trace，ArtifactManager 写 input/normalized_task/state/report/summary/suggestions
5. 根据 task_type 进入 model / operator / existing_hls_project 路径
6. 通过 registry 调用工具，不直接绕过工具层
7. 保存实验元数据、实现、综合结果、失败记录与 RAG chunk

## Core Components

- `ToolRegistry`: 强制统一工具调用入口
- `PermissionGate`: 控制读写目录和命令边界
- `HookManager`: 记录生命周期事件
- `TraceWriter`: 输出 `trace.jsonl`
- `ArtifactManager`: 管理运行产物与 `artifacts.json`
- `AgentState`: 保存任务全过程状态
- `MetadataRepository`: SQLite source of truth
- `RagMemory`: 历史经验检索

