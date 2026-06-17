# MNIST 真实识别 Demo 与面试讲解笔记

本文整理 `mnist_recognition_mlp` 真实 demo 的完整工作流、设计取舍、面试官可能追问的问题，以及推荐回答方式。

这个 demo 的核心价值是：它不只是“生成了一个 HLS 工程”，而是证明了一个训练过的 MNIST 模型经过 hls4ml 和 Vivado HLS 后，生成的 HLS C simulation 结果仍然能完成数字识别。

---

## 1. Demo 一句话介绍

`mnist_recognition_mlp` 是一个真实 MNIST 数字识别到 HLS 的端到端演示：

```text
训练好的 MNIST MLP
  -> 导出 ONNX
  -> Agent 检查模型与选择 hls4ml_path
  -> hls4ml / ONNX layer-list adapter 生成 HLS 工程
  -> Vivado HLS 2018.3 跑 csim + csynth
  -> 比较 HLS 输出与 ONNX reference
  -> 统计识别准确率、argmax match、综合资源和 timing
```

对应任务文件：

```text
examples/mnist_recognition_mlp.json
```

成功运行目录：

```text
runs/mnist_recognition_mlp_234d539d
```

---

## 2. 为什么要单独做 MNIST 真实识别 demo

之前已有 `mnist_mlp_hls4ml.json`、`mnist_tiny_cnn.json`、`mnist_qonnx_cnn.json` 等模型 demo，但这些更多是“模型结构 / 工具链验证”：

- 脚本生成的是随机初始化模型。
- 输入 reference 也偏向随机数据或工具链样本。
- 能证明 hls4ml / Vivado HLS 流程跑通。
- 不能诚实证明 HLS 代码真的会识别数字。

而一个经典 MNIST 识别 demo 至少要满足：

- 有训练好的权重。
- 有真实 MNIST 测试样本。
- 有 label。
- 能比较 HLS 输出和 Python/ONNX reference。
- 能统计分类准确率。
- 能给出 Vivado HLS 综合指标。

所以这次新增了：

```text
scripts/train_mnist_recognition_mlp.py
examples/mnist_recognition_mlp.json
models/mnist_recognition/*
```

---

## 3. 本次真实结果

训练模型：

```text
Architecture: MLP(784,64,32,10)
Epochs used: 2
Eval samples: 5000
Best eval accuracy: 91.76%
HLS reference samples: 20
Python/ONNX reference accuracy on 20 samples: 95%
```

真实 Vivado HLS run：

```text
Run ID: mnist_recognition_mlp_234d539d
Status: success
Selected path: hls4ml_path
Pipeline level: deployment_ready_candidate
Functional verified: true
Timing met: true
```

综合结果：

| 指标 | 结果 |
|---|---:|
| Latency min/max | 1234 / 1237 cycles |
| II min/max | 1234 / 1237 |
| BRAM | 48 |
| DSP | 133 |
| FF | 21275 |
| LUT | 31792 |
| Target clock | 10.0 ns |
| Estimated clock | 8.237 ns |
| Timing met | true |

识别验证结果：

| 指标 | 结果 |
|---|---:|
| Samples | 20 |
| Python/ONNX reference accuracy | 95% |
| HLS csim accuracy | 95% |
| HLS vs ONNX argmax match rate | 100% |
| HLS correct predictions | 19 / 20 |
| Numeric max abs error | 8.173832 |
| Numeric tolerance | 0.25 |
| Numeric pass | false |
| Recognition pass | true |

关键解释：

```text
HLS logits 数值误差较大，但分类 argmax 与 ONNX 完全一致，因此识别语义通过。
```

---

## 4. 这次走的是什么路径，有没有用 LLM

这次 demo 走的是确定性路径：

```text
deterministic run
  -> hls4ml_path
  -> ONNX layer-list adapter
  -> Vivado HLS 2018.3
  -> recognition-aware functional verification
```

没有启动 LLM。

执行命令是：

```powershell
python -m dl_op_to_hls.cli run examples/mnist_recognition_mlp.json
```

