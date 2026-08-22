# DL-Operator-to-HLS Agent 面试问答 100 题

## A. 项目定位

1. **Q: 这个项目一句话是什么？**
   A: 一个把深度学习算子/模型转换到 HLS 工程的传统工具链，改造成可规划、可调用工具、可恢复失败、可审计、可评测的 LLM Agent Harness。

2. **Q: 它和普通 hls4ml 脚本有什么区别？**
   A: 普通脚本只执行固定流程，本项目会先做 path selection，再通过 specialists 和 ToolRegistry 执行，并记录 trace、artifact 和 benchmark 指标。

3. **Q: 你最想让面试官记住的亮点是什么？**
   A: 我做的是 Agent harness 设计，包括工具约束、上下文隔离、错误恢复、RAG 证据控制和 Agent 质量评测。

4. **Q: 为什么这个项目适合互联网 Agent 岗位？**
   A: 它展示了 LLM 如何安全调用外部工具、如何处理失败、如何避免幻觉、如何被系统性评测。

5. **Q: 项目是不是 FPGA/HLS 岗位项目？**
   A: 它有 HLS 背景，但面试主线应放在 Agent 工程化，而不是硬件指标优化。

6. **Q: 真实跑通的主线是什么？**
   A: 当前真实闭环以 MNIST hls4ml 路径为主，其他路径覆盖 fallback、existing project、unsupported、LLM candidate 等 Agent 行为。

7. **Q: 为什么不用一开始就承诺支持 ResNet？**
   A: 因为 Agent 评测必须诚实，复杂模型不支持时应返回 partial/unsupported，而不是伪造结果。

8. **Q: 你如何描述项目边界？**
   A: 它验证了 Agent Harness 的可行性，但不是全模型、全算子、全工具链工业覆盖。

9. **Q: 项目最像大厂 Agent 系统的部分是什么？**
   A: plan validation、tool use safety、replan/repair、RAG evidence control、observability 和 benchmark。

10. **Q: 项目中的“Agent”体现在哪里？**
    A: 体现在任务分解、路径选择、todo 执行、工具调用、观察结果、失败恢复、总结和长期经验复用。

## B. 架构

11. **Q: 入口类是什么？**
    A: `src/dl_op_to_hls/main_agent/agent.py` 中的 `MainAgent`。

12. **Q: 核心 runtime 有哪些？**
    A: `PlanExecuteReactRuntime` 和 `LLMFirstRuntime`。

13. **Q: 两个 runtime 的区别是什么？**
    A: 前者偏确定性计划执行，后者让 LLM 先生成 plan/todo，再用 guard、schema 和 repair 约束。

14. **Q: 全局状态在哪里？**
    A: `src/dl_op_to_hls/main_agent/state.py` 的 `AgentState`。

15. **Q: Todo 模型负责什么？**
    A: 保存任务标题、依赖、状态、assigned tool/specialist、输入输出、错误和执行时间。

16. **Q: 为什么要有 Todo？**
    A: Todo 把长程任务拆成可观察、可重试、可路由、可评测的步骤。

17. **Q: Specialist Router 做什么？**
    A: 根据 todo 指定或能力匹配，将任务交给 HLS4ML、Vivado、Verification、Optimization、Memory specialist。

18. **Q: SpecialistResult 有什么价值？**
    A: 它把专家执行结果结构化，包括 status、summary、metrics、artifacts、errors、warnings、suggested_todos。

19. **Q: 为什么不让一个 Agent 做所有事？**
    A: 分专家可以控制上下文、限制工具、降低越权和提示污染，也便于评测每类能力。

20. **Q: 这个架构的核心闭环是什么？**
    A: plan -> todo -> specialist -> tool -> observation -> repair/replan -> summary。

## C. Path Selection

21. **Q: 支持哪些路径？**
    A: `hls4ml_path`、`fallback_template_path`、`existing_project_path`、`unsupported_path`、`llm_candidate_path`。

22. **Q: `hls4ml_path` 用在什么场景？**
    A: 用在当前真实可跑通的模型转换场景，例如 MNIST MLP/CNN。

