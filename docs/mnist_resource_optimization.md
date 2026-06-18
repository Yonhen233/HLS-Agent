# MNIST HLS 资源优化记录

日期：2026-06-18

目标：在 `mnist_recognition_mlp` 真实识别 demo 中降低 LUT、DSP、FF、BRAM 等 FPGA 资源，同时保持识别正确率不下降。

## 基线

基线 run：

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

## 真实候选实验

所有候选均使用真实 hls4ml + Vivado HLS 2018.3 路径，并执行 HLS csim/csynth。

| Run | Precision | RF | Latency max | BRAM | DSP | FF | LUT | HLS acc | Argmax match | 结论 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `mnist_recognition_mlp_234d539d` | `fixed<12,6>` | 512 | 1237 | 48 | 133 | 21275 | 31792 | 95% | 100% | 基线 |
| `mnist_recognition_mlp_p8_3_rf512_257dd391` | `fixed<8,3>` | 512 | 1235 | 33 | 0 | 26035 | 47977 | 25% | 25% | 拒绝：精度崩溃 |
| `mnist_recognition_mlp_p10_4_rf512_484f0799` | `fixed<10,4>` | 512 | 1235 | 40 | 0 | 24362 | 45607 | 90% | 95% | 拒绝：识别率下降 |
| `mnist_recognition_mlp_p10_5_rf512_216b0208` | `fixed<10,5>` | 512 | 1235 | 40 | 0 | 24360 | 45607 | 70% | 75% | 拒绝：识别率下降 |
| `mnist_recognition_mlp_p12_6_rf1024_97289a57` | `fixed<12,6>` | 1024 | 2141 | 47 | 67 | 10265 | 20400 | 95% | 100% | 默认推荐：资源下降且正确率不降 |
| `mnist_recognition_mlp_p12_6_rf2048_a3a74568` | `fixed<12,6>` | 2048 | 3949 | 47 | 34 | 10314 | 22010 | 95% | 100% | DSP 更低，但 LUT/FF/latency 更高 |
| `mnist_recognition_mlp_p11_5_rf1024_b08500b5` | `fixed<11,5>` | 1024 | 2141 | 43 | 67 | 9562 | 24345 | 95% | 100% | BRAM/FF 更低，但 LUT 高于默认推荐 |
| `mnist_recognition_mlp_p11_6_rf1024_e95b40bc` | `fixed<11,6>` | 1024 | 2141 | 43 | 66 | 9559 | 24357 | 70% | 75% | 拒绝：识别率下降 |

## 最终默认配置

默认选择：

```text
precision = fixed<12,6>
reuse_factor = 1024
clock_period = 10 ns
strategy = Resource
```

原因：

- 保持 HLS accuracy = 95%，与基线一致。
- 保持 ONNX/HLS argmax match = 100%，与基线一致。
- 相比基线，BRAM、DSP、FF、LUT 均下降。
- latency 增加到 2141 cycles，但 timing 仍满足 10 ns 目标。
- 相比 RF2048，RF1024 的 LUT/FF/latency 更优，是更平衡的 resource profile。

资源变化：

| 指标 | 基线 RF512 | 优化 RF1024 | 变化 |
|---|---:|---:|---:|
| BRAM | 48 | 47 | -2.1% |
| DSP | 133 | 67 | -49.6% |
| FF | 21275 | 10265 | -51.8% |
| LUT | 31792 | 20400 | -35.8% |
| Latency max | 1237 | 2141 | +73.1% |

## 工程结论

1. 对这个 MNIST MLP，盲目降低总位宽会破坏分类结果。`fixed<8,3>`、`fixed<10,5>`、`fixed<11,6>` 都出现明显识别率下降。
2. 保持 `fixed<12,6>` 并提高 `reuse_factor` 是更可靠的资源优化路径，因为它主要减少并行乘法器数量，不改变数值格式。
3. `reuse_factor=2048` 可以进一步降低 DSP，但 LUT、FF 和 latency 不如 `reuse_factor=1024`，因此不作为默认配置。
4. `fixed<11,5>, reuse_factor=1024` 可作为 BRAM/FF 优先 profile，但默认仍采用 LUT 更低的 `fixed<12,6>, reuse_factor=1024`。
5. MNIST demo 的验收阈值已收紧到 `classification_min_accuracy=0.95` 和 `argmax_match_min=1.0`，避免把“资源下降但正确率下降”的配置误判为成功。

## 后续优化方向

- 增加 per-layer precision：只降低对分类不敏感的中间层或权重类型，而不是全模型统一降位宽。
- 增加 layer-wise reuse factor：对大 Dense 层提高 RF，对小输出层保留更低 RF。
- 扩大 HLS csim 样本数：当前 20 个样本适合演示，后续可增加到 100 或 1000 做更稳健验证。
- 将 verified parameter experience 写入 ParameterAdvisor，用历史验证结果自动推荐 `fixed<12,6>, RF1024, 10ns`。
