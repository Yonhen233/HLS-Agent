# Operator Benchmark 当前报告

机器可读报告位于 `runs/benchmarks/operator_release.json`，Markdown 镜像位于 `runs/benchmarks/operator_release.md`。

当前阶段结果：120/120 Layer-1 Golden Case 可生成，覆盖 Dense 24、MatMul 24、ReLU 18、Add 18、ScaleShift 18、Conv2D 18。总体 Wilson 95% 区间为约 `[0.969, 1.0]`，但这个指标只属于 `unit` 证据。

当前历史证据审计识别到 Real CSim `3`、Real CSynth `3`、Mock `4`。其中 Conv2D `_09` 是本轮新增的真实 DeepSeek + Vivado HLS 锚点，已通过独立 Golden CSim、CSynth、timing 与当前 Run provenance 校验。

真实样本仍低于 Real CSim 18、Real CSynth 10 的门槛，LLM pass³ 与 False Success 故障注入也未完成，因此 `interview_ready=false`。这一状态是 Release Gate 的正确行为。

历史 token 审计识别到 101 次调用、590,817 tokens，p50 为 4,392 tokens/call，p95 为 8,009 tokens/call，共 12 次异常。新调用已带 call ID、stage 与 anomaly 标签；旧调用继续保留但标记为 legacy。
