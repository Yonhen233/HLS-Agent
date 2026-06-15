# 开发日志（Development Log）

维护约定：
- 从 **2026-06-01** 起，所有后续 bug 修复都追加到本文件，不新建分散日志。
- 每次记录必须包含：时间、测试动作、问题根因、修复方案、未修复原因。

---

## 2026-06-15 18:26:30 +08:00：修复 functional verification 与 memory 状态一致性，并复测 Demo1
### 1. 本次测试做了什么
在 Functional Verification Layer 接入后，又针对真实 Demo1 暴露出的状态一致性做了一轮收尾验证：

```powershell
$env:PYTHONPATH='src'
$env:PYTEST_ADDOPTS='-p no:cacheprovider --basetemp=.pytest-tmp-full'
pytest -q

$env:DL_OP_TO_HLS_MOCK_VIVADO='0'
$env:DL_OP_TO_HLS_MOCK_HLS4ML='0'
$env:DL_OP_TO_HLS_VIVADO_HLS_PATH='D:\Xilinx\Vivado\2018.3\bin\vivado_hls.bat'
$env:DL_OP_TO_HLS_HLS_TOOLCHAIN='vivado_hls'
$env:DL_OP_TO_HLS_VIVADO_TIMEOUT_SECONDS='900'
python -m dl_op_to_hls.cli run examples/matmul_resource.json
```

结果：

| 项目 | 结果 |
|---|---|
| focused tests | `tests/test_functional_verification.py`、`tests/test_memory.py`、`tests/test_runtime_hybrid.py`、`tests/test_specialists.py` 通过 |
| full pytest | 通过，含依赖缺失场景 skip |
| 真实 Demo1 run | `matmul_16x16_resource_9ac8e2e8_24` |
| final status | `partial_success` |
| Functional Verification | `golden_testbench` passed，`csim_executed=true` |
| Timing | target 8ns，estimated 9.634ns，timing failed |
| summary | 已包含 `Functional Verification` 和 `Parameter Advisor` |

### 2. 暴露的问题与修复
#### 问题：memory-ready state snapshot 会在 timing fail 时临时改成 success
现象：

- Demo1 的最终 `state.json` 是 `partial_success`。
- 但 memory 抽取前的中间快照曾经只检查 `report.status == success`，没有检查 `report.timing.met`。
- 这会让 memory candidate 的 summary 一度写成 success，和真实 run 结果不一致。

修复：

- `runtime.finalize()` 在 memory candidate 抽取前先调用 `update_status_from_todos(state)`。
- `_write_memory_ready_state_snapshot()` 的 success 条件增加 `state.report["timing"]["met"] is not False`。
- 复测后，Demo1 memory candidate 正确记录为：

```text
Run matmul_16x16_resource_9ac8e2e8_24 used fallback_template_path with status partial_success.
```

### 3. 未修复/后续观察
- Demo1 功能验证已经通过，但 timing 未满足；这是 HLS 参数/时钟约束问题，不再被误判为功能失败或完整成功。
- ParameterAdvisor 仍可从 verified history 给建议，但已避免把 timing failed history 当成 timing-clean 的推荐样本。

## 2026-06-15 18:06:50 +08:00：接入 Functional Verification Layer，并完成 Vivado HLS 2018.3 真实验证
### 1. 本次测试做了什么
本轮目标是把“能综合”升级为“先功能验证，再信任综合指标”：

- fallback Dense/MatMul/ReLU/Add 生成 deterministic golden testbench。
- hls4ml Demo2/3/4 生成小批量 ONNX Runtime reference input/output。
- Vivado HLS `csim_design` 后解析 functional pass/fail。
- `summary.md` 增加 `Functional Verification` 和 `Parameter Advisor` 章节。
- Memory/Skill/ParameterAdvisor 只把真正有 reference/golden 证据的结果当成 verified history。

实际执行过的关键命令：

```powershell
$env:PYTHONPATH='src'
$env:DL_OP_TO_HLS_MOCK_VIVADO='0'
$env:DL_OP_TO_HLS_MOCK_HLS4ML='0'
$env:DL_OP_TO_HLS_VIVADO_HLS_PATH='D:\Xilinx\Vivado\2018.3\bin\vivado_hls.bat'
$env:DL_OP_TO_HLS_HLS_TOOLCHAIN='vivado_hls'
$env:DL_OP_TO_HLS_VIVADO_TIMEOUT_SECONDS='1200'

python -m dl_op_to_hls.cli run examples\mnist_mlp_hls4ml.json
python -m dl_op_to_hls.cli run examples\mnist_tiny_cnn.json
python -m dl_op_to_hls.cli run examples\mnist_qonnx_cnn.json
python -m dl_op_to_hls.cli run examples\dense_operator.json
python -m dl_op_to_hls.cli run examples\matmul_resource.json

$env:PYTEST_ADDOPTS='-p no:cacheprovider --basetemp=.pytest-tmp'
pytest -q
```

测试结论：

| Demo | Run ID | 路径 | 状态 | Functional Verification | 关键指标 |
|---|---|---|---|---|---|
| Demo0 Dense | `dense_16x32_af6abf3c_21` | fallback_template | success | `golden_testbench` passed | latency 269, DSP 16, LUT 549, timing met |
| Demo1 MatMul | `matmul_16x16_resource_9ac8e2e8_23` | fallback_template | partial_success | `golden_testbench` passed | latency 2052, DSP 16, LUT 624, timing failed |
| Demo2 MLP | `mnist_mlp_demo_1ed09a79_05` | hls4ml | partial_success | `hls4ml_reference_compare` failed | max_abs_error 1.3666, timing met |
| Demo3 Tiny CNN | `mnist_tiny_cnn_154bde8b_03` | hls4ml | partial_success | `hls4ml_reference_compare` failed | max_abs_error 0.2815, timing met, LUT 354417 |
| Demo4 QONNX CNN | `mnist_qonnx_cnn_bc625576_10` | hls4ml/QONNX | success | `hls4ml_reference_compare` passed | max_abs_error 0.1873, latency 5040, LUT 354417, timing met |

全量测试结果：

```text
pytest -q
结果：通过，含 7 个依赖缺失时的 skip。
```

### 2. 暴露的问题与修复
#### 问题 A：旧版 csim pass 只是“程序运行成功”，不是功能正确
现象：

- Demo2 早期显示 `csim_passed`，但只是 Vivado 日志中出现 `CSim done with 0 errors`。
- hls4ml testbench 默认只打印 quantized predictions，不会 assert reference mismatch。

修复：

- 新增 `tools/functional_verification.py`。
- hls4ml conversion 后生成：
  - `tb_data/tb_input_features.dat`
  - `tb_data/tb_output_predictions.dat`
  - `tb_data/reference_manifest.json`
- Vivado csim 后递归查找 `solution1/csim/build/tb_data/csim_results.log`，与 reference output 做数值比较。
- verification 结果写入 `verification.json`、`state.json`、`summary.md`。

#### 问题 B：Vivado csim 运行目录下找不到 hls4ml weights/tb_data
现象：

```text
ERROR: file weights/w2.txt does not exist
ERROR: [SIM 211-100] 'csim_design' failed
```

根因：

- hls4ml 生成的 testbench 在 csim build 目录运行。
- 只复制源码不够，`weights/` 和 `tb_data/` 必须作为 testbench data 加入 TCL。

修复：

- `legacy_vivado_env.py` 自动追加：
  - `add_files -tb weights`
  - `add_files -tb tb_data`

#### 问题 C：Demo3 CNN 的 Conv ReuseFactor 触发 Vivado 2018.3 runtime assertion
现象：

```text
Assertion failed!
Expression: CONFIG_T::reuse_factor <= CONFIG_T::filt_height * CONFIG_T::filt_width * CONFIG_T::n_chan
```

根因：

- hls4ml 自动把第一层 Conv RF 调成 36。
- Vivado 2018.3 linebuffer resource conv 对第一层实际要求 RF <= 3*3*1 = 9。

修复：

- ONNX layer-list adapter 在生成 ModelGraph 前写入 `HLSConfig.LayerName`。
- 对 Conv2D 层按 `filt_height * filt_width * n_chan` 自动 cap per-layer ReuseFactor。
- 修复后 Demo3 不再 assertion，能跑到 csynth/report/reference compare。

#### 问题 D：Memory/ParameterAdvisor 会误用旧版“execution-only csim”历史
现象：

- 旧 run 里有 `mode=vivado_csim` 且 `passed=true` 的历史。
- 这类历史只说明程序运行过，不说明输出和 reference 一致。

修复：

- verified 判定收紧为：
  - `mode=golden_testbench` 且 passed
  - 或 `mode=hls4ml_reference_compare` 且 passed
  - 或 comparison 明确 passed
- `MemoryManager`、`MemoryPolicy`、`skills.py`、`ParameterAdvisor` 同步使用该定义。
- `ParameterAdvisor` 额外忽略 timing failed 的历史，不把它作为推荐参数的正样本。

#### 问题 E：timing failed 被全局状态误判为 success
现象：

- Demo1 MatMul 功能验证通过，但 timing 未达标，早期 run status 仍是 success。

修复：

- `VivadoSpecialist` 在 timing not met 时返回 `partial_success`。
- `reflector.update_status_from_todos` 将 `report.timing.met == false` 作为全局 `partial_success` 条件。
- Demo1 复测 `matmul_16x16_resource_9ac8e2e8_23` 已正确显示 `partial_success`。

#### 问题 F：测试不满足“无 ONNX 也能跑”
现象：

```text
ModuleNotFoundError: No module named 'onnx'
```

根因：

- 部分 adapter 单测直接 `__import__("onnx")`。

修复：

- 改成 `pytest.importorskip("onnx")` / `pytest.importorskip("numpy")`。
- 全量 pytest 通过。

### 3. 未完成或暂不修复的问题
#### Demo2 MLP 功能对比失败
现状：

- `csim_executed=true`，说明 Vivado CSim 已执行。
- reference compare failed，`max_abs_error=1.3666`。

判断：

- 当前 `fixed<8,3>` 是为了资源/timing 收敛选出的保守配置，但对 MLP 输出精度破坏明显。
- 这不是 Agent workflow 没跑通，而是功能验证层暴露了真实量化误差。

后续建议：

- 优先尝试更宽 precision，例如 `fixed<10,4>`、`fixed<12,5>`。
- 结合 verified history 做小范围参数建议，而不是盲目大扫参。

#### Demo3 Tiny CNN 功能对比略失败且资源偏大
现状：

- Conv RF cap 后不再 assertion。
- reference compare failed，`max_abs_error=0.2815`，略高于 tolerance 0.25。
- LUT 达到 354417，说明当前 hls4ml layer-list + resource conv 配置仍不够板级友好。

判断：

- 当前路径已经是真实 hls4ml/Vivado 路径，不是 mock。
- 失败集中在精度/资源权衡和 CNN adapter 参数策略。

后续建议：

- 增加 per-layer precision/ReuseFactor policy，而不是全模型统一参数。
- 对 Conv 层同时考虑 RF 合法性、LUT、timing 和 reference error。

#### 历史 DB/RAG 仍包含旧版本误判 memory
现状：

- 老 run 中仍有 `mode=vivado_csim` 的历史条目。

处理：

- 本轮已从代码层过滤，不再作为 verified recommendation 来源。
- 暂不直接清洗 DB，避免破坏可追溯开发历史；如后续需要，可做 migration 标记为 `execution_only`。

---

## 2026-06-05 16:13:37 +08:00：完成 Vitis HLS 2022.2 代表性复测，并补齐 vitis_hls 命令适配
### 1. 本次测试做了什么
用户安装了 Vitis 2022.2，安装目录为：

```text
D:\Vitis2022.2
```

本轮目标是回答：Vitis 2022.2 是否会像 Vitis 2025.2.1 一样，在 hls4ml CNN 上显著差于 Vivado HLS 2018.3。为了避免重新做大规模扫描，本轮复用 `2026-06-05 10:04:07` 的 Demo4 QONNX CNN 公平实验设计，只替换 Vitis 版本，并额外跑一个轻量 fallback Dense 点作为 sanity check。

实际执行命令摘录：

```powershell
$env:PYTHONPATH='src'
$env:TMP='D:\hls_agent\standalone_work\dl-op-to-hls-agent\tmp'
$env:TEMP=$env:TMP

python scripts\run_vitis_fairness_experiments.py `
  --output-root runs\vitis_fairness_qonnx_2022p2_20260605 `
  --vitis-run D:\Vitis2022.2\Vitis_HLS\2022.2\bin\vitis_hls.bat `
  --include g1_vivado_vitis g2_vitis_base g4_vitis_tuned `
  --timeout 1200 `
  --force

$env:DL_OP_TO_HLS_MOCK_HLS4ML='1'
$env:DL_OP_TO_HLS_MOCK_VIVADO='0'
$env:DL_OP_TO_HLS_HLS_TOOLCHAIN='vitis_hls'
$env:DL_OP_TO_HLS_VITIS_HLS_PATH='D:\Vitis2022.2\Vitis_HLS\2022.2\bin\vitis_hls.bat'
$env:DL_OP_TO_HLS_HLS4ML_BACKEND='Vitis'
$env:DL_OP_TO_HLS_VIVADO_TIMEOUT_SECONDS='900'
python -m dl_op_to_hls.cli run examples\dense_operator.json

python -m pytest tests\test_vivado_hls_mcp.py tests\test_report_parser.py -q -p no:cacheprovider
python -m py_compile scripts\run_vitis_fairness_experiments.py
```

### 2. Vitis 2022.2 命令行兼容问题
Vitis 2025.2.1 使用：

```text
vitis-run.bat --mode hls --tcl --input_file <tcl>
```

Vitis 2022.2 使用：

```text
vitis_hls.bat -f <tcl>
```

这不是参数小差异，而是不同 Vitis 版本真实 CLI contract 不同。本轮修复：

- `VivadoHLSAdapter`：`vitis_hls` toolchain 同时支持 `vitis-run.bat` 和 `vitis_hls.bat`。
- `scripts/run_vitis_fairness_experiments.py`：根据可执行文件名自动选择 `vitis-run` 参数或 legacy `vitis_hls -f` 参数。
- 测试新增：`test_vitis_run_csynth_uses_vitis_hls_legacy_command`。

### 3. 真实 HLS 对照结果
复用旧日志中的 Vivado HLS 2018.3 Demo4 baseline：

| 组别 | 工具链 | 状态 | Latency | BRAM | DSP | FF | LUT | Timing |
|---|---|---|---:|---:|---:|---:|---:|---|
| Demo4 Vivado baseline | Vivado HLS 2018.3 | success | 775-777 | 8 | 0 | 9,888 | 49,459 | met |

本轮 Vitis HLS 2022.2 结果：

| 组别 | 工具链 | 目的 | 状态 | Latency | BRAM | DSP | FF | LUT | Timing |
|---|---|---|---|---:|---:|---:|---:|---:|---|
| g1 Vivado backend + Vitis HLS | Vitis 2022.2 | 同源 Vivado backend 源码换综合器 | report_missing | - | - | - | - | - | failed before report |
| g2 Vitis backend baseline | Vitis 2022.2 | Vitis backend，uncertainty=1.25ns | success | 6391-6393 | 10 | 0 | 175,036 | 168,859 | met |
| g4 Vitis tuned combo | Vitis 2022.2 | safe TCL tuned：uncertainty/FIFO/bind_storage | success | 6396-6397 | 10 | 0 | 180,353 | 182,123 | met |

与 Vivado 2018.3 Demo4 baseline 的比例：

- Vitis 2022.2 baseline latency：约 8.23x。
- Vitis 2022.2 baseline FF：约 17.70x。
- Vitis 2022.2 baseline LUT：约 3.41x。
- Vitis 2022.2 tuned combo 没有改善，反而资源更高。

与 Vitis 2025.2.1 对比：

- Vitis 2025.2.1 baseline：Latency 6679-6681，FF 132,970，LUT 111,370。
- Vitis 2022.2 baseline：Latency 6391-6393，FF 175,036，LUT 168,859。
- 结论：2022.2 latency 比 2025.2.1 略好，但 FF/LUT 明显更高；整体仍不支持“全面切换 Vitis”的结论。

### 4. 轻量 fallback Dense sanity check
为了确认 Vitis 2022.2 不是对所有 HLS C++ 都极差，本轮额外跑了 Demo0 Dense fallback：

| 组别 | 工具链 | 状态 | Latency | BRAM | DSP | FF | LUT | Timing |
|---|---|---|---:|---:|---:|---:|---:|---|
| Demo0 Dense Vivado 2018.3 baseline | Vivado HLS 2018.3 | success | 269 | 0 | 16 | 732 | 549 | met |
| Demo0 Dense Vitis 2022.2 | Vitis HLS 2022.2 | success | 296 | 0 | 16 | 1,342 | 655 | met |

结论：

- 对简单手写/fallback HLS C++，Vitis 2022.2 不是灾难性退化：latency 约 1.10x，LUT 约 1.19x。
- 对 hls4ml CNN DATAFLOW/stream 模式，Vitis 2022.2 仍明显差于 Vivado 2018.3。

### 5. 遇到的问题与根因
1) Vitis 2022.2 没有 `vitis-run.bat`
- 现象：安装目录中找不到 `vitis-run.bat`，实际命令为 `D:\Vitis2022.2\Vitis_HLS\2022.2\bin\vitis_hls.bat`。
- 根因：2022.2 与 2025.2.1 的 Vitis HLS CLI 不同。
- 修复：adapter 和公平实验脚本都支持双命令格式。

2) `g1` returncode=0 但没有 report
- 现象：Vitis 2022.2 运行同源 Vivado backend HLS C++ 时，进程 returncode 为 0，但没有生成 csynth report。
- 根因：日志中出现 `Dataflow form checks found` 与 `Compilation of the preprocessed source 'myproject' failed`；Vitis 仍以 0 退出。
- 修复：`VivadoHLSAdapter` 的日志判错增加 `Compilation of the preprocessed source` / `failed before report` 模式，不能只相信 returncode。

3) Vitis safe TCL tuned 对 2022.2 无正向收益
- 现象：g4 tuned combo latency 与 baseline 接近，资源更高。
- 根因：当前 TCL 级调参不足以修复 hls4ml CNN 的 DATAFLOW/stream 代码结构问题。
- 处理：继续记录为工具链/codegen 边界，不用 fallback 掩盖。

### 6. 当前结论
- 继续保持 Vivado HLS 2018.3 为默认主线是合理的。
- Vitis 2022.2 可以作为可选工具链保留，尤其对简单 fallback HLS C++ 可用。
- 对 Demo4 这类 hls4ml CNN，Vitis 2022.2 仍显著差于 Vivado HLS 2018.3；如果以后要让 Vitis 成为主线，需要做 Vitis-specific hls4ml template/codegen 改造，而不是只换工具版本或 TCL 参数。

### 7. 当前测试结果
通过：

- `tests/test_vivado_hls_mcp.py tests/test_report_parser.py`：14 passed
- `python -m py_compile scripts\run_vitis_fairness_experiments.py`：通过

### 8. 未修复/后续问题
- 尚未修复 Vitis 对 hls4ml CNN DATAFLOW canonical form 的兼容性；这需要改 hls4ml Vitis backend/template 或增加 Vitis-specific graph/code rewrite。
- 尚未把 Vitis 2022.2 设为默认，因为真实指标不支持该切换。

---

## 2026-06-05 15:22:16 +08:00：收敛 Demo2/Demo3 优化方法，并增强 ONNX/QONNX 静态 adapter
### 1. 本次测试做了什么
本轮目标不是继续做大批量设计空间扫描，而是在真实路径上找出可解释、可复用的优化方法，并修复 Demo2-4 当前 ONNX/QONNX adapter 过窄的问题。

执行动作：

- 复盘 Demo2/Demo3/Demo4 真实 `hls4ml + Vivado HLS 2018.3` 历史 run，确认 Demo2/3/4 已经能够走真实 `hls4ml_path`，主要剩余问题从“链路跑不通”转为“资源/timing 是否适合作为后续 baseline”。
- 对 Demo2 MNIST MLP 做少量代表性真实 Vivado 点验证，没有继续大规模 sweep。
- 对 Demo3 Tiny CNN 做一个 focused resource-oriented 点验证，没有继续大规模 sweep。
- 扩展 `HLS4MLAdapter` 的 ONNX/QONNX layer-list adapter：增加 shape inference、更多静态 shape helper 消除、`MatMul + Add -> Dense+bias`、`BatchNormalization` folding、`AveragePool/GlobalAveragePool`、`Sigmoid/Tanh`、Q/DQ metadata skip，以及 residual/branched dataflow 的明确拒绝。
- 使用真实 hls4ml + mock Vivado 轻跑 Demo2-4，验证 adapter 改动没有破坏 Agent 编排和 hls4ml conversion。

实际执行命令摘录：

```powershell
$env:PYTHONPATH='src'
$env:TMP='D:\hls_agent\standalone_work\dl-op-to-hls-agent\tmp'
$env:TEMP=$env:TMP

python scripts\sweep_hls4ml_model.py --base-task examples\mnist_mlp_hls4ml.json --output-root runs\sweeps\mnist_mlp_real_vivado2018_rf512_timeout2400_20260605 --precisions 'fixed<8,3>' --reuse-factors 512 --clock-periods 10 --strategies Resource --max-runs 1 --hls-timeout 2400 --timeout 3000
python scripts\sweep_hls4ml_model.py --base-task examples\mnist_tiny_cnn.json --output-root runs\sweeps\mnist_tiny_cnn_real_vivado2018_rf64_p8_20260605 --precisions 'fixed<8,3>' --reuse-factors 64 --clock-periods 10 --strategies Resource --max-runs 1 --hls-timeout 2400 --timeout 3000

$env:DL_OP_TO_HLS_MOCK_HLS4ML='0'
$env:DL_OP_TO_HLS_MOCK_VIVADO='1'
$env:DL_OP_TO_HLS_HLS4ML_BACKEND='Vivado'
python -m dl_op_to_hls.cli run examples\mnist_mlp_hls4ml.json
python -m dl_op_to_hls.cli run examples\mnist_tiny_cnn.json
python -m dl_op_to_hls.cli run examples\mnist_qonnx_cnn.json