23. **Q: `fallback_template_path` 用在什么场景？**
    A: 用在 Dense、matmul、relu、add 等可用模板生成 HLS kernel 的算子。

24. **Q: `existing_project_path` 用在什么场景？**
    A: 用户已经有 HLS 工程时，Agent 应复用并解析，而不是重新生成。

25. **Q: `unsupported_path` 的价值是什么？**
    A: 它让系统在不支持时诚实停止，避免伪造 latency/resource/verification。

26. **Q: `llm_candidate_path` 解决什么问题？**
    A: 它让 LLM 生成小算子候选代码，再通过 sandbox 和验证工具检查。

27. **Q: Path selection 为什么是 Agent 指标？**
    A: 因为它评估 Agent 是否理解任务并选择正确工具链，而不是评估硬件质量。

28. **Q: 如何判断路径选对？**
    A: 看 selected_path 是否匹配 expected_path，同时关键工具调用是否符合该路径。

29. **Q: 如果 ResNet18 被选成 hls4ml_path 怎么办？**
    A: 这是边界识别失败，应修正为 unsupported 或 partial_success。

30. **Q: 为什么只测 hls4ml_path 不够？**
    A: 那只是在评测老工具链，不是在评测 LLM Agent 的计划、分流和恢复能力。

## D. Tool Use 与安全

31. **Q: ToolRegistry 做什么？**
    A: 统一注册和调用工具，并记录 `PreToolUse`、`PostToolUse`、`ToolFailed` trace。

32. **Q: PermissionGate 做什么？**
    A: 检查工具调用中的路径、命令和参数是否在允许范围内。

33. **Q: 为什么工具调用要经过 registry？**
    A: 这样可以统一权限、审计、错误处理和指标统计。

34. **Q: 如果 LLM 想调用不存在的工具？**
    A: registry 会拒绝，runtime 可将其作为 plan/repair 问题处理。

35. **Q: 如何防止任意文件读写？**
    A: PermissionGate 检查 `path`、`output_dir`、`work_dir`、`report_path` 等参数。

36. **Q: 工具失败如何记录？**
    A: 通过结构化错误和 `ToolFailed` trace 事件记录 stage、tool、args hash 和错误信息。

37. **Q: 为什么 trace 中要 hash 输入输出？**
    A: 既能审计一致性，又避免把大日志或敏感内容写爆 trace。

38. **Q: Specialist 如何被限制工具？**
    A: `ContextEnvelope.allowed_tools` 和 specialist 自身 allowlist 双重检查。

39. **Q: CandidateSandbox 防什么？**
    A: 防 OS/process/file/network/asm 等危险调用，以及明显不合规 HLS 接口。

40. **Q: sandbox 通过是否代表综合成功？**
    A: 不代表，它只说明静态安全检查通过，还需要编译、csim 和报告验证。

## E. Trace 与 Artifact

41. **Q: Trace 完整度检查什么？**
    A: 检查 plan、todo、tool call、specialist result、artifact、error stage、summary 是否齐全。

42. **Q: ArtifactManager 做什么？**
    A: 注册文件路径、类型、sha256，并生成 artifact manifest。

43. **Q: 为什么要 artifact manifest？**
    A: 它让每个 run 的产物可追踪、可复现、可审计。

44. **Q: Summary 有什么作用？**
    A: 把执行结果、路径、错误、工件和建议汇总给用户或 benchmark。

45. **Q: 错误 stage 为什么重要？**
    A: 没有 stage 就无法知道该修 config、candidate、report 还是 toolchain。

46. **Q: 结构化错误有哪些例子？**
    A: `HLS4MLConversionError`、`VivadoSynthesisError`、`ReportMissingError`、`LLMGenerationError`。

47. **Q: 如何证明 Agent 没有伪造结果？**
    A: 看 trace 中是否有真实 tool call 和 artifact，unsupported case 是否缺少伪造 metric。

48. **Q: 为什么日志不全塞进上下文？**
    A: 长日志浪费 token，还会干扰 LLM；更好做法是 artifact ref、摘要和错误 stage。