不是：

```powershell
python -m dl_op_to_hls.cli run-llm ...
```

最终 state 中：

```json
"llm_decisions": []
```

这说明没有真实 LLM 调用。

---

## 5. 没用 LLM 为什么仍然是 Agent demo

这是一个很重要的面试点。

这个 demo 没有调用 LLM，但仍然用到了 Agent 框架的大量核心能力：

| 模块 | 在 MNIST demo 中的作用 |
|---|---|
| Main Agent | 读取任务，维护全局状态，选择路径 |
| Planner | 生成 validate / inspect / support / convert / synth / summary / memory 的计划 |
| TodoList | 把任务拆成 `todo_001` 到 `todo_010` |
| Plan-Execute-ReAct Runtime | 每个 Todo 记录 reason / action / observation / decision |
| Specialist Sub-agent | HLS4MLSpecialist / VivadoSpecialist / OptimizationSpecialist / MemorySpecialist |
| ContextEnvelope | Specialist 只接收裁剪上下文，不直接吃完整 state/log/code |
| ToolRegistry | hls4ml / Vivado / summary / memory 工具统一注册和调用 |
| Artifact Manager | 管理 HLS project、report、reference data、summary、trace |
| Trace System | 记录 Run、Todo、Tool、Specialist 生命周期 |
| AgentState | 保存 state.json，支持复盘和恢复 |
| hls4ml Adapter | 将 ONNX Gemm/Relu 转成 hls4ml layer-list |
| Vivado Adapter | 调用真实 Vivado HLS 2018.3，跑 csim/csynth |
| Functional Verification | 比较 HLS 输出和 ONNX reference，统计 accuracy |
| Report Parser | 解析 latency、II、DSP、BRAM、LUT、FF、timing |
| Memory Layer | 提升 verified implementation、parameter experience、optimization memory |
| ParameterAdvisor | 用历史 verified memory 推荐 precision/reuse_factor/clock |

推荐回答：

> 这个 demo 没有启用 LLM，是为了展示 Agent 框架的确定性工程能力。它不是普通脚本，而是完整使用了 Planner、TodoBoard、Specialist、ToolRegistry、Artifact/Trace、functional verification、report parsing、memory 和 ParameterAdvisor。LLM 是用于不确定路径和生成路径的增强模块，不是整个 Agent 的唯一核心。

---

## 6. 网上下载的预训练模型为什么没有作为主 demo

本轮下载了外部预训练 MNIST ONNX：

```text
models/pretrained_external/mnist-8.onnx
```

它来自 ONNX Model Zoo / Hugging Face，输入为：

```text
1 x 1 x 28 x 28
```

输出为：

```text
1 x 10 logits
```

它是一个 CNN，包含：

```text
Conv / MaxPool / Reshape / MatMul / Add / Relu
```

它不是不能用，而是不适合作为当前第一版稳定 HLS 演示主路径。

原因：

- 它是 CNN，涉及 Conv、MaxPool、Reshape、layout 等更多 frontend 兼容问题。
- 它是老 opset 模型，权重暴露方式比较特殊。
- 当前 hls4ml 1.3.0 + Vivado HLS 2018.3 + 本项目 adapter 对静态 MLP 更稳定。
- 面试演示第一目标是证明“真实识别任务端到端跑通”，不是先攻克 CNN frontend 兼容性。

自己训练的 MLP 的优势：

- 真实 MNIST 权重，不是随机模型。
- 输入 `784`，结构简单。
- ONNX 图只有 `Gemm + Relu`。
- 正好映射到 hls4ml 的 Dense / Activation。
- reference input、label、accuracy、HLS csim 验证全都可控。

推荐回答：

> 网上预训练模型不是不能用，而是它的图结构和导出格式不一定 HLS 友好。我的目标是先做一个稳定、可复现、真实识别的端到端 demo，所以选择自己训练一个 HLS-friendly MLP。这样模型是真实训练的，识别任务是真实的，同时转换路径也足够稳定。后续如果要展示 CNN，可以再把外部 `mnist-8.onnx` 作为 CNN adapter 的攻关目标。

