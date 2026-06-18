# MNIST HLS 资源优化记录

日期：2026-06-18

目标：在 `mnist_recognition_mlp` 真实识别 demo 中降低 LUT、DSP、FF、BRAM 等 FPGA 资源，同时保持识别正确率不下降。所有可采纳结果必须满足：

- 真实 hls4ml + Vivado HLS 2018.3 路径。
- HLS csim 与 ONNX reference 对比通过。
- 20 个固定 MNIST 样本上 HLS accuracy = 95%。
- ONNX/HLS argmax match = 100%。

## 基线

原始基线 run：

```text
runs/mnist_recognition_mlp_234d539d
```

基线配置：

```text
precision = fixed<12,6>
reuse_factor = 512
clock_period = 10 ns
strategy = Resource
```

基线结果：

| 指标 | 数值 |
|---|---:|
| Latency max | 1237 cycles |
| BRAM | 48 |
| DSP | 133 |
| FF | 21275 |
| LUT | 31792 |
| Timing | 8.237 ns, met |
| HLS accuracy | 95% |
| Argmax match | 100% |

## 候选实验矩阵

| Run | 关键配置 | Clock | Latency max | BRAM | DSP | FF | LUT | HLS acc | Argmax | 结论 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `mnist_recognition_mlp_234d539d` | `fixed<12,6>`, RF512 | 10ns | 1237 | 48 | 133 | 21275 | 31792 | 95% | 100% | 基线 |
| `mnist_recognition_mlp_90d53ccc` | `fixed<12,6>`, RF1024 | 10ns | 2141 | 47 | 67 | 10265 | 20400 | 95% | 100% | 第一阶段默认 |
| `mnist_recognition_mlp_p8_3_rf512_257dd391` | 全局 `fixed<8,3>`, RF512 | 10ns | 1235 | 33 | 0 | 26035 | 47977 | 25% | 25% | 拒绝：精度崩溃 |
| `mnist_recognition_mlp_p10_4_rf512_484f0799` | 全局 `fixed<10,4>`, RF512 | 10ns | 1235 | 40 | 0 | 24362 | 45607 | 90% | 95% | 拒绝：准确率下降 |
| `mnist_recognition_mlp_p11_5_rf1024_b08500b5` | 全局 `fixed<11,5>`, RF1024 | 10ns | 2141 | 43 | 67 | 9562 | 24345 | 95% | 100% | 备选：BRAM/FF 更低但 LUT 高 |
| `mnist_recognition_mlp_p12_6_rf2048_a3a74568` | `fixed<12,6>`, RF2048 | 10ns | 3949 | 47 | 34 | 10314 | 22010 | 95% | 100% | 备选：DSP 更低但 LUT/latency 更高 |
| `mnist_recognition_mlp_layer_tail9_p12_6_6ea710a7` | 后两层 `fixed<9,4>` | 10ns | 2140 | 47 | 66 | 9535 | 20146 | 95% | 100% | 有效 |
| `mnist_recognition_mlp_middle8_final9_61b2327a` | 中间层 `fixed<8,3>`，输出 `fixed<9,4>` | 10ns | 2140 | 47 | 66 | 9339 | 19976 | 95% | 100% | 有效 |
| `mnist_recognition_mlp_relu0_9_middle8_final9_ff25b67f` | 第一 ReLU `fixed<9,4>`，中间 `fixed<8,3>`，输出 `fixed<9,4>` | 10ns | 2139 | 47 | 64 | 8548 | 19720 | 95% | 100% | 10ns balanced profile |
| `mnist_recognition_mlp_relu0_9_middle8_final8_8d6ac7cd_03` | 输出层降到 `fixed<8,3>` | 10ns | 2139 | 47 | 64 | 8528 | 19720 | 85% | 90% | 拒绝：输出 logits 8 位不稳 |
| `mnist_recognition_mlp_relu0_9_middle7_final9_a07ae725_03` | 中间层降到 7 位 | 10ns | 2139 | 47 | 64 | 8349 | 19616 | 80% | 85% | 拒绝：隐藏表示 7 位不稳 |
| `mnist_recognition_mlp_relu0_9_linear1_8_relu1_7_final9_0c1412c6_03` | 第二 ReLU 单独降到 7 位 | 10ns | 2139 | 47 | 64 | 8415 | 19648 | 90% | 95% | 拒绝：准确率下降 |
| `mnist_recognition_mlp_relu0_9_middle8_final9_weight8_1af80ae7_03` | best precision profile + weight `fixed<8,3>` | 10ns | 2139 | 33 | 63 | 8820 | 20439 | 90% | 95% | 拒绝：权重量化影响分类 |
| `mnist_recognition_mlp_relu0_9_middle8_final9_clock15_cb07b6df_03` | 10ns balanced profile + 15ns target | 15ns | 2135 | 47 | 64 | 5999 | 17899 | 95% | 100% | 最终资源优先默认 |
| `mnist_recognition_mlp_relu0_9_middle8_final9_clock20_6f40239b` | 同上 + 20ns target | 20ns | 2135 | 47 | 64 | 5999 | 17899 | 95% | 100% | 与 15ns 同资源，收益停止 |