49. **Q: Trace 和 benchmark 什么关系？**
    A: benchmark 从 run state、trace 和 artifacts 中提取 Agent 质量指标。

50. **Q: 如果 artifact 缺失怎么办？**
    A: 应进入 report/artifact recovery 或诚实返回 partial，而不是直接 success。

## F. RAG 与 Memory

51. **Q: Memory 的作用是什么？**
    A: 保存成功经验、失败案例、参数建议和优化规则，供后续 run 召回。

52. **Q: RAG 的目标是什么？**
    A: 召回相关 HLS case，辅助当前决策，而不是盲目增加上下文。

53. **Q: 什么是 RAG hit rate？**
    A: top-k evidence 中命中预期相关案例或领域的比例。

54. **Q: 什么是 pollution rate？**
    A: 不相关经验混入当前任务 evidence 的比例或 case 级污染率。

55. **Q: 为什么 failure memory 要 gating？**
    A: 失败经验很容易污染普通优化任务，只有失败类 query 才应召回。

56. **Q: RAG 如何排序？**
    A: 结合 token overlap、anchor、strong anchor 和 domain 匹配。

57. **Q: RAG 评测看哪些指标？**
    A: precision、recall、MRR、NDCG、hit rate、term coverage 和 pollution rate。

58. **Q: RAG 召回错误有什么后果？**
    A: Agent 可能错误选路、错误修复或使用不相关优化建议。

59. **Q: 为什么 RAG 是 Agent 证据而不是装饰？**
    A: 因为 benchmark 会检查 evidence 是否相关，以及是否污染当前任务。

60. **Q: 如何向面试官讲 MemorySpecialist？**
    A: 它负责抽取、压缩、保存、索引和召回经验，让长程 Agent 有可控记忆。

## G. LLM-first 与 Repair

61. **Q: LLM-first runtime 的价值是什么？**
    A: 它把项目从老工具链评测推进到真正的 LLM Agent harness 评测。

62. **Q: LLM plan 如何防止乱来？**
    A: 用 schema validation、path/tool guard、allowlist 和 repair 限制。

63. **Q: JSON repair 说明什么？**
    A: 说明系统能处理 LLM 输出格式不稳定，而不是依赖一次完美生成。

64. **Q: plan_acceptance_rate 是什么？**
    A: LLM 计划通过 schema 和 guard 的比例。

65. **Q: guard rejection 是坏事吗？**
    A: 不一定，合理拒绝危险或无效计划是 Agent 安全性的体现。

66. **Q: repair success rate 怎么理解？**
    A: 失败 case 最终被修复为 success 或诚实 partial 的比例。

67. **Q: candidate repair 的典型场景是什么？**
    A: LLM 生成 kernel 后 csim 或 report 失败，Agent 修改 candidate/testbench 或降级报告。

68. **Q: 如果修不好怎么办？**
    A: 返回 partial_success/unsupported，并说明失败 stage 和缺失证据。

69. **Q: 为什么 repair 比一次成功更重要？**
    A: 长程 Agent 面对真实工具链时失败常态化，恢复能力决定可用性。

70. **Q: 你修过的典型 bug 是什么？**
    A: LLM candidate 强制失败后没有正确转到 unsupported recovery，后来通过 todo coercion 和 tool allowlist 修复。

## H. 评测

71. **Q: 当前核心评测指标有哪些？**
    A: path selection accuracy、task success rate、unsupported honesty、repair success、trace completeness、RAG hit/pollution、latency/cost。

72. **Q: 为什么不主要看 latency/resource？**
    A: 因为目标是 Agent 岗位，首先要证明 harness 行为可靠，硬件指标只是下游产物。

73. **Q: 最新 LLM harness 结果如何？**
    A: 6 个 case 全部通过，4 个 success、2 个 partial_success，path/tool accuracy、honesty、repair、trace completeness 都为 1.0。

74. **Q: 指标是不是太好了？**
    A: 是偏高，因为当前 suite 偏 contract 和 MNIST 主线，需要继续增加 hard negative。

75. **Q: 如何解释高分不等于系统万能？**
    A: 高分说明当前评测合同通过，不说明支持所有模型和真实工具链长尾。

