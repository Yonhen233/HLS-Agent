# MNIST LLM Candidate 资源与并行度优化记录

日期：2026-06-19

本文记录了 MNIST MLP 真实识别 demo 中，直接由 LLM 生成 HLS candidate 的实验过程。实验目标是在真实 Vivado HLS 2018.3 下探索资源、延迟和吞吐率之间的 Pareto 取舍，同时保持 20 张 MNIST golden 样本识别正确数不低于既有门槛 `19/20`。

## 基线

本实验的基线是此前记录到的 hls4ml resource-priority 最佳 profile。

| 路径 | 准确率 | Latency | BRAM | DSP | FF | LUT | Resource Score |
|---|---:|---:|---:|---:|---:|---:|---:|
| hls4ml resource-priority | 19/20 | 2135 | 47 | 64 | 5999 | 17899 | 41398 |

`Resource Score` 是本项目内部用于横向比较资源占用的简化指标：

```text
score = LUT + FF + 200 * DSP + 100 * BRAM
```

它不是 FPGA 官方指标，只是为了在多轮实验中快速比较“资源压力”。

## LLM Candidate 方法

LLM 没有直接接收完整权重矩阵。它接收的是：

- 模型结构约束
- hls4ml baseline 指标
- 历史 attempt 的压缩摘要
- 固定 top function 合约

固定 top function：

```cpp
void mnist_llm_candidate(data_t input[784], data_t output[10]);
```

脚本随后把真实 ONNX 权重和 20 张 MNIST golden 样本注入生成的 HLS artifact，对 candidate 执行 `CandidateSandbox` 静态扫描，并调用真实 Vivado HLS 运行：

```text
csim_design + csynth_design
```

运行脚本示例：

```powershell
python scripts\llm_mnist_hls_candidate.py --continue-run --attempts 1 --clock-period 15 --required-correct 19
```

## 资源优先实验矩阵

| Attempt | Candidate | Golden CSim | Latency | BRAM | DSP | FF | LUT | Score | 备注 |
|---:|---|---|---:|---:|---:|---:|---:|---:|---|
| 1 | `mnist_minimal_serial_8bit` | failed | - | - | - | - | - | - | 8-bit activation 路径 CSim 失败 |
| 2 | `mnist_mixed_fixed_16_8` | passed | 105409 | 34 | 3 | 302 | 602 | 4904 | 第一个 verified direct candidate |
| 3 | `mnist_serial_32bit_fix` | passed | 107777 | 35 | 3 | 356 | 733 | 5189 | 更宽 accumulator 没有带来更好资源 |
| 4 | `mnist_fixed32_nosat` | failed | - | - | - | - | - | - | LLM 写成 `accum_t`，编译失败 |
| 5 | `mnist_serial_narrow_16_4` | passed | 157953 | 18 | 0 | 422 | 1443 | 3665 | 8-bit weight + serial MAC 消除了 DSP |
| 6 | `mnist_narrow_accum_24` | passed | 157953 | 18 | 0 | 371 | 911 | 3082 | 更窄 accumulator 降低 LUT/FF |
| 7 | `mnist_narrow_accum_20` | passed | 157953 | 18 | 0 | 347 | 899 | 3046 | 当前最佳 resource-first candidate |
| 8 | `mnist_narrow_accum_15_14` | failed | - | - | - | - | - | - | 准确率降到 3/20，证明更低精度边界不安全 |

## 资源优先最佳 Candidate

最佳 verified resource-first candidate：

```text
candidate = mnist_narrow_accum_20
data_t    = ap_fixed<16,4,AP_RND,AP_SAT>
weight_t  = ap_fixed<8,4,AP_RND,AP_SAT>
acc_t     = ap_fixed<20,16,AP_RND>
```

| 指标 | hls4ml Baseline | LLM Candidate | 变化 |
|---|---:|---:|---:|
| BRAM | 47 | 18 | -61.7% |
| DSP | 64 | 0 | -100.0% |
| FF | 5999 | 347 | -94.2% |
| LUT | 17899 | 899 | -95.0% |
| Score | 41398 | 3046 | -92.6% |
| Latency | 2135 | 157953 | +74.0x |

## 初步解读

这是一个资源优先的 Pareto 点，不是低延迟方案。LLM 找到的是一种 serial shared-MAC 实现：它去掉了大量并行度和 hls4ml 生成工程中的额外开销，因此显著降低面积，但代价是 latency 大幅上升。

这个结果有价值，因为它说明了两条互补路径：

- hls4ml 路径：延迟更好，工程结构更标准。
- LLM candidate 路径：在 latency 不敏感时，可以做激进资源压缩。

golden testbench 是安全门。Attempt 8 说明，LLM 提出的看似合理的低精度方案必须经过真实 C simulation；一旦准确率下降，就不能被标记为 verified。

## 按目标拆分：Resource / Balanced / Throughput

在 resource-first 实验之后，脚本扩展了显式目标：

```powershell
python scripts\llm_mnist_hls_candidate.py --objective resource --continue-run --attempts 1 --clock-period 15 --required-correct 19
python scripts\llm_mnist_hls_candidate.py --objective balanced --continue-run --attempts 3 --clock-period 15 --required-correct 19
python scripts\llm_mnist_hls_candidate.py --objective throughput --continue-run --attempts 4 --clock-period 15 --required-correct 19
```

目标合约：

| Objective | 合约 |
|---|---|
| `resource` | 在通过 golden CSim 的前提下最小化 resource score |
| `balanced` | 保持资源低于指定预算，同时比串行 LLM resource candidate 改善 latency / II |
| `throughput` | 改善 hls4ml baseline 的 latency 和 top interval / II，并且资源必须 fit 当前板卡容量 |

