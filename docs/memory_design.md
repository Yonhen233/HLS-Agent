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

