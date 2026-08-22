# DL-Operator-to-HLS Agent 真实场景面试指南

> 本文回答面试中最容易被连续追问的六类问题：工具、工具实现、异常治理、系统 Prompt、Skill、质量评测。口径以当前代码为准，不把 mock 结果包装成生产能力，也不把少量样例的 100% 当作开放世界可靠性。

## 一、项目现在是否应该转向真实场景

是。当前 Harness 已具备 LLM 规划、manager-as-tools 编排、Specialist 隔离、Tool Registry、权限、预算、证据门禁、会话恢复、RAG/Memory、durable queue、可观测性和评测骨架。继续增加抽象组件的边际价值已经较低，更有价值的是用真实任务分布持续暴露问题：

1. 多工具下的错选、漏选、重复调用和越权。
2. LLM 输出不稳定、计划不完整、跑偏和早停。
3. 工具超时、环境缺失、结果损坏和表面成功。
4. Prompt、Skill、模型升级后的回归和成本变化。
5. 小样本高分、mock 泄漏、数据污染造成的虚假结论。

MNIST 仍是主真实闭环；Dense、已有工程、ResNet 边界、LLM candidate 和强制失败用于覆盖 Agent 行为，不应被描述为全部真实工具链均已生产验证。

## 二、问题一：现在有多少工具，如何注册、调用和治理

### 面试时的直接回答

当前 Registry 中共有 **52 个可调用名称**，其中 **41 个 canonical tools**，另有 **11 个只为兼容旧 Skill/调用方保留的 aliases**。LLM 规划时只暴露 41 个 canonical tools，alias 不进入模型工具目录，避免同义工具竞争注意力。工具按 hls4ml、Vivado、workspace、task、生成与验证、memory/RAG、数据库、总结优化等能力域组织。

工具不是把 Python 函数名直接交给模型，而是注册为 `ToolSpec`：包含名称、描述、输入/输出 JSON Schema、权限等级、capability、风险、幂等性、缓存、并行安全、重试、超时、网络域和短期凭证范围。调用统一经过 `ToolRegistry.call()`，顺序是输入校验、权限/审批、预算、缓存、短期凭证、执行、输出校验、semantic postcondition、证据 receipt 和 trace。

### 41 个 canonical tools

| 能力域 | 数量 | 代表工具 |
|---|---:|---|
| hls4ml | 5 | `inspect_model`、`check_support`、`generate_config`、`convert`、`run_csim` |
| Vivado HLS | 5 | `create_project`、`run_csim`、`run_csynth`、`parse_report`、`parse_log` |
| Workspace | 4 | `scan`、`read_batch`、`search`、`symbol_search` |
| Task/边界/图改写 | 4 | `validate_schema`、`prepare_existing_project`、`write_unsupported`、`graph_rewrite.rewrite` |
| 生成与验证 | 4 | fallback kernel/testbench、LLM candidate、candidate verification |
| Memory/RAG | 11 | 短期记忆、压缩、候选提取、长期晋级、跨会话召回、RAG 检索与索引 |
| DB/报告/建议 | 8 | 五类元数据写入、summary、optimization suggestion、parameter advisor |

完整 canonical 名称可以由 `registry.list_tools(include_aliases=False)` 获取，数量不是手工写死的。

### 工具较多时如何保证准确调用

系统采用分层候选集，而不是把 41 个工具全部塞给每次 LLM：

1. Skill Registry 先根据任务类型、frontend、op type 和受控条件谓词召回最多 5 个 Skill。
2. Planner 只看到候选 Skill 的 allowlist、Main Agent 动作和可委派 Specialist。
3. Specialist 只拿到自己的 `ContextEnvelope` 和私有工具集合。
4. Plan Guard 校验 selected Skill、tool、specialist、所有权和 Goal Contract 覆盖。
5. LLM 选择不存在或越界工具时，计划在执行前被拒绝或有界修复。

本次检查发现并修复了一个真实路由缺陷：旧字符串条件未被解释，可能让 ResNet 边界任务优先匹配普通 hls4ml Skill。现在字符串条件映射为 fail-closed 的受控谓词，未知条件直接不匹配；主流程的精确 task type 匹配优先于横切优化 Skill，并新增 5 类真实任务路由合同测试。

### 如何保证快速调用和控制 Token

1. canonical-only 工具目录消除 11 个 alias 的重复描述。
2. Skill shortlist 减少 Prompt 中工具数量。
3. 已明确的 Specialist 委派和原子工具调用由 Harness 自动执行，不为每个 Todo 再调用一次 LLM。
4. 只对显式 `cacheable` 的幂等工具按 canonical tool + 参数 hash 缓存。
5. 只对 `parallel_safe` 的只读操作做有界并行；LLM 并发受独立上限控制。
6. RunBudget 限制 tool calls、LLM calls、tokens 和修复次数，Progress Supervisor 防循环。