---

## 7. HLS logits 是什么

`logits` 是神经网络最后一层输出的原始分类分数。

MNIST 有 10 类，因此输出是长度为 10 的向量：

```text
logits[0] -> 数字 0 的分数
logits[1] -> 数字 1 的分数
...
logits[9] -> 数字 9 的分数
```

分类时通常取最大值的位置：

```text
prediction = argmax(logits)
```

例如：

```text
logits = [-1.2, 0.3, 7.8, 1.1, ...]
argmax = 2
预测数字 = 2
```

`HLS logits` 就是 Vivado HLS C simulation 跑出来的 HLS C++ 模型输出分数。

`ONNX logits` 是 Python/ONNXRuntime 跑出来的 reference 输出分数。

---

## 8. 为什么 logits 数值漂移较大但 argmax 稳定

本次结果：

```text
max_abs_error = 8.173832
numeric_passed = false
argmax_match_rate = 100%
hls_accuracy = 95%
recognition_passed = true
```

这说明：

- 每个类别的原始分数和浮点 ONNX 有明显差别。
- 但 10 个类别里面最大值的位置没有变。
- 所以最终预测数字没有变。

例子：

```text
ONNX logits: [0.1, 8.0, 2.0]
HLS logits:  [0.0, 3.5, 1.1]
```

数值差很多，但最大值都是第 1 类，因此分类结果一致。

漂移原因：

- HLS 使用 `fixed<12,6>` 定点数，而不是 float32。
- 定点数有舍入、截断、饱和。
- 乘加顺序和浮点运行时不同。
- hls4ml 的层实现和 ONNXRuntime 的数值实现也不完全一致。

为什么还可以接受：

- 对分类任务，最核心的是 argmax 是否正确。
- 只要正确类别仍然分数最高，识别语义就是正确的。
- 但 numeric drift 仍然被保留在 summary 中，不能被隐藏。

推荐回答：

> 我没有把 numeric error 和 classification correctness 混为一谈。对于分类模型，我同时报告 logits 数值误差和 argmax/accuracy。这个 demo 里 fixed-point logits 漂移较大，但 HLS 与 ONNX 的 argmax 完全一致，HLS 对 20 个样本的识别准确率是 95%。所以它通过的是 recognition verification，而不是严格逐值 numeric verification。

---

## 9. Summary 是不是为这个 demo 写死的

不是。

本次改的是通用 summary 扩展：

```text
如果 verification 里有 classification 字段，
则额外显示 Recognition samples / accuracy / argmax match。
```

如果换成普通算子 demo：

- Dense
- MatMul
- ReLU
- Add

这些没有 label，也没有 classification 字段，summary 仍然显示原来的：

```text
golden testbench verification
numeric result
csynth report
latency/resources/timing
```

如果换成普通模型 demo，没有 classification data，也不会显示 MNIST accuracy。

所以逻辑是通用的：

```text
operator demo -> golden verification
model demo -> hls4ml reference compare
classification model demo -> reference compare + accuracy/argmax
```

推荐回答：

> Summary 不是为 MNIST 硬编码的。我只是让 verification schema 支持 classification metrics。只要某个任务提供 label 和 classification reference，summary 就会显示识别指标；否则仍然显示原来的 numeric verification 和 synthesis metrics。

---

## 10. 哪些是写死 workflow，哪些体现 Agent 决策能力

这是面试官最可能追问的问题之一。

### 10.1 写死的是工程流程骨架

HLS 工作流本身阶段性很强，因此这些阶段是确定性骨架：

```text
validate task
inspect model
check support
generate config / convert
run csim / csynth
parse report
write summary
promote memory
```

这些不应该每次交给 LLM 或自由策略重新发明。

推荐说法：

> 我把 HLS 工作流中确定性强、必须执行的阶段固化成 workflow skeleton，这保证了可复现、可追踪和可恢复。

### 10.2 Agent 决策能力体现在状态驱动的路径选择

MNIST demo 中的真实决策点：