python -m pytest tests\test_hls4ml_mcp.py -q -p no:cacheprovider
python -m pytest tests\test_demo_examples_schema.py tests\test_demo_model_scripts.py -q -p no:cacheprovider
python -m pytest tests\test_vivado_hls_mcp.py tests\test_report_parser.py -q -p no:cacheprovider
```

### 2. 找到的优化方法
Demo2 `mnist_mlp_hls4ml.json`：

- 原始配置：`fixed<16,6>`、`reuse_factor=64`、`clock=5ns`、`Resource`。
- 真实结果：能综合，但资源规模明显超出 `xc7z020` 参考板卡，timing failed。
- 代表性优化方法：降低精度到 `fixed<8,3>`，提高 `reuse_factor=512`，放宽 clock 到 `10ns`，继续使用 `Resource` strategy。
- 真实参考 run：`mnist_mlp_demo_pfixed8_3_rf512_clk10p0_resource_be1ca1bf`。
- 指标：Latency 1232-1235 cycles，BRAM 33，DSP 0，FF 26030，LUT 47977，Timing met。
- 已将该配置写回 `examples/mnist_mlp_hls4ml.json`，作为更真实的 board-feasible baseline。

Demo3 `mnist_tiny_cnn.json`：

- 原始配置：`fixed<16,6>`、`reuse_factor=32`、`clock=10ns`、`Resource`。
- 真实结果：timing met，但 LUT 约 58161，对 `xc7z020` 参考规模偏高。
- 代表性优化方法：降低精度到 `fixed<8,3>`，提高 `reuse_factor=64`，保持 `clock=10ns` 和 `Resource`。
- 真实参考 run：`mnist_tiny_cnn_pfixed8_3_rf64_clk10p0_resource_4769edbf`。
- 指标：Latency 148-150 cycles，BRAM 3，DSP 0，FF 2513，LUT 6680，Timing met。
- 已将该配置写回 `examples/mnist_tiny_cnn.json`。

说明：这不是宣称全局最优，只是当前开发阶段找到的可靠优化方向：降低定点位宽、提高 reuse factor、放宽过紧 clock，用真实 Vivado HLS 2018.3 结果证明资源/timing 能明显改善。

### 3. ONNX/QONNX adapter 问题与根因
此前 adapter 是为了 Demo2-4 快速打通而写的窄范围工程实现，主要处理：

- `Gemm -> Dense`
- `Relu -> Activation`
- NCHW `Conv -> channels_last Conv2D`
- `Flatten/Reshape -> static Reshape`
- 跳过少量 `Shape/Concat/Constant` 静态 shape 辅助节点

问题在于：

- 遇到 PyTorch/QONNX 常见的 `MatMul + Add` 表达时，不能折叠成 Dense+bias。
- 遇到 inference 常见的 `BatchNormalization` 时，不能 fold 到前一个 Dense/Conv。
- 静态 shape 子图不只包含 `Shape/Concat/Constant`，还可能包含 `Gather/Unsqueeze/Squeeze/Slice/ConstantOfShape`。
- 如果遇到 residual/branched Add，旧逻辑没有把“这需要真正图编译能力”表达得足够明确。

### 4. 修复方案
本轮没有把它伪装成完整 ONNX compiler，而是把它升级为更可靠的静态 layer-list adapter：

- 增加 ONNX shape inference，优先使用推理后的 value_info。
- 扩展静态 helper 消除：`Shape`、`Constant`、`ConstantOfShape`、`Concat`、`Gather`、`Unsqueeze`、`Squeeze`、`Slice`。
- 支持 `MatMul` 第二输入为静态 initializer 时生成 Dense。
- 支持紧跟 Dense/Conv 的静态 `Add` bias folding。
- 支持紧跟 Dense/Conv 的 `BatchNormalization` folding。
- 支持 `AveragePool`、`GlobalAveragePool` 到 channels_last pooling layer-list。
- 支持 `Identity/Dropout/QuantizeLinear/DequantizeLinear` 作为 no-op/precision metadata。
- 对 residual Add、分支图、grouped conv、不安全 transpose 等情况明确抛出 unsupported，避免假成功。

### 5. 当前验证结果
通过测试：

- `tests/test_hls4ml_mcp.py`：14 passed
- `tests/test_demo_examples_schema.py tests/test_demo_model_scripts.py`：14 passed
- `tests/test_vivado_hls_mcp.py tests/test_report_parser.py`：12 passed

真实 hls4ml + mock Vivado 轻跑结果：

| Demo | run_id | status | selected_path | report | errors |
|---|---|---|---|---|---|
| Demo2 MNIST MLP | `mnist_mlp_demo_1ed09a79_02` | success | hls4ml_path | success | none |
| Demo3 Tiny CNN | `mnist_tiny_cnn_154bde8b` | success | hls4ml_path | success | none |
| Demo4 QONNX CNN | `mnist_qonnx_cnn_bc625576_09` | success | hls4ml_path | success | none |

### 6. 未修复/后续问题
- 当前 ONNX/QONNX adapter 仍然不是完整 compiler，不支持任意动态图、任意分支、任意 residual block、grouped/depthwise conv 或复杂 QONNX 量化算子语义。
- 当前优化方法还没有做精度/准确率评估；后续如果接入真实 MNIST 数据，需要补 accuracy/cosine/error tolerance 评估。
- Demo2/Demo3 的参数只是可靠 baseline，不是全局 Pareto 最优；后续若目标板卡确定，再做更系统的 precision/reuse/clock sweep。

---

## 2026-06-05 12:24:37 +08:00：回到 Vivado HLS 2018.3 主线，修复真实综合暴露的 Memory/RAG/Suggestion 污染
### 1. 本次测试做了什么
根据 Vitis 2025.2.1 公平实验结论，本轮不再继续推进 Vitis 默认切换，而是把主线重新收拢到 `Vivado HLS 2018.3`：

- 保持默认工程路线为 `hls4ml backend: Vivado` + `vivado_hls.bat`。
- 使用真实 Vivado HLS 2018.3 复跑 Demo0 `dense_operator.json` 和 Demo1 `matmul_resource.json`。
- 使用 benchmark 复测 Agent 工程指标、RAG 召回指标、unsupported 语义指标。
- 修复真实综合后才暴露出的 memory 快照时序、RAG 检索污染、suggestion 展示污染。

实际执行命令：

```powershell
$env:PYTHONPATH='src'
$env:TMP='D:\hls_agent\standalone_work\dl-op-to-hls-agent\tmp'
$env:TEMP=$env:TMP

python -m pytest tests\test_memory.py tests\test_rag.py tests\test_llm_optimizer_fallback.py tests\test_agent_quality_benchmark.py -q -p no:cacheprovider
python -m pytest tests\test_runtime_hybrid.py -q -p no:cacheprovider
python -m pytest tests\test_token_budget.py -q -p no:cacheprovider
python -m pytest tests\test_main_agent.py -q -p no:cacheprovider

$env:DL_OP_TO_HLS_MOCK_HLS4ML='1'
$env:DL_OP_TO_HLS_MOCK_VIVADO='0'
$env:DL_OP_TO_HLS_HLS_TOOLCHAIN='vivado_hls'
$env:DL_OP_TO_HLS_HLS4ML_BACKEND='Vivado'
$env:DL_OP_TO_HLS_VIVADO_HLS_PATH='D:\Xilinx\Vivado\2018.3\bin\vivado_hls.bat'
python -m dl_op_to_hls.cli run examples\dense_operator.json
python -m dl_op_to_hls.cli run examples\matmul_resource.json

python -m dl_op_to_hls.benchmarks.agent_quality_benchmark `
  --runs dense_16x32_af6abf3c_18 matmul_16x16_resource_9ac8e2e8_20 relu_16_3acb1a59_03 add_16_0b53b9ed_03 existing_dense_project_20fa63c7_03 custom_unsupported_eval_893b0594_03 mnist_mlp_demo_aba95cc1_05 mnist_tiny_cnn_6d3a1cb8_06 mnist_qonnx_cnn_bc625576_07 tiny_residual_block_ad48a995_14 resnet18_boundary_demo_cd40d797_22 dense_vivado_missing_eval_3717adca_03 `
  --rag-eval-file benchmarks\rag_eval_labels.json `
  --rag-top-k 5 `
  --output runs\benchmark_vivado2018_mainline_20260605_after_memory_suggestion_fix.json
```

### 2. 真实 Vivado HLS 2018.3 结果
| Demo | run_id | 状态 | 路径 | Latency | II | BRAM | DSP | FF | LUT | Timing |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---|
| Demo0 Dense | `dense_16x32_af6abf3c_18` | success | fallback_template_path | 269 | 269 | 0 | 16 | 732 | 549 | met |
| Demo1 MatMul | `matmul_16x16_resource_9ac8e2e8_20` | success | fallback_template_path | 2052 | 2052 | 0 | 16 | 265 | 624 | failed |

补充说明：
- Demo0 最新输出中 `memory_candidates[0].value.status = success`，长期记忆不再把成功 run 错记为 `partial_success`。
- Demo0 suggestions 只包含当前 report 相关建议，不再混入 `VivadoNotFoundError` 失败经验。
- Demo1 suggestions 只保留 timing 未满足建议，不再输出 `optimization.xxx {json...}` 这类内部 memory key。

### 3. Benchmark 结果
最新 benchmark 输出文件：

```text
runs/benchmark_vivado2018_mainline_20260605_after_memory_suggestion_fix.json
```

核心指标：

- run_count: 12
- status_counts: success 8，partial_success 4
- artifact_completeness_avg: 1.0
- unsupported_semantics_pass_rate: 1.0
- rag_pollution_rate: 0.0
- RAG macro_precision@5: 0.8
- RAG macro_recall@5: 1.0
- RAG macro_hit@5: 1.0
- RAG macro_mrr: 1.0
- RAG macro_ndcg@5: 1.0
- RAG macro_pollution@5: 0.0

### 4. 遇到的问题与根因
1) 普通优化 query 检索到失败经验
- 现象：真实 Demo0 成功综合后，suggestions 曾引用 `VivadoNotFoundError` 历史失败经验。
- 根因：`retrieve_initial_memory` 固定同时拉取 similar/failure/optimization 三类 memory；`MemoryManager.retrieve_failure_cases` 没有区分“失败查询”和“普通优化查询”。
- 修复：新增 failure query 判定，仅当 query 包含 error/missing/unsupported/recoverable 等强失败锚点时返回 failure cases；普通 latency/resource 查询不再注入失败 memory。

2) 长期记忆把成功 run 错记为 partial_success
- 现象：Demo0/1 顶层 `state.status=success`，但 `memory_candidates` 的 episodic summary/value 曾记录 `partial_success`。
- 根因：`MemorySpecialist` 在自身 `Promote memories` todo 仍处于 `in_progress` 时读取 `state.json`，状态计算被当前 memory todo 干扰。
- 修复：新增 memory-ready state snapshot；在写给 MemorySpecialist 的 `state.json` 前，排除 `Promote memories` 自身的未完成状态。如果其余 todo 已完成、report 成功且无结构化错误，则按 success 写入长期记忆候选。

3) suggestion 将结构化 memory 当成自然语言历史经验
- 现象：Demo1 suggestions 曾出现 `Prior experience hint: optimization.matmul... {"objective": "resource"}`。
- 根因：`build_suggestions` 直接取 `rag_context[0]`，没有区分自然语言经验与内部结构化 memory payload。
- 修复：新增 `_select_prior_hints`，过滤 `episode.*`、`semantic.*`、`optimization.*`、`skill.*`、包含 JSON braces 的结构化摘要，只允许自然语言经验进入 suggestions。

4) Windows pytest 临时目录权限异常
- 现象：pytest setup 阶段报 `PermissionError: C:\Users\IC\AppData\Local\Temp\pytest-of-IC`。
- 根因：当前用户对默认 pytest temp root 权限异常。
- 修复：测试命令统一设置 `TMP/TEMP` 到独立工程目录 `D:\hls_agent\standalone_work\dl-op-to-hls-agent\tmp`。

### 5. 已修复内容
- `memory_manager.py`：增加 task-family anchor、failure-query gating、成功经验加权、带错误 partial_success 降权、候选 memory 写盘前清洗。
- `runtime.py`：增加 memory-ready state snapshot，避免 MemorySpecialist 读取半成品状态。
- `suggest_optimization.py`：只展示自然语言 prior hints，避免把内部 memory JSON 暴露给 summary/suggestions。
- `rag/retriever.py`：增加 source-anchor ranking、strong-anchor static docs boost、重复 chunk 去重，避免静态 playbook 被重复短 memory 淹没。
- 测试覆盖新增 memory failure gating、memory candidate 清洗、成功经验排序、RAG 静态 playbook 排序、suggestion prior hint 过滤。

### 6. 当前测试结果
通过：

- `tests/test_memory.py tests/test_rag.py tests/test_llm_optimizer_fallback.py tests/test_agent_quality_benchmark.py`：38 passed
- `tests/test_runtime_hybrid.py`：12 passed
- `tests/test_token_budget.py`：1 passed
- `tests/test_main_agent.py`：7 passed

说明：
- `pytest` 全量直接跑会因为集成测试总耗时较长而容易触发命令超时；拆分测试均通过。
- 本轮真实 Vivado HLS 2018.3 Demo0/Demo1 都成功执行到 csynth/report parsing。

### 7. 未修复/后续问题
- Demo1 MatMul timing failed 是真实综合结果，不是 Agent 框架错误；后续应作为优化实验入口，尝试 clock period、pipeline/dataflow、array partition/reuse-factor 的设计空间探索。
- Vivado 2018.3 仍是当前主线；Vitis 2025.2.1 保留为可选实验路径，不作为默认路径。
- Demo2-4 的 hls4ml 真实模型链路仍需要继续围绕 Vivado backend 修 Gemm/Shape/Flatten/QONNX 兼容，而不是依赖 Vitis 升级解决。

---

## 2026-06-05 10:04:07 +08:00：完成 Vivado HLS vs Vitis HLS 公平隔离实验，并修复 Vitis report timing 判定
### 1. 本次测试做了什么
围绕 Demo4 `mnist_qonnx_cnn.json` 生成的 hls4ml CNN HLS 工程，补充了 Vitis 公平性隔离实验脚本：

- 新增 `scripts/run_vitis_fairness_experiments.py`，用于复跑 Vivado HLS 2018.3 与 Vitis HLS 2025.2.1 的可控对照实验。
- 实验 1：同一份 Vivado backend HLS 源码，分别用 `vivado_hls` 与 `vitis-run --mode hls` 综合，隔离“综合器差异”。
- 实验 2：同一份 Vitis backend 工程，调整 `clock_uncertainty` 与 `config_dataflow`，隔离“Vitis 默认策略差异”。
- 实验 3：将部分 deprecated `RESOURCE` pragma 迁移到 `bind_storage`，隔离“pragma 兼容迁移”影响。
- 实验 4：新增 Vitis best-effort tuned 组，组合 normalized uncertainty、FIFO sizing off、explicit stream depth、bind_storage migration，回答“Vitis 在安全 TCL 级调参下最好能做到什么样”。

实际执行命令：

```powershell
$env:PYTHONPATH='src'
python scripts\run_vitis_fairness_experiments.py --output-root runs\vitis_fairness_qonnx_20260605
python scripts\run_vitis_fairness_experiments.py --output-root runs\vfe_qonnx_0605 --include g2_vitis_fifo2
python -m pytest tests\test_report_parser.py -q -p no:cacheprovider
python -m pytest -q -p no:cacheprovider
python -m py_compile scripts\run_vitis_fairness_experiments.py
```

### 2. 本轮真实 HLS 对照结果
| 组别 | 工具链 | 目的 | 状态 | Latency | BRAM | DSP | FF | LUT | Timing |
|---|---|---|---|---:|---:|---:|---:|---:|---|
| g1 Vivado backend + Vivado HLS | Vivado 2018.3 | Vivado baseline | success | 775-777 | 8 | 0 | 9,888 | 49,459 | met |
| g1 Vivado backend + Vitis HLS | Vitis 2025.2.1 | 同源代码换综合器 | report_missing | - | - | - | - | - | failed before report |
| g2 Vitis backend + Vitis HLS | Vitis 2025.2.1 | Vitis baseline，uncertainty=1.25ns | success | 6679-6681 | 10 | 0 | 132,970 | 111,370 | met |
| g2 + FIFO sizing off | Vitis 2025.2.1 | 隔离 FIFO 默认 sizing | success | 6679-6681 | 10 | 0 | 132,970 | 111,370 | met |
| g3 + bind_storage | Vitis 2025.2.1 | 迁移 RESOURCE 到 bind_storage | success | 6679-6681 | 10 | 0 | 132,970 | 111,370 | met |
| g4 tuned combo | Vitis 2025.2.1 | Vitis safe TCL best-effort | success | 5904-5904 | 10 | 0 | 176,854 | 172,590 | met |

补充核对：
- `parameters.h` 在 Vivado backend 与 Vitis backend 中完全一致。
- `myproject.cpp` 仅存在 Vitis backend 多一个 `#include <iostream>` 和空行的差异，网络结构、权重、层调用主体一致。
- Vitis backend 的 `project.tcl` 默认 `clock_uncertainty 27%`，Vivado backend 为 `12.5%`；本轮实验显式统一为 `1.25ns`，避免把默认 uncertainty 差异误判为综合器差异。

### 3. 结论
- 第三组不是 Vitis 最优组，只是 deprecated pragma 迁移验证；它没有改善 latency 或资源。
- 第四组是当前“安全 TCL 级 best-effort”对照：latency 从 6679-6681 降到 5904，但 FF/LUT 从 132,970/111,370 增加到 176,854/172,590。
- 当前 Demo4 上整体最优仍是 Vivado 2018.3：latency、FF、LUT 都显著优于 Vitis 2025.2.1。
- Vitis 更差的主因不是模型不同，也不是单纯 clock uncertainty；更像是 Vitis 对 hls4ml CNN 的 DATAFLOW canonical form、FIFO/stream 推断和 array partition 处理方式不同。
- 如果要追求真正 Vitis 最优，需要进入 hls4ml Vitis backend/custom template 层改生成代码结构，而不是只改 TCL 选项。

### 4. 遇到的问题与根因
1) Vitis report timing 被旧 parser 误判
- 现象：Vitis report 的 ap_clk 表包含 target、estimated、uncertainty 三列；旧 parser 只比较 `estimated <= target`。
- 根因：Vitis 的有效 timing budget 应是 `target - uncertainty`。
- 修复：`report_parser.py` 新增 `uncertainty_ns` 和 `effective_budget_ns`，timing met 改为比较 `estimated_ns <= effective_budget_ns`。

2) `config_dataflow` 语法初版写错
- 现象：Vitis 报 `config_dataflow: Unknown option 'true'`。
- 根因：Vitis 2025.2.1 的 `-disable_fifo_sizing_opt` 是 flag，不应写成额外 positional `true`。
- 修复：改为 `config_dataflow -disable_fifo_sizing_opt -fifo_depth 2 -start_fifo_depth 2 -scalar_fifo_depth 2 -task_level_fifo_depth 2`。

3) Windows 路径过长污染实验结果
- 现象：长目录名下 `g2_vitis_backend_vitis_tool_u1p25_fifo_sizing_off` 已生成 report，但进程 returncode=1。
- 根因：Vitis 后端生成的 VHDL 文件名很长，叠加长工作目录后触发 Windows path length 错误。
- 修复：实验脚本改用短 `dir_name`，并新增 `--include` 只复跑指定变体；短路径复跑 `g2_vitis_fifo2` 后 returncode=0，metrics 不变。

4) Vivado backend 源码无法直接由 Vitis 成功综合
- 现象：`g1_vivado_backend_same_source_vitis_tool_u1p25` 在 report 前失败。
- 根因：Vitis 对 Vivado backend 生成的 DATAFLOW canonical form 更严格，日志中出现 `Dataflow form checks found` 与 `Compilation of the preprocessed source 'myproject' failed`。
- 处理：记录为真实工具链兼容边界，不用 fallback 掩盖；后续若要支持，需要专门的 Vitis 代码生成/重写路径。

### 5. 已修复内容
- 新增 `scripts/run_vitis_fairness_experiments.py`，沉淀可复跑的真实工具链公平实验。
- `.gitignore` 增加 Vitis 临时噪声：`.hls.failed`、`dfx_runtime.txt`、`logs/`、`tmp/`。
- `report_parser.py` 支持 Vitis ap_clk uncertainty，并输出 `effective_budget_ns`。
- `tests/test_report_parser.py` 增加 Vitis timing uncertainty 单测。
- 新增 `docs/vitis_fairness_experiments.md`，说明实验分组、复跑方式与结论。

### 6. 当前测试结果
- `python -m pytest tests\test_report_parser.py -q -p no:cacheprovider`：通过。
- `python -m pytest -q -p no:cacheprovider`：通过。
- `python -m py_compile scripts\run_vitis_fairness_experiments.py`：通过。
- 真实 Vitis 短路径复跑 `g2_vitis_fifo2`：returncode=0，report success，metrics 与长路径一致。

### 7. 未修复完成的问题与原因
- 尚未全面切换到 Vitis：真实隔离实验显示 Demo4 上 Vivado 2018.3 仍显著更优。
- 尚未实现 Vitis 专用 HLS 代码结构优化：这需要改 hls4ml 生成模板或增加 Vitis-specific graph/code rewrite，风险和工作量高于 TCL 参数调优。
- Vitis 对 DATAFLOW canonical form 的警告仍存在：当前记录为后续专项优化方向，不在本轮用宽松 fallback 掩盖。

---

## 2026-06-05 08:50:39 +08:00：接入 Vitis HLS 2025.2.1 双工具链，并完成真实 DeepSeek-V4-Pro + Vitis Demo2-4 复测
### 1. 本次测试做了什么
在现有 Vivado HLS 2018.3 真实链路之外，新增 Vitis HLS 2025.2.1 可选工具链，并用真实 LLM + 真实 hls4ml + 真实 Vitis HLS 复测 Demo2-Demo4。

环境与模式：
- LLM：OpenAI-compatible API，Base URL `https://llmapi.paratera.com`，模型名严格使用 `DeepSeek-V4-Pro`。
- hls4ml：真实库，`DL_OP_TO_HLS_MOCK_HLS4ML=0`。
- HLS 工具链：Vitis 2025.2.1，`DL_OP_TO_HLS_HLS_TOOLCHAIN=vitis_hls`。
- Vitis 命令：`D:\vitis25.2.1\2025.2.1\Vitis\bin\vitis-run.bat`。
- hls4ml backend：`DL_OP_TO_HLS_HLS4ML_BACKEND=Vitis`。
- runtime：LLM-first / strict 模式，未静默降级为 deterministic planner。

关键真实 run：
- Demo2 MNIST MLP：`mnist_mlp_demo_aba95cc1_04`
- Demo3 Tiny CNN：`mnist_tiny_cnn_6d3a1cb8_05`
- Demo4 Torch/QONNX CNN：`mnist_qonnx_cnn_bc625576_06`

