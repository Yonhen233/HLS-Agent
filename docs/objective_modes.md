# Objective Modes 设计说明

本项目把 HLS 设计目标显式抽象为 `ObjectiveMode`。这不是普通参数开关，而是 Agent 架构里的决策契约：它会影响 Planner 如何安排 Todo、Specialist 如何解释报告、LLM candidate 如何生成方案、ParameterAdvisor 如何推荐参数，以及 Finalizer 如何判断结果是否达成目标。

## 支持的模式

可以通过 CLI 查看当前支持的模式：

```powershell
dl-op-to-hls objective-modes
```

| Mode | 主要目标 | 路径偏好 | 验收重点 |
|---|---|---|---|
| `standard` | 稳定、可维护、可复现 | 优先 hls4ml，其次 fallback，LLM candidate 只在显式请求或 unsupported 时进入 | 转换成功、功能验证、综合报告完整 |
| `resource` | 最小化 LUT/FF/DSP/BRAM | 允许 verified LLM candidate 或 fallback 打败 hls4ml | golden CSim 通过，资源 fit，resource_score 改善 |
| `latency` | 最小化单次 inference cycles | hls4ml 做 baseline，LLM candidate 需要真实降低 latency | latency 改善，资源 fit，timing 可接受 |
| `throughput` | 最小化 II/top interval | 接受更高资源，但必须 fit 当前 FPGA | II 改善，资源 fit，不能只看 latency |
| `performance` | 同时优化 latency 和 II | 允许更激进的 LLM 架构搜索 | latency/II 加权得分改善，资源 fit |
| `balanced` | 资源预算内尽量提升性能 | 比较 hls4ml、fallback、verified LLM Pareto 点 | 满足资源预算，再比较 latency/II |

## 对 Agent 架构的影响

### Planner

`standard` 模式下，Planner 倾向于保持稳定的 hls4ml 主路径，不主动扩展 speculative LLM candidate Todo。

`resource / latency / throughput / performance / balanced` 模式下，Planner 可以在 baseline 综合后追加 candidate generation、verification、optimization comparison 等 Todo，因为这些模式需要比较 Pareto 点，而不是只跑通转换链路。

### Todo / ReAct

Todo 的目标解释会随 objective 改变。比如同样是 `Generate optimization suggestions`：

- `resource` 会把 DSP/LUT/BRAM 压缩作为主要 reason。
- `throughput` 会把 II/top interval 作为主要 observation。
- `balanced` 会要求 decision 同时说明资源预算和 latency/II trade-off。

### Specialist

Specialist 不直接决定全局成功，但它会根据 objective 改变局部判断：

- `VivadoSpecialist` 需要返回 latency、II、resources、resource_feasible，避免只看综合成功。
- `OptimizationSpecialist` 根据 objective 选择建议语言和排序标准。
- `VerificationSpecialist` 始终先验证功能正确，防止 LLM 为了资源或速度破坏 argmax。
- `MemorySpecialist` 保存 memory 时要记录 objective，否则 resource-first 经验可能污染 throughput 检索。

### ParameterAdvisor

`ParameterAdvisor` 会按 objective 排序历史 verified profiles：

- `resource`：优先低 resource score。
- `latency`：优先低 latency，再考虑 II 和资源。
- `throughput`：优先低 II，再考虑 latency 和资源。
- `performance`：latency 与 II 加权。
- `balanced`：资源预算与 latency/II 同时计分。
- `standard`：偏向稳定 baseline，不主动追求极端压缩或极端并行。

### LLM Candidate

LLM candidate 不能直接标记为成功。不同 objective 只改变候选生成方向，不改变验证门：

```text
objective prompt
CandidateSandbox
golden CSim
Vivado HLS csynth
report parser
objective_met check
```

也就是说，LLM 可以提出 resource-first 或 throughput-first 架构，但只有通过真实验证与资源可行性检查后，才会进入可复用结论。

## 为什么这是 Agent 能力

如果只是 workflow，系统会固定按一种路径执行；而 ObjectiveMode 让 Agent 在同一任务上根据目标选择不同策略：

- 同一 MNIST MLP，`standard` 选择 hls4ml baseline。
- `resource` 可以选择 verified serial shared-MAC LLM candidate。
- `throughput` 可以选择 verified feasible-throughput LLM candidate。
- `balanced` 会拒绝过慢的 serial 方案，也拒绝资源爆炸的高并行方案。

因此它体现的是目标驱动的决策能力，而不是简单 if-else 兜底。
