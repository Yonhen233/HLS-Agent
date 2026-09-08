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

## Retrieval Pipeline

检索顺序是：

```text
namespace / domain / entity hard filter
    -> BM25/FTS5 ranking and embedding ranking
    -> Reciprocal Rank Fusion (RRF)
    -> Cross-Encoder second-stage reranking
    -> evidence and citation gate
```

域过滤发生在 RRF 之前，因此 BM25 和向量检索只能在同一个允许候选集上产生排名。RRF 使用排名而不是不可直接比较的原始分数，默认 `k=60`。Cross-Encoder 负责候选池的最终相关性排序，RRF 只作为召回融合和同分时的确定性依据。

## Provenance Policy

可信度不再作为 `final_score` 的软加权项。历史代码中的固定 `trust_weight` 已移除，因为它没有经过独立标注集校准。当前 provenance 只用于：

- 记录来源、时间、验证状态和 citation；
- 执行 domain/entity、过期、隔离和 prompt-injection 门禁；
- 为审计和 evidence receipt 提供依据。

因此“已验证实现优先”是资格和证据策略，不是人为给某类文本加一个未经学习的分数。若未来要学习来源质量，应在固定训练/验证/测试划分上校准，并报告置信区间，而不是直接修改常数。

## P0 Implementation

SQLite 表 `rag_chunks` 是 source of truth，保存切块、metadata 和 FTS5 索引；语义向量和 Cross-Encoder 是可重建的 retrieval index，不替代结构化数据库。

## Retrieval Contract

查询返回：

- `source_id`
- `score`
- `text`
- `metadata`

Agent 只把压缩后的摘要放进 `AgentState.rag_context`，不能让历史经验覆盖当前综合报告事实。

## Evaluation

项目保留两类互补评测，结果不能混用：

- 小型人工集合：12 个文档、9 条人工标注查询，用于快速回归检索语义和污染防护。历史结果 `Precision@K=88.89%`、`Recall=100%` 只适用于该集合。
- 真实历史集合：从功能验证通过且具有真实 CSynth evidence receipt 的 Run 自动构造 leave-one-run-out 弱监督 qrels，用于评估历史参数经验能否被复用。锚点 Run 从相关集合和返回结果中同时排除。

2026-09-07 的优化后真实历史评测使用 `16,062` chunks、`3,616` sources 和 `16,062` persisted embeddings，向量覆盖率为 `100%`；29 个 evidence-gated Run 形成 10 个组和 27 条有效查询。检索先按 `task_type/op_type/objective` 做结构化过滤；RRF 候选在进入 Cross-Encoder 前按 Run 限制 chunk 数，最终每个 Run 返回一条代表结果，避免长 artifact 的 chunk 数量成为隐式相关性权重。`top_k=5` 时结果如下：

| Retriever | Precision@5 | R-Precision | Recall@5 | Hit@5 | MRR | nDCG@5 | Pollution@5 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Structured lexical baseline | 57.78% | 100% | 100% | 100% | 100% | 100% | 0% |
| Domain filter + BM25/embedding + RRF + Cross-Encoder | 57.78% | 100% | 100% | 100% | 100% | 100% | 0% |

`Precision@5=57.78%` 采用标准固定 K 分母。许多任务组只有 2 个 leave-one-out peer，因此即使全部相关经验都被正确返回，Top-5 仍有 3 个空位；检索器不会用无关结果填满。相应地，平均 Returned-K fraction 也是 `57.78%`，而 R-Precision、Recall、MRR 和 nDCG 均为 `100%`。生产链路 median/p95 为 `392.002/927.305 ms`；相对本轮优化前的 `1920.282/6459.792 ms` 分别降低 `79.59%/85.64%`。

该大集合的标签由真实验证证据和结构化任务元数据生成，属于弱监督，不是独立人工 gold。结构化过滤字段与标签分组字段一致，因此这组 100% 指标只能证明“同类已验证历史参数经验的完整复用”，不能证明开放域语义检索完美。简历或报告引用时必须同时写明语料规模、查询数、`top_k`、leave-one-run-out、固定 K Precision 和弱监督口径；下一阶段应补充独立人工标注 hard-negative 集。