### 2. 本轮真实 Vitis 运行结果
Demo2 `examples/mnist_mlp_hls4ml.json`：
- status：`success`
- selected_path：`hls4ml_path`
- report_status：`success`
- latency：205-208 cycles
- resources：BRAM 415、DSP 933、FF 163499、LUT 62913
- timing：target 5.0ns、estimated 8.187ns、timing_met=false

Demo3 `examples/mnist_tiny_cnn.json`：
- status：`success`
- selected_path：`hls4ml_path`
- report_status：`success`
- latency：6987-7133 cycles
- resources：BRAM 14、DSP 30、FF 152301、LUT 117690
- timing：target 10.0ns、estimated 7.588ns、timing_met=true

Demo4 `examples/mnist_qonnx_cnn.json`：
- status：`success`
- selected_path：`hls4ml_path`
- report_status：`success`
- latency：6826-6972 cycles
- resources：BRAM 10、DSP 0、FF 133712、LUT 111638
- timing：target 10.0ns、estimated 9.070ns、timing_met=true

### 3. 与 Vivado HLS 2018.3 的对比结论
同一批 Demo 在 Vivado HLS 2018.3 上的最近真实结果：
- Demo2：latency 209-212，BRAM 1609、DSP 933、FF 1864080、LUT 610956。
- Demo3：latency 761-763，BRAM 14、DSP 29、FF 16390、LUT 58161。
- Demo4：latency 775-777，BRAM 8、DSP 0、FF 9888、LUT 49459。

阶段性判断：
- Demo2：Vitis 资源显著下降，但 5ns timing 未过。
- Demo3/Demo4：Vitis 能跑通，但 latency、FF、LUT 明显高于 Vivado 2018.3。
- 因此不全面切换到 Vitis；当前保持双配置，默认仍为 `vivado_hls`，Vitis 作为可选现代工具链继续优化。

### 4. 遇到的问题与根因
1) Vitis 2025.2.1 没有 `vitis_hls.bat`
- 现象：安装目录中不存在传统 `vitis_hls.bat`。
- 根因：当前 Vitis 版本推荐通过 `vitis-run --mode hls --tcl --input_file <tcl>` 执行 HLS。
- 修复：`vivado_hls_adapter.py` 增加 `vitis_hls` toolchain 分支，自动解析 `vitis-run.bat`，并复用已有 hls4ml TCL。

2) Vitis report timing 格式与 Vivado 2018.3 不完全一致
- 现象：Vitis report 中 timing 行包含 `10.00 ns` / `9.070 ns`，初版 parser 没有解析出 timing。
- 根因：原 parser 只覆盖旧 Vivado report 的数字格式。
- 修复：`report_parser.py` 增加带 `ns` 单位的 Vitis timing regex。

3) Vitis log 中的 `0 error(s)` 被误判为 synthesis error
- 现象：Demo2 初跑时 state 里出现 `VivadoSynthesisError`，但真实 log 是 `0 error(s), 1 warning(s)`。
- 根因：log parser 只按关键词匹配 `error`，没有识别 `0 error(s)` 这种否定形式。
- 修复：`vivado_hls_adapter.py` 的 error detector 忽略 `0 error(s)` / `0 errors`。

4) LLM planner 在真实 toolchain 中计划了 `hls4ml.run_csim`
- 现象：Demo3 初跑时 `hls4ml.run_csim` 返回结构化错误，后续 Todo 被阻塞。
- 根因：真实 hls4ml csim 目前统一交给 VivadoSpecialist/Vitis toolchain 执行，不应该让 Main Agent 计划 hls4ml direct csim。
- 修复：从 `hls4ml_model_flow.yaml` 的 allowlist 移除 `hls4ml.run_csim`，并在 `prompt_context.py` 中明确 real csim/csynth 交给 VivadoSpecialist。

5) LLM 计划生成了 summary / memory 循环依赖
- 现象：Demo3 初跑时真实综合和 report 都成功，但 `Promote memory` 与 `Write summary` 互相依赖，最终 run 被误标为 `partial_success`。
- 根因：LLM 计划图不是天然 DAG，需要 runtime 对核心 HLS 工作流和 finalization 阶段做结构化规范化。
- 修复：`llm_runtime.py` 增加依赖图规范化和 cycle removal，将终止阶段固定为 `suggestion -> summary -> memory`。

6) Windows GBK 控制台导致 CLI JSON 输出失败
- 现象：Demo4 初跑真实 run 成功，但 CLI 打印 state JSON 时遇到特殊连字符，触发 `UnicodeEncodeError`。
- 根因：Windows 默认控制台编码与 UTF-8 JSON 输出不一致。
- 修复：`cli.py` 启动时对 stdout/stderr 做 UTF-8 + replace 重配置。

7) 真实复测汇总脚本本身有 PowerShell 兼容问题
- 现象：脚本使用 `Resolve-Path` 写尚未创建的 stdout 文件，并使用当前 PowerShell 不支持的 `ConvertFrom-Json -Depth`。
- 根因：这是测试汇总脚本的兼容性问题，不是 Agent 运行链路问题。
- 处理：改为从最新 run 目录的 `state.json` / `todos.json` 读取结果；后续 benchmark 脚本应避免依赖新版 PowerShell 参数。

### 5. 已修复内容
- `src/dl_op_to_hls/core/config.py`：新增 `hls_toolchain`、`hls4ml_backend`、`vitis_hls_path` 配置。
- `src/dl_op_to_hls/main_agent/agent.py`：将 hls4ml backend override 和 HLS toolchain 注入 adapter。
- `src/dl_op_to_hls/adapters/hls4ml_adapter.py`：支持 `DL_OP_TO_HLS_HLS4ML_BACKEND=Vitis`。
- `src/dl_op_to_hls/adapters/vivado_hls_adapter.py`：支持 `vitis-run --mode hls`，并保留 Vivado 2018.3 路径。
- `src/dl_op_to_hls/tools/report_parser.py`：兼容 Vitis timing report。
- `src/dl_op_to_hls/main_agent/todo.py`：`completed_with_warning` 现在满足后续依赖，避免 warning 阻断主流程。
- `src/dl_op_to_hls/main_agent/llm_runtime.py`：规范化 LLM Todo DAG，移除 summary/memory 循环依赖。
- `src/dl_op_to_hls/cli.py`：修复 Windows 控制台 UTF-8 输出问题。
- `skills/hls4ml_model_flow.yaml`、`src/dl_op_to_hls/skills/prompt_context.py`：移除真实链路中不应规划的 `hls4ml.run_csim`。
- `README.md`：新增 Vivado/Vitis 双工具链配置说明。

### 6. 当前测试结果
- focused pytest：`tests/test_llm_runtime_plan_validation.py`、`tests/test_todo.py`、`tests/test_vivado_hls_mcp.py`、`tests/test_report_parser.py`、`tests/test_runtime_config.py`、`tests/test_hls4ml_mcp.py`、`tests/test_permissions.py`、`tests/test_skill_registry.py`、`tests/test_skill_policy.py` 全部通过。
- full pytest：`python -m pytest -q -p no:cacheprovider` 全部通过。
- 真实 DeepSeek-V4-Pro + hls4ml + Vitis Demo2-Demo4：全部生成真实 csynth report。
- Demo3/Demo4 修复后复测：CLI exit code 均为 0，state 均为 `success`。
- trace 中确认包含 `LLMPlanAccepted`、`LLMReActAutoDelegated`、`SpecialistSelected`、`ContextEnvelopeCreated`、`SpecialistFinished`、`SpecialistResultMerged`。

### 7. 未修复完成的问题与原因
- 尚未将默认工具链全面切换到 Vitis，因为真实指标不支持“Vitis 效果更好”的结论；Vitis 当前作为可选后端保留。
- Demo2 Vitis 虽然 report 成功，但 5ns timing 未过，需要后续做 clock/reuse/precision sweep 或修改 objective。
- Demo3/Demo4 Vitis 延迟和 LUT/FF 明显高于 Vivado 2018.3，可能需要专门的 Vitis backend 配置调优，而不是直接沿用 Vivado 2018.3 的 demo 参数。
- 当前 Vitis 路径复用了 hls4ml 生成的 TCL，尚未针对 Vitis 2025.2.1 新特性做优化探索。

---

## 2026-06-04 22:35:34 +08:00：Demo4 改造为 Torch/QONNX 量化演示，并跑通真实 DeepSeek-V4-Pro + hls4ml + Vivado Demo2-4
### 1. 本次测试做了什么
按开发期真实链路重新验证 Demo2-Demo4：
- LLM：OpenAI-compatible API，Base URL `https://llmapi.paratera.com`，模型名严格使用 `DeepSeek-V4-Pro`。
- LLM 可用性：先用极小请求确认 `DeepSeek-V4-Pro` 返回 `OK`，避免大小写或模型名误配。
- hls4ml：真实库路径，`DL_OP_TO_HLS_MOCK_HLS4ML=0`。
- Vivado HLS：真实 `D:\Xilinx\Vivado\2018.3\bin\vivado_hls.bat`，`DL_OP_TO_HLS_MOCK_VIVADO=0`。
- runtime：LLM-first / strict 模式，未静默降级为 deterministic planner。

本轮真实 LLM + Vivado 日志目录：
- `runs/real_demo_logs_20260604_221416_llm_deepseek_demo2_4_final/`

最终真实 run：
- Demo2 MNIST MLP：`mnist_mlp_demo_aba95cc1_02`
- Demo3 Tiny CNN：`mnist_tiny_cnn_6d3a1cb8_02`
- Demo4 Torch/QONNX CNN：`mnist_qonnx_cnn_bc625576_02`

### 2. 本轮真实运行结果
Demo2 `examples/mnist_mlp_hls4ml.json`：
- status：`success`
- selected_path：`hls4ml_path`
- report_status：`success`
- latency：209-212 cycles
- resources：BRAM 1609、DSP 933、FF 1864080、LUT 610956
- elapsed：492 秒

Demo3 `examples/mnist_tiny_cnn.json`：
- status：`success`
- selected_path：`hls4ml_path`
- report_status：`success`
- latency：761-763 cycles
- resources：BRAM 14、DSP 29、FF 16390、LUT 58161
- elapsed：375 秒

Demo4 `examples/mnist_qonnx_cnn.json`：
- status：`success`
- selected_path：`hls4ml_path`
- report_status：`success`
- latency：775-777 cycles
- resources：BRAM 8、DSP 0、FF 9888、LUT 49459
- elapsed：390 秒

### 3. 遇到的问题与根因
1) Demo4 原 QKeras/H5 输入链路不适合作为当前主线 demo
- 现象：旧 Demo4 依赖 QKeras/H5，而当前真实 adapter 主线主要围绕 ONNX/QONNX 静态图。
- 根因：QKeras/H5 和 Torch/PyTorch 是不同生态的输入前端；若强行用 H5 会继续把重点卡在 Keras/QKeras frontend 兼容，而不是验证 Agent 的主路径能力。
- 修复：新增 `scripts/make_mnist_qonnx_cnn.py`，从 Torch 生成静态量化风格 ONNX/QONNX demo；新增 `examples/mnist_qonnx_cnn.json`，将 Demo4 改为 Torch/QONNX FPGA-aware 量化演示。

2) 真实 hls4ml 1.3 默认 ONNX parser 对当前 Torch 导出图不够稳
- 现象：MLP/CNN 模型中出现 `Gemm`、`Reshape`、NCHW Conv 等 hls4ml 默认 parser 不稳定或不直接支持的模式。
- 根因：PyTorch 导出的 ONNX 与 hls4ml 期望的 Keras-like layer 表达存在前端语义差异。
- 修复：在 `hls4ml_adapter.py` 增加窄范围真实 ONNX/QONNX layer-list adapter：`Gemm -> Dense`、`Relu -> Activation`、`Conv NCHW -> channels_last Conv2D`、`MaxPool -> MaxPooling2D`、`Flatten/Reshape -> static Reshape`，并跳过 `Shape/Concat/Constant` 等静态 shape 辅助节点。

3) Vivado HLS 2018.3 Windows 对 hls4ml 新生成源码的 STL/debug include 兼容性差
- 现象：真实 Vivado 2018.3 在综合 hls4ml firmware 时会被 `<iostream>`、`<fstream>`、`std::vector` 等 debug/CSim 相关 include 或 helper 代码卡住。
- 根因：旧 Vivado HLS 自带 clang/libstdc++ 环境对现代 hls4ml 生成的部分非综合辅助代码兼容性不好。
- 修复：在 `vivado_hls_adapter.py` 增加只作用于 copied Vivado work dir 的 legacy sanitizer：对 `nnet_helpers.h`、`nnet_mult.h`、`nnet_pooling.h` 和 top source 中的非综合 STL/debug 片段做 `__SYNTHESIS__` 保护或移除，不修改原 hls4ml project。

4) Demo2 初始 latency 配置导致资源/展开过激
- 现象：初始低 reuse 配置下 Vivado 在 Dense Product unroll 处失败。
- 根因：MNIST MLP 784 输入维度对旧 Vivado 2018.3 + `Strategy=Latency` + 低 reuse 过于激进。
- 修复：Demo2 改为 `Strategy=Resource`、`reuse_factor=64`，以优先验证主路径可综合性。当前资源报告仍显示该 MLP 对 `xc7z020` 很重，但真实 report 已可生成。

5) Demo3 / Demo4 初始 28x28 CNN 触发 Vivado partition 阈值
- 现象：真实 Vivado 报 `layer2_out.V` 分区元素数超过阈值。
- 根因：28x28 输入下中间 feature map 过大，hls4ml 默认 array partition 对 Vivado 2018.3 过重。
- 修复：Demo3/Demo4 改为 14x14 静态输入，用于面试 demo 的 tiny CNN/QONNX CNN 路径验证；后续更大模型应进入 boundary/unsupported 或优化 sweep。

6) LLM planner 曾把 Demo4 resource objective 错选为 optimization-only skill
- 现象：Demo4 只生成 suggestion，没有先执行 hls4ml 模型转换。
- 根因：skill precondition 没有明确要求 optimization flow 必须已有 report metrics。
- 修复：`skills/policy.py` 增加 task-aware skill precondition 校验；`prompt_context.py` 明确初始 model-to-HLS 任务应优先 `hls4ml_model_flow`，optimization-only skill 只能用于已有 report 的二次优化。

### 4. 已修复内容
- `examples/mnist_qonnx_cnn.json`：新增 Torch/QONNX Demo4 任务。
- `scripts/make_mnist_qonnx_cnn.py`：新增 Torch 生成 QONNX 风格静态量化 ONNX 脚本。
- `scripts/make_mnist_mlp_onnx.py`、`scripts/make_mnist_tiny_cnn_onnx.py`：改为静态 shape，更适配 hls4ml/Vivado 2018.3。
- `models/generated/*.onnx`：重新生成 MLP、Tiny CNN、QONNX CNN 模型。
- `src/dl_op_to_hls/adapters/hls4ml_adapter.py`：增加真实 ONNX/QONNX layer-list adapter 和 fallback parser。
- `src/dl_op_to_hls/adapters/vivado_hls_adapter.py`：增加 Vivado 2018.3 legacy sanitizer。
- `skills/hls4ml_model_flow.yaml`：加入 `qonnx` frontend。
- `src/dl_op_to_hls/skills/policy.py`：增加 optimization-only skill 的 report metrics precondition。
- `src/dl_op_to_hls/main_agent/reflector.py`：修正缺少 selected path 或 report missing 时的 success / partial_success 语义。
- `README.md`、`docs/demo_examples.md`、`docs/model_generation.md`、`docs/agent_benchmark_suite.md`：同步 Demo4 改造说明。

### 5. 当前测试结果
- 真实 DeepSeek-V4-Pro + hls4ml + Vivado Demo2-Demo4：全部成功。
- Demo2/Demo3/Demo4 的 trace 均包含 specialist routing、context envelope、Vivado specialist、Optimization specialist、memory 写入等关键事件。
- Context isolation 在真实 report 上生效：Vivado specialist 只向 Main Agent 返回压缩 metrics/summary，不把完整 `csynth.log` / `csynth.rpt` 放进 AgentState。

### 6. 未修复完成的问题与原因
- Demo4 当前是 Torch 生成的 QONNX 风格静态量化演示，重点验证 Torch -> ONNX/QONNX -> hls4ml -> Vivado 主路径；尚未引入 Brevitas/QONNX 标准量化算子图，也未做精度/准确率 benchmark。
- ONNX/QONNX layer-list adapter 是面向本项目 demo 的窄范围实现，不承诺支持任意 PyTorch/ONNX 模型。
- Demo2 MLP 虽然真实 csynth 成功，但资源明显超过 `xc7z020` 的实际可用规模；这应作为后续 optimization sweep / boundary demo 的素材，而不是宣称可直接部署。
- 当前真实测试验证了 HLS project generation 和 csynth report parsing，尚未完成 PyTorch reference output 与 hls4ml csim 输出的数值一致性验证。

---

## 2026-06-04 20:09:34 +08:00：建立 Agent 能力 Benchmark Suite
### 1. 本次测试做了什么
为项目新增一套面向 Agent 实习岗位展示的能力 benchmark，不再只用“demo 能跑”描述贡献。

新增 benchmark suite：
- `benchmarks/agent_capability_suite.json`

新增 benchmark 专用任务：
- `benchmarks/tasks/custom_unsupported_operator.json`
- `benchmarks/tasks/dense_vivado_missing.json`

新增文档：
- `docs/agent_benchmark_suite.md`

新增 CLI 能力：
- `dl-op-to-hls benchmark --suite-file benchmarks\agent_capability_suite.json`

### 2. Benchmark 覆盖内容
当前 suite 包含 12 个 case，覆盖：
- operator fallback：Dense / MatMul / ReLU / Add。
- existing HLS project：已有工程路径。
- hls4ml mock path：MNIST MLP / Tiny CNN / QKeras task。
- unsupported recovery：自定义不支持算子 / residual block / ResNet18 boundary。
- toolchain recovery：强制 Vivado 路径缺失，验证 `VivadoNotFoundError` 结构化恢复。

评估指标包括：
- status / selected_path / report_status 契约。
- trace events：`TodoCreated`、`SpecialistSelected`、`SpecialistResultMerged` 等。
- Specialist 使用情况。
- artifact completeness。
- forbidden error types。
- Vivado metrics 是否存在。
- unsupported path 是否保持 partial_success，是否避免编造 latency / DSP 建议。
- RAG precision@k、recall@k、hit@k、MRR、nDCG、term coverage、pollution@k。

### 3. 本轮运行结果
运行命令：

```powershell
python -m dl_op_to_hls.cli benchmark --run-suite --suite-file benchmarks\agent_capability_suite.json --rag-eval-file benchmarks\rag_eval_labels.json --rag-top-k 5 --output runs\benchmarks\agent_capability_suite_smoke.json
```

复评结果：
- suite case_count：12。
- suite pass_count：12。
- suite pass_rate：1.0。
- suite average_score：1.0。
- category_scores：operator_fallback / model_hls4ml / unsupported_recovery / existing_project / toolchain_recovery 全部 1.0。
- artifact_completeness_avg：1.0。
- unsupported_semantics_pass_rate：1.0。
- rag_pollution_rate：0.0。
- RAG macro_precision_at_k：0.65。
- RAG macro_recall_at_k：1.0。
- RAG macro_hit_at_k：1.0。
- RAG macro_mrr：0.8。
- RAG macro_ndcg_at_k：0.3869。
- RAG macro_relevant_term_coverage_at_k：1.0。
- RAG macro_pollution_at_k：0.05。

### 4. 遇到的问题与根因
1) 初版 benchmark 标注过于理想化
- 现象：第一次 suite 运行时，部分 mock hls4ml 模型 case 被标注成 unsupported，但实际 mock adapter 走的是 hls4ml happy path。
- 根因：benchmark 期望没有区分 mock contract suite 和真实 toolchain suite。
- 修复：将 MNIST MLP / Tiny CNN / QKeras 的 mock suite 期望调整为 `hls4ml_path`，真实 hls4ml 边界继续由真实 demo benchmark 单独呈现。

2) unsupported custom operator case 的语义需要更精确
- 现象：自定义不支持算子会经历 LLM candidate 失败，然后生成 unsupported report；初版 benchmark 把内部 `LLMGenerationError` 视为禁止错误。
- 根因：benchmark 没有区分“内部候选失败且被正确恢复”和“最终 run 失败”。
- 修复：允许该 case 出现 1 个 failed todo 和 `LLMGenerationError`，但要求最终 `partial_success`、`unsupported_path`、`unsupported_report.md` 存在，并禁止 `PermissionDeniedError`。

3) 1.0 分容易被误读为泛化满分
- 现象：suite pass_rate 达到 1.0 后，容易让人误以为 Agent 已经全面泛化。
- 根因：小规模 contract suite 和大规模 generalization benchmark 的定位不同。
- 修复：新增 `docs/agent_benchmark_suite.md`，明确说明 1.0 只代表 12 个明确契约 case 全部通过，是稳定回归基线，不代表开放域泛化。

### 5. 已修复内容
- `src/dl_op_to_hls/benchmarks/agent_quality_benchmark.py`：增加 suite 文件加载、case 级契约评分、category score、per-case env/mock/runner 支持。
- `src/dl_op_to_hls/cli.py`：新增 benchmark `--suite-file` 参数。
- `tests/test_agent_quality_benchmark.py`：新增 suite 加载、case 评分、category 聚合测试。
- `benchmarks/agent_capability_suite.json`：新增 12-case Agent 能力评估集。
- `docs/agent_benchmark_suite.md`：新增 benchmark 设计、指标解释、运行方式和面试口径。

### 6. 当前测试结果
- `python -m pytest tests\test_agent_quality_benchmark.py -q -p no:cacheprovider`：通过。
- `python -m pytest -q -p no:cacheprovider`：209 个测试通过。
- `python -m dl_op_to_hls.cli benchmark --run-suite --suite-file benchmarks\agent_capability_suite.json ...`：12/12 case 通过。

### 7. 未修复完成的问题与原因
- 当前 suite 是 curated contract benchmark，case 数量仍偏少，不应声称泛化能力已经充分验证。
- 当前 suite 主要使用 deterministic/mock 路径，因此 `llm_decision_count_total=0` 是预期结果；LLM planning 能力需要单独用 real LLM suite 评估。
- RAG macro_precision@k 为 0.65、nDCG@k 为 0.3869，说明召回覆盖足够但排序质量仍有优化空间。
- 后续应增加 hard-negative case、重复运行、p95、LLM JSON 合规率、tool selection accuracy、repair success rate 等指标。

---

