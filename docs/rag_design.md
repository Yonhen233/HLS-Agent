# RAG Design

## Role

RAG 不是主数据库。SQLite 是 source of truth，RAG 只做经验检索层。

## Indexed Sources

- `summary.md`
- `suggestions.md`
- `compressed_logs.json`
- `report.json`
- `docs/*.md`
- `failures.log_summary`

## P0 Implementation

P0 用 SQLite 表 `rag_chunks` 存储切块文本，再用轻量 token-overlap 相似度检索，不依赖外部向量数据库。

## Retrieval Contract

查询返回：

- `source_id`
- `score`
- `text`
- `metadata`

Agent 只把压缩后的摘要放进 `AgentState.rag_context`，不能让历史经验覆盖当前综合报告事实。