```text
1. hls4ml 原生 ONNX parser 报 Gemm unsupported。
2. Agent 判断 ONNX layer-list adapter 可以处理 Gemm + Relu。
3. 系统继续走 hls4ml_path，而不是失败或 fallback。
4. ParameterAdvisor 从 verified memory 选择 fixed<12,6> + reuse_factor=512 + 10ns。
5. Verification 发现 numeric drift 大，但 classification argmax/accuracy 达标。
6. Agent 将结果标记为 recognition_passed 和 deployment_ready_candidate。
7. MemorySpecialist 将 verified implementation 和 parameter experience 写入长期记忆。
```

这不是单个 if-else 脚本，因为它依赖：

- tool observation
- specialist result
- report metrics
- verification result
- memory retrieval
- pipeline status policy
- artifact refs
- todo dependency

### 10.3 推荐回答

> 这个系统不是纯 LLM 自由发挥，也不是普通 if-else 脚本。我把它设计成“确定性工作流骨架 + Agent 决策点 + 工具验证闭环”。写死的是安全边界和工程流程；Agent 化的是状态驱动的路径选择、工具编排、失败恢复、经验复用和验证闭环。

如果面试官继续问：

> 那不还是 if-else 吗？

可以答：

> 工程 Agent 里有规则分支是正常的，关键是这些分支不是孤立脚本判断，而是挂在 Todo、Trace、SpecialistResult、Artifact、Report、Verification 和 Memory 上。每一步都有 observation、结构化状态和可复盘证据。这个系统更接近 workflow agent / tool-using agent，而不是一次性脚本。

---

## 11. 没用 LLM 的启发

MNIST demo 成功但没用 LLM，反而是一个亮点。

它说明这个项目不是“LLM wrapper”，而是一个可靠的工程 Agent runtime。

核心原则：

```text
LLM handles ambiguity.
Tools handle facts.
Workflow handles guarantees.
Verification decides trust.
```

含义：

- 能确定的，不交给 LLM 猜。
- 需要领域工具的，交给 Tool/Specialist。
- 需要开放推理和生成的，才启用 LLM。
- LLM 生成的东西必须经过验证，不能直接信任。

推荐回答：

> 对于 MNIST 这种路径清晰、工具链支持明确的任务，我优先走 deterministic specialist workflow，保证可复现和可验证。LLM 主要用于 unsupported operator、candidate HLS generation、repair、复杂优化解释等开放问题，而不是主干路径的必要条件。

---

## 12. LLM 在这个项目中什么时候有用

LLM 不参与本次 MNIST 主路径，但在以下场景有价值：

```text
1. hls4ml 不支持某个算子时，生成 graph rewrite 或 custom layer 建议。
2. 没有 fallback template 时，生成 candidate HLS C++。
3. candidate 验证失败时，根据 csim/log/report 做 repair。
4. 复杂 report 解释和优化建议生成。
5. 用户自然语言任务到结构化 task JSON 的转换。
6. 多方案权衡，例如 latency/resource/timing trade-off。
```

项目里已经有 LLM candidate 路径的真实测试：

```text
Dense / MatMul / ReLU / Add / ScaleShift LLM candidate
DeepSeek-V4-Pro
Vivado HLS 2018.3
golden csim + csynth
```

所以推荐表达：

> LLM 是不确定路径和生成路径的增强能力，不是 deterministic path 的替代品。主干流程能不用 LLM 跑通，说明系统有工程可靠性；异常路径能用 LLM 生成和修复，说明系统有弹性。

---

## 13. 这个 demo 展示了哪些 Agent 工程能力

可以按这几个层次讲：

### 13.1 Tool-use Agent

所有底层动作都通过 ToolRegistry：

```text
hls4ml.inspect_model
hls4ml.check_support
hls4ml.generate_config
hls4ml.convert
vivado.run_csynth
vivado.parse_report
summary.write_summary
memory.promote_to_long_term
```

### 13.2 Specialist Agent

领域隔离：