## 2026-06-04 18:24:00 +08:00：真实 DeepSeek-V4-Pro + Vivado Demo0-6 复测与 Agent 量化指标优化
### 1. 本次测试做了什么
按真实环境重新运行 Demo0-Demo6：
- LLM：OpenAI-compatible API，模型 `DeepSeek-V4-Pro`。
- HLS 工具：真实 `D:\Xilinx\Vivado\2018.3\bin\vivado_hls.bat`。
- hls4ml / Vivado：`DL_OP_TO_HLS_MOCK_HLS4ML=0`、`DL_OP_TO_HLS_MOCK_VIVADO=0`。
- runtime：strict 模式，未静默降级为确定性 planner。

本轮真实 demo 日志目录：
- `runs/real_demo_logs_20260604_174903/`

最终纳入 benchmark 的 run：
- Demo0 Dense：`dense_16x32_af6abf3c_12`
- Demo1 MatMul：`matmul_16x16_resource_9ac8e2e8_15`
- Demo2 MNIST MLP：`mnist_mlp_demo_4ff92a59_14`
- Demo3 Tiny CNN：`mnist_tiny_cnn_188af60c_13`
- Demo4 QKeras CNN：`mnist_qkeras_cnn_a7e2cdc5_11`
- Demo5 Tiny residual block：`tiny_residual_block_ad48a995_11`
- Demo6 ResNet18 boundary：`resnet18_boundary_demo_cd40d797_19`

最终 benchmark 输出：
- `runs/benchmarks/agent_quality_benchmark_real_20260604_174903_final.json`
- `runs/benchmarks/agent_quality_benchmark_real_20260604_174903_final.md`

### 2. 真实 Demo0-6 结果
| Demo | run_id | 状态 | 路径 | 真实 Vivado report |
|---|---|---|---|---|
| Demo0 | `dense_16x32_af6abf3c_12` | success | fallback_template_path | latency 269 cycles, DSP 16, LUT 549, timing met |
| Demo1 | `matmul_16x16_resource_9ac8e2e8_15` | success | fallback_template_path | latency 2052 cycles, DSP 16, LUT 624, timing not met |
| Demo2 | `mnist_mlp_demo_4ff92a59_14` | partial_success | unsupported_path | hls4ml/ONNX 边界，未伪造 metrics |
| Demo3 | `mnist_tiny_cnn_188af60c_13` | partial_success | unsupported_path | hls4ml/ONNX 边界，未伪造 metrics |
| Demo4 | `mnist_qkeras_cnn_a7e2cdc5_11` | partial_success | unsupported_path | H5/QKeras frontend 边界，未伪造 metrics |
| Demo5 | `tiny_residual_block_ad48a995_11` | partial_success | unsupported_path | residual boundary，生成可行动报告 |
| Demo6 | `resnet18_boundary_demo_cd40d797_19` | partial_success | unsupported_path | ResNet18 boundary，生成 unsupported report |

### 3. 量化指标提升
对比上一轮真实 benchmark（`runs/real_demo_logs_20260604_171039`）与本轮最终 benchmark：
- 成功 demo 数：1/7 -> 2/7，Demo1 MatMul 从 `partial_success` 修复为 `success`。
- LLM decision 总数：52 -> 32，减少 20 次，下降约 38.5%。
- ContextEnvelope 总数：37 -> 20，下降约 45.9%，说明不必要的 Main Agent 顶层 ReAct 被减少。
- Artifact completeness avg：0.987 -> 1.0。
- RAG Hit@K：0.75 -> 1.0。
- RAG MRR：0.625 -> 1.0。
- RAG relevant-term coverage@K：0.8333 -> 1.0。
- RAG macro pollution@K：0.10 -> 0.05。
- Unsupported 语义通过率：1.0，unsupported path 不再标成 full success，也不会为缺失综合报告编造 latency/DSP 建议。
- 真实 Vivado metric runs：2 个，Demo0 和 Demo1 均解析到 latency/resource/timing。

说明：
- runtime 受外部 API 与 Vivado 进程波动影响，本轮仅作为 observed metric，不作为严格性能结论。
- 本轮 median runtime：232s，max runtime：310s。

### 4. 遇到的问题与根因
1) Demo1 MemorySpecialist 阶段曾被顶层 LLM 空转卡住
- 现象：上一轮 MatMul run 出现 `LLMGenerationError`，错误为 API 返回 `reasoning_content` 但没有最终 `message.content`。
- 根因：Planner 已经把 todo 分派给 `MemorySpecialist`，但 Main Agent 又额外询问一次 LLM“是否 delegate”，这是冗余决策点。
- 修复：对已显式 `assigned_specialist` 的 todo 增加 `LLMReActAutoDelegated` 路径；Main Agent 直接按协议委派，Specialist 内部仍保留 local ReAct 和 allowed_tools guard。

2) Demo6 boundary skill allowlist 与实际计划不一致
- 现象：真实 LLM 为 `unsupported_boundary_flow` 生成第一步 `task.validate_schema`，但 SkillPolicy 拒绝，导致 Demo6 failed。
- 根因：`unsupported_boundary_flow.yaml` 的 `allowed_tools` 缺少公共入口 `task.validate_schema`。
- 修复：将 `task.validate_schema` 加入 boundary skill 的 `recommended_todos` 与 `allowed_tools`，没有放宽 guard。

3) unsupported report 产物可观测性不足
- 现象：`unsupported_report.md` 已生成，但 artifact type 被注册为 `summary`，state 中没有 `unsupported_report` key。
- 根因：`report.write_unsupported` tool 写文件时使用了通用 artifact 类型。
- 修复：改为 `unsupported_report` artifact type，并在 runtime 中写入 `state.artifacts["unsupported_report"]`。

4) RAG 对结构化错误查询召回不足
- 现象：`VivadoNotFoundError recoverable skipped synthesis` 查询容易召回只有“skipped synthesis”的泛化结果。
- 根因：轻量 term 检索只要求任意 anchor overlap，错误名这种强锚点没有被特殊处理。
- 修复：RAG retriever 增加 strong anchor 规则，像 `VivadoNotFoundError` 这类长错误标识必须命中；同时加入 `docs/vivado_failure_playbook.md` 静态 playbook。

5) RAG pollution 评测口径误伤
- 现象：有效的 Vivado skill 由于 metadata/source_run_id 中出现 `resnet18` 被误判为污染。
- 根因：benchmark 用整个 result dict 判断污染，包含 source_id 与 metadata。
- 修复：pollution@K 只检查检索正文 `text`，source_id 仅用于 Recall/MRR/nDCG 可追踪性。

### 5. 已修复内容
- `src/dl_op_to_hls/main_agent/llm_runtime.py`：新增已分派 Specialist todo 的确定性 auto-delegate。
- `skills/unsupported_boundary_flow.yaml`：补齐 `task.validate_schema`。
- `src/dl_op_to_hls/main_agent/agent.py` 与 `runtime.py`：修复 unsupported report artifact 类型与 state 挂载。
- `src/dl_op_to_hls/rag/retriever.py`：加入 memory_facts / skills / 静态 docs 混合检索与 strong anchor 过滤。
- `src/dl_op_to_hls/rag/memory.py`：接入静态 playbook 检索路径。
- `docs/vivado_failure_playbook.md`：新增 VivadoNotFoundError playbook。
- `src/dl_op_to_hls/benchmarks/agent_quality_benchmark.py`：修正 RAG pollution 评测口径。
- 新增/更新测试覆盖 auto-delegate、静态 playbook 检索、strong anchor 过滤、unsupported artifact 注册、benchmark pollution 口径。

### 6. 当前测试结果
- 真实 Demo0-Demo6：全部命令 exit=0，最终 2 个 success + 5 个 partial_success。
- `python -m pytest -q -p no:cacheprovider`：206 个测试通过。
- focused tests：
  - `tests/test_rag.py`
  - `tests/test_agent_quality_benchmark.py`
  - `tests/test_llm_runtime_plan_validation.py`
  - `tests/test_skill_registry.py`
  - `tests/test_fallback_templates.py`
  - `tests/test_demo_boundary_reports.py`

### 7. 未修复完成的问题与原因
- Demo2/Demo3 仍是 hls4ml/ONNX 图支持边界；需要后续继续做 Gemm/Shape/Flatten 静态 rewrite 或换更适配 hls4ml 的模型导出方式。
- Demo4 仍是 H5/QKeras frontend 适配边界；需要新增 Keras/QKeras adapter 分支，不能用 ONNX parser 硬读 `.h5`。
- Dense 查询仍存在少量 qkeras 内容污染；当前 macro pollution 已降至 0.05，后续可通过 op_type/source_type filter 或 curated eval corpus 继续优化。
- runtime 仍受外部 API 和 Vivado 启动耗时影响；严格性能评测应增加 `--repeat`、median/p95 与分阶段耗时拆分。

---

## 2026-06-04 16:57:41 +08:00：新增 Agent 质量 Benchmark 与 RAG 评估指标
### 1. 本次测试做了什么
新增可复现的 benchmark 工具，用于量化 Agent 工程贡献，而不是只用“demo 能跑”描述效果。

新增命令：
- `dl-op-to-hls benchmark`
- 也可直接运行：`python -m dl_op_to_hls.benchmarks.agent_quality_benchmark`

新增默认 RAG 标签：
- `benchmarks/rag_eval_labels.json`

新增说明文档：
- `docs/benchmark_metrics.md`

实际执行：
```powershell
$env:PYTHONPATH='src'
python -m dl_op_to_hls.cli benchmark `
  --runs dense_16x32_af6abf3c_10 matmul_16x16_resource_9ac8e2e8_13 resnet18_boundary_demo_cd40d797_13 resnet18_boundary_demo_cd40d797_15 `
  --compare resnet18_boundary_demo_cd40d797_13 resnet18_boundary_demo_cd40d797_15 `
  --rag-eval-file benchmarks\rag_eval_labels.json `
  --rag-top-k 5 `
  --output runs\benchmarks\agent_quality_benchmark_demo.json
```

### 2. 新增量化指标
Agent / workflow 指标：
- `runtime_s`
- `llm_decision_count`
- `tool_call_count`
- `specialist_event_count`
- `artifact_completeness.rate`
- `rag_pollution_rate`
- `unsupported_semantics_pass_rate`
- `vivado_metric_runs`
- `latency / DSP / LUT / FF / timing_met`

RAG 指标：
- `Precision@K`
- `Recall@K`
- `Hit@K`
- `MRR`
- `nDCG@K`
- `relevant_term_coverage@K`
- `pollution@K`

说明：
- 当标签包含 `relevant_source_ids` 时，计算标准 IR 指标。
- 当只有 `relevant_terms / irrelevant_terms` 时，计算 term coverage 与污染率，用于历史 runs source_id 不稳定的轻量评估。

### 3. 当前 benchmark 观测结果
基于已有真实 runs：
- Demo0 Dense：真实 Vivado report 成功，latency 269 cycles，DSP 16，LUT 549，timing met。
- Demo1 MatMul：真实 Vivado report 成功，latency 2052 cycles，DSP 16，LUT 624。
- 对比 `resnet18_boundary_demo_cd40d797_13` -> `resnet18_boundary_demo_cd40d797_15`：
  - runtime：184s -> 74s，单次观测下降 59.78%。
  - RAG pollution：true -> false。
  - unsupported status：`success` -> `partial_success`。
  - unsupported metric suggestion error：true -> false。
- Aggregated benchmark：
  - analyzed runs：4
  - artifact completeness avg：1.0
  - Vivado metric runs：2
  - RAG pollution rate：0.25（包含修复前 run）
  - unsupported semantics pass rate：0.5（包含修复前 run）
- RAG eval：
  - macro Precision@K：0.55
  - macro Hit@K：0.75
  - macro MRR：0.625
  - macro relevant-term coverage@K：0.8333
  - macro pollution@K：0.1

### 4. 遇到的问题与根因
1) RAG Recall@K 需要 ground truth source ids
- 现象：默认轻量标签没有 `relevant_source_ids`，因此 `recall_at_k` 和 `ndcg_at_k` 为 `null`。
- 根因：历史 runs 的 source_id 多来自 artifact path 或 memory id，不适合直接写死为稳定标签。
- 处理：benchmark 同时支持 source-id 标注和 term 标注；当前默认标签先用 term coverage / pollution，后续可为固定文档或 curated memory 增加稳定 source-id ground truth。

2) RAG eval 暴露 Dense / VivadoNotFoundError 查询仍有噪声
- 现象：Dense 查询出现 qkeras 相关污染；VivadoNotFoundError 查询 relevant-term coverage 偏低。
- 根因：当前 RAG 是轻量 TF/term 检索，且历史 memory 中不同 demo summary 的通用词较多。
- 处理：本轮不把 benchmark 结果美化；保留为后续改进证据。后续可以加 op_type/source_type filter、failure memory boost、curated eval corpus。

3) runtime 不能直接当作严格性能结论
- 现象：Demo6 单次观测下降 59.78%。
- 根因：外部 LLM API 和 Vivado 工具链耗时存在波动。
- 处理：日志和文档中明确使用 observed improvement；严格结论需要 `--repeat` 多次运行并报告 median/p95。

### 5. 已修复内容
- 新增 `src/dl_op_to_hls/benchmarks/agent_quality_benchmark.py`。
- 新增 `dl-op-to-hls benchmark` CLI。
- 新增 `benchmarks/rag_eval_labels.json`。
- 新增 `docs/benchmark_metrics.md`。
- 新增 `tests/test_agent_quality_benchmark.py`，覆盖 RAG 标准指标、term coverage、pollution、unsupported 语义和 before/after comparison。

### 6. 当前测试结果
- `python -m pytest tests\test_agent_quality_benchmark.py -q -p no:cacheprovider`：通过。
- 由于 Windows 用户临时目录权限问题，测试时仍需设置 `TMP/TEMP/TMPDIR` 到工程内 `tmp_pytest`；这与之前日志中的环境问题一致。

### 7. 未修复完成的问题与原因
- 尚未建立 curated source-id RAG ground truth corpus；需要先固定一批稳定文档/source ids。
- 尚未把 benchmark 输出加入 CI；当前先作为本地可复现评测工具。
- 尚未做多轮真实 LLM/Vivado repeat benchmark；原因是运行成本较高，建议后续按候选简历指标做专项测试。

---

## 2026-06-04 10:28:05 +08:00：LLM 速度、RAG 相关性与 unsupported 状态语义优化
### 1. 本次测试做了什么
针对真实运行中暴露的四类问题做了小步优化：
- LLM 响应速度慢，尤其 suggestion / memory 阶段。
- RAG 检索相关性偏粗，ResNet boundary 场景会间接带出 MatMul 优化经验。
- unsupported path 的 `success` / `partial_success` 语义不够精确。
- Context token 预算、并行调度、skill 自动进化仍有提升空间，需要区分“本轮可安全落地”和“需要单独架构变更”的事项。

验证动作：
- 相关测试：`python -m pytest tests\test_memory.py tests\test_rag.py tests\test_llm_optimizer_fallback.py tests\test_runtime_hybrid.py -q -p no:cacheprovider`，通过。
- 全量测试：`python -m pytest -q -p no:cacheprovider`，通过。
- 真实复测：OpenAI-compatible `https://llmapi.paratera.com`，模型 `DeepSeek-V4-Pro`，真实 hls4ml / Vivado 配置下运行 `examples\resnet18_boundary.json`。
- 真实复测结果：`resnet18_boundary_demo_cd40d797_15`，`status=partial_success`，`selected_path=unsupported_path`，`llm_decisions=5`。

### 2. 遇到的问题与根因
1) suggestion / memory 阶段仍会消耗不必要的 LLM 调用
- 现象：某些路径已经是固定 playbook，例如 MemorySpecialist 的 compress / extract / promote，但仍会进入 local LLM decider。
- 根因：Specialist ReAct 被统一设计成可 LLM 决策，但部分 specialist 子步骤实际上没有分支选择价值。
- 修复：为 `BaseSpecialist._local_react_step` 增加 `force_deterministic` 参数；MemorySpecialist 和 OptimizationSpecialist 的固定工具序列使用确定性 local ReAct 记录，不再请求外部 LLM，但仍保留 ReAct observation 和 allowed_tools 校验。

2) unsupported path 没有 synthesis report 时不应该生成“优化建议”
- 现象：ResNet boundary 这类 demo 没有可综合 HLS/report，优化建议阶段容易产生无意义建议或消耗 LLM。
- 根因：`suggestion.suggest_optimization` 没有区分“没有实现/report，所以优化不适用”和“有 report，需要优化”的状态。
- 修复：当 `selected_path=unsupported_path` 且 report 为 `missing/skipped/report_missing` 时，直接写入 `suggestions.md` 并返回 `status=skipped`、`llm_skipped=True`，提示下一步应处理 unsupported report，而不是做 latency/resource 优化。

3) RAG/Memory 出现二手经验递归污染
- 现象：真实 Demo6 中不再直接召回 MatMul 源，但旧的 ResNet memory 文本里嵌套了 `Prior experience hint: optimization.matmul...`。
- 根因：历史优化建议把“当时检索到的经验”作为 suggestions 内容保存进长期 memory，后续再检索 ResNet memory 时会间接带出 MatMul。
- 修复：新增 memory hygiene 清洗层，保存长期 memory 前删除 `retrieved_memories/rag_context/memory_used` 等上下文字段，并移除 `Prior experience hint` 二手提示；RAG index/retrieve 和 suggestion 渲染也接入清洗，阻断旧污染继续扩散。

4) unsupported boundary 流程状态语义需要更精确
- 现象：边界 demo 的工程流程可以完成，但这不代表模型已成功转换/综合。
- 根因：只看 Todo 是否完成会把 unsupported report 流程归为 `success`。
- 修复：`selected_path=unsupported_path` 的完整流程最终保持 `partial_success`，表示“Agent 安全完成边界处理和报告生成，但未得到可综合 HLS 实现”。

### 3. 本次代码修复
- `src/dl_op_to_hls/core/memory_hygiene.py`
  - 新增长期记忆/RAG 清洗工具，去除二手 retrieved context 和 `Prior experience hint`。
- `src/dl_op_to_hls/memory/memory_manager.py`
  - memory promotion 前清洗 candidate。
  - retrieval 返回前清洗旧 memory 文本。
  - 增强 anchor token 过滤，降低泛化词如 DSP/resource/reuse 导致的误召回。
- `src/dl_op_to_hls/rag/indexer.py`
  - RAG 建索引前清洗文本，避免 summary/suggestions 中的二手经验被索引。
- `src/dl_op_to_hls/rag/retriever.py`
  - RAG 检索时清洗旧 chunk，并使用 task anchor 过滤泛化词匹配。
- `src/dl_op_to_hls/tools/suggest_optimization.py`
  - unsupported + missing report 时跳过 LLM 优化，生成“优化不适用”的建议文件。
  - 渲染历史经验提示时清洗旧 prior hint。
- `src/dl_op_to_hls/specialists/base.py`
  - 支持 deterministic local ReAct step。
- `src/dl_op_to_hls/specialists/memory_specialist.py`
  - 固定 memory playbook 改为 deterministic local ReAct，减少外部 LLM 调用。
- `src/dl_op_to_hls/specialists/optimization_specialist.py`
  - 固定 optimization playbook 改为 deterministic local ReAct。
  - tool 返回 `skipped` 时 SpecialistResult 也返回 `skipped`。
- `src/dl_op_to_hls/main_agent/runtime.py`
  - direct optimization todo 遇到 skipped 结果时标记 TodoSkipped。
- `src/dl_op_to_hls/main_agent/reflector.py`
  - unsupported path 完成后保持 `partial_success`。
- `tests/test_memory.py`、`tests/test_rag.py`、`tests/test_llm_optimizer_fallback.py`、`tests/test_runtime_hybrid.py`
  - 增加 anchor 过滤、二手 memory 清洗、unsupported optimization skipped、unsupported partial_success 等回归测试。

### 4. 当前测试结果
- 相关测试通过。
- 全量 pytest 通过。
- 真实 Demo6 复测通过：`resnet18_boundary_demo_cd40d797_15`。
- 真实复测关键检查：
  - `status=partial_success`
  - `selected_path=unsupported_path`
  - suggestions 为“没有可综合实现/report，优化不适用”
  - retrieved memory 中不再包含 `matmul`
  - retrieved memory 中不再包含 `Prior experience hint`

### 5. 未修复完成的问题与原因
- 并行调度暂未实现：它会改变 Todo 执行顺序、trace 顺序、ArtifactManager 并发写入和 DB 写入一致性，需要单独引入 coordinator、锁或事务边界；本轮先不做高风险架构改动。
- skill 自动进化暂未实现：当前已有 skill candidate / procedural memory 存储，但自动写 YAML 会影响长期行为策略，需要增加审核/approval 或至少 candidate/approved 两阶段，不适合在这次小修中直接启用。
- Context token 预算仍可继续精细化：项目已有 `TokenBudgetManager` 和 specialist `context_usage` 的 token 估算，本轮重点修 RAG/memory hygiene；后续可以进一步把 token budget 做成按 specialist 类型的硬预算和截断报告。
- Demo2/Demo3/Demo4 的真实 hls4ml/H5 链路仍需要后续专项修复，本轮没有改变真实模型转换能力。

---

## 2026-06-04 09:39:33 +08:00：真实 DeepSeek-V4-Pro + hls4ml + Vivado Demo0-Demo6 复测与框架修复
### 1. 本次测试做了什么
执行环境：
- 工作目录：`D:\hls_agent\standalone_work\dl-op-to-hls-agent`。
- LLM：OpenAI-compatible，Base URL `https://llmapi.paratera.com`，模型 `DeepSeek-V4-Pro`，API key 仅通过环境变量注入，未写入仓库。
- 真实工具：`DL_OP_TO_HLS_MOCK_HLS4ML=0`，`DL_OP_TO_HLS_MOCK_VIVADO=0`，Vivado HLS 路径 `D:\Xilinx\Vivado\2018.3\bin\vivado_hls.bat`。
- 运行模式：`strict`，未在真实测试中用 mock 或确定性流程冒充 LLM-first。

