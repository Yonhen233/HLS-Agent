# DL-to-HLS Agent

用自然语言描述需求，将深度学习算子、模型或已有 C++ 工程交给 Agent，完成 HLS 代码生成、功能仿真、综合和结果分析。

你可以让它生成 HLS 工程、检查输出是否符合参考结果，也可以根据综合报告继续调整资源占用、延迟和吞吐率。每次任务的代码、测试文件、日志和报告都会保存在本地，方便查看和继续使用。

## 开始前的准备

- Python 3.11 或更高版本。
- 一个 OpenAI-compatible 大模型 API 的地址、模型名称和 API Key。
- 已安装的 Vivado HLS 或 Vitis HLS，用于运行仿真和综合。

下面的安装和运行示例使用 Windows PowerShell。建议在项目根目录运行命令。

## 安装

```powershell
git clone https://github.com/Yonhen233/HLS-Agent.git
cd HLS-Agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

如果需要处理 ONNX/QONNX 模型，再安装模型转换依赖：

```powershell
python -m pip install -e ".[real-toolchain]"
```

## 配置服务

### 大模型 API

将以下示例中的地址、模型名称和密钥替换为你自己的配置：

```powershell
$env:DL_OP_TO_HLS_LLM_ENABLED="1"
$env:DL_OP_TO_HLS_LLM_PROVIDER="openai-compatible"
$env:DL_OP_TO_HLS_LLM_BASE_URL="https://your-endpoint/v1"
$env:DL_OP_TO_HLS_LLM_MODEL="your-model"
$env:DL_OP_TO_HLS_LLM_API_KEY="your-api-key"
```

Base URL 按服务商提供的地址填写。查看程序读取到的配置：

```powershell
dl-op-to-hls llm-status
```

### HLS 工具

使用 Vivado HLS 2018.3 时，填写本机的可执行文件路径：

```powershell
$env:DL_OP_TO_HLS_HLS_TOOLCHAIN="vivado_hls"
$env:DL_OP_TO_HLS_VIVADO_HLS_PATH="D:\Xilinx\Vivado\2018.3\bin\vivado_hls.bat"
```

使用 Vitis HLS 时，改用对应配置：

```powershell
$env:DL_OP_TO_HLS_HLS_TOOLCHAIN="vitis_hls"
$env:DL_OP_TO_HLS_VITIS_HLS_PATH="D:\Vitis2022.2\bin\vitis_hls.bat"
```

这些环境变量在当前 PowerShell 窗口中有效。以后打开新窗口时，可以重新设置，或通过 Windows 用户环境变量保存常用配置。

## 方式一：直接对话

启动交互式命令行：

```powershell
dl-op-to-hls chat --real-tools
```

像描述任务一样输入你的需求，例如：

```text
> 把 Dense 16x32 转成 HLS，使用 ap_fixed<16,6>，目标器件 xc7z020clg400-1，时钟周期 10ns，优先降低资源占用。
> 查看这次的功能仿真和综合结果。
> 根据当前结果，分析降低 DSP 占用的方法。
> /status
> /exit
```

描述任务时，提供算子或模型、输入输出尺寸、目标器件、时钟周期，以及你最关心的优化目标，可以帮助 Agent 更准确地执行。

输入 `/help` 查看聊天命令，`/status` 查看当前会话，`/exit` 退出。

## 方式二：运行任务文件

如果希望保存配置、重复执行任务，可以使用 JSON 文件：

```powershell
dl-op-to-hls agent-run examples\dense_operator.json --real-tools
```

下面是一个 Dense 算子任务：

```json
{
  "task_type": "operator",
  "op_type": "Dense",
  "name": "dense_16x32",
  "input_shape": [16],
  "output_shape": [32],
  "dtype": "ap_fixed<16,6>",
  "target": {
    "backend": "VivadoHLS",
    "part": "xc7z020clg400-1",
    "clock_period": 10
  },
  "optimization": {
    "objective": "resource",
    "reuse_factor": 1,
    "pipeline_ii": 1
  }
}
```

| 配置项 | 填写内容 |
|---|---|
| `op_type` | 算子名称，例如 Dense、MatMul、ReLU 或 Add |
| `input_shape` / `output_shape` | 输入与输出尺寸 |
| `dtype` | 数据精度，例如 `ap_fixed<16,6>` 表示 16 位定点数，其中整数部分占 6 位 |
| `part` | 目标 FPGA 器件型号 |
| `clock_period` | 目标时钟周期，单位为 ns |
| `objective` | 优化目标，例如 `resource` 或 `latency` |
| `reuse_factor` | 运算单元复用配置 |
| `pipeline_ii` | 期望的流水线启动间隔，单位为周期 |

模型任务通过 `model_path` 指定模型文件；已有 HLS 工程通过 `hls_project_dir` 和 `top_function` 指定工程目录与顶层函数。可以参考以下任务文件修改：

| 任务 | 示例文件 |
|---|---|
| Dense 算子 | [dense_operator.json](examples/dense_operator.json) |
| MatMul 资源优化 | [matmul_resource.json](examples/matmul_resource.json) |
| ONNX MLP 模型 | [mnist_mlp_hls4ml.json](examples/mnist_mlp_hls4ml.json) |
| MNIST 数字识别 | [mnist_recognition_mlp.json](examples/mnist_recognition_mlp.json) |
| 已有 HLS 工程 | [existing_hls_project.json](examples/existing_hls_project.json) |

运行模型任务前，请确认任务中的模型路径指向你要使用的模型和权重。

## 查看代码和结果

每次运行的结果保存在 `runs/<run_id>/`。建议先打开 `summary.md` 了解任务结果，再查看 `suggestions.md` 中的优化建议。

```powershell
dl-op-to-hls report runs\<run_id>
dl-op-to-hls suggest runs\<run_id>
```

| 文件或目录 | 你可以看到什么 |
|---|---|
| `summary.md` | 本次任务、执行结果和生成文件位置 |
| `suggestions.md` | 根据本次结果给出的优化建议 |
| `report.json` | 延迟、II、资源占用和时序等综合结果 |
| `artifacts.json` | 本次生成的文件清单，可用于找到 HLS 工程和测试文件 |
| `todos.json` | 任务步骤及完成状态 |
| `trace.jsonl` | 详细执行记录，便于检查出错阶段 |

结果中的 latency 表示处理延迟，II 表示连续启动计算的间隔；DSP、BRAM、LUT 和 FF 分别反映计算与存储等硬件资源占用，timing 反映目标时钟的满足情况。

## 继续之前的任务

查看已有会话：

```powershell
dl-op-to-hls session-list
```

重新进入某个会话，继续补充需求：

```powershell
dl-op-to-hls chat --session-id <session_id> --real-tools
```

恢复未完成任务：

```powershell
dl-op-to-hls session-resume <session_id>
```

查看历史运行记录：

```powershell
dl-op-to-hls db-list-runs
```

## 查找历史经验

你可以查询以前保存的实现与优化经验，为下一次任务提供参考：

```powershell
dl-op-to-hls memory-search "Dense 降低 DSP 占用"
dl-op-to-hls rag-search "Dense reuse factor latency"
```

## 命令帮助

```powershell
dl-op-to-hls --help
dl-op-to-hls chat --help
dl-op-to-hls agent-run --help
```
