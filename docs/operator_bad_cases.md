# 算子 Bad Case 设计

`benchmarks/operator_bad_case_suite.json` 定义 20 类故障。目标不是让命令都返回 0，而是确保每类故障在正确阶段停止、返回正确 Structured Error，并且不会生成伪造指标。

Release Gate：False Success Rate、Stale Artifact Acceptance、Unsafe Candidate Acceptance、Unsupported Fake Metric Rate 均必须为 0。每个 Case 保存 failure stage、error type、recoverable、repair action、attempt count、final outcome 和 artifact evidence。

当前已落实的门禁包括危险系统调用、非字节对齐 `m_axi`、大型可变数组 complete partition、跨 Run 报告和缺失 Golden 标记。其余 Case 将在真实 LLM/Vivado Suite 中逐项执行，失败样本不会删除。