执行结果：
- Demo0 `dense_operator.json`：`dense_16x32_af6abf3c_10`，`success`，`fallback_template_path`，真实 Vivado csynth/report 成功。
- Demo1 `matmul_resource.json`：`matmul_16x16_resource_9ac8e2e8_13`，`success`，`fallback_template_path`，真实 Vivado csynth/report 成功。
- Demo2 `mnist_mlp_hls4ml.json`：`mnist_mlp_demo_4ff92a59_12`，`partial_success`，`unsupported_path`；真实 hls4ml 对原始 Gemm 不支持，graph rewrite 后仍因 shape 信息问题不能安全进入 hls4ml。
- Demo3 `mnist_tiny_cnn.json`：`mnist_tiny_cnn_188af60c_11`，`partial_success`，`unsupported_path`；真实 hls4ml 报 `Shape` 不支持，Agent 生成 unsupported report。
- Demo4 `mnist_qkeras_cnn.json`：`mnist_qkeras_cnn_a7e2cdc5_09`，`partial_success`，`unsupported_path`；H5/QKeras frontend 已被识别，但真实 H5 conversion branch 仍未启用。
- Demo5 `tiny_residual_block.json`：`tiny_residual_block_ad48a995_09`，`partial_success`，`unsupported_path`；符合 residual boundary demo 预期。
- Demo6 `resnet18_boundary.json`：首轮 `resnet18_boundary_demo_cd40d797_11` 暴露 graph rewrite 未执行问题；修复后 `resnet18_boundary_demo_cd40d797_13` 为 `success`，按 boundary playbook 执行 graph rewrite、unsupported report、summary、MemorySpecialist。

验证命令：
- `python -m pytest tests\test_runtime_hybrid.py -q -p no:cacheprovider`
- `python -m pytest -q -p no:cacheprovider`

### 2. 遇到的问题与根因
1) LLM 计划标题变体导致 graph rewrite 没执行
- 现象：Demo6 首轮 trace 中 LLM 选择 `unsupported_boundary_flow`，todo 的 `assigned_tool` 是 `graph_rewrite.rewrite`，但执行层标记 `No action mapped for this todo`。
- 根因：`runtime._execute_todo_actions` 对 graph rewrite 只匹配标题 `Try graph rewrite`，没有以 `assigned_tool` 作为稳定 contract。
- 修复：执行层改为优先/同时按 `assigned_tool == "graph_rewrite.rewrite"` 映射工具。

2) graph rewrite 后重复生成 unsupported report todo
- 现象：Demo6 修复 graph rewrite 后，又追加了新的 `Generate unsupported report`，而 LLM 原计划已经有 `report.write_unsupported` todo。
- 根因：Reflector 在 graph rewrite 未修复模型时直接 append 新 todo，没有复用现有 active `report.write_unsupported` todo。
- 修复：改用 `_ensure_active_todo(..., tool_names={"report.write_unsupported"})` 复用已有 pending/blocked report todo，并只在缺失时新增。

3) LLM plan 的 `inputs` 可能不是 dict
- 现象：真实 LLM 有时会把 inputs 写成字符串说明，如 `graph_rewrite output`。
- 根因：`_create_todos_from_llm_plan` 直接赋值，执行层默认 `todo.inputs` 是 dict。
- 修复：LLM plan 入库时做类型归一化，非 dict inputs 置为空 dict，避免把自然语言说明误当工具参数。

4) 本地 pytest 临时目录权限问题
- 现象：`C:\Users\IC\AppData\Local\Temp\pytest-of-IC` 和 `.pytest_cache` 出现 WinError 5。
- 根因：当前 Windows 用户与部分目录权限/所有权不一致。
- 处理：测试时设置 `TMP/TEMP/TMPDIR` 到工程内 `tmp_pytest`，并使用 `-p no:cacheprovider`。这是测试环境问题，不是项目代码问题。

5) API 配置差异
- 本次 Paratera endpoint 可以访问，模型名 `DeepSeek-V4-Pro` 可用，未再出现外部 API 审批拦截。
- 未遇到新的 base URL 拼接问题；之前的 root base URL 自动补 `/v1` 修复有效。
- `run-llm` 命令没有 `--json` 参数，但命令本身默认输出 state JSON；这是 CLI 使用差异，不影响真实测试。

### 3. 本次代码修复
- `src/dl_op_to_hls/main_agent/runtime.py`
  - graph rewrite 执行映射按 `assigned_tool` 生效。
  - graph rewrite 失败后复用现有 `report.write_unsupported` todo，避免重复 todo。
- `src/dl_op_to_hls/main_agent/llm_runtime.py`
  - LLM plan inputs 做 dict 类型归一化。
- `tests/test_runtime_hybrid.py`
  - 新增 `test_runtime_executes_graph_rewrite_by_assigned_tool_not_title`。
  - 新增 `test_runtime_reuses_existing_unsupported_report_todo_after_graph_rewrite`。

### 4. 当前测试结果
- `tests/test_runtime_hybrid.py`：9 个用例通过。
- 全量 pytest：通过。
- 真实 Demo6 修复后复跑：`resnet18_boundary_demo_cd40d797_13`，graph rewrite 已真实执行，unsupported report 未重复生成，MemorySpecialist 成功执行。

### 5. 未修复完成的问题与原因
- Demo2/Demo3 仍不能完整走 hls4ml 主路径：真实 hls4ml 对当前 ONNX 图的 Gemm/Shape 静态形状链路仍不兼容。已能生成 rewritten ONNX 和 unsupported report，但要完全通过需要更强的 ONNX shape/static rewrite 或重新导出更适合 hls4ml 的模型。
- Demo4 仍不能完整走 QKeras/H5 主路径：adapter 已识别 H5/QKeras frontend，但真实 H5 conversion branch 尚未接入。需要后续补 Keras/QKeras loader、依赖检查和 hls4ml Keras convert 分支。
- unsupported boundary demo 的状态语义需要继续打磨：Demo6 修复后为 `success`，表示“边界处理流程成功完成”，不是表示 ResNet18 被综合成功。summary/unsupported report 中已说明未做综合。

---

## 2026-06-04 08:42:45 +08:00：补充记录 Paratera DeepSeek API 配置差异
### 1. 本次补充记录的原因
上一次真实 LLM 验证耗时较长，中间经历了多次 API endpoint / model 配置切换。为了后续复现不再浪费 Codex 额度和 API token，本条专门补充 API 配置差异、遇到的问题和当前推荐配置。

### 2. API 配置差异与已遇到的问题
1) Base URL 形式不同
- 现象：用户提供的 Paratera Base URL 是根地址形式，而不是标准 OpenAI SDK 常见的 `/v1` 完整地址。
- 根因：项目 LLMClient 最初直接拼接 `base_url + /chat/completions`，根地址会导致请求路径不兼容。
- 修复：已在 LLMClient 中兼容 root base URL，若路径为空或 `/`，自动补 `/v1/chat/completions`。

2) 模型名必须严格匹配
- 现象：`DeepSeekv4pro` 与 `DeepSeek-V4-Pro` 表现不同。
- 根因：Paratera endpoint 对模型名大小写和连接符敏感。
- 当前策略：严格使用用户指定的 `DeepSeek-V4-Pro`，不降级、不替换模型。

3) DeepSeek-V4-Pro 可能返回 reasoning_content 但没有最终 content
- 现象：长输出场景中模型可能把 token 用在 reasoning 阶段，最终 `message.content` 为空。
- 根因：OpenAI-compatible 返回结构中存在 reasoning_content，但主流程需要最终 JSON/content。
- 修复：LLMClient 已识别该情况并返回结构化 `LLMGenerationError`，提示提高 `DL_OP_TO_HLS_LLM_MAX_TOKENS` 或缩短 prompt；strict 模式不启用规则兜底冒充成功。

4) 旧 API 曾有字节级限流
- 现象：之前的 endpoint 疑似存在每分钟约一万字节限制，导致 demo 执行极慢。
- 当前策略：Paratera endpoint 不再沿用该低速率限制，真实复测中设置 `DL_OP_TO_HLS_LLM_RATE_BYTES_PER_MIN=0` 和 `DL_OP_TO_HLS_LLM_MIN_REQUEST_INTERVAL_SEC=0`。

### 3. 当前真实测试推荐环境变量
- `DL_OP_TO_HLS_LLM_ENABLED=1`
- `DL_OP_TO_HLS_LLM_PROVIDER=openai-compatible`
- `DL_OP_TO_HLS_LLM_BASE_URL=https://llmapi.paratera.com`
- `DL_OP_TO_HLS_LLM_MODEL=DeepSeek-V4-Pro`
- `DL_OP_TO_HLS_LLM_MAX_TOKENS=4096`
- `DL_OP_TO_HLS_LLM_RATE_BYTES_PER_MIN=0`
- `DL_OP_TO_HLS_LLM_MIN_REQUEST_INTERVAL_SEC=0`
- `DL_OP_TO_HLS_MOCK_HLS4ML=0`
- `DL_OP_TO_HLS_MOCK_VIVADO=0`
- `DL_OP_TO_HLS_VIVADO_HLS_PATH=D:\Xilinx\Vivado\2018.3\bin\vivado_hls.bat`
- `DL_OP_TO_HLS_RUNTIME_MODE=strict`
- `DL_OP_TO_HLS_OPTIMIZATION_FALLBACK_MODE=strict`
- `DL_OP_TO_HLS_SPECIALIST_LLM_DECIDER_ENABLED=1`

### 4. 未完成 / 下一步
- 继续执行修复后的真实 DeepSeek-V4-Pro + hls4ml + Vivado Demo0-Demo6。
- 后续外部 API 测试默认直接运行，不再额外请求人工确认；如底层平台强制拦截，则只记录平台限制，不进行 mock 替代。

---

## 2026-06-04 08:20:40 +08:00：DeepSeek-V4-Pro 真实批跑暴露 DAG 依赖问题后的框架修复
### 1. 本次测试做了什么
执行与验证：
- 在独立目录 `D:\hls_agent\standalone_work\dl-op-to-hls-agent` 继续开发，未引用或修改旧 `D:\hls_agent` 脚本。
- 使用用户指定的 OpenAI-compatible endpoint、模型名 `DeepSeek-V4-Pro`、真实 hls4ml、真实 Vivado HLS 2018.3 启动 Demo0-Demo6 分层真实验证。
- 已完成的真实 LLM + Vivado 旧批跑结果：
  - Demo0：单独运行成功，`dense_16x32_af6abf3c_09`，`success`，`fallback_template_path`，真实 Vivado csynth 成功，latency 269 cycles，DSP 16，LUT 549，timing met。
  - Demo1：`matmul_16x16_resource_9ac8e2e8_12`，`success`，`fallback_template_path`，真实 Vivado csynth 成功。
  - Demo2：`mnist_mlp_demo_4ff92a59_11`，`partial_success`，`unsupported_path`，暴露 graph rewrite 后 Todo 分支调度问题。
  - Demo3：`mnist_tiny_cnn_188af60c_10`，`failed`，暴露 hls4ml unsupported 后旧下游 Todo 抢跑，以及 DeepSeek-V4-Pro 长优化调用返回 reasoning_content 但无最终 content 的问题。
  - Demo4：`mnist_qkeras_cnn_a7e2cdc5_08`，`partial_success`，`unsupported_path`。
  - Demo5：`tiny_residual_block_ad48a995_07`，`partial_success`，`unsupported_path`。
  - Demo6：`resnet18_boundary_demo_cd40d797_09`，`partial_success`，`unsupported_path`。
- 修复后执行：
  - `python -m pytest tests\test_todo.py tests\test_llm_runtime_plan_validation.py tests\test_runtime_hybrid.py -q`
  - `python -m pytest tests\test_fallback_templates.py::test_unsupported_report_generated tests\test_runtime_hybrid.py tests\test_todo.py -q`
  - `python -m pytest -q`

### 2. 当前测试结果
已通过：
- 相关回归测试通过。
- 全量 pytest 通过。

未完成：
- 修复后的真实 DeepSeek-V4-Pro + Vivado Demo0-Demo6 复测尚未完成。
- 原因不是 DeepSeek-V4-Pro 模型名不可用，而是本次新外网命令被 Codex 外部执行审批器以使用额度限制拦截，无法重新向 Paratera endpoint 发起 API 请求。
- 处理：没有降级模型，没有切换到 mock，也没有用确定性流程冒充 LLM-first 真实复测。

### 3. 发现的问题与根因
1) Todo DAG 把 `completed_with_warning` 当作普通成功依赖
- 现象：Demo2 中 hls4ml support 返回 unsupported 后，Agent 添加了 `Try graph rewrite`，但旧的 `Parse synthesis report`、`Generate optimization suggestions`、`Promote memories` 等下游 Todo 仍提前执行。
- 根因：Todo 依赖判断把 `completed_with_warning` / `skipped` 统一视为 DONE，导致核心 HLS/Vivado 节点错误消费了 unsupported warning。

2) LLM 计划依赖缺失没有被框架归一化
- 现象：LLM 计划中部分 Todo dependencies 为空，runtime 按 priority 执行时允许后续 Todo 抢跑。
- 根因：Main Agent guard 只校验工具/专家 allowlist，没有把 hls4ml model flow 的结构性边补齐为强 DAG。

3) graph rewrite recovery 分支只追加依赖，没有替换旧依赖
- 现象：rewrite 后新增了 retry support，但旧 config/convert/Vivado Todo 仍保留原始 unsupported support 依赖，可能永久 blocked 或走错路径。
- 根因：动态分支切换没有“替换依赖链”的操作，只做 append dependency。

4) fallback template 不支持时没有显式进入 candidate/unsupported 分支
- 现象：`CustomUnsupported` 测试中 fallback template 返回 recoverable error 后，Vivado synthesis 等待失败的 fallback 节点，`unsupported_report.md` 未生成。
- 根因：fallback warning 没有触发 LLM candidate / verification / unsupported report 的后续恢复链。

5) DeepSeek-V4-Pro 长输出可能只有 reasoning_content
- 现象：Demo3 的 OptimizationSpecialist 调用返回 reasoning_content 但没有最终 message.content，被客户端记录为真实 LLM 输出失败。
- 根因：该模型在长推理/长建议场景可能把 token 用在 reasoning 阶段，没有产生最终 content；当前 strict 模式正确失败而不是规则兜底。

### 4. 已修复内容（含修复方式）
- 在 `TodoManager` 中引入依赖状态契约：
  - 核心 HLS/Vivado 节点只接受 `completed` 依赖。
  - `graph_rewrite.rewrite`、`fallback.generate_operator_hls`、`llm.generate_candidate`、`report.write_unsupported`、`summary/suggestion/memory` 等恢复/收尾节点可消费 warning。
  - parse/summary/suggestion/memory 可消费 synthesis skipped，用于 Vivado 缺失时的 partial-success 收尾。
- 在 `LLMFirstRuntime` 中增加 LLM plan dependency normalization：
  - 自动补齐 `validate -> inspect -> support -> config -> convert -> Vivado -> parse -> suggest -> summary -> memory`。
  - 即使 LLM 输出 dependencies 为空，也不会让下游 Todo 抢跑。
- 在 runtime dynamic recovery 中增加依赖替换与终端分支切换：
  - graph rewrite 成功后重写为 `retry support -> config -> convert -> Vivado -> parse -> finalization`。
  - graph rewrite 后仍 unsupported 时取消旧 hls4ml/Vivado 分支，切到 `unsupported report -> suggestion -> summary -> memory`。
  - fallback template 失败后显式进入 `Generate LLM candidate -> Verify LLM candidate`，并且 Vivado synthesis 必须等待 verification。
- 新增回归测试：
  - warning dependency 不会解锁 hls4ml config。
  - warning dependency 会解锁 graph rewrite recovery。
  - LLM plan 缺失 dependencies 时会被归一化为 hls4ml flow DAG。
  - unsupported operator 能生成 `unsupported_report.md`。

### 5. 未修复 / 待继续验证
- 修复后的真实 DeepSeek-V4-Pro + Vivado Demo0-Demo6 需要在 Codex 外部执行额度恢复后重跑。
- Demo2/Demo3 真实 hls4ml 支持边界仍然存在：
  - Demo2：Gemm rewrite 后 hls4ml 仍可能因权重 shape 推断失败，需要继续增强 ONNX graph rewrite / initializer shape handling。
  - Demo3：Shape/Concat/Reshape/Flatten 静态消除仍需增强。
- DeepSeek-V4-Pro 的 reasoning-only 长输出需要继续验证：
  - 可尝试提高 `DL_OP_TO_HLS_LLM_MAX_TOKENS`。
  - 或对 OptimizationSpecialist prompt 进一步压缩，要求短 JSON suggestions。
  - strict 模式下仍应保持“LLM 无最终 content 即失败”，不启用规则兜底冒充成功。

---

## 2026-06-04 06:33:44 +08:00：更换 Paratera DeepSeek 配置后的真实链路复核
### 1. 本次测试做了什么
执行与验证：
- 继续在独立目录 `D:\hls_agent\standalone_work\dl-op-to-hls-agent` 开发，未修改旧 `D:\hls_agent` 脚本。
- 先运行全量单元测试：
  - `python -m pytest -q`
- 尝试使用新的 OpenAI-compatible LLM 配置运行真实 LLM + hls4ml + Vivado Demo0-Demo6：
  - Base URL：Paratera LLM endpoint。
  - Model：`DeepSeekv4pro`。
  - 真实 hls4ml：`DL_OP_TO_HLS_MOCK_HLS4ML=0`。
  - 真实 Vivado HLS：`DL_OP_TO_HLS_MOCK_VIVADO=0`。
  - Vivado HLS 路径：`D:\Xilinx\Vivado\2018.3\bin\vivado_hls.bat`。
  - strict runtime。
  - specialist LLM decider enabled。
- 因真实 LLM 调用被安全审批器阻止，转而运行不出网的真实 hls4ml + Vivado Demo0-Demo6：
  - `DL_OP_TO_HLS_RUNTIME_MODE=strict`
  - `DL_OP_TO_HLS_OPTIMIZATION_FALLBACK_MODE=demo`

### 2. 当前测试结果
已通过：
- 全量测试通过：
  - `python -m pytest -q`
- 非 LLM 的真实 hls4ml + Vivado Demo0-Demo6 跑完：
  - Demo0：`dense_16x32_af6abf3c_05`，`success`，`fallback_template_path`，`report.status=success`。
  - Demo1：`matmul_16x16_resource_9ac8e2e8_08`，`success`，`fallback_template_path`，`report.status=success`。
  - Demo2：`mnist_mlp_demo_4ff92a59_07`，`partial_success`，`unsupported_path`，`report.status=missing`，`HLS4MLConversionError`。
  - Demo3：`mnist_tiny_cnn_188af60c_06`，`partial_success`，`unsupported_path`，`report.status=missing`，`HLS4MLConversionError`。
  - Demo4：`mnist_qkeras_cnn_a7e2cdc5_04`，`partial_success`，`unsupported_path`，`report.status=missing`。
  - Demo5：`tiny_residual_block_ad48a995_04`，`partial_success`，`unsupported_path`，`report.status=missing`。
  - Demo6：`resnet18_boundary_demo_cd40d797_06`，`partial_success`，`unsupported_path`，`report.status=missing`。

真实 LLM + Vivado Demo0-Demo6：
- 本轮未运行成功。
- 原因：Codex 外部执行审批器拒绝向新的外部 LLM endpoint 发送本地 demo / 工程上下文。
- 处理：没有绕过审批器，也没有用 mock 冒充真实 LLM 结果。
- 后续：需要用户在了解“会向外部 LLM endpoint 发送本地任务与工程上下文”的风险后，明确批准继续执行。

### 3. 发现的问题与根因
1) 真实外部 LLM 调用涉及工作区上下文外发
- 现象：真实 LLM Demo0-Demo6 命令被审批器拒绝。
- 根因：`run-llm` 会把任务摘要、specialist context、RAG/memory 摘要等发送到 OpenAI-compatible endpoint；这属于本地项目上下文外发。
- 风险：即使用户提供了 API key，仍需要明确确认对外发送上下文的安全边界。

2) 本地真实 Vivado 路径稳定
- 现象：Demo0/Demo1 均完成真实 Vivado csynth 和 report parse。
- 根因：fallback template 生成的 HLS C++/TCL 能被 Vivado HLS 2018.3 执行。
- 结论：本地 EDA toolchain 不再是当前阻塞点。

3) 模型类 Demo 仍处于明确边界处理
- 现象：Demo2/Demo3 真实 hls4ml 仍进入 unsupported path，并记录 `HLS4MLConversionError`。
- 根因：当前 hls4ml 真实转换链路仍不能完整覆盖这些 ONNX 图中的边界算子。
- 结论：这是当前模型支持范围问题，不应通过 mock 或静默 fallback 伪装成 hls4ml 主路径成功。

### 4. 已修复内容（含修复方式）
- 本轮没有修改代码。
- 本轮确认了上一轮状态语义修复仍然有效：
  - Demo0/Demo1 真实 Vivado 成功后最终状态为 `success`。
  - hls4ml support warning 不再错误污染 fallback_template 路径最终状态。
- 本轮新增开发日志记录，明确区分：
  - 已完成的本地真实 hls4ml + Vivado 验证。
  - 未完成的外部 LLM 真实验证。

### 5. 未修复 / 待继续验证
- 真实 LLM + Vivado Demo0-Demo6 尚未完成。
  - 需要用户明确批准向 Paratera LLM endpoint 发送本地任务/工程上下文后继续执行。
- Demo2/Demo3 的模型图 rewrite / 静态消除能力仍需继续增强：
  - Demo2：继续验证 `Gemm -> MatMul + Add` 后是否能进入 hls4ml convert。
  - Demo3：继续实现或强化 `Shape` / flatten / reshape 静态消除。

---

## 2026-06-03 10:32:37 +08:00：Specialist 本地 ReAct 工具契约修复、真实 Vivado 状态语义修复
### 1. 本次测试做了什么
执行与验证：
- 继续在独立目录 `D:\hls_agent\standalone_work\dl-op-to-hls-agent` 开发，未修改旧 `D:\hls_agent` 脚本。
- 针对上一轮真实 DeepSeek + Vivado 暴露的 Demo2 / Demo3 失败继续排查：
  - Demo2 rewritten model 重试时，`HLS4MLSpecialist` 的 local ReAct 输出空/坏 arguments，覆盖了 ContextEnvelope 生成的 canonical `task` 参数，触发 `KeyError: 'task'`。
  - Demo3 inspect todo 中，local ReAct 选择了不匹配当前 todo 的动作，触发 `Specialist ReAct decision violated the local action/tool schema`。
- 运行聚焦测试：
  - `python -m pytest tests/test_specialist_react.py tests/test_specialists.py -q`
  - `python -m pytest tests/test_runtime_hybrid.py tests/test_specialist_react.py tests/test_specialists.py -q`
- 运行全量测试：
  - `python -m pytest -q`
- 运行非 LLM 的真实 hls4ml + Vivado Demo0-Demo6：
  - `DL_OP_TO_HLS_MOCK_HLS4ML=0`
  - `DL_OP_TO_HLS_MOCK_VIVADO=0`
  - `DL_OP_TO_HLS_VIVADO_HLS_PATH=D:\Xilinx\Vivado\2018.3\bin\vivado_hls.bat`
  - `DL_OP_TO_HLS_RUNTIME_MODE=strict`
  - `DL_OP_TO_HLS_OPTIMIZATION_FALLBACK_MODE=demo`