## 最终默认配置

资源优先默认选择：

```text
precision = fixed<12,6>
reuse_factor = 1024
clock_period = 15 ns
strategy = Resource

layer_overrides:
  node_relu:     fixed<9,4>
  node_linear_1: fixed<8,3>
  node_relu_1:   fixed<8,3>
  node_linear_2: fixed<9,4>
```

原因：

- 不改变模型拓扑，不写定制 RTL，只调整 hls4ml 可解释参数。
- 保持 HLS accuracy = 95%，与基线一致。
- 保持 ONNX/HLS argmax match = 100%，与基线一致。
- 相比原始 RF512 基线，DSP/FF/LUT 大幅下降。
- 相比 10ns RF1024 默认，15ns 资源 profile 进一步显著降低 FF/LUT。
- 20ns 与 15ns 资源一致，说明 15ns 已到达该配置下的资源平台，继续放宽时钟没有收益。

资源变化：

| 指标 | 原始 RF512 10ns | 第一阶段 RF1024 10ns | 最终 15ns profile | 相对原始变化 |
|---|---:|---:|---:|---:|
| BRAM | 48 | 47 | 47 | -2.1% |
| DSP | 133 | 67 | 64 | -51.9% |
| FF | 21275 | 10265 | 5999 | -71.8% |
| LUT | 31792 | 20400 | 17899 | -43.7% |
| Latency max | 1237 | 2141 | 2135 | +72.6% |
| HLS accuracy | 95% | 95% | 95% | 不下降 |
| Argmax match | 100% | 100% | 100% | 不下降 |

## 可选 Profile

如果演示或目标板要求 100MHz 级别的 10ns 时钟，使用 10ns balanced profile：

```text
clock_period = 10 ns
node_relu = fixed<9,4>
node_linear_1 = fixed<8,3>
node_relu_1 = fixed<8,3>
node_linear_2 = fixed<9,4>
```

该 profile 的真实结果为：

```text
BRAM=47, DSP=64, FF=8548, LUT=19720, HLS accuracy=95%, argmax match=100%
```

## 工程结论

1. 对这个 MNIST MLP，盲目降低全模型位宽会破坏分类排序，资源下降不能直接等同于可部署。
2. 输出 logits 对位宽更敏感，`node_linear_2 fixed<8,3>` 会导致 accuracy 下降到 85%。
3. 隐藏层可以降到 8 位，但 7 位会导致 accuracy 下降。
4. 权重 `fixed<8,3>` 虽然降低 BRAM/DSP，但 accuracy 下降到 90%，因此不能作为默认。
5. 放宽时钟从 10ns 到 15ns 可以显著降低 FF/LUT，20ns 没有进一步收益。
6. 当前默认是“真实路径 + 功能验证通过 + 资源优先”的 profile，不是 mock 报告，也不是只看综合的 profile。

## 后续优化方向

- 扩大 HLS csim 样本数：当前 20 个样本适合演示，后续可增加到 100 或 1000 做更稳健验证 profile。
- 如果未来确定板卡和吞吐目标，可以在 `10ns balanced` 与 `15ns resource` 之间选择默认 profile。
- 可以继续做更细粒度 per-layer reuse factor，但本轮已确认 RF2048 对该模型不是 balanced profile。
- ParameterAdvisor 应优先使用 functionally verified history，并忽略 mock/sample fixture 指标。