### 如何保证不越权

安全不是靠系统 Prompt 中一句“不要越权”，而是运行时强制：

1. `PermissionGate` 校验 principal、capability、文件路径、命令和网络域。
2. 高风险调用进入 `waiting_for_approval`，审批绑定 session、tool 和 args hash，默认一次消费。
3. `CredentialBroker` 只向指定 audience/scope 注入 run-bound、短时、一次性凭证。
4. Specialist allowlist 阻止跨域调用；Main Agent 不能直接调用 Specialist 私有工具。
5. alias 现在解析到 canonical ToolSpec 执行，完整继承权限、capability、重试、缓存和凭证策略，不能再形成旧名称绕过。
6. 所有决策和调用写入 trace，敏感字段先脱敏。

## 三、问题二：Tool 的具体实现是什么

### 面试时的直接回答

Tool 是“受治理的函数适配器”，不是 Prompt 文本。`ToolSpec` 描述契约，handler 实现具体动作，Registry 实现统一治理，Adapter/MCP 负责外部协议，Postcondition Registry 负责验证结果是否真的成立。

### 三种实现形态

1. **本地纯函数工具**：任务校验、summary、unsupported report、参数建议等，handler 直接接收 `arguments` 和 `context` 并返回 JSON object。
2. **外部工具链 Adapter**：hls4ml/Vivado 工具将 Tool call 转为 Python API、进程或报告解析，结构化映射安装缺失、转换失败、综合失败和报告缺失。
3. **MCP proxy**：配置 stdio transport 后，从 MCP `tools/list` 获取能力并映射回本地 Registry；远端调用仍必须经过本地 Schema、权限、预算、trace 和 evidence gate。

一次调用的伪代码是：

```text
resolve alias -> canonical ToolSpec
validate input schema
check principal/capability/path/command/network policy
consume one-shot approval when needed
reserve budget and check canonical cache
lease scoped credential
execute handler with bounded retry for idempotent tools
validate JSON serializability and output schema
verify semantic postcondition and create Evidence Receipt
write trace/metrics/cache and return structured result
```

Schema 只能证明“字段长得对”。例如综合工具返回 `status=success` 仍不足以证明完成，postcondition 还要检查报告/artifact、关键字段和 mock 标记。成功状态与证据不一致时，Registry 将其改为 `ToolPostconditionError`。

## 四、问题三：遇到异常如何处理，有哪些保护策略

### 面试时的直接回答

异常分为输入/计划、权限、资源预算、LLM、工具环境、产物语义、进度和基础设施八类。系统不使用一个笼统 try/except 把错误吞掉，而是把异常转成 `error_type`、`recoverable`、`source`、`suggested_action` 和 `details`，再由 Skill failure policy、Reflector、Completion Gate 和 Session Runtime 决定 retry、repair、replan、降级、等待审批、中断或诚实结束。

### 分层保护

| 层 | 典型异常 | 处理 |
|---|---|---|
| 输入和计划 | JSON/Schema 错、工具不存在、计划漏步骤 | JSON repair、Plan Guard、有界补计划 |
| 权限 | 路径越界、命令/网络/能力未授权 | deny 或一次性人工审批，不执行 handler |
| 预算 | 重复 Tool/LLM、Token 超限 | `BudgetExceededError`，停止继续消耗 |
| LLM | 超时、429、空响应、非法 JSON | 限速退避、结构化修复；不可静默伪装成成功 |
| 工具 | hls4ml/Vivado 缺失、转换/综合失败 | 幂等操作有界重试，解析日志后 repair/replan |
| 结果 | report 缺失、csim 错、表面 success | postcondition/evidence gate 拒绝假成功 |
| 长程进度 | 循环、重复调用、无新 artifact | Progress Supervisor 终止或重规划 |
| 会话/Worker | 用户中断、进程退出、lease 过期 | checkpoint、resume、CAS commit、幂等重放 |

停止条件由 Completion Gate 独立判断：Goal Contract、必须 Todo、关键 artifact、验证证据和状态均满足才能 success。unsupported 是合法的诚实 outcome；不得产生伪造的 latency/resource/verification 指标。

需要诚实说明的限制：当前超时主要依赖 handler 配合 deadline，调用结束后也会检测超时，但并非所有本地 handler 都能被线程级硬杀；队列状态提交支持幂等/CAS，不代表外部文件和工具副作用天然 exactly-once。