- 尝试运行真实 DeepSeek + Vivado Demo0-Demo6：
  - DeepSeek OpenAI-compatible。
  - strict runtime。
  - specialist LLM decider enabled。

### 2. 当前测试结果
已通过：
- 聚焦测试通过：
  - `tests/test_specialist_react.py`
  - `tests/test_specialists.py`
  - `tests/test_runtime_hybrid.py`
- 全量测试通过：
  - `python -m pytest -q`
- 非 LLM 真实 hls4ml + Vivado Demo0-Demo6 跑完：
  - Demo0：`dense_16x32_af6abf3c_03`，真实 Vivado csynth/report 成功，但修复前状态为 `partial_success`。
  - Demo1：`matmul_16x16_resource_9ac8e2e8_06`，真实 Vivado csynth/report 成功，但修复前状态为 `partial_success`。
  - Demo2：`mnist_mlp_demo_4ff92a59_06`，`partial_success`，`unsupported_path`，真实 hls4ml 仍报告 `HLS4MLConversionError`。
  - Demo3：`mnist_tiny_cnn_188af60c_05`，`partial_success`，`unsupported_path`，真实 hls4ml 仍报告 `HLS4MLConversionError`。
  - Demo4：`mnist_qkeras_cnn_a7e2cdc5_03`，`partial_success`，`unsupported_path`。
  - Demo5：`tiny_residual_block_ad48a995_03`，`partial_success`，`unsupported_path`。
  - Demo6：`resnet18_boundary_demo_cd40d797_05`，`partial_success`，`unsupported_path`。
- 状态语义修复后，重新运行真实 Vivado Demo0/Demo1：
  - Demo0：`dense_16x32_af6abf3c_04`，`success`，`fallback_template_path`，`report.status=success`。
  - Demo1：`matmul_16x16_resource_9ac8e2e8_07`，`success`，`fallback_template_path`，`report.status=success`。

真实 DeepSeek + Vivado Demo0-Demo6：
- 本轮未能启动。
- 原因：Codex 当前会话的外部执行审批器因 usage limit 拒绝联网/API执行请求：
  - `You've hit your usage limit...`
- 处理：没有绕过审批器，也没有用 mock 冒充真实 DeepSeek 结果。
- 后续：额度恢复后，需要用相同 strict 配置重新运行 Demo0-Demo6，重点观察 Demo2/Demo3 是否从 `InvalidTaskError` 转为正常 graph rewrite / unsupported 边界处理。

### 3. 发现的问题与根因
1) Specialist local ReAct 仍能破坏工具输入契约
- 现象：Demo2 rewritten model 重试时，`hls4ml.check_support` 被调用时缺少 `task`，报 `KeyError: 'task'`。
- 根因：`HLS4MLSpecialist.handle()` 先从 ContextEnvelope 构造了 canonical args，但随后允许 LLM action 的 `arguments` 整体覆盖 canonical args。
- 风险：即使 Main Agent 正确隔离了 ContextEnvelope，sub-agent 内部仍可能把结构化 tool input 退化成自由拼参。

2) Specialist local ReAct 仍能偏离当前 Todo 的 assigned_tool
- 现象：Demo3 的 inspect todo 被 local ReAct 判为 schema violation。
- 根因：guard 只检查工具是否在 specialist allowed_tools 内，没有强制“当前 todo 的 preferred_tool 必须被执行”。
- 风险：HLS4MLSpecialist 可见多个 hls4ml tool，LLM 可能在 inspect/config/check/convert 间跳转，导致 TodoList 的依赖语义被破坏。

3) 成功的 fallback 路径被早期 hls4ml warning 错误降级为 partial_success
- 现象：Demo0/Demo1 真实 Vivado csynth 和 report parse 都成功，但最终状态仍是 `partial_success`。
- 根因：`update_status_from_todos()` 看到任意 `completed_with_warning` 就把 run 置为 partial，没有区分“主路径不适合但替代路径成功”和“最终目标未完成”。
- 风险：演示和评估中会低估 fallback_template 路径的真实完成度。

### 4. 已修复内容（含修复方式）
- 收紧 Specialist local ReAct 契约：
  - 如果 Todo 有 `assigned_tool` / preferred tool，local ReAct 可以决定 `call_tool`、`mark_blocked`、`mark_failed`。
  - 但不允许改选其它 tool。
  - 不允许用 LLM action arguments 覆盖 ContextEnvelope 生成的 canonical arguments。
  - 如果 LLM 返回 `finish_with_result`，guard 会修复为调用 required tool。
  - 如果 LLM 返回 wrong tool，guard 会修复为 preferred tool。
  - 如果 canonical args 缺失，则标记 `mark_blocked`，不强行调用工具。
- 增加回归测试：
  - local ReAct 返回 wrong tool 时自动修复到 preferred tool。
  - local ReAct 返回 bad args 时保留 canonical arguments。
  - HLS4MLSpecialist 在 LLM 返回空 arguments 时仍使用 ContextEnvelope 中的 canonical `task`。
- 修复 fallback 路径状态聚合：
  - 当 `state.report.status == success` 且 selected path 为 `fallback_template_path` / `hls4ml_path` / `existing_hls_project_path` / `llm_candidate_path`，并且没有真实 error / blocked / meaningful skipped 时，最终 run 状态为 `success`。
  - 早期 hls4ml support warning 仍保留在 Todo Execution Summary 中，但不再污染最终 run status。
- 增加回归测试：
  - `test_runtime_fallback_success_not_downgraded_by_hls4ml_warning`。

### 5. 未修复 / 待继续验证
- 真实 DeepSeek + Vivado Demo0-Demo6 尚未完成本轮复测。
  - 原因不是项目代码，而是当前 Codex 会话 usage limit 阻止联网/API执行。
  - 需要额度恢复后继续跑。
- Demo2/Demo3 的真实 hls4ml 模型支持边界仍存在：
  - Demo2 的 ONNX `Gemm` rewrite 已有实现，但仍需真实 DeepSeek strict loop 复测确认完整链路。
  - Demo3 的 `Shape` / reshape / flatten 静态消除仍是后续重点。
- MatMul Demo1 真实 Vivado report 显示 timing 未满足：
  - `target_ns=8.0`
  - `estimated_ns=9.634`
  - synthesis 本身成功，因此 run status 为 success；优化建议应继续提示 timing/resource trade-off。

---

## 2026-06-02 15:32:42 +08:00：Agent 框架契约收紧、真实 Graph Rewrite、上下文预算与沙箱补强
### 1. 本次测试做了什么
执行与验证：
- 继续在独立目录 `D:\hls_agent\standalone_work\dl-op-to-hls-agent` 开发，未修改旧 `D:\hls_agent` 脚本。
- 复查外部评审提出的 5 类架构问题：
  - ContextEnvelope token budget 只有声明、没有真实预算控制。
  - Specialist Sub-agent 串行执行，是否需要 Multi-Agent Coordinator。
  - Skill YAML 仍主要手工维护，是否需要自动提炼。
  - LLM candidate 只有目录权限约束，缺少 HLS C++ 静态安全扫描。
  - strict/demo/production 模式和 fallback 策略主要靠环境变量，契约不够显式。
- 针对 Demo2 既往失败继续排查：
  - 真实 hls4ml 遇到 ONNX `Gemm` 报 `Unsupported operation type: Gemm`。
  - LLM reflection 曾提出未注册工具/专家，如 `onnx_graph_rewrite`、`GraphRewriteSpecialist`。
- 运行新增/聚焦测试：
  - `python -m pytest tests/test_demo_examples_schema.py tests/test_llm_reflection_guard.py tests/test_token_budget.py tests/test_candidate_sandbox.py tests/test_runtime_config.py -q`
- 运行全量测试：
  - `python -m pytest -q`
- 尝试启动真实 DeepSeek + Vivado Demo0-Demo6 批量复测：
  - DeepSeek OpenAI-compatible。
  - `DL_OP_TO_HLS_MOCK_HLS4ML=0`
  - `DL_OP_TO_HLS_MOCK_VIVADO=0`
  - `DL_OP_TO_HLS_VIVADO_HLS_PATH=D:\Xilinx\Vivado\2018.3\bin\vivado_hls.bat`
  - `DL_OP_TO_HLS_RUNTIME_MODE=strict`
  - `DL_OP_TO_HLS_OPTIMIZATION_FALLBACK_MODE=strict`
  - `DL_OP_TO_HLS_SPECIALIST_LLM_DECIDER_ENABLED=1`

### 2. 当前测试结果
已通过：
- 聚焦测试通过：`18 passed`。
- 全量测试通过：`python -m pytest -q`，全部通过。
- 新增 ONNX Gemm rewrite 单元测试通过：
  - 构造真实 ONNX `Gemm(transB=1)` 图。
  - `graph_rewrite.rewrite` 生成 rewritten ONNX。
  - rewritten graph 中不再包含 `Gemm`，包含 `MatMul` 和 `Add`。

真实 Demo0-Demo6 复测状态：
- 本轮批量真实运行未能启动。
- 原因：Codex 提权审批器因当前 usage limit 拒绝联网 API/Vivado 执行请求：
  - `You've hit your usage limit...`
- 处理：按照安全规则，没有绕过审批器继续执行同等网络/API命令，也没有改用 mock 冒充真实结果。
- 后续：额度恢复后可直接用本轮同等 strict 配置重跑 Demo0-Demo6。

### 3. 发现的问题与根因
1) ContextEnvelope token budget 之前只是“声明式”
- 现象：`max_context_tokens=3000` 存在，但 ContextBuilder 没有实际估算/截断。
- 根因：context isolation 已经做了 artifact ref 隔离，但没有把 budget 变成执行约束。
- 风险：RAG / memory 摘要积累后，Main Agent 或 Specialist prompt 仍可能越界。

2) Demo2 的 Gemm 问题不是简单“LLM 基模不行”
- 现象：真实 hls4ml 对当前 MNIST MLP ONNX 的 `Gemm` 不支持。
- 根因：`graph_rewrite.rewrite` 之前只返回建议，`implemented=False`，没有真的改写 ONNX。
- 风险：LLM 会尝试凭空提出 `onnx_graph_rewrite` 等不存在工具，说明框架没有把可用能力边界喂清楚并强校验。

3) LLM reflection 新增 todo 缺少二次 ToolRegistry / Specialist allowlist 校验
- 现象：LLM reflection 可以提出未知 tool / unknown specialist。
- 根因：planner 阶段有 guard，但 reflect 阶段新增 todo 进入 TodoList 前缺少同等级别 guard。
- 风险：后续执行阶段才爆 PermissionDenied / KeyError，问题定位太晚。

4) Candidate 代码缺少 HLS C++ 静态沙箱
- 现象：已有 `LLMGuard.validate_candidate_files` 限制 candidate 目录，但不扫描 C++ 内容。
- 根因：路径隔离与代码安全扫描没有分层。
- 风险：LLM candidate 可能包含 `system()`、危险 include、进程/网络 API 等不适合 HLS 验证环境的内容。

5) runtime mode / fallback 策略配置不够集中
- 现象：strict/demo 切换分散在多个环境变量中。
- 根因：缺少统一 `runtime.yaml` 作为声明式配置源。
- 风险：开发期 strict 与 demo 展示期 fallback 语义混淆。

### 4. 已修复内容（含修复方式）
- 新增 `core/token_budget.py`
  - 实现轻量 token 估算：默认 `1 token ~= 4 chars`。
  - ContextBuilder 构造 ContextEnvelope 后立即执行预算检查。
  - 超预算时优先截断 RAG / retrieved memory，再截断 state summary / notes，最后裁剪 artifact refs。
  - SpecialistResult `context_usage` 新增：
    - `estimated_input_tokens`
    - `estimated_output_tokens`
    - `max_context_tokens`
    - `context_truncated`
- 新增 `core/candidate_sandbox.py`
  - 对 LLM candidate HLS C++ 做 pattern-based 静态扫描。
  - 拒绝：
    - `system()`
    - `popen()`
    - process spawn API
    - `#include <fstream>` / `<filesystem>` / `<windows.h>` / `<unistd.h>` 等危险 include
    - socket/network include
    - inline asm
  - `llm/candidate_generator.py` 写文件前先扫描，违规则返回 `PermissionDeniedError`，不写 candidate 文件。
- 新增 `runtime.yaml`
  - 集中声明：
    - `runtime.mode: strict | demo | production`
    - `runtime.llm.fallback: error`
    - `runtime.optimization.fallback: demo | strict`
    - `runtime.specialist.llm_decider_enabled`
  - `core/config.py` 读取 runtime.yaml，并保留环境变量 override。
- `graph_rewrite.rewrite` 从建议升级为真实 ONNX rewrite 工具
  - 对安全模式 `Gemm(alpha=1,beta=1,transA=0)` 执行自动改写。
  - 支持 `transB=1` 时转置常量 initializer。
  - 输出 rewritten ONNX 到 `runs/<run_id>/rewritten/*_gemm_rewritten.onnx`。
  - 注册 rewritten model artifact。
  - 遇到非平凡 Gemm 参数时返回结构化“不可安全改写”，不强行改变语义。
- Runtime 接入 rewritten model
  - `Try graph rewrite` 成功后更新：
    - `state.task["original_model_path"]`
    - `state.task["model_path"]`
    - `state.artifacts["rewritten_model"]`
  - rewrite 成功后重新追加 `Check hls4ml support`，再进入 config/convert。
  - rewrite 未实现或不安全时才进入 unsupported report。
- LLM reflection 新增 todo guard
  - `LLMFirstRuntime._validate_reflection_todo()` 校验：
    - assigned_tool 必须存在于 ToolRegistry。
    - assigned_specialist 必须存在于 SpecialistRouter。
    - specialist-private tool 必须委派给对应 specialist。
    - assigned_tool 必须在 assigned_specialist.allowed_tools 内。
  - 被拒绝的 reflection todo 写入 `LLMReflectionTodoRejected` trace，并记录脱敏结构化错误。
- 优化建议 strict schema 继续收紧
  - 支持 DeepSeek 可能返回的 `justification` / `rationale` 字段映射到 `reason`。
  - 占位标题但 reason 具体时规范化为 `Optimization action`。
  - 纯占位/空建议 strict 模式下仍失败，不再静默规则兜底。

### 5. 新增或更新的测试
- `test_graph_rewrite_rewrites_onnx_gemm_to_matmul_add`
- `test_llm_reflection_rejects_unknown_tool_and_specialist`
- `test_llm_reflection_rejects_specialist_tool_mismatch`
- `test_token_budget_*`
- `test_candidate_sandbox_*`
- `test_runtime_config_*`
- `test_llm_react_fills_delegate_specialist_from_todo`
- `test_llm_optimizer_strict_mode_accepts_justification_field`

测试结果：
- 聚焦测试：通过。
- 全量测试：通过。

### 6. 未修复完成的问题及原因
1) Multi-Agent Coordinator 并行调度暂未进入主线
- 原因：当前 artifact manifest、SQLite、Todo 状态、Vivado 工作目录 merge 都是共享状态；贸然并行会引入竞态，降低 demo bug 信号质量。
- 策略：作为后续 feature flag 实验模式实现，例如 `runtime.coordinator.parallel_enabled=true`；默认 production/strict 仍保持串行、可追踪、可复现。

2) Skill 自动提炼暂未写入 YAML 自动生成流程
- 原因：当前 MemoryManager 已能抽取/promote memory candidates，但自动写 skill YAML 会改变可执行能力集合，必须先增加 review/approval gate，避免 Agent 自行扩大权限。
- 策略：后续实现 `skills/candidates/*.yaml`，先作为候选 skill，不自动启用；通过人工批准或 tests 后再移入 `skills/*.yaml`。

3) Demo3 Shape/Reshape/Flatten 静态消除未完成
- 原因：本轮优先修复 Demo2 已知 `Gemm -> MatMul + Add` 的真实 rewrite；Shape/Reshape/Flatten 需要更多 ONNX shape/value_info 语义处理。
- 策略：后续补 `static_shape_elimination`，并用真实 Tiny CNN ONNX 单元图测试。

4) Demo4 QKeras/H5 真实前端仍未完成
- 原因：当前环境缺 `qkeras` / `tensorflow`，adapter 只能结构化 unsupported。
- 策略：后续增加 Keras/QKeras frontend adapter，或提供先导出为 hls4ml 支持输入格式的转换脚本。

5) 真实 DeepSeek + Vivado Demo0-Demo6 未完成
- 原因：Codex 当前外部命令审批因 usage limit 拒绝联网真实运行。
- 策略：额度恢复后继续执行 strict 真实复测；不使用 mock 替代真实结果。

---

## 2026-06-02 10:32:02 +08:00：真实/Mock 边界体检、严格验证修补、DeepSeek Demo0 真实复测
### 1. 本次测试做了什么
执行与验证：
- 使用独立目录：`D:\hls_agent\standalone_work\dl-op-to-hls-agent`。
- 检查用户指出的潜在问题：
  - `adapters/` 是否只有 `__init__.py`。
  - `cli:main` 是否缺失。
  - `verify_candidate` 是否写死 mock 报告。
  - `hls4ml.run_csim` 是否仍然无条件 mock 成功。
  - Permission / Hook / Trace 等基础设施是否存在。
- 使用 DeepSeek OpenAI-compatible 配置进行真实 Demo0 复测：
  - `DL_OP_TO_HLS_LLM_PROVIDER=openai-compatible`
  - `DL_OP_TO_HLS_LLM_BASE_URL=https://api.deepseek.com`
  - `DL_OP_TO_HLS_LLM_MODEL=deepseek-v4-pro`
  - `DL_OP_TO_HLS_LLM_API_KEY=<redacted>`
  - `DL_OP_TO_HLS_MOCK_HLS4ML=0`
  - `DL_OP_TO_HLS_MOCK_VIVADO=0`
  - `DL_OP_TO_HLS_VIVADO_HLS_PATH=D:\Xilinx\Vivado\2018.3\bin\vivado_hls.bat`
  - `DL_OP_TO_HLS_OPTIMIZATION_FALLBACK_MODE=strict`
- 运行聚焦测试：
  - `python -m pytest tests/test_fallback_templates.py -vv`
  - `python -m pytest tests/test_hls4ml_mcp.py tests/test_specialists.py -q`
  - `python -m pytest tests/test_llm_optimizer_fallback.py tests/test_fallback_templates.py tests/test_hls4ml_mcp.py tests/test_specialists.py -q`
- 运行全量测试：
  - `python -m pytest -q`

### 2. 当前复测结果
已确认不是问题的项：
- `src/dl_op_to_hls/adapters/` 并非只有 `__init__.py`，当前已存在：
  - `hls4ml_adapter.py`
  - `vivado_hls_adapter.py`
  - `legacy_vivado_env.py`
  - `llm_adapter.py`
  - `senior_agent_adapter.py`
- CLI 入口存在：
  - `src/dl_op_to_hls/cli.py`
  - `pyproject.toml` 中注册：`dl-op-to-hls = "dl_op_to_hls.cli:main"`。
- Permission / Hook / Trace / Artifact / DB / RAG 等基础设施存在，且本轮 pytest 仍全量通过。

已确认确实存在的问题：
- `verify_candidate.run` 之前会写死 `MOCK_REPORT` 并返回 `status=verified`。
- `hls4ml.run_csim` 之前无论真实/非真实模式都会写入 `Mock hls4ml csim completed successfully.`。
- Demo JSON 中 `demo.mock_tools=true` 会污染 LLM plan/summary，使真实运行也被描述成 mock demo。
- Demo0 真实运行虽然完成，但 `suggestions.md` 出现了泛化占位输出：`Suggestion` / `Suggestion`。这不是 mock，但属于 LLM 输出质量 guard 不足。

Demo0 真实复测结果：
- run_id：`dense_16x32_115c1f11_07`
- 运行状态：`success`
- selected_path：`fallback_template_path`
- DeepSeek LLM plan/react 成功；Main Agent 使用 `delegate_to_specialist` 调度 VivadoSpecialist / OptimizationSpecialist / MemorySpecialist。
- VivadoSpecialist 真实调用 `vivado_hls.bat` 完成 synthesis/report parsing。
- 真实报告指标：
  - Latency：269 / 269 cycles
  - II：269 / 269
  - DSP：16
  - BRAM：0
  - LUT：549
  - FF：732
  - Timing estimated：4.304 ns
  - Timing met：true
- summary 已包含：
  - `Todo Execution Summary`
  - `Specialist Execution Summary`
  - `Context Isolation`
  - `Memory Summary`

依赖状态：
- `hls4ml`：已安装。
- `onnx`：已安装。
- `qkeras`：未安装。
- `tensorflow`：未安装。
- 因此 Demo4 的真实 QKeras/H5 分支当前预期应结构化 unsupported，而不是伪造成功。

### 3. 发现的问题与根因
1) `verify_candidate` 将 mock 结果伪装为 verified
- 现象：无论候选代码是否真实通过 csim/csynth，工具都会写固定 csynth.rpt 并返回 `verified`。
- 根因：P0 mock 验证接口未与真实模式隔离。
- 风险：LLM candidate 可能未经真实 testbench/Vivado 验证就进入可复用 implementation 记忆。

2) `hls4ml.run_csim` 真实模式下仍写 mock 成功日志
- 现象：真实工具环境下仍输出 `Mock hls4ml csim completed successfully.`。
- 根因：adapter 没有区分 `mock_mode=True/False`。
- 风险：真实 hls4ml csim 状态被错误标记为 success。

3) Specialist local ReAct 可能重复调用 LLM，导致长流程卡顿
- 现象：上轮真实 Demo0 卡在 OptimizationSpecialist。
- 根因：Main Agent 已经做了 LLM ReAct 决策，Specialist 内部 local ReAct 又默认使用 LLM decider。
- 修复策略：Specialist local ReAct 默认使用确定性 schema guard；只有显式设置 `DL_OP_TO_HLS_SPECIALIST_LLM_DECIDER_ENABLED=1` 时才启用 LLM。

4) Demo JSON 的 `mock_tools=true` 会误导 LLM
- 现象：真实 Demo0 summary 的 LLM reasoning 提到了 mock Vivado。
- 根因：任务 JSON 中的 demo 元数据仍写着 mock_tools true。
- 修复策略：Demo0-Demo6 的 `mock_tools` 改为 `false`，描述改成真实优先，`--mock-tools` 仅用于离线冒烟测试。

5) Optimization suggestions 缺少质量 guard
- 现象：DeepSeek 返回的 suggestions 被规范化成 `Suggestion` / `Suggestion`，系统仍写入 summary。
- 根因：schema 只检查字段存在，没有检查内容是否为空壳/占位。
- 修复策略：新增 placeholder suggestion guard；strict 模式下空建议/占位建议返回 `LLMGenerationError`，demo 模式下才允许回退到规则建议。

