# 算子测试方法

测试采用四层证据金字塔。低层快速、覆盖广；高层慢、样本少，但才能支持硬件结论。

## Layer 1：数学与位精确 Golden

统一 Case 包含 operator、shape、dtype、输入族、seed、舍入、溢出、累加位宽、目标、器件和时钟。当前生成 120 个独立组合，覆盖六类算子、三种定点位宽和十种输入族。

数学参考按实数运算；位精确参考逐步模拟 `ap_fixed` 的量化、截断、wrap/saturation。两者的差异记录为误差、mismatch、overflow 和 saturation，它不是 HLS 错误，而是后续选择容差与位宽的依据。

## Layer 2：真实 CSim

计划保留 18 个锚点，每类算子 3 个。门禁要求 `mock_tools=false`、当前 Run 的日志、独立 Testbench、`GOLDEN_CHECK_PASSED` 和 Artifact Hash。进程退出 0 但缺少 Golden 标记仍然失败。

## Layer 3：真实 CSynth

计划保留 10 个锚点，记录 cycles、II、clock、latency time、DSP/BRAM/LUT/FF、timing、Vivado 版本、Git commit、Run ID 和报告 Hash。预期 Timing Failure 可以作为“失败识别正确”通过测试，但不能进入成功配置。

## Layer 4：真实 LLM pass³

Dense、MatMul、ReLU、Add、ScaleShift 各重复 3 次。完整报告每次生成、repair、Sandbox、CSim、CSynth、token、工具调用与运行时间，不采用 best-of-3。Conv2D 在独立锚点稳定后加入。

## 统计口径

比率同时报告分子、分母、样本量、证据类别和 Wilson 95% 区间。少于 20 个样本时，即使结果为 1/1，也显示 `insufficient_data`。Mock、Fixture、Unit、Real 不计算混合成功率。

资源比较使用相同 Shape、Dtype、输入、Clock、Part、Vivado 版本和目标。Latency 同时报告 cycles 与 `cycles × clock`，吞吐使用 II 与 Clock，DSE 输出 Pareto Front，不用一个任意加权分数掩盖权衡。
