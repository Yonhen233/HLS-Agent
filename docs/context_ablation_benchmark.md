# 上下文压缩端到端消融 Benchmark

## 目标

该 Benchmark 将上下文管理拆成两个正交变量，并固定运行三组：

- A：`full + raw`
- B：`scoped + raw`
- C：`scoped + compressed`

生产默认值保持 C。A 与 B 衡量 Specialist 输入裁剪，B 与 C 衡量 SpecialistResult 压缩，A 与 C 衡量整体上下文管理方案。

## 公平性门禁

正式运行要求 tracked worktree 无修改，所有任务绑定同一 Git commit。每个 case/mode 使用独立 runs root 和由同一源 SQLite snapshot 复制出的私有数据库，关闭 mock、fixture、历史 verified implementation 复用与模板静默替代。三组保留相同模型、Prompt、工具、权限、重试和完成门禁，仅改变两个上下文变量。

`full` 模式保留 Specialist 原有必需字段契约，并额外提供完整 AgentState；它不会扩大 allowed tools。`raw` 模式只注入文本产物，二进制仍为引用。每次真实传递的 envelope、原始 SpecialistResult 和实际交付结果均写入当前 run 的 `context_telemetry/`。

## Token 口径

离线载荷统计必须显式传入 DeepSeek V4 官方 tokenizer 目录；加载失败立即终止，不使用 `字符数/4`。Tokenizer 来源、文件哈希、vocab 和 context limit 写入 `tokenizer_metadata.json`。

API 成本只采用 DeepSeek 响应 `usage`：prompt、completion、total、cache hit 和 cache miss。离线 tokenizer 数字与 API usage 分开报告。

## 运行

先确保 API key 只存在于环境变量，然后执行：

```powershell
$env:PYTHONPATH = "src"
$env:DL_OP_TO_HLS_LLM_API_KEY = "<secret>"
$env:DL_OP_TO_HLS_LLM_BASE_URL = "https://api.deepseek.com"
$env:DL_OP_TO_HLS_LLM_MODEL = "deepseek-v4-pro"
$env:DL_OP_TO_HLS_VIVADO_HLS_PATH = "D:\Xilinx\Vivado\2018.3\bin\vivado_hls.bat"

python -m dl_op_to_hls.cli context-ablation-benchmark `
  --tokenizer-path "D:\model_assets\deepseek-v4-pro-tokenizer" `
  --smoke
```

冒烟通过后去掉 `--smoke` 执行 12 个任务、36 个首次配对运行。运行顺序按 ABC/BCA/CAB 轮换。结果目录不会覆盖历史 Benchmark。

## 输出

每次实验输出 manifest、environment、tokenizer metadata、raw runs、trace 副本、机器结果、Markdown 报告和简历结论。二分类使用配对 discordant counts 与 exact McNemar；Token/耗时使用配对中位数差和 bootstrap 95% CI。小样本必须按低统计功效解释。

## 严格结论门槛

只有 C 相比 A 的完成率下降不超过 5 个百分点、false-success 为 0、关键约束保留率为 100%、验证证据不降低且输入 Token 明确下降时，才能写“降低 Token 且未降低执行效果”。否则报告必须列出受损任务，不能只选择最好的一次。
