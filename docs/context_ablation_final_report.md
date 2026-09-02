# 上下文压缩真实消融评测报告

## 1. 实验规模

本实验固定 Git commit `95da930e7cc2d96cd5930813da8d8b9a24f0378c`，使用真实 `deepseek-v4-pro`、DeepSeek V4 官方离线 tokenizer 和 Vivado HLS 2018.3。首轮覆盖 12 个任务、A/B/C 各 12 次；对结果不一致、发生 LLM 格式错误或触发 repair/replan 的 9 个任务再独立复测两轮。总计 90 次真实运行，没有使用 mock、fixture、历史最佳 HLS 产物或静默模板替代。

- A：`full + raw`
- B：`scoped + raw`
- C：`scoped + compressed`，也是生产默认模式

完整机器结果位于 `benchmarks/context_ablation_final_results.json`。原始 Trace、State、API Usage 和 HLS 产物保存在本机 `runs/benchmarks/context_ablation_20260901_201035_full`、`context_ablation_20260902_034702_repeat1` 与 `context_ablation_20260902_102634_repeat2`。

## 2. 首轮结果

| 模式 | 任务数 | 完成率 | Golden CSim | 真实 CSynth | 错误成功 | 约束字段可用率 | API 总 Token P50 | Specialist 输入 P50 | 运行时间 P50/P95 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A | 12 | 25.0% | 0% | 0% | 0% | 92.5% | 65,187.5 | 275,082 | 376.1 / 2718.3 s |
| B | 12 | 25.0% | 0% | 0% | 0% | 92.5% | 55,552.0 | 5,844 | 366.1 / 2055.3 s |
| C | 12 | 25.0% | 0% | 0% | 0% | 92.5% | 37,388.5 | 5,901.5 | 408.7 / 2772.6 s |

首轮中 C 相对 A 的 API 总 Token 中位数下降 `42.6%`。但三组完成的都是 unsupported/recovery 类任务，没有任何 LLM Candidate 获得本轮 Golden CSim 和真实 CSynth 双重证据，因此不能据此声称“压缩保持了成功 HLS 生成效果”。

## 3. 复测与合并结果

两轮复测共 54 次。复测 cohort 的 A/B/C 完成率均为 `5.6%`，三组 Golden CSim/CSynth 仍为 `0%`。合并首轮和复测后，每组 30 次：

| 模式 | N | 完成率及 95% Wilson CI | API 总 Token P50/P95 | 总 API Token | Specialist 输入 P50 | 运行时间 P50/P95 |
|---|---:|---:|---:|---:|---:|---:|
| A | 30 | 13.3% `[5.3%, 29.7%]` | 66,236.5 / 115,818.9 | 1,910,003 | 290,309 | 388.7 / 2650.2 s |
| B | 30 | 13.3% `[5.3%, 29.7%]` | 59,388.0 / 105,600.3 | 1,524,709 | 5,844 | 477.2 / 2560.7 s |
| C | 30 | 13.3% `[5.3%, 29.7%]` | 36,677.5 / 88,646.4 | 1,082,227 | 5,988.5 | 408.7 / 2832.8 s |

90 次运行共记录 746 次真实 LLM 调用，API 总 Token 为 `4,516,939`。A/B/C 的错误成功计数均为 0，但 0/30 的 Wilson 上界仍约为 `11.4%`，不能把小样本零观测解释为绝对不会发生。

## 4. 配对比较

- A vs B：Specialist 输入裁剪使离线上下文 P50 从 `290,309` 降至 `5,844`，下降 `98.0%`；API 总 Token P50 下降 `10.3%`。配对 API Token 差中位数为 `-10,537.5`，bootstrap 95% CI 为 `[-15,299.5, -3,082.5]`。
- B vs C：结构化输出压缩使交付结果 Token P50 从 `17,622.5` 降至 `7,496`，下降 `57.5%`；API 总 Token P50 下降 `38.2%`。配对差 95% CI 为 `[-23,925, -2,536]`。
- A vs C：完整方案使 API 总 Token P50 下降 `44.6%`，离线 Specialist 输入下降 `97.9%`，交付结果下降 `69.3%`。API Token 配对差中位数为 `-26,842`，95% CI 为 `[-40,837.5, -13,990]`。
- A vs C 的墙钟 P50 从 `388.7` 秒变为 `408.7` 秒；配对差中位数仅 `0.21` 秒，95% CI `[-34.29, 57.57]` 跨 0，因此不能声称压缩稳定加速运行。
- 三组完成率配对差均为 0，但 Golden CSim/CSynth 全为 0，属于地板效应，不能用“完成率相同”证明功能效果等价。

## 5. 真实开发中暴露的问题

1. 7 个 trial 出现模式间最终状态差异，涉及 Dense、MatMul、Add、ScaleShift、Conv2D 和 unsupported custom operator。Trace 首次差异主要出现在 LLM finalization、reflection decision、格式错误或路径选择处。
2. A 组超长上下文显著增加 Token，但“注意力分散”只能作为与失败相关的工程线索，当前实验不能证明因果关系。
3. LLM Candidate 的 testbench、数值验证和综合修复仍是主要失败源。上下文优化降低成本，但没有解决候选代码正确性。
4. 每个模式都使用唯一绝对运行目录，但同一任务在隔离 runs root 下产生相同逻辑 Run ID。产物没有复用，不过这不满足任务书对独立 Run ID 的严格字面要求。
5. 冻结版本的“约束保留率”混合了上下文传递与最终验证字段是否存在。失败任务会因没有 report/verification 而降低该指标，所以它只能称为“约束字段可用率”，不能称为纯上下文信息保留率。
6. 冻结提交没有单独记录 context build/compression 自身耗时，也没有注入进程 kill 测试恢复；这两项指标明确记为未测，未使用估算值填充。

## 6. 严格结论

可以写入简历：

> 设计并执行 90 次真实 DeepSeek-V4-Pro + Vivado HLS 配对消融，使用官方 tokenizer 与 provider usage 分离统计；作用域上下文和结构化返回将 API 总 Token 中位数降低 44.6%，并通过 Trace 对 7 个模式分歧 trial 做首差异归因。

必须同时说明：当前任务集上的 LLM Candidate Golden CSim/真实 CSynth 通过率为 0，因此不能宣称压缩“未降低成功执行效果”，也不能宣称它提升了 HLS 生成成功率。下一轮应先修复 Candidate 验证链路，再在具有非零成功基线的隐藏任务集上重做消融。
