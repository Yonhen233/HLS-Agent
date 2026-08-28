# 算子能力与证据审计

审计时间：2026-08-28。审计目标不是证明项目“全绿”，而是把声明、单元证据、Mock、Fixture 与真实 Vivado 证据拆开。

## 当前结论

项目已具备 Dense、MatMul、ReLU、Add、ScaleShift、Conv2D 六类算子的统一数值 Case Schema。默认算子生成策略已设为 `llm_candidate`；Dense、MatMul、ReLU、Add 的模板只保留作公平基线和已验证实现复用，不是 LLM 失败后的静默降级。hls4ml 不参与本轮算子生成主路径。

新口径审计得到 120 个 Layer-1 Golden Case。它们证明数学参考、定点量化、输入族和形状推导可以复现，不证明 HLS CSim/CSynth 已通过。当前可验证的历史 Artifact 累积为 Real CSim 3、Real CSynth 3、Mock 4；不满足新字段的旧 Run 不会被倒推为真实锚点。

## 支持路径

| Operator | LLM Candidate | Template baseline | Graph pattern inventory | 当前边界 |
|---|---:|---:|---|---|
| Dense | yes | yes | Gemm、MatMul+Add | 静态 Shape；模型路径要求静态权重 |
| MatMul | yes | yes | 静态 MatMul | 静态 Shape |
| ReLU | yes | yes | Relu | 静态长度 |
| Add | yes | yes | bias Add | residual/branch Add 不宣称支持 |
| ScaleShift | yes | no | none | 必须通过生成、repair、CSim、CSynth 闭环 |
| Conv2D | yes | no | Conv 相关模式仅用于图检查 | 静态 NHWC、group=1、静态权重/Bias、valid/same |

## 证据分类

统一分类为 `unit`、`mock`、`fixture`、`real_csim`、`real_csynth`、`rtl_cosim`、`implementation`。真实证据必须同时满足：

- Artifact 位于当前 Run；
- Artifact 时间不早于 Run；
- 保存 SHA256；
- CSim 有独立 Golden 成功标记且无失败标记；
- CSynth 报告包含 Latency、II、Resource、Timing；
- `mock_evidence=false`，且来源不在 `tests/fixtures`。

历史 Run 不满足新字段时保留原数据，但只归入未迁移/单元口径。不会为了让数字好看删除失败或自动升级证据。

## 发现的问题

1. 旧 Support 统计容易把同一 Run 的多个 Tool Receipt 当成多个 Case。现改为每个 Run、每个 evidence class 最多计一次。
2. 旧 LLM trace 记录了 token，但没有 call ID、阶段、累计量和异常原因。当前 101 次历史调用共 590,817 tokens、12 次异常；新调用已补充 call ID、stage、累计预算和异常标签。
3. 最新历史 Dense harness Run 含 Mock Vivado receipt。虽然完成门禁写明 `production_ready=false`，但不能进入真实 CSim/CSynth 成功率。
4. 历史开发日志中的 Vivado 结果不会根据文字描述反推真实计数；只有仍存在且通过 provenance/hash/语义检查的 Artifact 才能迁移。
5. Conv2D 已新增独立 Operator Task 和 LLM 静态契约，并完成 1 个真实 DeepSeek + Vivado 修复闭环；单次成功仍不足以宣称稳定 pass³。

## 当前不能宣称的内容

- 不能把 120/120 Golden Case 写成 120 个真实 HLS 通过案例。
- 不能把 Mock fixture 的 45-cycle 示例写成真实 Vivado 性能。
- 不能宣称 Conv2D 已稳定 pass³。
- 不能宣称 RTL Co-sim、Implementation 或板级部署已经完成。