```text
HLS4MLSpecialist -> 模型检查、support、config、convert
VivadoSpecialist -> project、csim、csynth、report
OptimizationSpecialist -> suggestions
MemorySpecialist -> memory promotion
```

Main Agent 不直接吞 raw Vivado log、HLS C++、csynth report。

### 13.3 Verification Agent

不是“工具返回 success 就相信”，而是检查：

```text
csim 是否执行
HLS 输出文件是否存在
ONNX reference 是否存在
numeric drift
classification accuracy
argmax match
timing met
```

### 13.4 Memory-aware Agent

本次 run 结束后 promotion：

```text
episodic memory
verified_implementation
parameter_experience
optimization memory
skills
```

ParameterAdvisor 使用历史 verified memory 推荐：

```text
precision = fixed<12,6>
reuse_factor = 512
clock_period = 10
```

---

## 14. 面试官可能追问与推荐回答

### Q1：为什么不用更复杂的 CNN，MLP 会不会太简单？

推荐回答：

> 这是第一版真实识别闭环，我优先选择 HLS-friendly MLP 来证明端到端链路：训练权重、ONNX、hls4ml、Vivado csim/csynth、accuracy、report、memory 全部打通。CNN 不是不能做，而是会引入 layout、Conv/Pool adapter、资源爆炸和版本兼容问题。工程上应该先建立稳定 verified baseline，再扩展 CNN。

### Q2：20 个样本是不是太少？

推荐回答：

> 20 个样本用于 Vivado HLS csim 的快速演示，因为 HLS 仿真很慢。训练评估用了 5000 个样本，准确率 91.76%。后续可以把 Python/ONNX accuracy 扩展到 10000 个测试样本，而 HLS csim 保持 20/100 个 representative samples 来控制演示时间。

### Q3：为什么 numeric error 很大还算通过？

推荐回答：

> 我没有把它算作 numeric pass。summary 明确显示 numeric_passed=false、max_abs_error=8.17。它通过的是 recognition verification，因为 HLS 和 ONNX 的 argmax 完全一致，HLS accuracy 达到 95%。分类任务最终关心类别预测，数值漂移仍然作为优化风险保留。

### Q4：这个 demo 是否能上板？

推荐回答：

> 当前项目边界是不生成 bitstream、不做上板验证。这个 demo 达到的是 deployment_ready_candidate：HLS conversion 成功、csim 功能验证通过、csynth 成功、timing met。上板还需要 AXI interface、IP packaging、Vivado block design、bitstream 和板端驱动，这属于下一阶段。

### Q5：Agent 失败时会不会乱 fallback？

推荐回答：

> 现在区分开发期和演示期。主路径不会静默吞掉错误；unsupported、verification failed、Vivado missing 都会写 structured error、trace 和 summary。本次 MNIST 第一轮就暴露了 numeric verification failed，系统没有伪造成功，而是促使我们增加 classification-aware verification。

### Q6：为什么 hls4ml 原生不支持 Gemm，你们还能跑？

推荐回答：

> hls4ml 1.3.0 的原生 ONNX parser 对 Gemm 支持有限。我们没有直接绕过 hls4ml，而是在 adapter 层把静态 ONNX Gemm/Relu 图转换成 hls4ml layer-list，对应 Dense/Activation，然后仍然用 hls4ml ModelGraph 生成 HLS 工程。这是工程化 frontend adapter，不是完整 ONNX compiler。

### Q7：这个 adapter 是完整 ONNX compiler 吗？

推荐回答：

> 不是。它是窄范围工程 adapter，支持静态 MLP/CNN 的常见模式，比如 Gemm->Dense、Relu->Activation、部分 Conv/Pool/layout 处理。它的定位是让 Agent 能识别支持边界，能跑通明确范围内的模型，不盲目承诺任意 ONNX。

### Q8：如果换 PyTorch 模型怎么办？

推荐回答：

> 长远路径是 PyTorch -> ONNX/QONNX -> hls4ml。PyTorch 负责训练和导出，ONNX 作为中间表示，Agent 负责检查、rewrite、adapter、HLS conversion 和 verification。这样比直接 PyTorch->hls4ml 更可扩展，也更容易做 frontend 边界控制。

