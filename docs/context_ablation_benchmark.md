# 上下文压缩端到端消融 Benchmark

## 长时运行断点恢复

真实 LLM 加 Vivado 的评测可能持续数小时。外部进程中断后，可使用完全相同的 output directory、execution root 和 `--resume` 恢复。恢复以 pair 为原子单位：只接受 `context_ablation_results.partial.json` 中完整存在且均有效的 A/B/C 三元组；只完成一个或两个模式的中断尝试会隔离为 `interrupted_incomplete_pair`，整组重新执行。

首次启动只保存一份 `memory_snapshot.db`，所有隔离 Run 的数据库都从该不可变 snapshot 复制。恢复时强制核对 Git commit、context modes、模型、base URL、tokenizer hash、trial 数、重试上限、Run timeout、execution root 及 memory snapshot hash；任一字段变化都会拒绝继续。成功恢复记录在 `resume_history.json`。

```powershell
dl-op-to-hls context-ablation-benchmark `
  --execution-root D:\ca_eval `
  --output-dir runs\benchmarks\context_ablation_fixed_example `
  --tokenizer-path D:\model_assets\deepseek-v4-pro-tokenizer `
  --trials 3 --max-pair-attempts 10 --resume
```

Resume 不会合并不同实验，也不会从无效 pair 中挑选单个成功模式。

## 目标

该 Benchmark 将上下文管理拆成两个正交变量，并固定运行三组：

- A：`full + raw`
- B：`scoped + raw`
- C：`scoped + compressed`

生产默认值保持 C。A 与 B 衡量 Specialist 输入裁剪，B 与 C 衡量 SpecialistResult 压缩，A 与 C 衡量整体上下文管理方案。

## 公平性门禁

正式运行要求 tracked worktree 无修改，所有任务绑定同一 Git commit。真实 HLS 工程使用 `--execution-root` 指定的短绝对路径；报告仍写在项目 `runs/benchmarks/`。每个 case/trial/mode 使用唯一 Run ID 和由同一源 SQLite 快照复制出的私有数据库，关闭 mock、fixture、历史 verified implementation 复用与模板静默替代。三组保留相同模型、Prompt、工具、权限、重试和完成门禁，仅改变两个上下文变量。

启动 Vivado 前会预估最深内部路径；超过 200 字符时以 `EvaluationConfigurationError` 拒绝启动，不计为 Agent 或 HLS 失败。

`full` 模式保留 Specialist 原有必需字段契约，并额外提供完整 AgentState；它不会扩大 allowed tools。`raw` 模式只注入文本产物，二进制仍为引用。每次真实传递的 envelope、原始 SpecialistResult 和实际交付结果均写入当前 run 的 `context_telemetry/`。

## Token 口径

离线载荷统计必须显式传入 DeepSeek V4 官方 tokenizer 目录；加载失败立即终止，不使用 `字符数/4`。Tokenizer 来源、文件哈希、vocab 和 context limit 写入 `tokenizer_metadata.json`。

API 成本只采用 DeepSeek 响应 `usage`：prompt、completion、total、cache hit 和 cache miss。离线 tokenizer 数字与 API usage 分开报告。

## 运行

先确保 API key 只存在于环境变量，然后执行：

```powershell
$env:PYTHONPATH = "src"
$env:DL_OP_TO_HLS_LLM_API_KEY = "<secret>"
$env:DL_OP_TO_HLS_LLM_BASE_URL = "<openai-compatible-base-url>"
$env:DL_OP_TO_HLS_LLM_MODEL = "DeepSeek-V4-Pro"
$env:DL_OP_TO_HLS_VIVADO_HLS_PATH = "D:\Xilinx\Vivado\2018.3\bin\vivado_hls.bat"

python -m dl_op_to_hls.cli context-ablation-benchmark `
  --tokenizer-path "D:\model_assets\deepseek-v4-pro-tokenizer" `
  --execution-root "D:\ca_eval_smoke" `
  --smoke
```

冒烟只运行 Add 的 A/B/C 三组，必须同时通过真实 API、Golden CSim、真实 CSynth、完成门禁、100% 约束保留、当前 Run 证据、唯一 Run ID 和短路径门禁。

冒烟通过后去掉 `--smoke`，使用新的空短目录执行正式实验：

```powershell
python -m dl_op_to_hls.cli context-ablation-benchmark `
  --tokenizer-path "D:\model_assets\deepseek-v4-pro-tokenizer" `
  --execution-root "D:\ca_eval" `
  --trials 3
```

正式实验固定为 12 个任务 × 3 个模式 × 3 个 trial = 108 个有效运行；trial 顺序依次为 ABC、BCA、CAB。禁止选择性复测。若任一模式发生 429、5xx、网络或 API 超时，当前 A/B/C 配对整体作废并完整补跑；402 立即停止整个 Benchmark。

## 输出

每次实验输出 manifest、environment、tokenizer metadata、短路径 raw-run 索引、无效运行清单、机器结果、Trace 分歧归因、Markdown 报告和简历结论。二分类使用配对 discordant counts 与 exact McNemar；Token/耗时使用配对中位数差和 bootstrap 95% CI。支持任务与正确拒绝任务分开统计。

Golden CSim 由当前 Run 的退出状态和 `GOLDEN_CHECK_PASSED` 日志哈希独立判断；后续 CSynth 失败不会覆盖已经通过的 CSim。真实 CSynth 要求当前 Run 启动综合、成功退出、生成可解析报告且 SHA256 有效。

## 严格结论门槛

只有 C 相比 A 的完成率下降不超过 5 个百分点、false-success 为 0、关键约束保留率为 100%、验证证据不降低且输入 Token 明确下降时，才能写“降低 Token 且未降低执行效果”。否则报告必须列出受损任务，不能只选择最好的一次。