## 五、问题四：系统提示词怎么写，是否优化，如何证明

### 面试时的直接回答

系统不是一个巨型 Prompt，而是按职责拆成 8 个 Prompt：task interpreter、todo planner、Main ReAct、specialist ReAct、JSON repair、reflection、optimizer 和 candidate generator。Prompt 负责表达角色、输出 Schema 和决策语义；权限、工具 allowlist、证据和完成条件由代码门禁执行。

Planner Prompt 的重点约束是：只能从候选 Skill 中选一个；Main Agent 不得直调 Specialist 私有工具；todo 的工具和 Specialist 必须属于 selected Skill；边界任务走 unsupported Skill；只返回严格 JSON。Candidate Prompt 则强调生成目录、接口契约、golden testbench、禁止危险 API 和“生成后必须验证”。

### 本次补齐的发布链路

之前 Prompt 有 release/canary 数据结构，但推理代码直接引用常量，版本记录没有真正控制运行时。现在每个 LLM 调用都通过 `resolve_prompt(context, name)` 从该 run 的 immutable release manifest 解析文本；缺失配置时才回退内置默认值。`runtime-prompts@2.0.0` 保存全部 Prompt 和 SHA-256 fingerprint，可以做确定性 cohort 路由、灰度和回滚。

### 如何优化 Prompt

1. 从 Bad Case 建立失败标签：非法 JSON、错 Skill、越权工具、漏验证、早停、假成功、Token 回归。
2. 冻结测试集，避免一边改 Prompt 一边改答案。
3. baseline/candidate 使用相同模型、task、tool mock/real 配置和重复次数。
4. 比较 task success、false success、tool/path accuracy、repair、tokens/success 和 p95。
5. 通过门槛后先小流量 canary；运行时 manifest 记录实际版本，异常自动回滚。

### 怎么证明优化有效

不能用“某一个 MNIST 跑通”证明。当前代码证据包括 Prompt schema/guard 回归、manifest 确实控制运行时文本、fingerprint 完整性、确定性 canary 和自动回滚。统计上，Release Manager 现在要求 baseline 和 candidate 各至少 20 个样本；样本不足即拒绝晋级。质量报告输出二项指标的 95% Wilson 区间。

当前仍没有一组足够规模的 DeepSeek baseline/candidate A/B 历史结果，因此面试时应说“优化与发布机制已实现，已有合同回归，但尚不能声称 Prompt 提升具有统计显著性”。这是可信度，不是短板掩饰。

## 六、问题五：Skill 怎么写，是否优化，如何证明

### 面试时的直接回答

Skill 是版本化的领域执行契约，不是一段可任意扩权的提示词。每个 `skills/*.yaml` 定义 name/version/status、intent、trigger、preconditions、recommended Todo DAG、allowed tools/specialists、required artifacts、failure/verification/memory policy、context/token budget、并发和权限策略。

加载阶段由 `SkillValidator` 检查必填字段、SemVer、生命周期、Todo DAG 重复/环/未知依赖、预算、并发上限、风险、依赖和可选完整性 hash。运行阶段再检查工具和 Specialist 是否真实注册。Planner 只能在候选 Skill 的能力边界内实例化 Todo，不能通过修改 Skill 动态添加权限。

### Skill 优化方法

1. **召回优化**：trigger 使用 task type、frontend、op type 和安全条件 DSL，不让 LLM从全部 Skill 猜。
2. **排序优化**：精确主流程优先，横切的 optimization/report/memory Skill 作为次级能力。
3. **上下文优化**：Prompt 只注入最多 5 个候选 Skill 的摘要，不注入完整文件。
4. **失败优化**：把特定错误映射为 retry、repair、fallback 或 unsupported。
5. **成本优化**：每个 Skill 自带 max steps/tool calls/LLM calls/tokens 和并行策略。
6. **发布优化**：Skill 版本固定在 run manifest，可 canary 和回滚。

### 怎么证明优化有效

本次新增真实分布路由合同，覆盖 MNIST hls4ml、Dense fallback、existing project、ResNet unsupported 和 ScaleShift LLM candidate，验证第一候选 Skill。未知字符串条件按 fail-closed 处理，避免配置拼写错误让 Skill 无条件命中。端到端 LLM suite 还会检查 selected Skill、实际工具、禁用工具和 Specialist。

Skill 测试应分两层：静态编译合同在每次提交运行；端到端行为测试按版本在冻结数据集上重复运行。只看 YAML 能否解析，不足以证明 Skill 有效。

## 七、问题六：质量评测怎么做，如何保证分数准确

### 面试时的直接回答

