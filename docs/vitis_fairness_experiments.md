# Vitis Fairness Experiments

本文记录 Vivado HLS 2018.3 与 Vitis HLS 2025.2.1 的公平对照实验方法。目标不是证明某个工具一定更好，而是把“模型差异、backend 差异、综合器差异、默认策略差异、pragma 迁移差异”拆开看。

## 背景

Demo4 `mnist_qonnx_cnn.json` 在 Vivado HLS 2018.3 与 Vitis HLS 2025.2.1 上都能生成真实 csynth report，但 Vitis 的 latency、FF、LUT 明显更高。为了判断原因，需要做隔离实验，而不是直接比较两个完整 run。

## 实验脚本

脚本：

```powershell
python scripts\run_vitis_fairness_experiments.py
```

常用参数：

```powershell
$env:PYTHONPATH='src'
python scripts\run_vitis_fairness_experiments.py `
  --output-root runs\vfe_qonnx_0605 `
  --vivado-backend-work runs\mnist_qonnx_cnn_bc625576_02\vivado_hls `
  --vitis-backend-work runs\mnist_qonnx_cnn_bc625576_06\vivado_hls
```

只复跑某个变体：

```powershell
python scripts\run_vitis_fairness_experiments.py --include g2_vitis_fifo2
```

脚本会为每个变体生成：

- `experiment_result.json`
- `csynth.log`
- HLS work directory

全局汇总：

- `summary.json`
- `best_by_objective`

## 分组设计

| 组别 | 目的 | 解释 |
|---|---|---|
| g1 Vivado backend + Vivado HLS | baseline | 使用 Vivado backend 生成的 HLS 工程，并用 Vivado HLS 2018.3 综合。 |
| g1 Vivado backend + Vitis HLS | 综合器差异 | 尽量使用同一份 HLS 源码，改用 Vitis HLS 综合。 |
| g2 Vitis backend + Vitis HLS | Vitis baseline | 使用 Vitis backend 工程，显式统一 `clock_uncertainty=1.25ns`。 |
| g2 + FIFO sizing off | 默认 dataflow/FIFO 策略 | 调整 `config_dataflow`，观察 FIFO sizing 默认策略是否导致资源膨胀。 |
| g3 + bind_storage | pragma 迁移 | 将部分 deprecated `RESOURCE` pragma 迁移到 Vitis 推荐的 `bind_storage`。 |
| g4 tuned combo | Vitis safe TCL best-effort | 组合 uncertainty、FIFO depth、stream depth、bind_storage，观察不改 C++ 主体时 Vitis 能做到哪里。 |

第三组不是 Vitis 最优组，它只是迁移兼容性验证。第四组才是当前安全 TCL 级别的 best-effort 对照。

## 当前结果

| 组别 | 工具链 | 状态 | Latency | BRAM | DSP | FF | LUT | Timing |
|---|---|---|---:|---:|---:|---:|---:|---|
| g1 Vivado backend + Vivado HLS | Vivado 2018.3 | success | 775-777 | 8 | 0 | 9,888 | 49,459 | met |
| g1 Vivado backend + Vitis HLS | Vitis 2025.2.1 | report_missing | - | - | - | - | - | failed before report |
| g2 Vitis backend + Vitis HLS | Vitis 2025.2.1 | success | 6679-6681 | 10 | 0 | 132,970 | 111,370 | met |
| g2 + FIFO sizing off | Vitis 2025.2.1 | success | 6679-6681 | 10 | 0 | 132,970 | 111,370 | met |
| g3 + bind_storage | Vitis 2025.2.1 | success | 6679-6681 | 10 | 0 | 132,970 | 111,370 | met |
| g4 tuned combo | Vitis 2025.2.1 | success | 5904-5904 | 10 | 0 | 176,854 | 172,590 | met |

## 结论

- 当前 Demo4 上，Vivado HLS 2018.3 仍是整体最优。
- Vitis safe TCL best-effort 可以降低 latency，但会显著增加 FF/LUT。
- `bind_storage` 迁移没有恢复 Vivado 级别的性能。
- FIFO sizing off 没有改善指标。
- Vitis 对 hls4ml 生成的 DATAFLOW canonical form 更敏感，可能需要 Vitis-specific HLS 代码生成策略。

## 注意事项

Windows 下 Vitis 生成的 VHDL 文件名可能很长。实验脚本使用短 `dir_name`，避免路径长度错误污染结果。如果看到 report 已生成但 returncode=1，先检查日志中是否有 `file name(s) ... would be too long`。

Vitis timing 判定应使用：

```text
estimated_ns <= target_ns - uncertainty_ns
```

不能只比较 `estimated_ns <= target_ns`。