76. **Q: 当前 LLM suite 覆盖哪些路径？**
    A: hls4ml、fallback、existing project、unsupported、llm candidate 和 candidate repair。

77. **Q: 传统 suite 有什么价值？**
    A: 它提供 deterministic contract coverage，适合快速回归。

78. **Q: LLM suite 有什么价值？**
    A: 它评测 plan、JSON repair、tool calls、candidate generation 和 failure recovery。

79. **Q: p50/p95 runtime 为什么重要？**
    A: Agent 成本不仅是 tokens，也包括真实工具调用和长程运行耗时。

80. **Q: avg tool calls/run 说明什么？**
    A: 说明每个 run 的外部动作复杂度，可用于成本和稳定性分析。

## I. 工具链与 HLS

81. **Q: hls4ml 在项目中负责什么？**
    A: 负责支持模型的配置生成、转换和 HLS 工程产出。

82. **Q: Vivado/Vitis 在项目中负责什么？**
    A: 负责已有 HLS 工程或生成工程的 csim、csynth、report/log 解析。

83. **Q: fallback template 的意义是什么？**
    A: 当不需要完整模型转换时，用模板快速生成可验证的小算子 HLS 实现。

84. **Q: report parser 为什么重要？**
    A: Agent 的判断必须基于可解析报告，而不是自然语言猜测。

85. **Q: verification 和 synthesis 的区别是什么？**
    A: verification 更关注功能正确性，synthesis/report 才涉及资源和时序。

86. **Q: 为什么不能把 compile success 当最终 success？**
    A: 编译通过不代表功能正确，也不代表有合法资源/latency 报告。

87. **Q: unsupported report 里应包含什么？**
    A: 支持边界、已尝试步骤、失败 stage、建议，不应包含伪造硬件指标。

88. **Q: MNIST 在项目中承担什么角色？**
    A: 它是真实跑通主线，用于证明 hls4ml path 不是纯 mock。

89. **Q: CIFAR/ResNet 应如何定位？**
    A: 更适合作为边界、future work 或 unsupported honesty case，不能夸大。

90. **Q: HLS 背景如何转成 Agent 亮点？**
    A: 强调复杂外部工具链、多阶段失败和证据约束正是 Agent harness 的好试金石。

## J. 深挖与反问

91. **Q: 如果让你继续改，优先做什么？**
    A: 增加 hard negative、fake metric trap、verification mismatch、timeout 和 RAG pollution cases。

92. **Q: 如何做消融实验？**
    A: 对比 no-RAG、no-repair、no-guard、no-specialist-context 下的成功率和错误率。

93. **Q: 如何证明 specialist context 有用？**
    A: 统计 token/use、越权工具调用、错误工具调用和 plan rejection 的变化。

94. **Q: 如何扩展到更多模型？**
    A: 先扩展真实 hls4ml 支持矩阵，再把不支持模型纳入 honesty/boundary 评测。

95. **Q: 如何处理工具链环境不可用？**
    A: 检测 toolchain missing，记录 error stage，并返回 toolchain recovery partial result。

96. **Q: 你如何避免 benchmark 被 prompt hack？**
    A: 指标来自 trace、artifact 和结构化 state，而不是只相信 summary 文本。

97. **Q: 如果 LLM 总是选错 path 怎么办？**
    A: 加 path guard、few-shot evidence、negative examples，并在 benchmark 中单独统计 path accuracy。

98. **Q: 如果 RAG 召回了错误经验怎么办？**
    A: 用 pollution rate 捕获问题，并通过 domain gating、anchor scoring 和 hard negative 调整。

99. **Q: 这个项目最大的工程收获是什么？**
    A: Agent 成功不在于一次生成，而在于受控执行、可观察状态、失败恢复和可信评测。

100. **Q: 面试最后怎么总结？**
     A: 我把一个老 HLS 工具链改造成了可评测的 LLM Agent 系统，重点解决工具调用安全、路径选择、repair、RAG 证据和 trace observability，这些能力可以迁移到通用 Agent 场景。