脚本现在把 `objective_met` 和 CSim/csynth 是否成功分开记录。这样做很重要：一个 candidate 可以功能正确、也能综合通过，但仍然没有达成指定设计目标。

## 早期 Pareto 点

| 路径 | Candidate | Golden CSim | Latency | II / Interval | BRAM | DSP | FF | LUT | Resource Score | 解读 |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| hls4ml baseline | hls4ml resource profile | passed | 2135 | 1024 | 47 | 64 | 5999 | 17899 | 41398 | 标准 hls4ml dataflow 工程 |
| LLM resource-first | `mnist_narrow_accum_20` | passed | 157953 | 157953 | 18 | 0 | 347 | 899 | 3046 | 面积极小，吞吐率很低 |
| LLM balanced | `balanced_UF8_layerwise` | passed | 6776 | 6776 | 24 | 0 | 1391 | 4158 | 7949 | 比串行 LLM 快约 23 倍，资源仍显著低于 hls4ml |
| LLM throughput-first | `throughput_pipe_II1` | passed | 465 | 465 | 0 | 0 | 38783 | 68311 | 107094 | latency/II 打过 hls4ml，但 LUT 超过当前 xc7z020 容量 |

## 最新可行 Pareto 点

后续 controlled repair 实验把目标定义收紧为：

- `balanced`：要求 `resource_score <= 12000`。
- `throughput`：要求打过 hls4ml latency/II，并且 fit xc7z020 report capacity。
- 中断后产生的 orphan attempt 通过 `--continue-run --attempts 0` 从磁盘合并回 `summary.json`。

最新 verified points：

| 路径 | Candidate | Golden CSim | Latency | II / Interval | BRAM | DSP | FF | LUT | Resource Score | Fits xc7z020 | 解读 |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| hls4ml baseline | hls4ml resource profile | passed | 2135 | 1024 | 47 | 64 | 5999 | 17899 | 41398 | yes | 标准 hls4ml baseline |
| LLM resource-first | `mnist_narrow_accum_20` | passed | 157953 | 157953 | 18 | 0 | 347 | 899 | 3046 | yes | 最小资源串行设计 |
| LLM strict-balanced | `balanced_UF16_8_10_II1` | passed | 3906 | 3906 | 24 | 0 | 2577 | 5540 | 10517 | yes | 当前 balanced 资源预算内最佳 |
| LLM performance-balanced | `balanced_control_UF32_8_10` | passed | 2388 | 2388 | 40 | 0 | 3883 | 7715 | 15598 | yes | 比 strict-balanced 更快，但超过 strict score 预算 |
| LLM feasible-throughput | `throughput_control_UF64_input2_UF32_10` | passed | 545 | 545 | 126 | 0 | 4209 | 33364 | 50173 | yes | 当前最佳可行 II/latency candidate |
| LLM throughput boundary | `throughput_control_UF64_input4_UF32_10` | passed | 545 | 545 | 2 | 0 | 8342 | 49891 | 58433 | yes | 更多 input unroll 没有改善 II，反而增加 LUT |

与 hls4ml 相比，feasible-throughput candidate：

- latency 降低 74.5%
- II 降低 46.8%
- DSP 从 64 降到 0
- 代价是 LUT 和 BRAM 增加

## 找回的 Orphan Results

一次长时间 Vivado run 被中断后，多个结果已经写入 `attempt_*/attempt_result.json`，但没有合并进 `summary.json`。恢复流程找回并合并了这些结果。

这些 orphan attempts 的核心教训是：不是所有 low-II candidate 都可部署。

| Candidate | Latency / II | 主要失败原因 |
|---|---:|---|
| `throughput_pipe_II1_input_cyclic16_repair` | 490 | LUT 超过 xc7z020 容量 |
| `throughput_pipe_input_cyclic8_w1_8_repair` | 514 | BRAM 和 LUT 都超容量 |
| `throughput_pipe_no_input_partition_repair` | 857 | LUT 超容量 |
| `throughput_pipe_no_input_weight16_dsp_repair` | 944 | DSP 和 LUT 都超容量 |

这些失败结果同样是有价值的 memory：它们解释了为什么最终 feasible-throughput 设计选择 2-way input parallelism，而不是 4/8/16-way 或强制 DSP 映射。

## 来自真实 HLS Feedback 的经验

- 当 objective 明确时，LLM 可以生成结构差异很大的 HLS 架构，而不仅是微调参数。
- 高并行 candidate 不自动等于 balanced candidate，必须有 objective-specific acceptance check。
- `ap_fixed<W,I>` 只检查位宽不够；如果缺少 `AP_SAT`，默认 overflow 可能 wrap，导致 golden accuracy 下降。
- Vivado HLS 2018.3 的 pragma 语法必须被 guard。真实工具拒绝了部分 LLM 生成的 `type=cyclic` 写法。
- `DATAFLOW` 和 `STREAM` pragma 看起来并行，但如果没有真正的 producer/consumer 结构，真实综合可能得到很差的 II。
- `resource_feasible` 必须进入吞吐优先目标，否则会把超板卡容量的 low-II 设计误判为好结果。
- 中断恢复很重要：长时间 EDA run 可能已经产出局部结果，Agent 需要能从 artifact 目录恢复 orphan attempt。

最适合面试表达的结论是：这不是一次 one-shot code generation demo。Agent 会记录真实综合与功能验证反馈，收紧 prompt 和 guard，用 objective-specific scoring 探索 HLS 设计的 Pareto surface。