### 4. 已修复内容（含修复方式）
- `verify_candidate.run`
  - 新增显式 `mock` / `real` 模式判断。
  - mock 模式才允许写 fixture report。
  - real 模式要求 candidate dir 存在、testbench 存在，并通过 Vivado adapter 创建项目、运行 Tcl、解析 report 后才返回 `verified`。
  - 缺 testbench / Vivado 失败 / report 缺失 / report 解析失败都会返回 structured error。
- `hls4ml.run_csim`
  - mock 模式保留原有 demo 行为并标记 `mode=mock`。
  - real 模式不再写假成功日志。
  - 缺项目目录、缺 hls4ml/onnx、缺 `build_prj.tcl` 或直接 csim 未启用时返回结构化错误。
- `MainAgent.create_run_context`
  - 注入 `hls4ml_adapter`、`vivado_adapter`。
  - 显式设置 `specialist_llm_decider_enabled=False`。
- `BaseSpecialist`
  - local ReAct 默认走确定性 decider。
  - 只有 `DL_OP_TO_HLS_SPECIALIST_LLM_DECIDER_ENABLED=1` 才调用 Specialist 内部 LLM decider。
- `PermissionGate`
  - `check_tool` 增加 `candidate_dir`、`testbench_path`、`report_dir` 检查。
- `VerificationSpecialist`
  - 描述从 mock csim/csynth 改为 explicit mock or real Vivado-backed verification。
- Demo JSON
  - Demo0-Demo6 的 `demo.mock_tools` 改为 `false`。
  - 描述改成真实优先，mock 仅用于 offline smoke test。
- `suggest_optimization`
  - 新增占位建议识别。
  - strict 模式下拒绝 `Suggestion` / 空 reason / 空建议。

### 5. 新增或更新的测试
- `test_verify_candidate_mock_success`
  - 显式传 `mode=mock`。
- `test_verify_candidate_real_mode_requires_testbench`
  - 验证真实模式下没有 testbench 不能返回 verified。
- `test_hls4ml_run_csim_real_mode_does_not_mock_success`
  - 验证真实模式不会写 mock 成功。
- `test_llm_optimizer_strict_mode_rejects_placeholder_suggestions`
  - 验证 strict 模式拒绝占位建议。

测试结果：
- 聚焦测试通过：
  - fallback / hls4ml / specialists / optimizer tests 全部通过。
- 全量测试通过：
  - `python -m pytest -q` 通过。

### 6. 未修复完成的问题及原因
1) Demo1-Demo6 本轮未能继续真实运行
- 原因：批量真实命令需要联网调用 DeepSeek API 并调用 Vivado HLS，Codex 提权系统返回 usage limit，拒绝继续执行：
  - `You've hit your usage limit...`
- 处理：按照安全规则，未绕过提权限制继续执行同等网络/Vivado命令。
- 后续：额度恢复后继续运行 Demo1-Demo6，或用户可在本机 PowerShell 中直接运行同等命令。

2) Demo0 在新增 suggestions guard 后尚未重新真实复测
- 原因：同样受 usage limit 限制，不能继续调用 DeepSeek API。
- 已完成的验证：pytest 已覆盖 placeholder suggestion strict rejection。
- 后续：额度恢复后需要重新运行 Demo0，确认 DeepSeek 在 strict guard 下能返回高质量建议；如果不能，应继续优化 optimizer prompt 或将该阶段标为结构化失败。

3) Demo2/Demo3 真实 hls4ml 图支持问题仍可能存在
- 既往结果显示 MNIST MLP 可能包含 Gemm，Tiny CNN 可能包含 Shape/reshape/flatten 类节点。
- 当前已有 graph rewrite suggestion，但并未真正完成 ONNX graph rewrite。
- 后续：实现真实 Gemm -> MatMul + Add、静态 Shape/Reshape/Flatten 消除，不能只靠 fallback。

4) Demo4 QKeras/H5 真实链路未完成
- 当前 `qkeras` / `tensorflow` 未安装，adapter 只做结构化 unsupported。
- 后续：补 Keras/QKeras frontend 分支，或提供从 QKeras/H5 到 hls4ml 支持输入的真实转换路径。

---

## 2026-06-01 20:31:40 +08:00：修复后真实 LLM Demo0 复测结果
### 1. 本次测试做了什么
执行与验证：
- 使用独立目录：`D:\hls_agent\standalone_work\dl-op-to-hls-agent`。
- 使用真实 LLM API、真实 Vivado HLS 路径、非 mock 工具配置复测 Demo0：
  - `python -m dl_op_to_hls.cli run-llm examples/dense_operator.json`
  - `DL_OP_TO_HLS_MOCK_HLS4ML=0`
  - `DL_OP_TO_HLS_MOCK_VIVADO=0`
  - `DL_OP_TO_HLS_OPTIMIZATION_FALLBACK_MODE=strict`
- 本次命令外层 15 分钟超时，后台 Python 进程继续运行；后续确认其长时间停留在 OptimizationSpecialist 阶段，因此已停止该孤儿进程，避免继续消耗 API。

### 2. 当前复测结果
本轮 run_id：
- `dense_16x32_115c1f11_06`

已经验证通过的链路：
- Main Agent ReAct 不再卡在缺失 `decision`，trace 中已出现合法决策：
  - `direct_tool_only_when_no_specialist`
  - `delegate_to_specialist`
- Fallback HLS template 已生成成功：
  - `generated/dense_16x32.h`
  - `generated/dense_16x32.cpp`
  - `generated/testbench.cpp`
  - `generated/run_hls.tcl`
- VivadoSpecialist 已被正确委派并执行成功：
  - `vivado.create_project` success
  - `vivado.run_csynth` success
  - `vivado.parse_report` success
- Vivado report artifact 已生成：
  - `runs/dense_16x32_115c1f11_06/vivado_hls/vivado_hls/solution1/syn/report/dense_16x32_csynth.rpt`
- `Parse synthesis report` todo 也通过 `VivadoSpecialist` 完成。

未完成的链路：
- 执行到 `Generate optimization suggestions` / `OptimizationSpecialist` 后，trace 停在 `SpecialistStarted`，没有后续 tool event。
- 外层命令超时后后台进程仍存在，说明该阶段可能卡在 Specialist local ReAct 的 LLM 调用、API 等待或 optimizer LLM 调用上。

### 3. 发现的问题与根因
1) 之前的 `decision` 缺失问题已明显改善
- 证据：trace 中 Main Agent 多次返回合法 `decision`，并成功委派 VivadoSpecialist。
- 结论：schema enum、prompt 示例、strict JSON repair 对主 ReAct 契约有效。

2) 新瓶颈转移到 OptimizationSpecialist 阶段
- 现象：trace 最后事件为 `SpecialistStarted` for `OptimizationSpecialist`，之后无 `PreToolUse` / `SpecialistFinished`。
- 初步根因：OptimizationSpecialist 内部 local ReAct 也会调用 LLM decider；在当前真实 API/限速环境下可能等待过长或挂起。
- 下一步修复方向：为 Specialist local ReAct 增加 per-call timeout、超时结构化错误、以及针对 OptimizationSpecialist 的“必须先发出 local_react trace 再调用 LLM”可观测性。

3) run-llm 长流程缺少全局 wall-clock budget
- 现象：外层 shell 超时后子进程仍继续运行。
- 初步根因：当前 runtime 没有统一 run-level deadline / cancellation propagation。
- 下一步修复方向：增加 `DL_OP_TO_HLS_RUN_TIMEOUT_SEC` 或 runtime deadline，在 LLM/tool/specialist 层统一检查并返回 structured timeout error。

### 4. 已修复内容（含修复方式）
- 本次为真实复测与定位，未修改业务代码。
- 停止了超时后残留的 Python 进程，避免继续消耗 API。

### 5. 未修复完成的问题及原因
1) Demo0 run-llm 尚未完整成功
- 原因：虽然已通过 Main Agent ReAct、fallback generation、Vivado synthesis/report parsing，但卡在 OptimizationSpecialist 阶段。

2) 本次没有 push 到 GitHub
- 原因：用户要求“如果成功则 push”；本轮复测未完整成功，因此不推送新的日志/状态提交，避免把未完成验证误标为通过。
---

## 2026-06-01 15:11:00 +08:00：LLM 契约层、Skill 工具边界、hls4ml stdout 与 QKeras/H5 前端修补
### 1. 本次测试做了什么
执行与验证：
- 修补 Main Agent ReAct schema：增加 `title`、`decision enum` 和强示例。
- 增强 `REACT_SYSTEM_PROMPT`：明确只能输出严格 JSON，`decision` 必须来自 `allowed_actions`。
- 新增严格 JSON repair 回合：第一次 LLM JSON 缺字段/格式错误时，只允许修复 JSON 结构和缺失必填字段，不允许改变任务语义。
- 新增脱敏 LLM debug artifact：repair 失败时写入 `runs/<run_id>/llm_debug/*.json`，并对 API key/token/secret 做脱敏。
- 收紧 planner capability exposure：planner 的 `direct_tools` 现在按候选 skill contract 过滤，同时显式提供 `skill_tool_contracts`。
- 对齐 `hls4ml_model_flow` allowlist：加入 `graph_rewrite.rewrite`、`report.write_unsupported`、`summary.write_summary`，避免 failure policy 允许但 skill policy 拒绝。
- 修复 LLM candidate 工具命名不一致：同时识别 `llm.generate_candidate` 和旧别名 `llm.generate_hls_candidate`。
- 增加 QKeras/H5 frontend 分支：`.h5/.hdf5` 不再被当成 ONNX ModelProto 解析，而是返回结构化 unsupported / conversion error。
- 捕获真实 hls4ml 部分 stdout：在 `config_from_onnx_model` / `convert_from_onnx_model` 调用处 redirect stdout 到 log artifact，避免污染 CLI JSON。
- 增强 graph rewrite 检测：支持检测 ONNX `Gemm`、`Shape/Reshape/Flatten` 并给出明确 rewrite suggestion，但不假装已完成真实图重写。

运行测试：
- Focused：`python -m pytest tests/test_llm_client_config.py tests/test_llm_todo_plan_schema.py tests/test_skill_policy.py tests/test_hls4ml_mcp.py tests/test_demo_examples_schema.py tests/test_llm_react_decision_guard.py -q`，结果：27 passed。
- Full：`python -m pytest -q`，结果：158 passed。

### 2. 发现的问题与根因
1) LLM ReAct 缺 `decision` 不应只靠 prompt 期待模型遵守
- 根因：OpenAI-compatible 模型可能返回近似 JSON，但不稳定遵守必填字段。
- 修复策略：schema enum + 强示例 + strict JSON repair + 失败 artifact，而不是静默 deterministic fallback。

2) Boundary planner 违反 skill allowlist 是 tool contract 不一致问题
- 根因：`hls4ml_model_flow` 的 failure_policy 提到 graph rewrite / unsupported report，但 allowed_tools 中没有这些工具；planner 也能看到比当前 skill 更多的 direct tools。
- 修复策略：对齐 skill allowlist，并把 planner 可见 direct tools 限制到候选 skill contracts。

3) Demo4 的 QKeras/H5 不应走 ONNX parser
- 根因：adapter 没有 frontend 分支，导致 `.h5` 被 ONNX parser 解析并报 `Error parsing onnx.ModelProto`。
- 修复策略：识别 `keras/qkeras/h5` frontend，返回明确结构化 unsupported/转换错误，指向专门 H5 frontend 后续实现。

4) 真实 hls4ml stdout 污染 CLI JSON
- 根因：第三方库直接打印 stdout，CLI 同时输出 JSON state。
- 修复策略：在 adapter 真实调用点捕获 stdout 并写入日志 artifact。

### 3. 已修复内容（含修复方式）
修复文件：
- `src/dl_op_to_hls/llm/schemas.py`
- `src/dl_op_to_hls/llm/prompts.py`
- `src/dl_op_to_hls/llm/client.py`
- `src/dl_op_to_hls/llm/planner.py`
- `src/dl_op_to_hls/llm/guards.py`
- `src/dl_op_to_hls/skills/policy.py`
- `skills/hls4ml_model_flow.yaml`
- `src/dl_op_to_hls/adapters/hls4ml_adapter.py`
- `src/dl_op_to_hls/tools/graph_rewrite.py`
- `tests/test_llm_client_config.py`
- `tests/test_llm_todo_plan_schema.py`
- `tests/test_hls4ml_mcp.py`
- `tests/test_demo_examples_schema.py`

关键修复点：
- `REACT_DECISION_SCHEMA.decision` 增加 enum：`delegate_to_specialist`、`direct_tool_only_when_no_specialist`、`request_replan`、`mark_blocked`、`mark_failed`。
- `SPECIALIST_REACT_DECISION_SCHEMA.decision` 增加 enum：`call_tool`、`mark_blocked`、`mark_failed`、`finish_with_result`。
- `LLMClient.complete_json()` 支持一次 strict repair，修复失败写脱敏 debug artifact。
- Planner payload 新增 `skill_tool_contracts`，并过滤掉候选 skill 外的 direct tools。
- HLS4MLAdapter 对 `.h5/.hdf5/qkeras/keras` 做前端识别，不再误走 ONNX parse。
- Graph rewrite 明确返回 `implemented: false`，避免把建议误表示成已完成转换。

### 4. 当前结果
- 本地 mock/单元/集成测试全部通过：158 passed。
- 已修复框架侧最直接的 LLM schema 缺字段问题，并增加可调试 artifact。
- 已修复 skill contract 与 planner capability exposure 的主要不一致点。
- 已修复 QKeras/H5 输入链路误报 ONNX parse 的问题。
- 已部分修复 hls4ml stdout 污染 CLI JSON 的问题。

### 5. 未修复完成的问题及原因
1) 未完成真实 API Demo0 复测
- 原因：尝试运行真实 API + Vivado Demo0 探针时，当前 Codex 环境提示使用额度限制，无法继续发起该外部执行。

2) Gemm/Shape 仍只是 rewrite suggestion，不是真实 ONNX 图重写
- 原因：真实 ONNX graph rewrite 需要安全地重写 initializer、shape metadata 和下游节点，不能在本轮用字符串级伪转换冒充完成。

3) hls4ml stdout 捕获可能还不覆盖所有第三方打印点
- 原因：已覆盖 adapter 中主要真实调用点，但其他库内部异步/底层输出仍需后续真实复测确认。

4) Boundary demo 仍需真实 LLM 复测
- 原因：本轮已修 prompt/contract/allowlist，但受额度限制未能重新运行真实 `run-llm` 验证。
---

## 2026-06-01 14:48:53 +08:00：真实 LLM API 与真实 Vivado/HLS 工具链 Demo0-Demo6 全量验证
### 1. 本次测试做了什么
执行与验证：
- 使用独立目录：`D:\hls_agent\standalone_work\dl-op-to-hls-agent`。
- 先执行真实 LLM-first 验证：`python -m dl_op_to_hls.cli run-llm <demo>`。
- LLM API 配置为 OpenAI-compatible endpoint，模型为 `mimo-v2.5-pro`；API Key 只通过环境变量注入，未写入仓库文件或日志。
- LLM 限速配置：`DL_OP_TO_HLS_LLM_RATE_BYTES_PER_MINUTE=10000`、`DL_OP_TO_HLS_LLM_MIN_REQUEST_INTERVAL_SEC=12`、`DL_OP_TO_HLS_LLM_MIN_RETRY_429_SECONDS=30`。
- Vivado HLS 配置：`DL_OP_TO_HLS_VIVADO_HLS_PATH=D:\Xilinx\Vivado\2018.3\bin\vivado_hls.bat`。
- 关闭 mock：`DL_OP_TO_HLS_MOCK_HLS4ML=0`、`DL_OP_TO_HLS_MOCK_VIVADO=0`。
- 开发期严格模式：`DL_OP_TO_HLS_OPTIMIZATION_FALLBACK_MODE=strict`。
- 随后执行真实工具链基线验证：`python -m dl_op_to_hls.cli run <demo>`，用于确认 hls4ml/Vivado adapter 的真实行为。

### 2. 真实 LLM API 验证结果（run-llm）
| Demo | 文件 | run_id | status | 主要结果 |
|---|---|---|---|---|
| Demo 0 | `examples/dense_operator.json` | `dense_16x32_115c1f11_04` | `failed` | Main Agent ReAct 响应缺少 `decision` 字段 |
| Demo 1 | `examples/matmul_resource.json` | `matmul_16x16_resource_b0ad01f2_03` | `failed` | Main Agent ReAct 响应缺少 `decision` 字段 |
| Demo 2 | `examples/mnist_mlp_hls4ml.json` | `mnist_mlp_demo_88b12719_06` | `failed` | Main Agent ReAct 响应缺少 `decision` 字段 |
| Demo 3 | `examples/mnist_tiny_cnn.json` | `mnist_tiny_cnn_6bbae346_06` | `failed` | Main Agent ReAct 响应缺少 `decision` 字段 |
| Demo 4 | `examples/mnist_qkeras_cnn.json` | `mnist_qkeras_cnn_4c10f7fa_04` | `failed` | Main Agent ReAct 响应缺少 `decision` 字段 |
| Demo 5 | `examples/tiny_residual_block.json` | `tiny_residual_block_b66fa9b1_05` | `failed` | LLM planner 生成了 selected skill allowlist 外的工具 |
| Demo 6 | `examples/resnet18_boundary.json` | `resnet18_boundary_demo_16dc6e00_04` | `failed` | LLM planner 生成了 selected skill allowlist 外的工具 |

结论：
- API 实际被调用，限速后未再观察到 429 作为主失败原因。
- 失败集中在 LLM 输出契约：Demo0-Demo4 是 `REACT_DECISION_SCHEMA` 缺 `decision`；Demo5-Demo6 是 planner 违反 SkillPolicy allowlist。
- 因为当前是开发期严格模式，系统没有把这些错误静默 fallback 到确定性流程，这是符合“暴露问题并修 Agent”的目标的。
- 这些失败发生在 Vivado 调用之前，因此 run-llm 这轮没有完成真实 Vivado 综合验证。

### 3. 真实 hls4ml/Vivado 工具链基线验证结果（run，非 mock）
| Demo | 文件 | run_id | status | selected_path | report_status | 主要结果 |
|---|---|---|---|---|---|---|
| Demo 0 | `examples/dense_operator.json` | `dense_16x32_115c1f11_05` | `partial_success` | `fallback_template_path` | `success` | fallback HLS + Vivado work dir/report 生成成功 |
| Demo 1 | `examples/matmul_resource.json` | `matmul_16x16_resource_b0ad01f2_04` | `partial_success` | `fallback_template_path` | `success` | matmul fallback + Vivado work dir/report 生成成功 |
| Demo 2 | `examples/mnist_mlp_hls4ml.json` | `mnist_mlp_demo_88b12719_07` | `partial_success` | `unsupported_path` | `missing` | 真实 hls4ml 报 `Unsupported operation type: Gemm` |
| Demo 3 | `examples/mnist_tiny_cnn.json` | `mnist_tiny_cnn_6bbae346_07` | `partial_success` | `unsupported_path` | `missing` | 真实 hls4ml 报 `Unsupported operation type: Shape` |
| Demo 4 | `examples/mnist_qkeras_cnn.json` | `mnist_qkeras_cnn_4c10f7fa_05` | `partial_success` | `unsupported_path` | `missing` | h5/QKeras 输入被当前 ONNX parser 链路解析失败 |
| Demo 5 | `examples/tiny_residual_block.json` | `tiny_residual_block_b66fa9b1_06` | `partial_success` | `unsupported_path` | `missing` | residual boundary 按预期进入 unsupported 路径 |
| Demo 6 | `examples/resnet18_boundary.json` | `resnet18_boundary_demo_16dc6e00_05` | `partial_success` | `unsupported_path` | `missing` | ResNet18 boundary 按预期进入 unsupported 路径 |

补充现象：
- Demo2/Demo3 的 CLI stdout 被真实 hls4ml 打印的 `Output layers` / `Topology` 污染，导致外层 PowerShell `ConvertFrom-Json` 解析失败；但 run 目录中的 `state.json` 和 `summary.md` 正常生成。
- Demo0/Demo1 的 `vivado_work_dir` 已生成，说明本机 Vivado HLS bat 路径可被 adapter 调用。

### 4. 发现的问题与根因
1) LLM ReAct 输出缺少 `decision`
- 根因：当前 prompt/schema 约束还不足以让该 OpenAI-compatible 模型稳定返回严格 JSON 字段；客户端严格校验后正确报错。
- 下一步修复方向：加强 `REACT_SYSTEM_PROMPT` 的字段示例，增加 schema title/enum 提示，并在 error details 中保留脱敏后的 raw LLM payload，便于调试。

2) Boundary demo 的 LLM planner 违反 skill allowlist
- 根因：planner 会提出 `graph_rewrite.rewrite`、`report.write_unsupported`、`summary.write_summary` 等工具，但当前 selected skill allowlist 未覆盖这些工具或工具名注册不一致。
- 下一步修复方向：统一 skill YAML、ToolRegistry 注册名和 planner layered capability view；不应通过放宽 guard 解决。

3) Demo2/Demo3 真实 hls4ml 不支持当前 ONNX 图
- 根因：MNIST MLP 包含 `Gemm`；Tiny CNN 包含 `Shape`，当前 hls4ml 转换链路不支持。
- 下一步修复方向：实现 graph rewrite：`Gemm -> MatMul + Add`，并对 `Shape`/reshape/flatten 做静态消除。

4) Demo4 QKeras/H5 输入链路不匹配
- 根因：当前 adapter 的真实模型解析链路按 ONNX ModelProto 解析，不能直接解析 `.h5`。
- 下一步修复方向：增加 QKeras/H5 frontend 分支，或先导出为 hls4ml 支持的 Keras/QKeras 输入格式。

5) 真实 hls4ml stdout 污染 CLI JSON 输出
- 根因：底层库直接向 stdout 打印，CLI 同时输出 JSON state，导致调用方无法直接 `ConvertFrom-Json`。
- 下一步修复方向：adapter 捕获/重定向第三方 stdout 到 log artifact，CLI stdout 只输出 JSON。

### 5. 已修复内容（含修复方式）
- 本次主要是全量真实验证与问题定位，未改动业务代码。
- 新增/更新开发日志，记录真实 API、真实 Vivado、真实 hls4ml 的验证结果与后续修复方向。

### 6. 未修复完成的问题及原因
1) run-llm Demo0-Demo6 尚未真实跑通
- 原因：LLM 输出契约和 SkillPolicy allowlist 暴露真实问题；开发期不应静默 fallback。