质量评测采用分层证据：单元/合同测试验证门禁；deterministic suite 验证 Harness；LLM suite 验证模型参与后的路径、工具、修复和成本；MNIST real-tool case 验证真实主链；RAG hard-negative 和 Bad Case suite 验证污染、假成功、循环和早停。不同证据层分开报告，mock 与 real 绝不混算。

### 核心指标

1. Tool/path selection accuracy。
2. Task success rate，按 operator fallback、model hls4ml、unsupported recovery、toolchain recovery 等分桶。
3. Unsupported honesty 和 false success rate。
4. Repair success rate。
5. Trace/artifact/Goal Contract completeness。
6. RAG Precision/Recall/Hit/MRR/nDCG 和 pollution rate。
7. p50/p95、tool calls/run、LLM calls/run、tokens/run、tokens/success。
8. 越权率、审批率、duplicate call、plan rejection、completion gate 和 evidence receipt 有效率。

### 如何避免“评测分数虚高”

1. 测试集与 Prompt/Skill 开发集分离并版本化。
2. 同时包含 happy path、边界、故障注入、对抗输入和 hard negative。
3. 对 LLM case 重复运行，报告均值、方差和置信区间，不只报最好一次。
4. 按模型、Prompt、Skill、toolchain、mock/real 和数据集版本记录 manifest。
5. success 必须通过 Goal Contract 和 Evidence Gate，不能只看最终字符串。
6. 人工抽检失败样例和 false success；评测器自身也有单元测试。
7. 样本不足 20 的比率标记 `statistically_usable=false`，不能用于自动晋级。
8. canary 同时限制成功率下降、false success、RAG 污染、Token 和 p95 回归。

当前 12-case deterministic capability suite 和 6-case LLM harness suite 提供行为覆盖，但 6 个 LLM case 仍是小样本。它适合作为回归门禁，不足以证明生产可靠性。真实 MNIST 是端到端证据，其余 mock case 主要证明 Harness 行为。

## 八、还能补充哪些真实场景问题

### 1. Tool discoverability 与语义冲突

继续建立 tool-selection hard negatives：相似名称、相似 Schema、同能力不同风险、缺参数和误导描述。指标除 top-1 accuracy 外，还应统计 illegal-tool rate、unnecessary-tool rate 和 time-to-first-correct-tool。

### 2. Tool version 与可复现性

当前 ToolSpec 尚未把 tool/schema/adapter hash 纳入完整 release bundle。下一步应为 canonical tool 增加独立版本和实现 digest，checkpoint 恢复时校验版本兼容，避免工具升级后旧 run 行为漂移。

### 3. 真正的超时和副作用恢复

长时外部命令应迁入可终止的进程/容器边界，使用 operation id、fencing token、reconciliation 和补偿逻辑。这样 Worker 崩溃后可以判断“未执行、执行中、已完成但未提交”，而不是盲目重跑。

### 4. Prompt 注入与 MCP 供应链

RAG 文本、工具输出和 MCP metadata 都按不可信数据处理；不得提升为 system instruction。远端 MCP 还需要 server identity、工具签名/版本、域名 allowlist、响应大小限制和 schema drift 检测。

### 5. 线上反馈闭环

用户反馈先进入 quarantine，经过来源、运行证据和人工/规则审核后才能影响长期记忆或 reranker；支持撤销和追溯。否则攻击者可通过反馈污染后续所有会话。

### 6. 面试演示顺序

1. 用自然语言提交 MNIST，展示 LLM plan、selected Skill 和分层工具目录。
2. 展示一次 Specialist 委派和 Tool evidence receipt。
3. 注入错误 Schema 或 verification failure，展示 repair/replan。
4. 提交 ResNet18，展示 unsupported honesty 和无伪造指标。
5. 展示中断、checkpoint、追加要求、撤回和恢复。
6. 最后展示 benchmark 的分桶指标、Token、p95 和 95% 区间。

## 九、30 秒总结答法

这个项目的重点不是把 hls4ml 包一层，而是建立一个可运行、可恢复、可审计、可发布和可评测的 LLM Agent Harness。当前有 41 个 canonical tools、10 个版本化 Skills，以及受限的 Main Agent/Specialist 编排。工具调用经过 Schema、权限、预算、短期凭证、证据和 trace；异常通过结构化错误、repair/replan、durable checkpoint 和 Completion Gate 处理。Prompt 与 Skill 都进入 release manifest 并支持 canary/rollback。评测以真实 MNIST 为主线，同时用边界和故障样例评估工具选择、任务完整性、诚实性、修复、RAG、Token 和延迟，并用样本门槛和置信区间避免把小样本高分说成生产可靠性。
