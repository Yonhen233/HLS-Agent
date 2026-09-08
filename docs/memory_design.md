# Memory Design

## Layering

本项目把 memory 分成五层：

- `L0 Runtime State`
- `L1 Short-term Memory`
- `L2 Long-term Episodic Memory`
- `L3 Long-term Semantic Memory`
- `L4 Skills Layer`

## L0 Is Not Memory

文档上必须明确：

`L0 is runtime state, not memory.`

L0 对应：

- `AgentState`
- `state.json`
- current todo
- current tool outputs
- current errors
- selected path

它的职责是支撑执行、恢复和可观测性，而不是长期记忆。

## L1 Short-term Memory

L1 保存当前 run 内仍然有价值的压缩上下文：

- recent tool observations
- compressed Vivado summaries
- recent decisions
- recent errors

文件：

- `runs/<run_id>/memory/short_term.json`
- `runs/<run_id>/memory/compressed_context.json`

## L2 Long-term Episodic Memory

L2 回答“以前发生过什么”：

- 某次 run 用了哪条 path
- 最终 status 是什么
- latency / II / DSP / LUT / BRAM / FF
- 哪个 failure 发生过

主存储：

- `experiments`
- `implementations`
- `synthesis_runs`
- `failures`

## L3 Long-term Semantic Memory

L3 回答“我们从历史中学到了什么”：

- Dense 提高 ReuseFactor 常会降低 DSP 但增加 latency
- VivadoNotFoundError 是 recoverable
- II > 1 时优先检查 dependency / partition

主存储：

- `memory_facts`
- `memory_items` 中的 `semantic / optimization / failure`
- RAG 索引

## L4 Skills Layer

L4 更准确地说是 `Skills / Playbooks`：

- hls4ml path skill
- fallback template skill
- Vivado synthesis skill
- unsupported operator skill

主存储：

- `procedural_memories`
- 相关文档 / playbook

## SQLite vs RAG

这里也必须明确：

- `SQLite is the source of truth.`
- `RAG is the retrieval layer.`

SQLite 保存结构化事实；RAG 只负责把可检索文本切块后辅助找回。

## Promotion Policy

会 promote 的内容：

- verified implementation
- 新 failure type
- synthesis metrics
- optimization suggestions
- hls4ml unsupported reason
- successful repair
- 可复用 workflow / skill

不会 promote 的内容：

- 原始长日志
- 重复 stdout
- 临时路径
- 未压缩 report 原文
- 无意义 tool output

## Decision Ledger and Trace

系统只保存一份运行历史文件：`runs/<run_id>/trace.jsonl`。Trace 是唯一的运行事实源，既包含 Run、Todo、Specialist、Tool 等生命周期事件，也包含结构化的 `DecisionRecorded` 事件。Decision Ledger 不是第二份可变文件，而是 `TraceReader` 从 Trace 中生成的只读投影视图。

`DecisionRecorded` 保存 Todo 决策、触发原因、决策前后状态、结果和 artifact evidence refs。`trace.query` 通过 ToolRegistry 和 PermissionGate 提供以下有界视图：

- `decision_ledger`
- `todo_history`
- `failures`
- `evidence`
- `memory_context`

MemorySpecialist 只能查询当前 run，不能读取其他 run，也不接收完整 `trace.jsonl`。读取器按字段白名单移除 raw log、stdout、stderr、完整代码和完整 Trace 字段，并限制返回条数；长任务优先保留最新记录。

启用 LLM 时，MemorySpecialist 把候选经验和有界 Decision Ledger 交给 LLM。LLM 可以决定保留多少条候选、如何把它们表达为可复用设计经验，但只能通过 `source_index` 和 `decision_indexes` 引用已有候选和已有决策。原始验证状态、综合报告和 evidence refs 由确定性代码保留，最终是否允许 promotion 仍由 MemoryPolicy 决定。未启用 LLM 的确定性运行继续保留原候选，不伪装成 LLM 总结。