2) Demo2-Demo4 尚未真实 hls4ml full success
- 原因：当前模型图和 frontend 与 hls4ml 支持范围不完全匹配，需要 graph rewrite / frontend 分支改造。

3) CLI JSON 输出仍可能被第三方 stdout 污染
- 原因：真实 hls4ml 库直接打印 stdout，需要后续在 adapter 层捕获。
---

## 2026-06-01 13:57:09 +08:00：中文 README、Demo0-Demo6 递进验收与 GitHub 发布准备
### 1. 本次测试做了什么
执行与验证：
- 将 `README.md` 重写为较详细中文版本，覆盖项目边界、Agent 架构、两层 ReAct、Specialist、Memory、运行模式、Demo 路线、环境变量、测试和目录结构。
- 使用独立目录运行：`D:\hls_agent\standalone_work\dl-op-to-hls-agent`。
- 按 Demo0 → Demo6 递进运行稳定演示验收命令：`python -m dl_op_to_hls.cli run <example> --mock-tools`。
- 运行时显式设置：`PYTHONPATH=src`、`DL_OP_TO_HLS_OPTIMIZATION_FALLBACK_MODE=demo`。
- 生成本轮 Demo 摘要：`runs/demo0_6_progressive_summary_20260601.json`。

### 2. Demo0-Demo6 递进结果
| Demo | 文件 | run_id | status | selected_path | report_status | 说明 |
|---|---|---|---|---|---|---|
| Demo 0 | `examples/dense_operator.json` | `dense_16x32_115c1f11_03` | `partial_success` | `fallback_template_path` | `success` | fallback template 工程闭环可用 |
| Demo 1 | `examples/matmul_resource.json` | `matmul_16x16_resource_b0ad01f2_02` | `partial_success` | `fallback_template_path` | `success` | matmul resource trade-off 演示可用 |
| Demo 2 | `examples/mnist_mlp_hls4ml.json` | `mnist_mlp_demo_88b12719_05` | `success` | `hls4ml_path` | `success` | hls4ml 主路径演示可用 |
| Demo 3 | `examples/mnist_tiny_cnn.json` | `mnist_tiny_cnn_6bbae346_05` | `success` | `hls4ml_path` | `success` | tiny CNN 主路径演示可用 |
| Demo 4 | `examples/mnist_qkeras_cnn.json` | `mnist_qkeras_cnn_4c10f7fa_03` | `success` | `hls4ml_path` | `success` | qkeras/量化演示路径在 mock-tool 验收中可用 |
| Demo 5 | `examples/tiny_residual_block.json` | `tiny_residual_block_b66fa9b1_04` | `partial_success` | `unsupported_path` | `missing` | residual boundary 按预期进入边界/unsupported 路径 |
| Demo 6 | `examples/resnet18_boundary.json` | `resnet18_boundary_demo_16dc6e00_03` | `partial_success` | `unsupported_path` | `missing` | ResNet18 boundary 按预期不盲目承诺 full synthesis |

### 3. 发现的问题与根因
1) 直接运行 `python -m dl_op_to_hls.cli ...` 会找不到包
- 根因：当前独立目录尚未 editable install，Python 默认搜索路径不包含 `src`。
- 处理：本轮命令显式设置 `PYTHONPATH=src`；README 中也写明该运行方式。
2) Demo 验收需要区分 mock-tool 与真实工具
- 根因：Demo0-Demo6 的演示验收目标是稳定展示 Agent 工程闭环；真实 hls4ml/Vivado 环境会受到本机依赖、license、模型图和 API 限速影响。
- 处理：本轮明确使用 `--mock-tools`，并在 README 和本日志中标注，不把它伪装成真实 Vivado 综合。
3) GitHub 发布前需要确认不泄露 API Key
- 根因：历史对话中出现过 API Key，但不能写入仓库。
- 处理：上传前用 `rg` 检查仓库文件，未发现真实 API Key；代码中只保留环境变量读取方式。

### 4. 已修复内容（含修复方式）
修复文件：
- `README.md`
- `docs/development_log.md`

关键修复点：
- README 从简短英文说明扩展为中文交付文档。
- README 明确 `run` / `run-llm` 差异、Specialist Local ReAct、strict/demo 优化建议模式、Demo0-Demo6 运行方式。
- development log 继续按“最新在最上面”的顺序追加本次 Demo 验收记录。

### 5. 未修复完成的问题及原因
1) 本轮 Demo 使用 mock-tool 验收，不代表真实 Vivado HLS 综合全通过
- 原因：本次目标是仓库发布前的递进演示验收；真实工具链测试需要单独记录 hls4ml/Vivado 环境、license、模型转换错误和运行耗时。
2) 独立目录尚未安装为 editable package
- 原因：为了避免修改用户全局 Python 环境，本轮使用 `PYTHONPATH=src` 运行；后续可执行 `python -m pip install -e .` 改善 CLI 体验。
---

## 2026-06-01 12:32:30 +08:00：Specialist Local ReAct 与优化建议 strict/demo 模式
### 1. 本次测试做了什么
执行与验证：
- 新增 Specialist local ReAct decider / guard / schema / prompt。
- 将 HLS4MLSpecialist、VivadoSpecialist、VerificationSpecialist、OptimizationSpecialist、MemorySpecialist 的局部工具调用接入 local ReAct 决策。
- 将 `suggestion.suggest_optimization` 的 rule fallback 改成可配置模式：`demo` 允许规则建议，`strict` 下 LLM 不可用或失败即返回 `LLMGenerationError`。
- 新增并运行 focused 回归：`python -m pytest tests/test_specialist_react.py tests/test_specialists.py tests/test_llm_optimizer_fallback.py tests/test_llm_runtime_plan_validation.py tests/test_llm_react_decision_guard.py tests/test_llm_todo_plan_schema.py tests/test_llm_trace_events.py tests/test_llm_runtime_no_silent_legacy_fallback.py -q`，结果：42 passed。
### 2. 发现的问题与根因
1) Specialist 内部仍是固定工具编排
- 根因：虽然 Main Agent 已经不能直接看 specialist 私有 tool，但 specialist 自己的 `handle()` 仍然直接调用工具，没有独立的局部 ReAct action schema。
2) Specialist 越权调用需要在局部层直接暴露
- 根因：如果把越权工具温柔转换成普通失败，会让 guard 契约不够尖锐；开发期应该直接暴露 schema violation。
3) 优化建议仍存在隐式规则 fallback
- 根因：`suggest_optimization` 在无 LLM 或 LLM 异常时默认走 rule fallback，开发期会掩盖 API / prompt / schema 问题。
### 3. 已修复内容（含修复方式）
修复文件：
- `src/dl_op_to_hls/specialists/react.py`
- `src/dl_op_to_hls/specialists/base.py`
- `src/dl_op_to_hls/specialists/hls4ml_specialist.py`
- `src/dl_op_to_hls/specialists/vivado_specialist.py`
- `src/dl_op_to_hls/specialists/verification_specialist.py`
- `src/dl_op_to_hls/specialists/optimization_specialist.py`
- `src/dl_op_to_hls/specialists/memory_specialist.py`
- `src/dl_op_to_hls/llm/schemas.py`
- `src/dl_op_to_hls/llm/prompts.py`
- `src/dl_op_to_hls/llm/optimizer.py`
- `src/dl_op_to_hls/tools/suggest_optimization.py`
- `tests/test_specialist_react.py`
- `tests/test_specialists.py`
- `tests/test_llm_optimizer_fallback.py`

关键修复点：
- 新增 Specialist action schema：`call_tool`、`mark_blocked`、`mark_failed`、`finish_with_result`。
- 新增 `SPECIALIST_REACT_SYSTEM_PROMPT`，和 Main Agent ReAct prompt 分离。
- 新增 `SpecialistReActGuard`，`call_tool` 必须命中当前 specialist 的 `allowed_tools`。
- 新增 `SpecialistReActDecider`，输入限定为 `ContextEnvelope`、`allowed_tools`、recent specialist observations、candidate arguments。
- `BaseSpecialist` 新增 `_local_react_step()`，每个工具调用前记录局部 ReAct 决策。
- 每个 specialist 现在先通过 local ReAct 决策，再通过 ToolRegistry 调工具。
- `suggest_optimization` 新增 `fallback_mode`：默认 `demo`，可通过参数/context/环境变量 `DL_OP_TO_HLS_OPTIMIZATION_FALLBACK_MODE=strict` 切到严格模式。
### 4. 当前结果
- Focused 回归通过：42 passed。
- Main Agent ReAct 与 Specialist ReAct 已分成两套 schema：Main Agent 负责 delegation/direct-tool/replan/block/fail；Specialist 负责局部 call_tool/block/fail/finish。
- strict 模式下，无 LLM 的优化建议不会再自动规则兜底，而是返回结构化 `LLMGenerationError`。
### 5. 未修复完成的问题及原因
1) 尚未运行全量 `pytest`
- 原因：本次先完成架构契约 focused 回归，尚未花更长时间跑全部测试矩阵。
2) Specialist local ReAct 当前支持 LLM decider，但默认仍有 deterministic policy
- 原因：无 API 或测试环境下仍需要可测的本地决策路径；它不是静默兜底，而是显式的局部策略，所有决策都会进入 observations。
---

## 2026-06-01 12:26:23 +08:00｜Main Agent 动作层、分层工具视图与 Specialist 隔离契约加固

### 1. 本次测试做了什么

执行与验证：
- 新增 Main Agent action schema。
- 将 planner 输入从扁平 `available_tools` 改为分层能力视图。
- 收紧 Main Agent ReAct，只允许高层动作。
- 为 specialist 隔离和本地工具调用契约增加测试。
- 运行回归：`python -m pytest tests/test_llm_runtime_plan_validation.py tests/test_llm_react_decision_guard.py tests/test_llm_todo_plan_schema.py tests/test_specialists.py tests/test_llm_trace_events.py tests/test_llm_runtime_no_silent_legacy_fallback.py -q`（36 passed）。

### 2. 已修复内容（含修复方式）

修复文件：
- `src/dl_op_to_hls/llm/actions.py`
- `src/dl_op_to_hls/llm/planner.py`
- `src/dl_op_to_hls/llm/react.py`
- `src/dl_op_to_hls/llm/prompts.py`
- `src/dl_op_to_hls/llm/guards.py`
- `src/dl_op_to_hls/llm/client.py`
- `src/dl_op_to_hls/main_agent/llm_runtime.py`
- `tests/test_llm_todo_plan_schema.py`
- `tests/test_llm_react_decision_guard.py`
- `tests/test_llm_runtime_plan_validation.py`
- `tests/test_specialists.py`

关键修复点：
- 新增 Main Agent action schema：`delegate_to_specialist`、`direct_tool_only_when_no_specialist`、`request_replan`、`mark_blocked`、`mark_failed`。
- Planner 现在接收 layered capability view：
  - `main_agent_actions`
  - `direct_tools`
  - `available_specialists`
- Main Agent planner 不再直接接收 specialist 私有工具列表，例如 `hls4ml.*`、`vivado.*`、`memory.*`、`suggestion.*`。
- Specialist 私有 tool 若未分配对应 specialist，plan validator 会直接拒绝。
- Specialist-owned todo 的 Main Agent ReAct 只允许 `delegate_to_specialist`、`request_replan`、`mark_blocked`、`mark_failed`。
- Atomic todo 的 Main Agent ReAct 只允许 `direct_tool_only_when_no_specialist`、`request_replan`、`mark_blocked`、`mark_failed`。
- JSON normalize 层不再在缺失 `decision` 时自动补 `call_tool`。
- LLM reflection 失败不再调用父类逻辑继续执行，而是明确标记失败。
- 增加 specialist 契约测试，确认每个 specialist：
  - 只接收 `ContextEnvelope`。
  - 只调用自身 `allowed_tools`。
  - 只返回 `SpecialistResult`。
  - 不把 `raw_log`、`stdout`、`stderr` 合入返回结果。

### 3. 剩余架构问题与原因

1) Specialist 内部仍主要是确定性编排
- 原因：当前 specialist 的 `handle()` 内部直接按固定逻辑调用工具，还没有自己的 LLM local ReAct decider。
- 影响：隔离边界已经更清楚，但还不是完整的“Specialist 局部 ReAct”。

2) `suggest_optimization` 中仍存在 rule fallback
- 原因：优化建议工具为了无 LLM/LLM 失败时可输出建议，仍有规则建议兜底。
- 影响：这是工具内部的建议生成兜底，不会绕过 Main Agent/Specialist 的权限边界，但开发期需要在结果中显式标记 `llm_fallback_used`。

3) Deterministic `run` 模式仍存在
- 原因：项目保留 `run` 作为非 LLM 基线流程，`run-llm` 才是 LLM-first Agent 流程。
- 影响：这不是 `run-llm` 的静默 fallback，但文档和 CLI 输出需要继续强调两者不同。

### 4. 下一步建议

- 为 Specialist 增加独立 local ReAct decider：
  - 输入：`ContextEnvelope`、`allowed_tools`、recent specialist observations。
  - 输出：`call_tool`、`mark_blocked`、`mark_failed`、`finish_with_result`。
- 给每个 Specialist 增加 prompt 和 guard，形成 Main Agent ReAct 与 Specialist ReAct 两层不同 schema。
- 把 `suggest_optimization` 的 rule fallback 改为开发期可配置：strict 模式下 LLM 失败即失败，demo 模式下才启用规则建议。

## 2026-06-01 12:13:24 +08:00｜开发期严格模式纠偏：禁止静默 fallback 掩盖 Agent 架构问题

### 1. 本次测试做了什么

执行与验证：
- 重新审查 `LLMFirstRuntime.execute_todo_with_react` 与 `LLMGuard.validate_todo_plan`。
- 增加测试：`test_llm_plan_rejects_tool_specialist_mismatch`。
- 运行回归：`python -m pytest tests/test_llm_runtime_plan_validation.py -q`（3 passed）。

### 2. 关键概念澄清

本项目中有两类容易混淆的 fallback：
- 领域路径 fallback：例如 hls4ml 不支持算子时，进入 `fallback_template_path` 或 `unsupported_path`。这是任务书要求的 HLS 工作流分支。
- Agent 运行时 fallback：例如 LLM 计划非法时，系统自动切回确定性 todo 或直接执行 assigned tool。开发阶段不应该依赖这种兜底，因为它会掩盖 planner、tool scope、specialist isolation 的真实问题。

本次纠偏针对第二类：Agent 运行时静默兜底。

### 3. 发现的问题与根因

1) LLM 获取到了不该直接使用的 tool
- 根因：计划 prompt / guard / specialist scope 三者没有形成闭环约束。LLM 在 Main Agent 层仍能规划底层工具与 specialist 的组合，而不是只看到当前层级允许的动作。

2) Sub-agent 隔离没有完全生效
- 根因：Main Agent 的 ReAct 分支允许对 specialist-owned todo 做 `call_tool`，这让本应由 specialist 内部处理的局部工具决策泄漏到了 Main Agent 层。

3) “优先走 specialist”不是理想最终形态
- 说明：它只是防止 Main Agent 越权执行底层工具的保护。顶尖 Agent 的目标应该是：Main Agent 只做 delegation/merge/reflect；Specialist 内部再做局部 ReAct，并且只能看到自己的 `allowed_tools` 与 `ContextEnvelope`。

4) Guard reject 后回退执行 assigned tool 是错误方向
- 根因：这会把安全/契约错误变成“系统帮忙跑完”，导致开发期看不到真正的 planner 或 prompt 问题。

### 4. 已修复内容（含修复方式）

修复文件：
- `src/dl_op_to_hls/main_agent/llm_runtime.py`
- `src/dl_op_to_hls/llm/guards.py`
- `tests/test_llm_runtime_plan_validation.py`

关键修复点：
- `run-llm` 的计划验证失败后不再静默切到确定性 skill expansion，而是直接返回 `LLMGenerationError`，并带出 `last_plan` 供调试。
- specialist/tool 错配时直接拒绝，记录 `PermissionDeniedError`，不再把 specialist 清空后继续执行。
- ReAct 决策被 guard 拒绝时直接失败并记录结构化错误，不再自动执行 todo 的 assigned tool。
- plan validator 增加检查：`assigned_tool` 必须属于 `assigned_specialist.allowed_tools`。
- 增加测试覆盖 specialist-tool mismatch。

### 5. 当前仍未完成的问题

1) Main Agent 与 Specialist 的 ReAct 层级还需要进一步拆清
- 当前 Main Agent 仍会调用 LLM ReAct 判断每个 todo 的动作。
- 更好的设计是：Main Agent 对 specialist-owned todo 只允许 `delegate_to_specialist`、`mark_blocked`、`request_replan` 等高层动作；底层 `call_tool` 只出现在 Specialist 内部 ReAct。

2) Tool exposure 还需要分层
- 当前 planner 仍可能看到较多底层 tools。
- 下一步应按层级暴露能力：Main Agent 看 specialist/action schema；Specialist 看自己的 scoped tools；ToolRegistry 继续执行原子动作。

3) Specialist 内部 ReAct 还不够完整
- 目前部分 specialist 仍是确定性工具编排。
- 下一步需要让 specialist 在自己的 `ContextEnvelope` 和 `allowed_tools` 内执行局部 ReAct，同时保留可审计 trace。

### 6. 下一步建议

- 引入 Main Agent action schema：`delegate_to_specialist`、`direct_tool_only_when_no_specialist`、`request_replan`、`mark_blocked`、`mark_failed`。
- 将 planner prompt 的 tool 列表改为层级视图：Main Agent 不直接看到 specialist 私有 tool。
- 为每个 Specialist 增加本地 ReAct loop 测试：确保它只接收 `ContextEnvelope`，只调用 `allowed_tools`，只返回 `SpecialistResult`。

---

## 2026-06-01 12:07:04 +08:00｜LLM Agent Demo 全量失败排查与修复

### 1. 本次测试做了什么

工作目录（独立目录）：
- `D:\hls_agent\standalone_work\dl-op-to-hls-agent`

执行与验证：
- 检查运行配置：`python -m dl_op_to_hls.cli llm-status`
- 在真实环境下运行 `run-llm`（非 mock）：
  - hls4ml：已安装（`hls4ml 1.3.0`）
  - Vivado HLS：`D:\Xilinx\Vivado\2018.3\bin\vivado_hls.bat`
  - LLM API：`https://token-plan-sgp.xiaomimimo.com/v1`，模型 `mimo-v2.5-pro`
- 重跑 Demo0~Demo6，并生成汇总：
  - `runs/demo_rerun_after_fixes_final_20260601.json`
- 回归测试：
  - `python -m pytest tests/test_llm_runtime_plan_validation.py -q`（通过）

### 2. 发现的问题与根因

1) 独立目录权限问题（历史目录）
- 现象：`runs/` 目录不可写，导致数据库和运行产物无法创建。
- 根因：旧独立包目录 ACL/权限异常，写入被拒绝。

2) Specialist Todo 被 LLM “call_tool”分支绕开
- 现象：出现 `KeyError: 'model_path'` / `KeyError: 'hls_project_dir'`。
- 根因：带 specialist 的 todo 未强制走 specialist，导致工具入参由自由动作拼接，缺字段。

3) LLM 计划中 specialist 与 tool 错配
- 现象：如 `task.validate_schema` 被分配给 `HLS4MLSpecialist`，触发 `PermissionDeniedError`。
- 根因：计划校验未检查 “assigned_tool 是否在 assigned_specialist.allowed_tools 内”。

4) Guard 拒绝后直接失败
- 现象：一个 ReAct 决策不合法就直接 fail，流程中断。
- 根因：guard reject 没有兜底回退到确定性执行路径。

5) hls4ml convert/config 失败后仍继续 run_csim
- 现象：`hls4ml.run_csim` 缺 `hls_project_dir`，触发失败。
- 根因：context 未提供 `hls_project_dir`，且 specialist 没有“缺项目目录则跳过”的保护。

### 3. 已修复内容（含修复方式）

修复文件：
- `src/dl_op_to_hls/main_agent/llm_runtime.py`
- `src/dl_op_to_hls/main_agent/reflector.py`
- `src/dl_op_to_hls/main_agent/runtime.py`
- `src/dl_op_to_hls/llm/guards.py`
- `src/dl_op_to_hls/specialists/context.py`
- `src/dl_op_to_hls/specialists/hls4ml_specialist.py`

关键修复点：
- 对于命中 specialist 的 todo，优先走 specialist 执行路径，避免参数丢失。
- 增加 specialist-tool 一致性校验，阻止错配计划通过。
- guard 拒绝时回退到 todo 的确定性执行，不直接失败。
- 为 HLS4MLSpecialist 增加 `run_csim` 前置检查：缺 `hls_project_dir` 时标记 `skipped`（可恢复）。
- 将 hls4ml 可恢复失败（如 `HLS4MLConversionError`）转为 `completed_with_warning` 并触发 unsupported/boundary 分支。
- 优化状态汇总逻辑，避免 `initialized` 等异常终态残留。

### 4. 当前结果（修复后）

汇总文件：
- `runs/demo_rerun_after_fixes_final_20260601.json`

结果概览：
- Demo0 `dense_operator.json`：`partial_success`（fallback 路径可用）
- Demo1 `matmul_resource.json`：`partial_success`（fallback 路径可用）
- Demo2 `mnist_mlp_hls4ml.json`：`partial_success`
- Demo3 `mnist_tiny_cnn.json`：`partial_success`
- Demo4 `mnist_qkeras_cnn.json`：`partial_success`
- Demo5 `tiny_residual_block.json`：`partial_success`（boundary 预期）
- Demo6 `resnet18_boundary.json`：`partial_success`（boundary 预期）

### 5. 未完全修复项与原因

1) Demo2 未进入 full hls4ml success
- 原因：模型包含 `Gemm`，当前 hls4ml 转换链路报 `Unsupported operation type: Gemm`。

2) Demo3 未进入 full hls4ml success
- 原因：模型图包含 `Shape`，当前转换链路不支持该 op。

3) Demo4 未进入 full hls4ml/qkeras success
- 原因：`mnist_qkeras_cnn.h5` 与当前 onnx/hls4ml 解析链路不匹配，报 `Error parsing onnx.ModelProto`。

4) Demo6 保持 boundary/unsupported
- 原因：ResNet18 本身按任务书即为“边界/不承诺”演示目标，当前行为符合预期。

### 6. 下一步建议

- 为 Demo2/Demo3 增加稳定 graph rewrite（如 Gemm→MatMul+Add、Shape 消除/静态化）。
- 为 Demo4补齐“QKeras → 可转换 ONNX/hls4ml”导出流程（非占位 h5）。
- 将“boundary/unsupported”路径与“full success”路径分层展示，避免演示期望混淆。

---