### Q9：ParameterAdvisor 是不是写死参数？

推荐回答：

> 不是纯写死。它优先读取 verified memory，也就是之前 csim/csynth/timing 都通过的 run。如果有相似任务，会推荐历史成功参数；没有历史时才用 heuristic bootstrap。MNIST 这次使用 `fixed<12,6> + reuse_factor=512 + 10ns`，是来自历史 verified run 的经验。

### Q10：这个项目和普通 pipeline 脚本最大的区别是什么？

推荐回答：

> 普通 pipeline 脚本通常只顺序执行命令。这个项目有 AgentState、TodoBoard、Specialist、ContextEnvelope、ToolRegistry、Trace、Artifact、Structured Error、Memory、RAG 和 verification-aware status。每一步都有可观测状态和可恢复证据，工具结果会影响后续路径，成功也由 csim/csynth/report/accuracy 证明，而不是脚本跑完就算成功。

---

## 15. 简历表述建议

可以写成：

```text
构建 DL-Operator-to-HLS Agent：面向 FPGA HLS 工作流的 tool-using Agent，支持 hls4ml/Vivado HLS 工具编排、Todo-driven Plan-Execute-ReAct runtime、Specialist Sub-agent、Artifact/Trace、SQLite Memory/RAG 和 verification-aware status。
```

MNIST demo 可写：

```text
实现真实 MNIST recognition-to-HLS demo：训练 MLP(784,64,32,10)，导出 ONNX，通过 hls4ml adapter 转换为 HLS 工程，并在 Vivado HLS 2018.3 上完成 csim/csynth；HLS csim accuracy 95%，ONNX/HLS argmax match 100%，timing met，latency 1237 cycles。
```

Agent 工程亮点可写：

```text
设计 classification-aware functional verification，将 numeric drift 与 recognition correctness 解耦；在 fixed-point logits 数值漂移较大时，通过 label accuracy 和 argmax match 判定分类语义是否保持，同时保留数值误差用于后续优化。
```

决策能力可写：

```text
通过 hls4ml support probing、ONNX layer-list adapter、ParameterAdvisor verified-memory retrieval 和 structured verification status，实现确定性 workflow 与 Agent 决策点结合，避免 LLM 在确定性 EDA 流程中不必要地引入不稳定性。
```

---

## 16. 建议演示顺序

推荐面试演示顺序：

1. 展示 `examples/mnist_recognition_mlp.json`，说明输入是训练好的 ONNX 和真实 MNIST reference data。
2. 打开 `scripts/train_mnist_recognition_mlp.py`，说明模型是自己训练的，不是随机权重。
3. 运行或展示已完成 run：

```text
runs/mnist_recognition_mlp_234d539d/summary.md
```

4. 强调四个结果：

```text
HLS csim accuracy = 95%
argmax match = 100%
timing met = true
deployment_ready_candidate = true
```

5. 打开 `trace.jsonl` / `todos.json` / `specialists/*/summary.json`，说明这不是普通脚本，而是 Agent runtime。
6. 最后解释没用 LLM的原因：确定性路径不该强依赖 LLM，LLM 用于 unsupported/candidate/repair/optimization 等开放问题。

---

## 17. 当前局限与下一步

当前局限：

- HLS csim 只跑 20 个 MNIST 样本，适合演示，不代表完整测试集上板验证。
- MLP 比 CNN 简单，主要用于稳定展示端到端能力。
- fixed-point logits 漂移较大，后续需要精度校准或 per-layer precision。
- 当前仍不生成 bitstream，不做上板验证。

下一步建议：

- 增加 100/1000 样本的 HLS csim profile 或分批验证。
- 加入 per-layer precision advisor。
- 将外部 `mnist-8.onnx` CNN 接入 CNN adapter 攻关。
- 生成 AXI interface / IP packaging，为后续上板做准备。
- 把 recognition verification 扩展为通用 classification benchmark。

