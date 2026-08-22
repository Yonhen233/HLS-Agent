# AI Agent 工程面试补习指南

> 配合你的 `dl-op-to-hls-agent` 项目食用。每个概念从零讲起，附面试话术和可能的追问。

---

## 目录

1. [Agent 到底是什么](#1-agent-到底是什么)
2. [ReAct：Agent 怎么"想"和"做"](#2-reactagent-怎么想和做)
3. [Tool 和 ToolRegistry：Agent 的"手"](#3-tool-和-toolregistryagent-的手)
4. [PermissionGate：Agent 的"安全护栏"](#4-permissiongateagent-的安全护栏)
5. [Skill：Agent 的"标准作业流程"](#5-skillagent-的标准作业流程)
6. [Specialist：Agent 的"专家团队"](#6-specialistagent-的专家团队)
7. [ContextEnvelope 和 TokenBudget：Agent 的"注意力管理"](#7-contextenvelope-和-tokenbudgetagent-的注意力管理)
8. [Memory 和 RAG：Agent 的"记忆系统"](#8-memory-和-ragagent-的记忆系统)
9. [Trace 和 Hook：Agent 的"黑匣子"](#9-trace-和-hookagent-的黑匣子)
10. [LLM Guard：防止 LLM"胡说八道"](#10-llm-guard防止-llm-胡说八道)
11. [Plan-Execute-ReAct Hybrid：混合运行时](#11-plan-execute-react-hybrid混合运行时)
12. [两层 ReAct 设计](#12-两层-react-设计)
13. [真实/mock 模式切换](#13-真实mock-模式切换)
14. [如何讲你在开发日志中的 Bug 故事](#14-如何讲你在开发日志中的-bug-故事)
15. [面试话术速查表](#15-面试话术速查表)

---

## 1. Agent 到底是什么

### 大白话解释

想象你让一个实习生帮你做事。你有两种方式：

**方式 A（脚本）**：你给他一张纸条，上面写着"第一步：打开文件A。第二步：数一下有多少行。第三步：把结果写到文件B。"他照着做，不管中间发生什么都不会变通。文件不存在？报错。格式不对？报错。

**方式 B（Agent）**：你告诉他"帮我统计一下文件A的行数，写到文件B"。他打开文件，发现格式不太对，自己判断需要先清洗一下数据。文件太大，他决定分段读。过程中遇到一个他不认识的符号，他来问你"这个怎么处理？"你告诉他规则，他继续干活。

**Agent 的核心能力是**：在运行时根据观察到的情况做决策。它不是死板地执行预定义的步骤，而是在一个大框架内灵活应变。

### 在你项目中的位置

你的项目有两种运行模式，恰好对应了这两种方式：

- `python -m dl_op_to_hls.cli run <task>` → **确定性基线流程（脚本模式）**。按固定的 Todo 模板一步步执行，不会根据中间结果动态改策略。
- `python -m dl_op_to_hls.cli run-llm <task>` → **LLM-first Agent 流程（Agent 模式）**。LLM 先读任务、选 Skill、生成 Todo 计划，执行过程中根据工具返回的结果动态调整。

看代码：`src/dl_op_to_hls/main_agent/workflow.py` 里有两个函数：

```python
def run_task(...)      # 脚本模式
def run_task_llm(...)  # Agent 模式
```

### 面试话术

> "我项目中的 Agent 不是一个固定流程的脚本。它有动态规划能力——LLM 根据输入任务和可用的 Skill 生成 Todo 计划；有运行时决策能力——ReAct 循环中根据工具返回的 observation 决定下一步动作；有自我纠错能力——Reflection 阶段可以根据执行结果追加新 Todo、跳过旧 Todo、甚至切换整个执行路径。同时我保留了确定性基线流程作为对照，两个模式不互相污染。"

### 可能的追问

**问："那你觉得什么情况下用 Agent，什么情况下用脚本就够了？"**

答：当任务路径是确定的、已知的、不需要变通的，脚本就行。比如你的项目里，如果已知所有算子都能走 fallback template，那脚本模式完全够用。Agent 的价值在于处理不确定性和边界情况——比如 hls4ml 不支持某个算子时，Agent 要判断是走 graph rewrite、走 fallback、还是生成 unsupported report。另一个考量是成本——LLM API 调用有延迟和费用，确定性的脚本没有。

---

## 2. ReAct：Agent 怎么"想"和"做"

### 大白话解释

ReAct = **Rea**soning + **Act**ing。是 Agent 领域的核心范式。

想象你在玩一个迷宫游戏。你不是一次性画出完整路线（那叫 Plan-only），也不是闭着眼睛乱走撞墙就回头（那叫纯试错）。ReAct 的做法是：

1. **观察**（Observation）：看看周围有什么
2. **推理**（Reason）：分析一下现在的情况，决定下一步往哪走
3. **行动**（Action）：走一步
4. 回到第 1 步，直到到达终点

每次行动后你会获得新的观察，新的观察影响你的下一次推理。这就是 ReAct 循环。

**为什么 ReAct 比纯规划强**：纯规划假设你一开始就知道全局信息。但如果中间工具返回了一个你没预料到的结果（比如 hls4ml 报"不支持 Gemm 算子"），纯规划就卡住了。ReAct 可以在这个观察之后调整策略。

### 在你项目中的位置

你的每个 Todo 执行时都记录了 `react_steps`，包含四个字段：

```python
# src/dl_op_to_hls/main_agent/todo.py
react_steps: list[dict]  # 每个 step 包含:
  - reason       # 为什么做这个决定（推理）
  - action       # 调了什么工具（行动）
  - observation  # 工具返回了什么（观察）
  - decision     # 下一步做什么（决策）
```

具体的 ReAct 决策由 `src/dl_op_to_hls/llm/` 下的代码完成：
- **Planner**：生成初始 Todo 计划
- **ReAct Decider**：在每个 Todo 执行时决定做什么
- **Reflector**：执行完后总结经验、追加或修改 Todo

### 面试话术

> "我的项目采用 ReAct 范式，但不是单纯的 ReAct。外层有一个 Plan-Execute 的大框架——先规划 Todo 列表，然后逐个执行。内层在每个 Todo 执行时做 ReAct——记录推理原因、工具调用、观察结果、下一步决策。这样既保持了整体结构化（你知道整个流程大概要做什么），又保留了局部灵活性（遇到意外可以动态调整）。"

### 可能的追问

**问："ReAct 和 Chain-of-Thought 有什么区别？"**

答：Chain-of-Thought（CoT，思维链）只是让模型"多想一步"，但它不会真的执行任何动作——它只是在脑子里推演。ReAct 是把推理和真实世界的行动交织在一起。每次行动（比如调一个工具）会从真实世界拿到新信息，这个新信息可能改变后续推理。CoT 是"脑子里想想"，ReAct 是"边做边想"。我的项目里，LLM 的 ReAct 决策会通过 ToolRegistry 真正执行工具，工具返回的结果会影响下一步决策，这就是 ReAct 而非 CoT。

**问："你的 ReAct loop 会不会无限循环？"**

答：不会。第一，Todo 的数量是有限的（plan 生成时确定的，reflection 追加也有上限，比如 LLM candidate 最多修复 2 次就转 unsupported）。第二，失败的 Todo 会被标记为 failed/skipped/blocked，状态机会推动流程前进。第三，有全局 wall-clock（虽然目前在开发中）和明确的终止条件——比如当 selected_path 变为 unsupported_path 且 unsupported report 已生成时，运行停止。

---

## 3. Tool 和 ToolRegistry：Agent 的"手"

### 大白话解释

LLM 本身只能生成文本。它不能读写文件、不能运行命令、不能调用 Vivado HLS。**Tool（工具）**就是给 LLM 装上"手"，让它能真正做事。

**ToolRegistry** 是一个工具箱，里面所有工具统一注册、统一调用。它的价值在于：

1. **统一入口**：不管谁想用工具，都通过 registry 调用，不能绕过去
2. **统一安全检查**：每次调用前都过 PermissionGate
3. **统一记录**：每次调用都写 trace

你可以把 ToolRegistry 理解成一个刷卡门禁系统——每扇门（工具）都要刷卡（权限检查）才能进，而且每次进出都有记录（trace）。

### 在你项目中的位置

`src/dl_op_to_hls/core/tool_registry.py`。核心代码：

```python
class ToolRegistry:
    def register(self, tool):    # 注册工具
        self._tools[tool.name] = tool

    def call(self, name, arguments, context):
        # 1. 权限检查
        # 2. 触发 PreToolUse hook
        # 3. 执行工具
        # 4. 触发 PostToolUse hook
        # 5. 验证返回结果是合法 JSON
```

你项目中有大约 30 个工具，按领域分：

| 领域 | 工具举例 | 作用 |
|---|---|---|
| hls4ml | `hls4ml.check_support`、`hls4ml.convert` | 模型检查、转换 |
| Vivado | `vivado.create_project`、`vivado.run_csynth` | HLS 综合 |
| fallback | `fallback.generate_operator_hls` | 生成模板 HLS 代码 |
| LLM | `llm.generate_candidate` | LLM 生成 HLS 候选代码 |
| memory | `memory.retrieve_similar_experiences` | 检索历史经验 |
| RAG | `rag.index_artifact`、`rag.retrieve_experience` | 轻量知识检索 |
| DB | `db.save_experiment`、`db.save_synthesis_run` | SQLite 写入 |
| summary | `summary.write_summary` | 生成运行摘要 |

每个工具都用 `ToolSpec` 定义，包含：名称、描述、输入格式（schema）、输出格式、权限等级、处理函数。

### 面试话术

> "我实现了一个统一的 ToolRegistry，所有工具——不管是 hls4ml 模型检查、Vivado HLS 综合、fallback 模板生成还是 LLM 候选代码——都通过同一个注册和调用入口。每次调用自动走三层：PermissionGate 权限检查、PreToolUse/PostToolUse Hook 事件、以及 trace jsonl 记录。工具之间不能互相绕过 registry 直接调用，这保证了安全边界和可观测性。"

### 可能的追问

**问："为什么不用 function calling 直接用？"**

答：OpenAI 的 function calling 只是一个接口规范——它告诉 LLM"你可以调这些函数"。但它不提供权限检查、不提供调用追踪、不提供统一的序列化约束。我的 ToolRegistry 是在 function calling 的思想之上加了一层工程化的执行框架。而且我对接的是自部署的 OpenAI-compatible endpoint，有些 endpoint 的 function calling 稳定性不太好，自己实现 ToolRegistry 给了我完全的控制权。

**问："你的工具返回结果怎么保证一定是合法 JSON？"**

答：`ToolRegistry.call()` 在拿到工具返回结果后，会做 `json.dumps(result, default=str)` 来验证结果是否可序列化。不可序列化的结果（比如包含 Python 对象）会在这一步暴露，不会传给 LLM。

---

## 4. PermissionGate：Agent 的"安全护栏"

### 大白话解释

给 LLM 装上"手"（工具）之后，你必须确保这只手不会乱碰不该碰的东西。PermissionGate 就是这个护栏。

想象你让一个实习生用你的电脑。你给他设了限制：只能读写 `runs/` 目录，不能碰系统文件；可以运行 `vivado_hls` 和 `pytest` 命令，绝对不能运行 `rm`、`curl`、`ssh`。这就是 PermissionGate 在做的事。

### 在你项目中的位置

`src/dl_op_to_hls/core/permissions.py`。核心逻辑：

```python
class PermissionGate:
    # 检查文件读权限：路径是否在 allowed_read_dirs 内
    def check_read_path(self, path)

    # 检查文件写权限：路径是否在 allowed_write_dirs 内
    def check_write_path(self, path)

    # 检查命令执行权限：命令是否在 allow/ask/deny 列表中
    def check_command(self, command)

    # 检查工具调用：综合检查工具涉及的所有路径和命令
    def check_tool(self, tool_name, args)
```

默认权限配置在 `core/config.py` 的 `DEFAULT_PERMISSIONS` 中：

```python
DEFAULT_PERMISSIONS = {
    "filesystem": {
        "allowed_read_dirs": [".", "./examples", "./models", "./runs"],
        "allowed_write_dirs": ["./runs"],        # 只能写到 runs/
        "denied_dirs": ["/", "/etc", "~/.ssh", "~/.aws"],
    },
    "commands": {
        "allow": ["vivado_hls", "pytest"],
        "ask": ["python"],                         # P0 中视为 deny
        "deny": ["rm", "rm -rf", "curl", "wget", "ssh", "sudo"],
    },
}
```

关键设计："ask" 级别在 P0（当前原型阶段）直接视为 deny。这意味着任何需要用户确认的操作默认都是拒绝的，只有明确在 "allow" 列表中的才可以执行。这是一种保守的安全策略——宁可拒绝合法的操作，也不放行危险的操作。

### 面试话术

> "Agent 安全不能只靠 prompt 约束——prompt 可以被绕过。我实现了一个多层安全体系：最底层是文件系统级别的 PermissionGate，限制读写目录和可执行命令；中间层是工具调用时自动触发的权限检查；最上层是 LLM candidate 代码的静态沙箱扫描。这三个层次互相独立，任何一层失败都会阻止操作执行。"

### 可能的追问

**问："如果有工具需要写文件，你怎么保证它不会覆盖重要文件？"**

答：第一，PermissionGate 只允许写 `./runs/` 目录；第二，每个 run 有自己的子目录（`runs/<run_id>/`），不会互相覆盖；第三，ArtifactManager 会记录每个生成文件的 SHA256 hash 和创建时间，可追溯。

---

## 5. Skill：Agent 的"标准作业流程"

### 大白话解释

Skill 不是一段代码。它是一个 YAML 文件，定义了一种**完成任务的标准方式**。它告诉 Agent：

- 什么情况下用这个 Skill（trigger）
- 推荐做哪些步骤（recommended_todos）
- 只能用哪些工具（allowed_tools）
- 只能用哪些 Specialist（allowed_specialists）
- 失败了怎么处理（failure_policy）
- 生成代码后要不要验证（verification_policy）

你可以把它理解成麦当劳的操作手册——"做巨无霸的流程：第一步拿面包，第二步放牛肉饼，第三步放生菜..."。新员工（LLM）照着这个手册做，就不会乱来。

**Skill 的关键作用是约束**：它限制了 LLM 的能力范围，而不是扩大。这听起来反直觉——你给 Agent 加能力，为什么反而要限制它？因为不加限制的 LLM 什么都能生成，但它可能生成"用不存在的工具"、"把模型检查任务分配给 Vivado 综合专家"这种不合理的计划。Skill 的 allowlist 就是告诉 LLM："在这个任务里，你只能用这些工具，不要想别的。"

### 在你项目中的位置

Skill 文件在 `skills/*.yaml`，例如 `skills/hls4ml_model_flow.yaml`。加载和管理在 `src/dl_op_to_hls/skills/` 下：

- `skill.py`：定义了 Skill 的数据结构
- `registry.py`：管理所有 Skill 的加载和查询
- `policy.py`：**SkillPolicy**，校验 LLM 生成的计划是否在 Skill allowlist 内

核心数据结构：

```python
@dataclass
class Skill:
    name: str               # 名称
    intent: str             # 意图（这个 Skill 是干什么的）
    trigger: dict           # 什么条件下触发
    recommended_todos: list # 推荐步骤
    allowed_tools: list     # 允许的工具（白名单）
    allowed_specialists: list  # 允许的专家
    failure_policy: dict    # 失败处理策略
    verification_policy: dict  # 验证要求
```

SkillPolicy 的校验逻辑（`src/dl_op_to_hls/skills/policy.py`）：

```python
def validate_llm_plan_against_skill(self, plan, selected_skill):
    # 检查 plan 中的每个 todo:
    # 1. 用到的 tool 在 skill.allowed_tools 内吗？
    # 2. 用到的 specialist 在 skill.allowed_specialists 内吗？
    # 3. 如果生成了代码，有没有安排验证步骤？
    # 任何一个不满足 → 返回 invalid，拒绝这个 plan
```

### 面试话术

> "Skill 是我项目中的一个关键设计。它不是一个执行引擎，而是一组声明式的约束——告诉 LLM '在这个任务类型下你能用什么工具、应该走什么路径、失败了怎么处理'。更重要的是，SkillPolicy 会对 LLM 生成的计划做白名单校验——如果 LLM 提出了 Skill allowlist 之外的工具或 Specialist，直接拒绝。这解决了 LLM agent 的一个核心问题：LLM 什么都能生成，但你需要保证它生成的计划是安全的、可执行的。"

### 可能的追问

**问："Skill 和 Tool 有什么区别？"**

答：Tool 是原子操作——做一件事。Skill 是流程模板——定义了一组相关的 Tool 怎么配合使用，以及约束条件。类比：Tool 是"切菜"、"开火"、"放油"；Skill 是"炒青菜的标准流程"。

**问："如果 LLM 生成的计划违反了 Skill 约束会怎样？"**

答：在 strict 模式下直接报 `LLMGenerationError`，不会静默切换到确定性流程。这是我刻意设计的——开发期不应该用兜底掩盖问题。如果是 demo 模式，会回退到确定性的 Todo 模板。这个选择体现在 `LLMFirstRuntime` 的代码里。

---

## 6. Specialist：Agent 的"专家团队"

### 大白话解释

想象一个建筑项目。项目经理（Main Agent）不可能亲自画水电图、算结构力学、挑选瓷砖颜色。他会把这三种任务分别交给水电工程师、结构工程师、室内设计师。每个专家只做自己领域的事，只用自己的专业工具，最后交回一个汇总结果。

你的项目中，**Specialist** 就是这些领域专家。Main Agent 负责任务的整体调度，具体执行交给对应的 Specialist。

**为什么要搞 Specialist？三个原因**：

1. **上下文隔离**：Vivado 的综合报告可能有几千行。如果全塞给 Main Agent，它的 LLM 上下文窗口就炸了，决策质量会下降。Specialist 自己消化这些原始数据，只返回压缩后的摘要。

2. **安全隔离**：HLS4MLSpecialist 只能调 hls4ml 相关工具，不能碰 Vivado 的命令行。每个 Specialist 有自己的 allowed_tools 白名单。

3. **可维护性**：如果要增加一个 ModelSim 仿真工具，你只需要加一个 ModelSimSpecialist，不用动 Main Agent 的逻辑。

### 在你项目中的位置

在 `src/dl_op_to_hls/specialists/` 下，你有 5 个 Specialist：

| Specialist | 职责 | 可用的工具 |
|---|---|---|
| HLS4MLSpecialist | 模型检查、hls4ml 支持判断、配置生成、模型转换 | hls4ml.inspect_model, hls4ml.check_support, hls4ml.generate_config, hls4ml.convert 等 |
| VivadoSpecialist | Vivado 项目创建、csim/csynth 执行、报告解析 | vivado.create_project, vivado.run_csynth, vivado.parse_report 等 |
| VerificationSpecialist | 验证 LLM 生成的 HLS 候选代码 | verify_candidate.run, vivado.run_csynth, vivado.parse_report |
| OptimizationSpecialist | 结合报告和历史经验生成优化建议 | rag.retrieve_experience, suggestion.suggest_optimization |
| MemorySpecialist | 压缩上下文、提取记忆、索引 RAG | memory.compress_run_context, memory.promote_to_long_term 等 |

每个 Specialist 的交互遵循严格的契约：

- **输入**：`ContextEnvelope`（限定范围的上下文包，不是整个 AgentState）
- **输出**：`SpecialistResult`（压缩后的结果，不能包含原始 log/code）
- **调用**：只能通过 ToolRegistry 调用自己的 allowed_tools

看 `SpecialistRouter`（`src/dl_op_to_hls/specialists/router.py`）的路由逻辑：

```python
def route(self, todo):
    # 1. 如果 Todo 显式指定了 specialist，直接用那个
    if todo.assigned_specialist:
        return find_by_name(todo.assigned_specialist)
    # 2. 否则看哪个 specialist 声称能处理这个 todo
    for specialist in self.specialists:
        if specialist.can_handle(todo):
            return specialist
    # 3. 都不行 → 返回 None，由 Main Agent 自己处理
    return None
```

### 面试话术

> "Specialist 是我实现上下文隔离和安全隔离的核心机制。Main Agent 不直接看到 Specialist 的私有工具——比如它不知道 `vivado.run_csynth` 的具体参数格式。它只能通过 `delegate_to_specialist` 委派任务。Specialist 接收一个 ContextEnvelope（限定 token 预算的上下文片段），在内部做局部决策，最后返回压缩后的 SpecialistResult。这解决了 LLM Agent 的一个常见问题：上下文越长，决策质量越低。通过把领域噪声隔离在 Specialist 内部，Main Agent 始终保持清晰的全局视角。"

### 可能的追问

**问："Specialist 内部也是 LLM 驱动的吗？"**

答：默认不是。我经历过一个教训——最初 Specialist 内部的 ReAct 决策也调用了 LLM，导致 OptimizationSpecialist 在真实 API 环境下卡住不动（每次决策都在等 API 返回，而 OptimizationSpecialist 本身就要调 LLM 做优化建议生成，两者叠加造成性能灾难）。后来我把 Specialist 的局部 ReAct 改为默认使用确定性决策，只有显式设置环境变量 `DL_OP_TO_HLS_SPECIALIST_LLM_DECIDER_ENABLED=1` 时才启用 LLM 决策。这是一个"少即是多"的设计选择。

**问："Main Agent 和 Specialist 怎么通信？会不会有信息丢失？"**

答：通过 `ContextEnvelope` → `SpecialistResult` 的契约通信。信息丢失是刻意的——不是 bug，是 feature。我们故意不让 Specialist 把原始 Vivado 日志、完整 HLS 代码、全量 stdout/stderr 传回 Main Agent。传回的只是摘要、指标、结构化错误、artifact 引用。Main Agent 需要原始数据时可以通过 artifact ref 去读文件，但它的决策不依赖原始数据。核心指标（context_usage）会记录压缩比——原始 artifact 读了多少字节，摘要返回了多少字节，压缩比是多少。这样上下文隔离不是"黑箱"，而是可量化的。

---

## 7. ContextEnvelope 和 TokenBudget：Agent 的"注意力管理"

### 大白话解释

LLM 有一个根本限制：它一次能处理的文本量是有限的，叫做"上下文窗口"（或 token 预算）。GPT-4 可以处理约 8K-128K token，你用的 DeepSeek 可能是 32K-128K。Token 可以粗略理解为 1 个 token ≈ 0.75 个英文单词 ≈ 0.5 个中文字。

问题来了：你的一次 HLS run 会产生模型元数据、生成的 C++ 代码、testbench、TCL 脚本、Vivado 日志、综合报告、历史记忆检索结果……全塞给 LLM，token 预算瞬间爆掉。

**ContextEnvelope** 就是解决这个问题的。它是传给 Specialist 的一个"信息包"，里面的内容经过裁剪：只包含当前 Todo 相关的 state 片段、top-K 记忆摘要、artifact 引用（只给路径不传内容），以及一个明确的 token 预算上限。

**TokenBudget** 是执行这个预算的机制。它不是精确的 tiktoken 计数（为了减少依赖），而是用简单的 1 token ≈ 4 字符估算。如果包的内容超过了预算，它会做渐进式截断。

### 在你项目中的位置

**ContextEnvelope**（`src/dl_op_to_hls/specialists/context.py`）：

```python
@dataclass
class ContextEnvelope:
    run_id: str                    # 哪个 run
    todo_id: str                   # 哪个 Todo
    specialist_name: str           # 哪个 Specialist
    task_summary: dict             # 任务摘要
    scoped_state: dict             # 限定范围的 state——
                                   # 不是整个 AgentState，
                                   # 而是按 Specialist 类型裁剪的字段
    artifact_refs: list            # artifact 引用（只有路径和类型）
    retrieved_memory_refs: list    # top-K 记忆摘要
    constraints: dict              # 约束条件
    allowed_tools: list            # 允许的工具白名单
    max_context_tokens: int        # token 预算上限
```

关键：`scoped_state` 不是整个 `AgentState`。它是按 Specialist 类型裁剪的：

```python
# 对 HLS4MLSpecialist：只传模型路径、精度、reuse_factor 等
# 对 VivadoSpecialist：只传工程目录、top_function、时序约束等
# 对 OptimizationSpecialist：只传报告、目标、RAG 上下文等
```

**TokenBudget**（`src/dl_op_to_hls/core/token_budget.py`）：

截断是分层递进的，从温和到激进：

```
Step 1: 截断 RAG 上下文中每条摘要的长文本（截到 80 token）
Step 2: 截断 retrieved memory refs 的长文本
Step 3: 截断 state_summary 中的 suggestions 和 task 描述
Step 4: 截断 notes（截到 60 token）
Step 5: 还不够 → 对 scoped_state 和 task_summary 中所有字符串做通用截断
Step 6: 还不够 → 删除末端的 memory refs 和 rag_context 条目
Step 7: 还不够 → 最小化所有内容（只保留最核心的字段）
```

每一步都记录在 `truncation_steps` 中，最终写入 `context_usage`，让截断过程完全可观测：

```python
context_usage = {
    "estimated_input_tokens_before": 4500,   # 截断前
    "estimated_input_tokens": 2850,           # 截断后
    "max_context_tokens": 3000,               # 预算
    "truncated": True,                        # 是否做了截断
    "truncation_steps": [                     # 做了哪些步骤
        "truncate_scoped_rag_context",
        "truncate_retrieved_memory_refs"
    ],
    "context_truncated": True
}
```

### 面试话术

> "LLM Agent 的一个核心挑战是上下文窗口有限。我通过 ContextEnvelope + TokenBudget 两层机制来管理。ContextEnvelope 从架构上限制了 Specialist 能看到什么——不是传整个 AgentState，而是按 Specialist 类型裁剪相关字段。TokenBudget 在运行时用渐进式截断保证预算不超标——先截 RAG 摘要，再截 memory refs，再截 state 文本，实在不够就删尾部条目。每次截断都会被记录，写入 context_usage，让压缩过程完全透明。我选择用轻量估算而非 tiktoken，因为 3000 token 级别的预算下，4 chars/token 的精度已经足够，不值得引入额外依赖。"

### 可能的追问

**问："你怎么知道截断后信息没有丢失关键内容？"**

答：有两个保障。第一，截断的顺序是从"最可替换"到"最关键"——RAG 上下文和 memory 摘要是辅助信息，先截；task_summary 和 scoped_state 是核心信息，最后才截。第二，即使截断了，原始数据没有被删除——artifact refs 仍然指向完整的文件路径。如果 Specialist 确实需要更多上下文（比如怀疑截断丢失了关键信息），它可以通过 artifact ref 去读取完整文件。但这种情况在实践中很少发生，因为 Specialist 的 `_scoped_state` 本身就是按领域裁剪的，截断通常只影响 RAG/memory 这些辅助信息。

**问："为什么是 4 chars/token，这个数字怎么来的？"**

答：这不是精确数字，是一个工程估算。英文场景下通常是 4 chars/token，中文场景下约 1.5-2 chars/token。对于我项目中混合中英文的 HLS 报告和 RAG 内容，4 是一个保守估算（高估 token 数量，确保不超预算）。如果将来预算要求更精确，可以替换为 tiktoken，但当前原型阶段精度已经够用。

---

## 8. Memory 和 RAG：Agent 的"记忆系统"

### 大白话解释

人的记忆是分层的：
- **工作记忆（短期）**：现在在想的事——"这行代码的 reuse_factor 设的是多少来着？"
- **情景记忆（中期）**：上次发生了什么——"上回跑 Dense 算子的 Vivado 综合，DSP 用了 16 个"
- **语义记忆（长期）**：从多次经验中提炼的规律——"ReuseFactor 提高通常会降低 DSP 但增加 latency"
- **操作手册（技能）**：会做某事的标准流程——"我知道怎么用 hls4ml 转换一个 ONNX 模型"

你的项目的 Memory 系统就是按照这个模型设计的。

**RAG（Retrieval-Augmented Generation，检索增强生成）** 是另一种"记忆"——但不是在 LLM 内部记住，而是从外部数据库检索相关内容，然后"喂给" LLM。比如你做 Dense 算子的优化，系统会检索之前所有 Dense 相关的综合报告和优化建议，把最相关的几条塞进 LLM 的上下文。

### 在你项目中的位置

你的 Memory 系统在 `src/dl_op_to_hls/memory/` 下，分五层：

| 层级 | 名称 | 存储内容 | 文件/数据库 |
|---|---|---|---|
| L0 | Runtime State | 当前正在运行的状态（不是真正的记忆） | `state.json` |
| L1 | Short-term | 当前 run 的压缩上下文、近期决策 | `short_term.json`, `compressed_context.json` |
| L2 | Episodic | 历史 run 的摘要：路径、结果、延迟、资源、错误 | SQLite `experiments`, `implementations`, `synthesis_runs`, `failures` 表 |
| L3 | Semantic | 从多次经验提炼的事实："Dense 提高 ReuseFactor 会降低 DSP" | SQLite `memory_facts`, `memory_items` 表 |
| L4 | Skills/Playbooks | 可复用的操作流程 | YAML 文件 + SQLite `procedural_memories` 表 |

**记忆的生命周期**：

```
Run 完成
  ↓
extract_memory_candidates()   # 从这次 run 中提取值得记住的东西
  ↓
MemoryPolicy.should_promote() # 判断哪些值得提升为长期记忆
  ↓
promote_to_long_term()        # 写入 SQLite + RAG 索引
```

什么值得记住？什么不记？这是 `MemoryPolicy` 决定的（`src/dl_op_to_hls/memory/memory_policy.py`）：

```python
# 会记住的：
- verified implementation     # 验证通过的实现
- new failure type            # 新类型的失败
- synthesis metrics           # 综合指标
- optimization suggestions    # 优化建议
- successful repair           # 成功的修复

# 不记的：
- raw logs                    # 原始日志（太长太噪）
- stdout noise                # 标准输出的噪音
- temporary paths             # 临时路径
- uncompressed report         # 未压缩的完整报告
```

**RAG** 在你的项目中是一个轻量实现（`src/dl_op_to_hls/rag/`）：
- 不用外部向量数据库（如 Pinecone、Weaviate）
- 用 SQLite 表 `rag_chunks` 存储切好的文本块
- 用 token-overlap 的方式计算相似度（query 和每个 chunk 的 token 交集比例）
- 检索到的结果作为辅助信息放入 `AgentState.rag_context`

**RAG 和 SQLite 的关系**（这是你的架构中的一个重要原则）：

> SQLite 是 source of truth。RAG 只是检索层。

意思是：SQLite 里存的是结构化事实（DSP=16, LUT=549, 时间是 2026-06-02）。RAG 存的是从这些事实中切出来的文本块，用于模糊检索。你不能用 RAG 的检索结果覆盖 SQLite 的事实记录。

### 面试话术

> "我的 Memory 系统仿照人脑的分层记忆模型设计，分五层：L0 运行时状态、L1 短期记忆（当前 run 的压缩上下文）、L2 情景记忆（历史 run 的摘要和指标）、L3 语义记忆（从多次经验提炼的优化规则）、L4 技能记忆（可复用的操作流程）。这不是一个简单的"存下来就完了"的设计——我有 MemoryPolicy 来决定什么值得记、什么只是噪音，有 promotion 机制从短期提升到长期，有 RAG 检索来找到最相关的历史经验。SQLite 是结构化事实的 source of truth，RAG 只是检索层——两者互补但不互相替代。"

### 可能的追问

**问："你的 RAG 为什么不用向量数据库？"**

答：原型阶段不值得。向量数据库的部署和维护成本远高于项目本身的需求——我只有几十到几百条历史 run 记录，SQLite 的 token-overlap 检索完全够用。如果将来数据量上了万条，可以换成向量数据库，但替换成本很低——因为 RAG 层在架构上就是一个独立的检索接口，SQLite 实现只是其中一个 adapter。

**问："你怎么防止错误记忆污染后续决策？"**

答：Memory promotion 不是自动的——它经过 MemoryPolicy 的筛选。比如 mock 模式下的验证结果不会被 promote（因为只有 verified 的实现才会被 promote）。如果是 LLM 生成的错误优化建议，它会带有低 confidence 分，不会进入 memory。另外，每次检索到的记忆在传给 LLM 时会标注来源和 run_id，LLM 可以知道这是"上次的经验"而非"当前的事实"。

---

## 9. Trace 和 Hook：Agent 的"黑匣子"

### 大白话解释

飞机有黑匣子（飞行记录器），出了事可以回放发生了什么。你的 Agent 系统的黑匣子就是 **Trace**。

**Hook** 是"事件监听器"——每当系统里发生什么事（工具被调用了、Todo 状态变了、Specialist 开始了、LLM 做决策了），Hook 就会触发，把事件记录下来。

**Trace** 是 Hook 记录下来的东西。你的项目用的是 jsonl 格式（每行一个 JSON 对象），便于逐行调试。

### 在你项目中的位置

**Hook 系统**（`src/dl_op_to_hls/core/hooks.py`）：

```python
class HookManager:
    def register(self, event_name, handler)  # 注册监听器
    def emit(self, event_name, payload)      # 触发事件

# 注册的例子：
hooks.register("PreToolUse", ConsoleHook())    # 工具调用前打印到控制台
hooks.register("*", TraceHook(writer))         # 所有事件写到 trace.jsonl
hooks.register("*", DbHook(callback))          # 所有事件触发数据库记录
```

你的事件类型覆盖了整个生命周期：

| 阶段 | 事件 |
|---|---|
| 运行 | `RunStarted`, `RunFinished` |
| Todo | `TodoCreated`, `TodoStarted`, `TodoCompleted`, `TodoFailed`, `TodoBlocked` 等 |
| 工具 | `PreToolUse`, `PostToolUse`, `ToolFailed`, `PermissionDenied` |
| Specialist | `SpecialistSelected`, `SpecialistStarted`, `SpecialistFinished`, `SpecialistResultMerged` |
| LLM | `LLMCallStarted`, `LLMCallFinished`, `LLMCallFailed`, `LLMPlanGenerated`, `LLMPlanRejected` 等 |
| 其他 | `ArtifactCreated`, `ContextCompressed`, `RagRetrieved`, `DbRecordCreated` |

**Trace 输出**（`src/dl_op_to_hls/core/trace.py`）：

每行长这样：

```json
{"ts": "2026-06-02T10:30:00Z", "event": "PostToolUse", "run_id": "dense_16x32_115c1f11", "tool": "vivado.run_csynth", "status": "success", "duration_ms": 45230}
```

还可以单独过滤 LLM 相关的 trace：

```powershell
python -m dl_op_to_hls.cli llm-trace runs/dense_16x32_115c1f11
```

### 面试话术

> "可观测性是 Agent 系统的基石——因为 Agent 的决策是 LLM 做的，你不能在代码里打断点去调试。我实现了一个发布-订阅式的 Hook 系统，覆盖了从 Run 开始到结束的完整生命周期。所有事件通过 TraceHook 写入 jsonl 文件，可以逐行回放查找问题。比如之前排查 OptimizationSpecialist 卡住的问题时，我只看 trace 的最后几行就定位到了——最后一个事件是 `SpecialistStarted`，之后没有 `PreToolUse` 或 `SpecialistFinished`，说明卡在 Specialist 内部。另外 LLM 相关的 trace 可以单独过滤查看，方便排查 LLM 输出质量问题。"

### 可能的追问

**问："Trace 文件会不会很大？你怎么处理的？"**

答：jsonl 格式本身就是增量写入的，不会撑爆内存。文件大小取决于 run 的复杂度——一个典型的 Vivado 综合 run 的 trace 大概几十 KB。如果将来数据量大，可以做轮转或者只保留最近 N 个 run 的 trace。但原型阶段这完全不是问题。

---

## 10. LLM Guard：防止 LLM"胡说八道"

### 大白话解释

LLM 什么都能生成，但它生成的东西不一定对、不一定安全、不一定符合你的系统规则。

打个比方：LLM 像一个想象力过剩的实习生，你让它"写一个 Dense 算子的 HLS 实现"，它可能交回来一份包含 `system("rm -rf /")` 的代码。不是因为它恶意，而是因为你没有告诉它边界在哪里。

**LLM Guard** 就是在 LLM 输出之后、系统执行之前的一道检查关卡。它不依赖 LLM 的自觉，而是用代码规则去校验。

### 在你项目中的位置

`src/dl_op_to_hls/llm/guards.py`。

你的 LLMGuard 校验四类内容：

**1. Todo Plan 校验**（`validate_todo_plan`）：

```python
# 检查 LLM 生成的 Todo 计划是否合理：
- 每个 todo 的 assigned_tool 是不是真实存在的工具？
- 每个 todo 的 assigned_specialist 是不是真实存在的 Specialist？
- 如果工具是某个 Specialist 的私有工具，有没有分配给那个 Specialist？
- 如果工具和 Specialist 都指定了，工具在不在 Specialist 的 allowed_tools 里？
- 如果生成了 LLM candidate，有没有安排验证步骤？

# 例子：如果 LLM 计划了 "assigned_tool: vivado.run_csynth, assigned_specialist: HLS4MLSpecialist"
# → 拒绝！因为 vivado.run_csynth 不在 HLS4MLSpecialist 的 allowed_tools 中
```

**2. ReAct 决策校验**（`validate_react_decision`）：

```python
# 检查 LLM 的 ReAct 决策是否合法：
- decision 在不在允许的动作列表中？
  （delegate_to_specialist, direct_tool_only_when_no_specialist, request_replan, mark_blocked, mark_failed）
- 如果是 "direct_tool_only_when_no_specialist"，工具在不在允许工具中？
- 如果是 "delegate_to_specialist"，有没有指定 specialist_name？
```

**3. Reflection 校验**（`validate_reflection`）：

```python
# 检查 LLM 的反省会是否合理：
- 有没有 new_todos？
- todo_status 是不是合法的状态值？
- 如果当前没有 selected_skill，不能 "switch_skill"
```

**4. Candidate 文件校验**（`validate_candidate_files`）：

```python
# 检查 LLM 生成的候选代码文件是否安全：
- 有没有把 status 设成 "verified"？（不行，必须走验证流程）
- 文件路径是不是相对路径？（不能是绝对路径）
- 文件是不是在 runs/<run_id>/candidate 目录下？（不能写到外面）
```

**你的 CandidateSandbox**（`src/dl_op_to_hls/core/candidate_sandbox.py`）则更进一步，扫描文件**内容**：

```python
# 用正则扫描 HLS C++ 代码，拦截：
- system()           # 系统调用
- popen()            # 进程创建
- CreateProcess / fork / exec   # 进程创建 API
- #include <cstdlib> / <fstream> / <filesystem> / <windows.h> / <unistd.h>  # 危险头文件
- #include <winsock2.h> / <sys/socket.h>  # 网络头文件
- __asm__ / asm()    # 内联汇编
```

### 面试话术

> "LLM 的输出不能直接信任。我实现了一个多层 Guard 体系：Plan Guard 确保 Todo 计划中工具和 Specialist 的匹配正确；ReAct Guard 确保 LLM 决策在允许的动作范围内；Reflection Guard 确保动态追加的 Todo 也符合约束；Candidate Guard 确保生成的代码文件路径不越界；最后 CandidateSandbox 用静态模式扫描代码内容，拦截系统调用、危险 include 等。这个体系的设计理念是'零信任'——不对 LLM 的输出做任何假设，一切都用规则校验。"

### 可能的追问

**问："Guard 如果拒绝了 LLM 的输出怎么办？"**

答：取决于运行模式。在 strict 模式下（开发期），直接报 `LLMGenerationError` 并记录结构化错误到 trace，不会静默 fallback。这确保我能看到 guard 触发的原因，从而改进 prompt、skill、或 guard 规则本身。在 demo 模式下，优化建议等非关键路径可以有规则兜底。这个设计选择反映了一个理念：**开发期应该暴露问题，不是掩盖问题**。

**问："CandidateSandbox 能覆盖所有安全风险吗？"**

答：不能，也不应该试图做到。静态模式扫描只能拦截已知的危险模式。一个精心构造的恶意代码可能绕过正则匹配。但 HLS C++ 本身的约束（无动态内存分配、无递归、无系统调用）天然限制了攻击面。三层防护（PermissionGate 限目录 + LLMGuard 限路径 + CandidateSandbox 扫内容）的组合比单层防护强得多——攻击者需要同时绕过三层才能造成实际损害。

---

## 11. Plan-Execute-ReAct Hybrid：混合运行时

### 大白话解释

前面讲了 ReAct（边想边做）。但纯 ReAct 有一个问题：如果任务有很长的步骤链（比如 HLS 综合需要 10 个步骤），纯 ReAct 可能迷失方向——它只关注"下一步做什么"，看不到"我们的大目标是什么"。

纯 Plan-Execute 有相反的问题：它一开始就规划好所有步骤，但无法应对中间的变化。比如规划了"步骤 5：Vivado 综合"，但步骤 4 发现 hls4ml 不支持当前模型，整个计划就作废了。

**Plan-Execute-ReAct Hybrid（混合模式）** 结合了两种思路：

- **外层（Plan-Execute）**：有一个总体计划（Todo 列表），确保不迷失方向
- **内层（ReAct）**：每个 Todo 执行时可以灵活应变，根据工具返回的结果动态调整
- **Reflection（反射）**：执行完一个 Todo 后，根据需要追加、跳过、修改后续 Todo

### 在你项目中的位置

`src/dl_op_to_hls/main_agent/runtime.py` 的 `PlanExecuteReactRuntime`：

```python
def run(self, task_path):
    state = self.initialize(task_path)      # 初始化
    state = self.retrieve_initial_memory(state)  # 检索历史记忆
    state = self.plan(state)               # 生成计划（Plan）
    state = self.create_todos(state)       # 创建 Todo 列表
    state = self.execute_todos(state)      # 逐个执行（Execute + 内层 ReAct）
    state = self.finalize(state)           # 生成总结、建议、记忆
```

`execute_todos` 的核心循环：

```python
while self.todo_manager.has_pending_or_ready():
    todo = self.todo_manager.get_next_ready_item()  # 取下一个就绪的 Todo
    observation = self.execute_todo_with_react(state, todo)  # 执行 + 内层 ReAct
    state = self.reflect(state, todo, observation)  # Reflection：根据结果调整后续 Todo
    if self.should_stop(state):  # 检查终止条件
        break
```

**Reflection 的核心作用**（`reflect` 方法中的分支逻辑）：

```python
if todo 是 "Check hls4ml support" 且结果是 "unsupported":
    → 追加 "Try graph rewrite" Todo
    → 追加 "Generate fallback HLS template" 或 "Generate unsupported report" Todo

if todo 是 "Verify LLM candidate" 且失败了，且还没到最大重试次数:
    → 追加 "Generate LLM candidate"（修复模式）
    → 如果已经到了最大重试次数:
        → 追加 "Generate unsupported report"，并取消后续的 Vivado 综合步骤
```

这就是混合模式的价值——不是死板地执行初始计划，而是根据执行结果动态调整。

### 面试话术

> "纯 ReAct 和纯 Plan-Execute 都有各自的弱点。我采用了混合模式：外层有一个 Todo 驱动的 Plan-Execute 框架保证整体方向不迷失；内层每个 Todo 执行时做 ReAct 决策保证局部灵活性；Reflection 阶段可以根据执行结果动态追加、跳过或取消后续 Todo。比如当 hls4ml 不支持某个模型时，Reflection 会自动追加 graph_rewrite 和 fallback 步骤，同时取消原来的 Vivado 综合步骤。这种设计兼顾了结构化（可追踪、可恢复）和灵活性（可动态调整路径）。"

### 可能的追问

**问："Reflection 会不会导致无限循环——一直追加新的 Todo？"**

答：有保护机制。LLM candidate 修复最多重试 2 次，超过就转 unsupported。Todo 有明确的状态流转（pending → in_progress → completed/failed/skipped），不会回退到 pending。有终止条件——比如 unsupported_path 的 unsupported report 生成后，`should_stop()` 返回 true。Todo 依赖图也保证了顺序——不会出现两个 Todo 互相依赖的死锁。

---

## 12. 两层 ReAct 设计

### 大白话解释

你的项目有两层决策体系，这是从 Claude Code 源码泄露中借鉴的核心架构思想。

**Main Agent ReAct**（主控层）：负责"宏观调度"。它只能做 5 种高层动作：

```
delegate_to_specialist     → "这事交给 Vivado 专家做"
direct_tool_only_when_no_specialist  → "没有专家能处理，我自己用这个工具"
request_replan             → "方向错了，重新规划"
mark_blocked               → "卡住了，标记阻塞"
mark_failed                → "彻底失败了，记录原因"
```

Main Agent **不能**做的事情：直接调用 `hls4ml.check_support`、直接调 `vivado.run_csynth`、直接操作底层工具的输入参数。

**Specialist Local ReAct**（专家层）：负责"微观执行"。每个 Specialist 内部有自己的局部决策，只能做 4 种动作：

```
call_tool          → "先调这个工具"
mark_blocked       → "参数不全，标记阻塞"
mark_failed        → "工具返回错误，标记失败"
finish_with_result → "做完了，返回摘要"
```

Specialist **不能**做的事情：决定全局方向（那是 Main Agent 的事）、访问其他 Specialist 的私有工具、修改全局 AgentState。

### 为什么这样分层？

从你的开发日志中能找到具体证据。在 2026-06-01 的日志里：

> "Main Agent 已经做了 LLM ReAct 决策，Specialist 内部 local ReAct 又默认使用 LLM decider"

也就是说，最初你没有分层，Specialist 内部也在调 LLM 做决策。结果是 OptimizationSpecialist 卡住不动——Main Agent 调一次 LLM 做高层决策，把任务交给 OptimizationSpecialist，然后 OptimizationSpecialist 内部又调 LLM 做局部决策，而 OptimizationSpecialist 本身的任务就是调 LLM 生成优化建议。LLM 调 LLM 调 LLM，在 API 限速环境下直接变成性能灾难。

修复就是：**Specialist 局部 ReAct 默认使用确定性决策**，不走 LLM。只有显式配置 `DL_OP_TO_HLS_SPECIALIST_LLM_DECIDER_ENABLED=1` 时才启用 LLM。

### 代码位置

- Main Agent ReAct：`src/dl_op_to_hls/llm/react.py`
- Specialist ReAct：`src/dl_op_to_hls/specialists/react.py`
- 两层决策的串联：`src/dl_op_to_hls/specialists/base.py` 中的 `_local_react_step()`

### 面试话术

> "两层 ReAct 是我从 Claude Code 泄露源码中学到的核心设计。Main Agent 的 ReAct 只做 5 种宏观动作——委派专家、直接调工具、重规划、标记阻塞、标记失败。它不能直接看到 Specialist 的私有工具。Specialist 的 ReAct 只做 4 种局部动作——调工具、标记阻塞、标记失败、返回结果。它不能决定全局方向。更重要的是，我从实际运行中得到了一个教训——Specialist 内部的 LLM 决策会导致性能灾难，所以我把它默认关掉了，改为确定性决策。这个设计的安全性和性能提升都有真实数据支撑。"

---

## 13. 真实/mock 模式切换

### 大白话解释

你的项目需要同时满足两种场景：

1. **演示/开发场景**：没有真实的 Vivado HLS 环境（或者不想等几十分钟的综合），但想展示 Agent 的完整工作流
2. **真实运行场景**：连接真实的 Vivado HLS、真实的 hls4ml、真实的 LLM API，做真正的 HLS 综合

Mock 模式就是"假装做了"——生成模拟的综合报告、模拟的模型检查结果、模拟的 LLM 候选代码。

真实模式就是"真的做了"——调用本机的 `vivado_hls.bat`、真实的 hls4ml Python 库、真实的 LLM API。

**关键原则**：这两种模式绝对不能混。你的开发日志里记录了之前的一个严重 bug——`verify_candidate.run` 在真实模式下也会生成假的报告并返回 `verified`。这意味着生成的代码可能从未被真实验证，就被标记为"已验证"并存入长期记忆。

### 在你项目中的位置

切换逻辑分散在多个地方：

- `core/config.py`：`mock_hls4ml`、`mock_vivado` 配置项，默认从环境变量读取
- `adapters/hls4ml_adapter.py`：每个方法开头检查 `self.mock_mode`，决定走 mock 分支还是真实分支
- `adapters/vivado_hls_adapter.py`：同上
- `tools/verify_candidate.py`：`_use_mock_verification()` 判定，然后分 `_mock_verify()` 和 `_real_verify()`

### 面试话术

> "Mock 模式和真实模式的边界是我在开发中重点修复的问题。之前有一个严重的 bug——验证工具在真实模式下也会写 mock 报告并返回'已验证'。这意味着未经真实 Vivado 验证的代码可能被存入长期记忆。我做了系统性的修复：每个 adapter 方法都根据 mock_mode 做显式分派；verify_candidate 在真实模式下要求 candidate 目录和 testbench 都存在，并通过 Vivado adapter 完成完整的项目创建→综合→报告解析链条；hls4ml adapter 增加了 placeholder 模型检测和 QKeras/H5 前端识别，避免把不支持的文件格式当成正常输入。Mock 模式只在明确配置或 `DL_OP_TO_HLS_MOCK_*=1` 时才启用。"

### 可能的追问

**问："你怎么保证以后不会再出现 mock/真实 混淆的 bug？"**

答：第一，每个方法的 mock_mode 分派在方法最开头，是第一个 if-else，不会被后续逻辑跳过。第二，测试覆盖了两种模式的关键路径。第三，trace 中会记录工具的模式（mock vs real），可以事后审计。

---

## 14. 如何讲你在开发日志中的 Bug 故事

面试官特别喜欢问："你在项目中遇到过什么困难？怎么解决的？"

你现在有一整本开发日志可以讲。以下是几个最容易讲好、也最能展示能力的故事。

### 故事 1："8 个 Demo 全部失败"

**背景**：2026-06-01，你第一次用真实 LLM API 跑全量 Demo0-Demo6。

**问题**：8 个 Demo 全部 failed。表如下：

| Demo | 失败原因 |
|---|---|
| Demo0-Demo4 | LLM ReAct 响应缺少 `decision` 字段 |
| Demo5-Demo6 | LLM planner 生成的计划违反了 Skill allowlist |

**你怎么排查的**：不是看屏幕输出（输出被 hls4ml stdout 污染了），而是看每个 run 目录下的 `trace.jsonl` 和 `state.json`。发现了两个不同的问题。

**你怎么修的**：
- 针对 `decision` 缺失：Schema 加 enum 约束 → Prompt 加强示例 → 新增一次 JSON repair 回合 → repair 失败写脱敏 debug artifact
- 针对 Skill 违反：对齐 skill YAML allowlist → 收紧 planner 的 capability exposure → Main Agent 不再直接看到 Specialist 私有工具

**面试时怎么讲**：

> "最有意思的一个 bug 是我第一次用真实 LLM API 跑全量 Demo 的时候——8 个 Demo 全部失败。这不是 API 挂了，而是 OpenAI-compatible 模型输出的 JSON 不够稳定。我做了三步修复：在 schema 层加 enum 约束，在 prompt 层加强示例，在客户端层加一次 JSON repair——但有个原则，repair 只修复结构和缺失字段，不改变语义。最重要的是，我选择不在开发期做静默 fallback，而是让错误暴露出来。因为如果你在开发期把错误掩盖了，你就不知道你的 Agent 架构到底哪里有问题。"

### 故事 2："Mock 工具伪装成真实成功"

**背景**：在检查代码时发现 `verify_candidate.run` 无论真实还是 mock 模式都返回 `verified`，`hls4ml.run_csim` 都写 "Mock hls4ml csim completed successfully"。

**问题**：未经真实 Vivado 验证的代码可以被标为"已验证"并存入长期记忆，后续的优化建议可能基于假数据。

**你怎么修的**：
- verify_candidate：新增 `_use_mock_verification()` 判定，mock 走 `_mock_verify()`，真实走 `_real_verify()`（要求 testbench 存在 + Vivado adapter 完成完整链条）
- hls4ml.run_csim：真实模式下不再写假成功日志，而是根据项目状态返回不同的结构化错误
- 修复后写测试覆盖两种模式

**面试时怎么讲**：

> "我发现了一个比较隐蔽的安全问题——验证工具在真实模式下也会返回假的'已验证'结果。这意味着 LLM 生成的候选代码可能从未经过真实的 Vivado 综合，就被当成正确实现存入了长期记忆。后续的优化建议也会基于这个假数据。根因是 mock 和真实模式的代码路径没有分离。我做了完整的重构，让验证工具在真实模式下走真正的 Vivado 调用链——创建工程、运行 TCL、解析报告——任何一步失败都返回结构化错误。同时加了测试覆盖，确保两种模式的边界清晰。"

### 故事 3："真实 hls4ml stdout 污染 CLI JSON"

**背景**：Demo2 真实运行时，CLI 的 JSON 输出无法被 PowerShell `ConvertFrom-Json` 解析。

**排查**：发现 hls4ml 库的 `config_from_onnx_model` 和 `convert_from_onnx_model` 会直接向 stdout 打印 "Output layers"、"Topology" 等信息，和 CLI 的 JSON state 输出混在一起。但文件系统里的 `state.json` 和 `summary.md` 都是正常的。

**修复**：在 adapter 调用第三方库的地方加 `contextlib.redirect_stdout`，把 stdout 重定向到 log artifact。

**面试时怎么讲**：

> "有一个有趣的 bug——CLI 输出 JSON 时总是解析失败，但文件系统里的 state.json 是正常的。排查发现是第三方库 hls4ml 在调用时向 stdout 打印了日志，和我的 JSON 输出混在一起。这个 bug 的教训是：当你集成第三方库时，永远不要假设它们会安静运行。我用 Python 的 redirect_stdout 把第三方输出捕获到日志文件，CLI stdout 保持干净的 JSON。"

---

## 15. 面试话术速查表

以下是面试中高频问题和你应该给出的回答要点的速查表。不要在面试中逐字背诵——理解这些点，用自己的话讲。

### 开场自我介绍（1 分钟版本）

> "我最近做了一个 AI Agent 工程项目，叫 dl-op-to-hls-agent。它的功能场景是帮助 FPGA 开发者把深度学习模型转成 HLS 实现——但我的重点不是 FPGA 领域本身，而是 Agent 工程架构。这个项目包含：统一的工具注册和权限控制、基于 Plan-Execute-ReAct 的混合运行时、用于上下文隔离的 Specialist 子代理体系、五层记忆系统、LLM 输出的多层 Guard 校验、以及完整的 trace 可观测性。项目在 mock 模式下有 150+ 个通过测试，真实 Vivado HLS 环境下的核心路径也已经跑通。"

### 核心概念一句话版本

| 概念 | 一句话 |
|---|---|
| Agent | 能在运行时根据观察做决策的系统，不是死板执行预定步骤的脚本 |
| ReAct | 推理和行动交织的循环：观察 → 推理 → 行动 → 再观察 |
| Tool | Agent 调用外部世界的能力（读写文件、运行命令、调 API） |
| ToolRegistry | 统一工具箱：所有工具通过同一个入口调用，自动做权限检查和追踪 |
| PermissionGate | 安全护栏：限制能读写的目录和能执行的命令 |
| Skill | 标准作业流程：定义了某类任务的推荐步骤、可用工具、失败处理 |
| Specialist | 领域专家：隔离执行特定领域的任务，只返回压缩结果 |
| ContextEnvelope | 限定范围的信息包：不让 Agent 看到不相关的原始数据 |
| TokenBudget | 注意力管理：确保传给 LLM 的内容不超过其上下文窗口限制 |
| Memory | 分层记忆：短期 → 情景 → 语义 → 技能，越重要的越持久 |
| RAG | 外部知识检索：从历史数据中找出最相关的内容，喂给 LLM |
| Trace | 黑匣子：记录系统里发生的每一件事，用于调试和审计 |
| Guard | 安全关卡：LLM 输出必须通过代码规则校验才能执行 |

### 你的项目的亮点（面试中主动提）

1. **不是 demo 级项目**：有完整的工程架构，不是"调个 API + 写个 prompt"就完了
2. **真实跑通过**：DeepSeek + Vivado HLS 真实环境下的 Demo0 完整成功（Dense 算子，latency 269 cycles，DSP=16，LUT=549，FF=732，timing met）
3. **有失败后的系统修复**：从 8 个 Demo 全量失败到逐一修复，开发日志记录了完整过程
4. **安全设计不是事后加的**：PermissionGate + LLMGuard + CandidateSandbox 三层防护
5. **借鉴了业界前沿设计**：Claude Code 源码泄露中的分层隔离、多层验证等思想
6. **知道什么不该修**：有明确的未修复原因记录，展示工程判断力

### 面试中要保持的心态

1. **诚实承认边界**：不知道就说不知道，不要硬编。面试官更看重你"知道自己不知道什么"。
2. **用项目中的具体例子回答问题**：不要说"我认为 Agent 应该是这样设计的"，要说"在我的项目中，我是这样处理的，因为我遇到了这样一个问题..."
3. **展示迭代过程**：不要说"我设计了一个完美的系统"，要说"我先做了一版，然后发现 X 不工作，于是我查了 Y，修复了 Z，现在它好了"。
4. **主动提安全性**：Agent 安全是 2025-2026 年的热门话题。主动提到 PermissionGate、Guard、Sandbox 会加分。
5. **如果被问到不会的概念**：可以说"这个概念我在项目中还没有直接用到，但我理解它大概是什么——能不能请您稍微解释一下，我结合我的项目经验谈谈我的理解？"
