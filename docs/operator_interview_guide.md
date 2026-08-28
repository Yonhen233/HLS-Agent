# 算子级 HLS Agent 面试指南

## 30 秒介绍

我做了一个 LLM-first 的算子到 HLS Agent。它不是让模型直接输出代码就结束，而是把 LLM Candidate 放进受限工具链：静态契约、Sandbox、独立 Golden CSim、真实 Vivado CSynth、报告解析、证据哈希和经验复用。Benchmark 严格拆分 Unit、Mock、Fixture 与 Real，防止把样例报告写成真实性能。

## 1 分钟介绍

系统外层是 Todo-driven Plan-Execute-ReAct，Main Agent 负责目标、计划和状态；Specialist 只看到裁剪后的 ContextEnvelope。算子生成默认走 LLM Candidate，模板仅作公平基线。每次 LLM 调用记录模型、阶段、输入/输出 token、累计预算和异常原因。生成代码先经过危险 API、接口位宽和数组分割检查，再用独立 Testbench 验证，只有功能与综合都通过的实现才能进入高置信 Memory。ParameterAdvisor 只复用同任务族、功能验证通过且 timing 可用的经验。

## 3 分钟技术深挖

当前统一 Functional Suite 有 120 个独立 Case，覆盖 Dense、MatMul、ReLU、Add、ScaleShift、Conv2D，三种位宽和十种输入族。每个 Case 同时计算数学参考和位精确参考，记录量化误差、overflow 与 saturation。高层计划是 18 个真实 CSim、10 个真实 CSynth 和 15 次 LLM pass³。所有真实 Artifact 必须位于当前 Run、晚于 Run 创建时间、带 SHA256，并包含完整语义字段；否则只能算 Unit/Fixture。

Agent 的价值不在于把固定 workflow 换个名字，而在于局部失败后的受约束决策：生成失败可 repair，Sandbox 失败必须拒绝，CSim 数值失败根据结构化 observation 修复，timing/resource 失败按 objective 重新生成；达到预算上限则诚实 Unsupported。LLM 看不到 Specialist 私有工具，Specialist 也不能直接修改全局 State。

## 常见追问

1. 为什么 120/120 不是 100% HLS 成功？因为它们是 Unit Golden，只证明参考与 Case Schema；真实 HLS 有单独分母。
2. 为什么不用 hls4ml？本轮评估 LLM Candidate 的未知算子生成能力，hls4ml 不参与主路径，避免结论混杂。
3. 模板还有什么用？作为稳定、公平、同约束的 baseline，以及已验证实现复用来源。
4. 怎么防止 LLM 假成功？Candidate 不能自报 verified；状态由 Sandbox、Golden CSim、CSynth 报告和 Completion Gate 决定。
5. 怎么防止旧报告污染？当前 Run 路径、时间、Hash 和关键字段四重校验。
6. token 为什么会异常？常见原因是全量记忆、重复代码、repair 携带旧 prompt 或输出用尽上限；新 trace 按 stage 定位。
7. RAG 会不会把 MatMul 经验给 Conv2D？Candidate 只接收同算子且已验证的 memory，未验证建议不会进入复用上下文。
8. 为什么要 Wilson 区间？防止把 1/1 说成稳定 100%。
9. 为什么不能只看 latency cycles？Clock 不同；实际延迟是 cycles × period，吞吐还取决于 II。
10. 当前最大限制？真实 CSim/CSynth 与 pass³ 样本尚未补齐，RTL Co-sim、Implementation 和上板未完成。
11. AP_TRN 和 AP_RND 有什么差异？前者截断，后者舍入；误差与资源可能不同，必须写入 Case。
12. AP_WRAP 和 AP_SAT 怎么选？Wrap 成本低但溢出会回绕；Sat 更安全但可能增加逻辑，应由数值边界测试决定。
13. 为什么 Accumulator 往往更宽？乘加会扩大动态范围，输入位宽不足以安全保存部分和。
14. II 和 Latency 有什么区别？Latency 是单次结果耗时，II 是流水线接受下一组输入的间隔。
15. Reuse Factor 的代价是什么？提高复用通常省 DSP，但增加 latency/II 和控制、多路选择逻辑。
16. Array Partition 为什么危险？Complete partition 可把大数组展开成大量寄存器和端口，导致 LUT/FF 或综合内存爆炸。
17. Conv2D 为什么先限制 NHWC？固定布局能消除索引歧义，并与当前流式接口契约保持一致。
18. 为什么拒绝 Depthwise/Grouped Conv？它们需要不同的数据复用和通道映射，不能假装等价于 group=1。
19. Golden 为什么不能调用被测 Kernel？那会让实现和参考共享同一个 bug。
20. CSim 退出 0 就算通过吗？不算，还需要 Golden marker、数值比较且日志无失败标记。
21. CSynth 退出 0 就可信吗？不一定，旧工具可能在日志报 compiler error；还要检查日志和报告完整性。
22. Repair 为什么有限次？避免无进展循环和 token/工具预算失控，达到上限应输出 Unsupported。
23. Specialist 与 Tool 的区别？Tool 是原子动作；Specialist 在受限上下文和工具集内执行局部 ReAct。
24. ContextEnvelope 解决什么？Main Agent 不摄入完整日志/代码，只接收结构化摘要与 Artifact 引用。
25. Memory 何时可复用？只有功能验证、综合和 timing 语义满足对应置信等级时才可提升。
26. 如何测 RAG 污染？构造带相关/无关标签的查询，统计 top-k 中跨算子或未验证结果比例。
27. DSE 为什么用 Pareto Front？资源、延迟、吞吐互相冲突，单一加权分数会隐藏真实权衡。
28. 如何复现实验？Run ID 关联 task、Git commit、工具版本、trace、报告和 Artifact Hash。
29. 哪些数字可以写简历？只写最新 Release JSON 中样本量足够、证据类别明确且可追溯的指标。
30. 为什么这个项目属于 Agent 工程？LLM 决策、工具执行、局部修复、状态恢复、权限、证据、记忆和评测形成闭环，而不是单次代码生成脚本。
