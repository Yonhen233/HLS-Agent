# Unsupported Path

当 hls4ml 不支持模型或算子时，Main Agent 按以下顺序处理：

1. `graph_rewrite.rewrite`
2. 自定义 layer 建议
3. fallback template
4. LLM candidate + verify
5. unsupported report

P0 中重点实现第 1、3、4、5 步。

## 当前策略

- operator JSON 默认优先 fallback template
- Dense / MatMul / ReLU / Add 直接走模板
- 其他算子走 mock LLM candidate
- 如果 candidate 验证失败，生成 `unsupported_report.md`

## 输出

unsupported 报告会给出：

- 原因
- rewrite/custom layer/fallback/reference implementation 等后续建议

