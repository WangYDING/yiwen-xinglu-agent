# Agent 项目面试回答手册

> 适用岗位：AI Agent 工程、游戏 AI、LLM 应用工程、Agent Runtime/平台工程。  
> 使用方式：先背“结论句”，再用代码证据展开。不要把本手册逐字朗读，也不要把设计目标说成已经证明的效果。  
> 当前代码证据：2026-09-27 本地完整回归 `674 passed in 54.40s`。它只证明代码回归通过，不代表线上成功率、真人体验或模型能力收益。

## 第一部分：项目核心定位

### 1. 产品角度：这个项目是什么

《异闻行录》是一个本地运行的古风志怪调查游戏。玩家与一个由 `GameNPCAgent` 驱动的调查搭档共同完成六个案件：玩家可以用自然语言提出假设、质疑、证据解释和行动建议，NPC 会评价这些贡献，维护调查目标和计划，在公开线索范围内选择下一步，并在诊断或高风险处置前与玩家协商。

它解决的产品问题不是“让 NPC 说得更像人”这么简单，而是：

- 让 NPC 能理解玩家没有预先写入脚本的表达；
- 让 NPC 的判断、行动和长期经验具有连续性；
- 同时保证 NPC 不偷看隐藏答案、不把玩家一句话当成授权、不绕过案件规则；
- 让失败、拒绝、确认和状态变化可以解释、恢复和测试。

用户通过本地 Web 入口 `yiwen-xinglu` 使用。每次提交形成一个 `PlayerContribution`，系统执行一个 cooperative turn，返回 NPC 回复、行动状态、环境反馈以及必要的确认请求。正式服务只绑定 `127.0.0.1`，不是公网 SaaS。

### 2. Agent 技术角度：为什么它是 Agent

它不是只根据当前一句话生成回复的 Chatbot，也不是只有固定台词树的普通 NPC。真实实现中具备以下 Agent 要素：

| Agent 要素 | 当前真实实现 | 代码证据 |
|---|---|---|
| 状态 | World、Player、Campaign、Goal/Plan、History、Memory 分域持久化 | `domain/*`, `storage/*` |
| 目标 | `AgentGoalState`，含类型、完成条件、状态和 revision | `domain/cooperative_planning.py` |
| 计划 | 有序 `AgentPlan` / `PlanStep`，可保持、修订、完成或放弃 | 同上；`plan_evaluator.py` |
| 决策 | LLM 根据 Observation、贡献、Goal/Plan、Memory 生成结构化 Proposal | `agents/game_npc.py::propose_turn` |
| 行动 | Proposal 经验证后可形成一个 `AgentAction` / ToolCall | `domain/actions.py` |
| 环境反馈 | Tool 执行后重读 `CaseObservation`，由 PlanEvaluator 处理真实结果 | `cooperative_runtime.py` |
| 持续性 | 每个 HTTP 请求执行一个 turn，跨 turn 依靠持久 State/History/Memory 连续 | Runtime + Store |

“持续运行”要准确解释：它不是在一个请求里无限 `while` 自循环，而是 **request-scoped turn + persistent continuity**。任务连续性来自下一次请求重新读取已提交状态。

它也不是纯 Workflow。Workflow 决定不可违反的执行协议；LLM Agent 动态完成贡献评价、Goal/Plan proposal、候选行动选择和解释。最准确的描述是：

> **一个受约束的、状态化、工具使用型 Cooperative Game NPC Agent。**

### 3. 工程角度：本质是什么系统

工程上，它是四个系统的组合：

1. **Agent Runtime**：`CooperativeRuntime` 编排一个 turn 的观察、检索、决策、验证、执行和状态更新。
2. **显式状态系统**：JSON 保存 World/Player/Campaign/Agent State，SQLite 保存 Memory、Reflection receipt 和 cooperative history。
3. **受约束决策系统**：`GameNPCAgent` 只提交 Proposal；Policy、Contract、Alignment 和 Authority 决定它能否继续。
4. **确定性执行系统**：`CaseToolExecutor` 将 Action 转成 typed command，`CaseEngine` 独占案件规则与 world transition。

一句工程定位：

> **这是一个把概率型 LLM 决策嵌入确定性领域执行链的单 Agent 系统。**

## 第二部分：30 秒项目介绍

### 版本 A：HR / 开场版

“我做的是《异闻行录》，一个可在本地运行的 AI 调查搭档项目。玩家可以用自然语言和 NPC 一起分析六个志怪案件，NPC 不只是聊天，还会维护目标和计划、使用调查工具、记住过去经历，并根据真实环境反馈调整行动。工程上我把大模型限制在‘提出建议’这一层，真正的权限校验、工具执行和状态修改由确定性程序负责。当前完整代码回归是 674 项通过；同时我也明确保留了 Memory 效果、跨进程并发和恢复能力尚未完全证明的边界。”

### 版本 B：技术面版

“这是一个单 Agent、显式 State、受约束执行的 Cooperative Game NPC。一次玩家输入由 `CooperativeRuntime` 恢复 Observation、Goal/Plan、History 和 scoped Memory，经 `ContextAssembler` 形成模型上下文，`GameNPCAgent` 输出结构化 Goal/Plan/Action Proposal。Proposal 依次经过 Planning Policy、两次 Plan—Decision alignment、Action Contract 和 Authority，合法后才进入 `CaseToolExecutor` 与 deterministic `CaseEngine`。world 提交后系统重读 Observation、评估 Plan，再更新 Agent State、Memory 和 Reflection。LLM 没有直接写状态或扩大权限的能力。”

## 第三部分：3 分钟项目介绍

### 可直接口述版本

“这个项目叫《异闻行录》，产品上是一个古风志怪调查游戏，技术上是一个 Human-Agent Cooperative Game NPC 系统。我做它的原因是传统脚本 NPC 虽然稳定，但面对玩家开放的假设、质疑和证据组合很难覆盖；普通 Chatbot 又通常只有对话，没有目标、行动和权威环境反馈，容易把‘说过了’误当成‘做到了’。

我的核心设计是把 Agent 的语义决策和系统的执行权拆开。一次玩家输入先被建模为 `PlayerContribution`。`CooperativeRuntime` 从持久化状态恢复案件 Observation、玩家能力、Agent 的 Goal/Plan、协作历史和跨 session Memory，再构造 `GameNPCAgentInput`。`ContextAssembler` 只放公开信息，隐藏真相不会进入 Prompt；最终 payload 还会经过 tokenizer-aware budget，历史和 Memory 可按优先级裁剪，必选内容放不下就 fail closed。

`GameNPCAgent` 通过 LLM 一次性提出 Goal、Plan 和当前 Decision，但这个输出只是 Proposal。程序先验证 Goal/Plan 是否与公开行动空间一致，再检查当前 Action 是否匹配 active PlanStep；之后通过 `PublicActionContractValidator` 验证 Tool、target 和参数，必要时只允许一次有限 repair；因为 repair 可能改变 Action，所以还会再做一次 alignment。最后 `NPCAuthorityPolicy` 判断它是可自主调查、只提案、需要玩家确认，还是禁止执行。

真正执行时，`CaseToolExecutor` 把 ToolCall 转成强类型 Engine command，`CaseEngine` 负责调查前置、证据发现、诊断、处置、结局和评分。只有 Engine 接受并成功提交的事件才是世界事实。提交后 Runtime 会重读新的 Observation，由确定性 PlanEvaluator 判断计划步骤是否完成，再保存 Agent State。

Memory 也不是把聊天历史直接塞进向量库。普通 Memory 只从已提交事件投影；Reflection 只基于真实结果形成候选经验，并经过 grounding 和写入策略。检索时按玩家、来源 session、类型、生命周期和冲突过滤，再以 BGE-M3 做语义排序。系统还记录 selected、declared 和 accepted，区分‘检索到’与‘真的影响了决策’。

从仓库能确认的工作包括这套架构、实现和测试证据，但仅凭仓库不能证明每一部分的个人归属，所以面试中我会按自己的真实提交说明负责范围。如果我的实际贡献覆盖了 Runtime、Context、Policy 和评测，我会重点讲这些，并用代码和故障注入测试说明。当前完整回归是 674 项通过；不过我不会把它说成线上成功率。项目仍有明确不足：多存储没有全局事务，pending confirmation 还不持久，跨进程 CAS 未完成，Memory、Reflection 和 A1 Planning 的行为收益也还需要更严格评测。”

### “我的贡献”安全表达模板

仓库不能证明个人贡献比例，请从下面选择与你真实经历一致的内容，并删除未参与项：

“我主要负责了 **[架构设计 / Runtime 主链 / Context 与 Token Budget / Planning 与 Action Contract / Memory/Reflection / 故障恢复 / Evaluation]**。我不是只写 Prompt，而是把 **[具体模块]** 从数据结构、运行链、失败处理到测试闭环落地。AI 辅助了代码搜索、样板生成和测试分析，但关键架构边界、验收标准、故障判断和最终修改由我审查并验证。对于 **[未亲自完成的模块]**，我能解释接口和调用关系，但不会声称是我独立实现。”

## 第四部分：10 分钟深度介绍

### 第一层：整体架构与原因

“我先给结论：这是一个 deterministic workflow 中嵌入 constrained agentic decision core 的系统。之所以混合，是因为玩家输入具有开放语义，需要 LLM；但案件真相、权限和状态提交必须确定，不能依赖 Prompt 自律。

主链是：`PlayerContribution → Observation/State → Context → GameNPCAgent Proposal → Policy/Contract/Authority → Executor → CaseEngine → world commit → refreshed Observation → Plan/Memory/Reflection update`。每个 cooperative turn 最多执行一个 Tool。”

### 第二层：Runtime

“Runtime 在 `application/cooperative_runtime.py`，核心是 `CooperativeRuntime.handle()`。它不是模型，也不是 Engine，而是控制面。它恢复状态、检索 Memory、构造 Agent input、调用 Agent、执行校验链、处理确认、提交 Tool、重读环境并收口状态。

为什么需要它？因为 Agent 输出是不可信候选，Engine 又只理解强类型命令，中间需要一个组件管理生命周期、顺序和失败语义。例如 world commit unknown 不能当普通 Tool failure 重试；world 已提交但 PlanEvaluator 失败也不能说行动没发生。Runtime 和外层 `ClinicService` 会把这些情况区分为 commit uncertain 或 committed follow-up incomplete。”

### 第三层：State

“World State 是 `CaseSessionState`，包含行动历史、已发现线索、诊断、处置、status 和 revision，是案件事实权威。Agent State 是 `CooperativeAgentState`，保存 Goal、Plan、PlanEvaluation 和下一轮可见的安全反馈，表示意图，不是世界真相。Player 和 Campaign 另有状态；History 和 Memory 使用 SQLite；pending confirmation 当前在进程内。

显式 State 比全 Prompt 更可靠，因为它有 ownership、revision、schema、生命周期和写权限。Prompt 只是某一轮的只读投影，不是数据库。”

### 第四层：Context

“LLM 每轮看到 public PlayerView、CaseObservation、当前贡献、Goal/Plan、上一评价、Authority view、有效历史、scoped Memory 和公开 Action Space。它看不到隐藏线索、正确答案、内部存储错误或未授权能力。

Context 分四层：`AgentContextFilter` 做公开投影；`build_context_snapshot()` 选历史和 pending；Memory service 返回安全投影；`ContextAssembler` 渲染 initial/repair 请求。DeepSeek adapter 在加入完整 Schema 和 provider framing 后做最终 token 预算。”

### 第五层：Decision

“`GameNPCAgent.propose_turn()` 生成 `GameNPCTurnProposal`，里面包含 Goal/Plan 变更、贡献评价、Action 和 Memory 使用声明。结构化调用最多一次 initial 加一次 format repair；Action Contract 还有一次专用、受限 repair。失败就返回不执行 Tool 的 safe fallback。

这不是模型直接完成任务，而是模型在公开候选空间内做语义选择。程序仍会检查它是否与 Goal、Plan、target、arguments 和权限一致。”

### 第六层：Execution

“Proposal 经验证后形成 `AgentAction`。RESPOND 不调用 Tool；诊断或处置可能生成 `PendingActionConfirmation`；只有 Authority 允许的动作才进入 `MultiCaseEpisodeService.submit_action_with_receipt()`。`CaseToolExecutor` 严格解析参数并生成 `InvestigationCommand`、`SubmitDiagnosisCommand` 或 `ExecuteTreatmentCommand`。`CaseEngine` 计算新的 Session 和事件，应用层负责持久化。”

### 第七层：Memory

“写入侧是 world-first：先保存成功的 world，再由 `V1MemoryCoordinator` 将已提交事件投影为 Memory，失败则标记 projection pending 并可从 world 对账。读取侧由 `GameNPCMemoryRetrievalService` 构造查询、按 scope 检索、过滤并投影为 `AgentMemoryContext`。Memory 是非权威经验，不能覆盖当前 Observation。

Reflection 在回合后基于 evidence bundle 生成候选 lesson，再经 validator 和 consolidation 才能写入。同一个模型总结本身不是事实。”

### 第八层：Reliability

“可靠性不是单个 Prompt，而是多层控制：Pydantic schema、GoalPlanPolicy、两次 alignment、Action Contract、Authority、Executor 参数模型、Engine rules、revision、Session lock、operation ledger、world-first commit、reconciliation 和 safe fallback。

我也会主动说明限制：进程内锁不等于跨进程 CAS；JSON/SQLite 没有全局事务；pending 不 durable；没有完成公网认证、多租户隔离和系统性攻击测试；Memory/Reflection/Planning 的行为收益还没有充分证明。当前 674 项回归说明工程边界有较强覆盖，但不是生产安全认证。”

## 第五部分：白板讲解模板

### 5～8 个框版本

```text
[玩家输入 / PlayerContribution]
                ↓
[CooperativeRuntime + Explicit State]
                ↓
[Context Assembly: Observation + Goal/Plan + History + Memory]
                ↓
[Single GameNPCAgent / LLM]
                ↓
[Structured Proposal]
                ↓
[Policy + Alignment + Contract + Authority]
                ↓
[CaseToolExecutor → Deterministic CaseEngine]
                ↓
[World Commit → Observation / Agent State / Memory / Reflection]
```

### 每个框讲什么

1. **玩家输入**：自然语言先成为有类型的贡献，不直接成为 ToolCall。
2. **Runtime + State**：一次请求一个 turn；恢复多个权威状态并管理失败顺序。
3. **Context**：只投影公开事实，历史/Memory 有范围和 token budget。
4. **Agent/LLM**：负责语义判断、Goal/Plan 和候选 Action，不写 State。
5. **Proposal**：顶层强类型对象，不等于执行结果。
6. **控制链**：验证计划、业务参数和权限；repair 后重新对齐。
7. **Executor/Engine**：把候选动作转成 typed command，唯一改变 world 的规则源。
8. **状态更新**：先 world，再 Memory、post Observation、PlanEvaluator、Agent State 和 Reflection；多存储无全局事务。

白板最后补一句：“MCP 是独立外部工具适配入口，不是这条 Web Cooperative Agent 主链的内部 Runtime。”

## 第六部分：项目核心问题回答库（50 题）

> 使用方法：先说推荐回答第一句，再根据面试官兴趣展开后续段落。代码位置用于证明，不需要现场全部打开。

### Q1：为什么这是 Agent，而不是 Chatbot？

**面试官考察：** 是否能用闭环能力而不是“用了大模型”定义 Agent。

**推荐回答：** “因为它不只生成文本，而是维护 Goal/Plan 和长期状态，基于 Observation 作出结构化决策，能提出 Tool Action，接收真实环境反馈并跨 turn 调整计划。” Chatbot 的成功通常止于回复质量；本项目的成功必须由 Engine event、world commit 和 post Observation 证明。连续性不是靠把整段聊天都塞回 Prompt，而是显式 Agent State、History 和 Memory。

**本项目依据：** `CooperativeRuntime.handle()`；`CooperativeAgentState`；`GameNPCAgent.propose_turn()`；`CaseEngine.execute()`。

### Q2：它和传统脚本 NPC 有什么区别？

**面试官考察：** LLM 在项目中是否有不可替代价值。

**推荐回答：** 传统脚本适合确定台词树和固定触发条件，但难以覆盖玩家对同一证据的多种自然表达、反驳和组合推理。本项目让 LLM 负责贡献评价、动态 Goal/Plan 和公开候选中的行动选择；脚本/规则仍负责隐藏真相、前置条件、权限和状态变化。因此它不是删除脚本，而是把脚本从“决定全部行为”收缩为“定义不可违反的世界规则”。

**本项目依据：** `PlayerContributionEvaluation`；`GameNPCTurnProposal`；`engine/case_engine.py`；病例资源 JSON。

### Q3：为什么不用纯脚本实现？

**面试官考察：** 是否理解开放输入与可枚举规则的边界。

**推荐回答：** 纯脚本可以稳定执行调查，但需要提前枚举玩家意图、说法和证据组合，交互很容易退化为菜单。项目需要 NPC 理解“我部分同意，但这个证词和时间线冲突”之类开放表达，并用自然语言解释判断，这部分由 LLM 更合适。可形式化的 action legality 和 world transition 则继续脚本化。

**本项目依据：** `domain/cooperation.py` 的贡献类型/Disposition；`agents/game_npc.py`；`application/action_contract.py`。

### Q4：Agent 的自主性具体在哪里？

**面试官考察：** 是否把“自主”误解成无边界权限。

**推荐回答：** 自主性体现在它可以独立评价玩家意见、提出或修订 Goal/Plan、选择公开调查并解释原因；不是体现在可以绕过系统。普通可逆调查可在 Authority 允许时自主执行，诊断只形成提案，高风险处置需要绑定当前 decision/action/revision 的确认。自主性是“合法空间内的选择权”，不是“世界状态写权限”。

**本项目依据：** `NPCAuthorityPolicy`；`AuthorityMode`；`PendingActionConfirmation`。

### Q5：Runtime 是什么？

**面试官考察：** 是否能定位系统控制面。

**推荐回答：** “Runtime 是把一次玩家贡献变成一次受控 Agent turn 的编排器。” 它负责读取 State、恢复 Observation、检索 Memory、构造 AgentInput、调用 Agent、执行 Planning/Contract/Authority 检查、提交 Tool、处理 post Observation、PlanEvaluator 和 Agent State。它不负责产生语义判断，也不实现病例规则。

**本项目依据：** `application/cooperative_runtime.py::CooperativeRuntime`。

### Q6：为什么需要 Runtime？直接在 Agent 里做不行吗？

**面试官考察：** Agent 与执行基础设施的边界。

**推荐回答：** 如果把状态读取、权限、Tool 执行和持久化都塞进 Agent，模型边界会和副作用耦合，难以测试“模型提错但系统不执行”。Runtime 把不可信 Proposal 与权威执行隔离，还能区分执行前拒绝、world commit unknown、world 已提交但后处理失败等语义。这样可用 fake Agent 测 Runtime，也可用 fake adapter 测 Agent。

**本项目依据：** `GameNPCAgent` 无 Store/Engine；`CooperativeCommitUncertainError`；`CooperativePostCommitError`。

### Q7：Runtime 和 Agent 有什么区别？

**面试官考察：** 是否把框架、模型和业务控制混为一谈。

**推荐回答：** Agent 是智能决策边界：输入公开上下文，输出 Goal/Plan/Action Proposal。Runtime 是生命周期和控制边界：决定何时调用 Agent、如何校验、是否执行、如何更新状态。简单说，Agent 回答“我建议做什么”，Runtime 决定“这个建议能否成为真实行动”。

**本项目依据：** `agents/game_npc.py` 对比 `application/cooperative_runtime.py`。

### Q8：Runtime 和 Workflow 有什么区别？

**面试官考察：** 是否理解当前混合架构。

**推荐回答：** Runtime 是运行容器和编排者；其中包含确定性 Workflow，也调用 Agent 完成动态决策。当前 Workflow 顺序大体固定，但 Goal/Plan/Action 不是固定分支写死，而由模型根据 Observation 选择。因此这是 agent-in-workflow，不是纯流程引擎，也不是自由自治 loop。

**本项目依据：** `handle()` 固定阶段 + `propose_turn()` 动态 Proposal。

### Q9：一轮 Agent 的完整生命周期是什么？

**面试官考察：** 能否从代码讲清端到端链路。

**推荐回答：** `ClinicRequestHandler.do_POST()` 接收协作表单，`ClinicService` 做 operation ledger 和 history snapshot，再调用 Runtime。Runtime 恢复 Observation/State、取 Memory、构造 `GameNPCAgentInput`，Agent 生成 Proposal；随后 GoalPlanPolicy、alignment、Action Contract、repair 后 alignment、Authority。合法 Tool 经 MultiCase、Executor、Engine 执行，先提交 world，再投影 Memory；Runtime 重读 Observation、评估 Plan、保存 Agent State、运行 Reflection，最后 history 标记 completed。

**本项目依据：** `clinic/server.py`、`application/clinic.py`、Runtime、MultiCase。

### Q10：你的状态管理怎么做？

**面试官考察：** 是否只有聊天历史，还是有明确事实源。

**推荐回答：** 状态按权威域拆分：World 是 `CaseSessionState`，Agent 意图是 `CooperativeAgentState`，Player/Campaign 独立，协作账本和长期 Memory 使用 SQLite。JSON 写入用临时文件、`fsync` 和 `os.replace`；同 Session 有进程内 `RLock`；Agent State 有 expected revision。它不是一个万能 State dict，也没有跨所有存储的全局事务。

**本项目依据：** `storage/json_store.py`、`sqlite_memory.py`、`sqlite_cooperation.py`。

### Q11：World State 是什么？谁能修改？

**面试官考察：** 权威世界与模型叙述是否分离。

**推荐回答：** World State 是 `CaseSessionState`，记录 action history、已发现线索、诊断、处置、结局、分数和 revision。LLM 不能直接修改；它只能提出 `AgentAction`。`CaseToolExecutor` 转成 typed command，`CaseEngine` 验证规则并返回新 State/events，应用服务再保存。模型说“已经调查”不会改变 World。

**本项目依据：** `domain/cases.py`、`application/case_tools.py`、`engine/case_engine.py`。

### Q12：Agent State 是什么？

**面试官考察：** 是否区分“意图状态”和“环境事实”。

**推荐回答：** `CooperativeAgentState` 保存 episode/current Goal、current Plan、最近 PlanEvaluation、下一轮安全反馈和 revision。它表达 Agent 想做什么、做到哪一步，不是病例事实。它由 Runtime 根据合法 Proposal 和真实执行结果更新；Plan 不能授予 Tool 权限。

**本项目依据：** `domain/cooperative_planning.py`；Runtime `_apply_proposal()` / `_save_state()`。

### Q13：Context 是 State 吗？

**面试官考察：** 是否理解持久状态和模型视图。

**推荐回答：** Context 不是新的权威 State，而是某一 turn 从 State、Observation、History、Memory 和 Contribution 构造的只读快照。它可以裁剪、重新渲染甚至因 token budget 改变，但不能反向改变持久状态。`ContextBuildTrace` 记录构造来源，真正事实仍在 Store/Engine。

**本项目依据：** `agents/context.py::BuiltContext`；`application/cooperative_context.py`。

### Q14：为什么不能把所有信息都放进 Prompt？

**面试官考察：** Context engineering 和状态治理能力。

**推荐回答：** Prompt 有长度和成本限制，也没有 ownership、revision、生命周期或写权限。全历史会带入过期确认、旧 Observation、无关内容和 prompt injection 风险。项目只放当前公开事实、必要 Goal/Plan、有限历史和经过隔离的 Memory；History/Memory 可裁剪，当前事实和安全契约保持必选，仍超限就 fail closed。

**本项目依据：** `ContextAssembler`、`agents/token_budget.py`、CE-2A tests。

### Q15：上下文是怎么构造的？

**面试官考察：** 能否定位 Context 数据流。

**推荐回答：** `AgentContextFilter` 从 Player/Case State 生成公开 View；`build_context_snapshot()` 从 cooperative history 选同 scope 已完成回合和有效 pending；Memory service 返回 scoped `AgentMemoryContext`；Runtime 合并 Goal/Plan、当前 Contribution、Authority 和反馈形成 `GameNPCAgentInput`；`ContextAssembler` 渲染 A1 initial 或 repair request。

**本项目依据：** `application/views.py`、`cooperative_context.py`、`game_npc_memory.py`、`agents/context.py`。

### Q16：LLM 每轮具体能看到什么？

**面试官考察：** 是否明确可见性边界。

**推荐回答：** 它能看到 public PlayerView、CaseObservation、当前贡献、Goal/Plan、最近评价和安全反馈、Authority view、公开 Action Space、有效历史、scoped Memory 与 pending 摘要。它看不到隐藏 clue truth、正确诊断/处置答案、数据库内部异常、原始私有记录或未授权工具。

**本项目依据：** `GameNPCAgentInput`；`ContextAssembler.build_planning_request()`；`AgentContextFilter`。

### Q17：为什么不输入全部历史？

**面试官考察：** 历史选择、成本与污染控制。

**推荐回答：** 全历史不仅昂贵，还会混入旧状态、已失效 pending 和重复内容。CE-2A 只选同 player/case/session、当前 operation 之前的 completed 记录，并按完整 pair 处理；最终预算先去 Memory 诊断、再移除最旧 history pair、再移除低相关 Memory。当前输入和权威 Observation 优先级最高。

**本项目依据：** `SQLiteCooperativeHistoryRepository.recent_completed_before()`；`build_context_snapshot()`；token budget tests。

### Q18：如何避免 Context 污染？

**面试官考察：** Prompt injection 和来源治理。

**推荐回答：** 第一，隐藏事实先在 View 层过滤；第二，History 只来自已完成、同 scope 的 durable record；第三，Memory 经过来源、玩家、session、类型和冲突过滤，并标成非权威；第四，用户文本永远只是 `PlayerContribution`，不能创建 Tool authority；第五，模型输出还要经过程序 gate。Context 防污染不是只靠 system prompt。

**本项目依据：** Views、History repository、Memory projection policy、Authority policy。

### Q19：你怎么控制 Token 长度？

**面试官考察：** 是否有真实端到端预算。

**推荐回答：** `ContextAssembler` 先产生有来源记录的候选 context；DeepSeek adapter 在加入完整 JSON Schema、provider framing、输出额度和安全余量后，用 tokenizer-aware budget 计算最终 payload。裁剪按优先级进行，只裁 History/Memory 等可选内容；Observation、Goal/Plan、Authority、Contract 等必选内容仍放不下时不发请求，也不预留费用。

**本项目依据：** `agents/token_budget.py`、`deepseek.py::complete()`、`test_context_token_budget.py`。

### Q20：Agent 是怎么做决策的？

**面试官考察：** LLM 决策与程序决策分工。

**推荐回答：** `GameNPCAgent.propose_turn()` 把 `GameNPCAgentInput` 交给 `ContextAssembler`，经 `BoundedStructuredOutput` 调用 `LLMAdapter`，解析成 `GameNPCTurnProposal`。LLM 决定贡献 disposition、Goal/Plan proposal、候选 capability/action 和 Memory 使用声明；程序决定结构是否合法、计划是否一致、参数是否合法、权限是否足够、Engine 是否接受。

**本项目依据：** `agents/game_npc.py`、`agents/bounded_output.py`、`domain/planning_contract.py`。

### Q21：你的 Agent 是 ReAct 吗？

**面试官考察：** 是否会准确使用架构标签。

**推荐回答：** 不是经典自由 ReAct。没有在单请求中不断输出自由 Thought、调用多个 Tool、再观察；每 turn 最多一个 Tool，也不保存思维链。它具有跨 turn 的 observe–decide–act–observe 特征，但由 Runtime 控制，并带持久 Goal/Plan。所以我称它为 plan-carrying single-step agent loop，而不是纯 ReAct。

**本项目依据：** Runtime 一次 handle；单 Tool；无 Thought 字段。

### Q22：它是 Plan-and-Execute 吗？

**面试官考察：** Planning 是否真实存在、是否机械执行。

**推荐回答：** 它有显式 Goal/Plan，但不是一次生成计划后机械执行到底。A1 每轮可以提出 plan change，Runtime 只执行当前一个匹配 step 的 Action；执行后基于真实 post Observation 评估并可能 keep/revise/complete/abandon。因此是持久 Plan + 单步执行 + 反馈 replanning 的混合方式。

**本项目依据：** `AgentPlan`、`GameNPCTurnProposal`、`DeterministicPlanEvaluator`。

### Q23：为什么不能让 LLM 直接执行？

**面试官考察：** 安全与一致性意识。

**推荐回答：** LLM 可能幻觉 target、伪造证据、误解玩家授权或把自然语言描述当成已完成事实。直接执行还会让 provider retry 产生重复副作用。项目让 LLM 只产生 Proposal，Authority 和 Engine 保留执行权，使错误停留在无副作用边界，并能把 rejection、unknown commit 和 post-commit failure 分开。

**本项目依据：** Agent 无 Store；Runtime gates；operation history；commit errors。

### Q24：Proposal 到底是什么？

**面试官考察：** 是否理解建议、批准、执行三种状态。

**推荐回答：** Proposal 是模型生成的结构化候选，不是命令，也不是世界事实。A1 的 `GameNPCTurnProposal` 包括 Goal/Plan 更新意图、Decision proposal 和 Memory 使用声明。Runtime 验证后才构造带运行元数据的 `GameNPCDecision`；最终 `AgentAction` 还必须经过 Authority 和 Executor。Proposal 可以被拒绝、修复或只展示给玩家。

**本项目依据：** `domain/planning_contract.py`、`domain/cooperation.py`、Runtime。

### Q25：LLM 输出格式错误怎么办？

**面试官考察：** Structured output 的失败策略。

**推荐回答：** `BoundedStructuredOutput` 允许一次 initial 和最多一次 format repair，并记录每次 attempt、usage、failure stage 和 token budget。仍失败时 `GameNPCAgent` 返回安全 fallback，Action 是 RESPOND，不执行 Tool。业务 contract 错误不是 format repair，而走专门的安全 feedback 和一次 action-contract repair。

**本项目依据：** `agents/bounded_output.py`；`GameNPCAgent._format_planning_repair_request()`；fallback methods。

### Q26：Action 和 Tool 有什么区别？

**面试官考察：** 是否混淆 Agent 意图和能力接口。

**推荐回答：** `AgentAction` 是当前决策的完整行动表达，包含 action type、dialogue、confidence 和可选 `ToolCallRequest`。Action 可以只是 RESPOND；Tool 是系统暴露的一项具体能力，例如 `observe_patient` 或 `submit_diagnosis`。只有 `USE_TOOL` Action 才必须带 ToolCall，并不代表它已经获准执行。

**本项目依据：** `domain/actions.py::AgentActionType/AgentAction/ToolCallRequest`。

### Q27：Executor 的作用是什么？

**面试官考察：** 工具层是否只是函数字典。

**推荐回答：** `CaseToolExecutor` 是 Proposal 和领域 Engine 之间的适配/校验边界。它检查 Action shape，用严格 Pydantic arguments model 解析参数，确认 investigation 与 Tool 类型匹配，应用 diagnosis readiness，然后构造 typed Engine command。它不自己决定案件结果，也不直接写 Store。

**本项目依据：** `application/case_tools.py::CaseToolExecutor.execute()`。

### Q28：Tool 是怎么注册的？

**面试官考察：** 是否了解真实工程，而非想象中的 registry。

**推荐回答：** 内部没有统一动态 Tool Registry。`ToolName` 在 domain 枚举，Executor、Action Contract、Planning、Authority 和 MultiCase 各有映射/集合；MCP 入口另外用 `FROZEN_MCP_TOOL_NAMES`、`_TOOL_INPUTS` 和 `_TOOL_DESCRIPTIONS` 创建 tools。这是当前真实实现，也是扩展时容易漏配的技术债。

**本项目依据：** `domain/actions.py`、`case_tools.py`、`action_contract.py`、`mcp_server/server.py`。

### Q29：谁最终修改 World State？

**面试官考察：** 副作用所有权。

**推荐回答：** `CaseEngine` 计算权威状态转移和事件，`MultiCaseEpisodeService`/`V1MemoryCoordinator` 负责持久化。更精确地说，Engine 本身返回新的 immutable-ish Pydantic State，不直接写磁盘；应用层在执行 receipt 语义下调用 `JsonStateStore.save_case_session()`。LLM、Context、Memory retriever 都没有写 world 的接口。

**本项目依据：** `engine/case_engine.py`、`application/multicase.py`、`storage/json_store.py`。

### Q30：Function Calling 和你的方案有什么区别？

**面试官考察：** 是否把模型协议当成完整安全系统。

**推荐回答：** Function Calling 解决模型如何表达函数名和参数；本项目解决的是 Proposal 的业务生命周期。当前 DeepSeek 使用 JSON mode 加完整 Schema instruction，输出还包含 Goal/Plan/贡献评价，不只是 Tool args。即使改用原生 function calling，仍需要 Plan alignment、Action Contract、Authority、Executor、Engine、commit receipt 和状态更新。

**本项目依据：** `DeepSeekChatAdapter._chat_payload()`；`GameNPCTurnProposal`；Runtime。

### Q31：新增一个 Tool 要改哪里？

**面试官考察：** 是否具备实际接手能力。

**推荐回答：** 先加 `ToolName` 和必要的 domain action/command/event；在 `case_tools.py` 加 arguments model 和执行分支；更新 `action_contract.py` 的公开投影/验证；按权限更新 Authority；若可规划则更新 planning domain、GoalPlanPolicy 和 PlanEvaluator；若可修改案件则加入 MultiCase allowlist；需要 MCP 时更新 contracts/inputs/descriptions。最后补合法执行、非法参数、权限、重复/过期、拒绝零写入和持久化测试。

**本项目依据：** 第 10 份文档的 Tool 扩展地图及上述文件。

### Q32：Memory 是怎么设计的？

**面试官考察：** 是否把 Memory 简化成向量库。

**推荐回答：** Memory 分写入和读取。写入只从已提交领域事件或经验证的 Reflection 投影，保存来源、player、session、type、时间和生命周期；读取先 scope/filter，再用 BGE-M3 cosine ranking，最后投影成非权威 `AgentMemoryContext`。当前 Observation 永远优先。Memory 与 World 分库，失败不会回滚已提交 world，而是标记 pending 并支持 reconciliation。

**本项目依据：** `V1MemoryCoordinator`、`DeterministicMemoryProjector`、`SQLiteMemoryRepository`、`GameNPCMemoryRetrievalService`。

### Q33：什么信息值得记？谁决定？

**面试官考察：** Memory writer 和真实性边界。

**推荐回答：** 普通 Memory 不是让 LLM自由挑选，而是确定性 projector 从 investigation/diagnosis/treatment 的已提交事件生成。Reflection 类型的经验先由 LLM 形成 candidate，但必须引用真实 evidence，经过 grounding validator 和 conservative write policy，可能合法地 `no_write`。因此“值得保存”最终由允许的事件类型、证据和程序策略共同决定，而不是模型分数单独决定。

**本项目依据：** `memory/projection.py`；`application/reflection.py`、`reflection_memory.py`、`reflection_lifecycle.py`。

### Q34：Memory 如何影响未来决策？

**面试官考察：** 是否有真实闭环，而非仅存储。

**推荐回答：** Runtime 的 `_retrieve_memory_context()` 调 retrieval service，将结果放入 `GameNPCAgentInput.memory_context`；`ContextAssembler` 把保留的 Memory 渲染进 A1 Prompt。模型要声明 used IDs，Runtime 再将 selected、declared、accepted/rejected 写入 `MemoryUsageTrace`。所以代码上有“检索 → 曝光 → 声明 → 验证归因”的链，但当前评测尚未证明它稳定提高任务成功率。

**本项目依据：** Runtime、`game_npc_memory.py`、`agents/context.py`、`domain/cooperative_memory.py`。

### Q35：Memory 记错了怎么办？

**面试官考察：** 错误记忆治理。

**推荐回答：** 第一，写入只接受已提交事件或 grounded Reflection，减少源头错误；第二，读取按来源、玩家、session、类型、生命周期过滤；第三，与当前 Observation 冲突会降低 confidence 并明确标成历史经验、不能作为当前事实；第四，Memory 无法扩大 Authority；第五，当前事实总是优先。现有限制是还没有完整的用户纠错/版本化遗忘 UI，未来要增加 correction lineage 和失效机制。

**本项目依据：** Memory contracts、projection policy、retrieval scope；Memory 设计文档。

### Q36：Memory 和 RAG 有什么区别？

**面试官考察：** 概念准确性。

**推荐回答：** 本项目使用 embedding 检索，所以技术上有 retrieval augmentation；但不是普通外部文档 RAG。Agent Memory 表示过去经历，需要身份、时间、事件来源、生命周期、冲突和使用归因。向量相似度只负责排序，不能决定可信度和权限。未来世界观知识可以另建 Knowledge RAG，与 autobiographical Memory 分开治理。

**本项目依据：** `MemoryScope`、`VerifiedMemorySource`、`AuthoritativeMemoryRecord`、BGE retrieval。

### Q37：项目里有没有 Planner？

**面试官考察：** 是否虚构独立模块。

**推荐回答：** 有 Planning subsystem，但没有独立 `Planner` class 或 Planner Agent。A1 Planning 生成嵌入 `GameNPCAgent.propose_turn()`；Goal/Plan 数据结构在 domain；合法性由 `GoalPlanPolicy` 验证；proposal 由 Runtime 应用；完成和推进由 `DeterministicPlanEvaluator` 判断。面试中应说“规划职责分布”，不能说有一个独立 Planner 服务。

**本项目依据：** `agents/game_npc.py`、`domain/cooperative_planning.py`、`goal_plan_policy.py`、`plan_evaluator.py`。

### Q38：Goal、Plan、Action 有什么区别？

**面试官考察：** 时间尺度和语义分层。

**推荐回答：** Goal 表示当前想达到的状态，例如形成诊断；Plan 是达成目标的有序步骤和完成信号；Action 是本 turn 实际提出的一次回复或 ToolCall。Goal 不等于执行方案，Plan 不等于权限，Action 不等于已提交结果。三者由不同 contract 和生命周期控制。

**本项目依据：** `AgentGoalState`、`AgentPlan/PlanStep`、`AgentAction`。

### Q39：Plan 如何判断完成？

**面试官考察：** 是否让模型自评完成。

**推荐回答：** 模型可以提出计划，但不能宣告权威完成。执行 Tool 后 Runtime 重读 post Observation，`DeterministicPlanEvaluator` 根据 completion condition、Action、tool_succeeded、事件和 pending 判断 step/plan/goal 状态。对于纯 RESPOND 的非 Tool step，也有显式 evaluator transition，避免对话步骤永久卡在 ACTIVE。

**本项目依据：** `application/plan_evaluator.py`；Runtime RESPOND 和 post-commit 分支。

### Q40：如何 Replan？

**面试官考察：** 对失败与环境变化的适应。

**推荐回答：** Runtime 每 turn 恢复现有 Plan 和上一评价，模型可提交 plan change；`GoalPlanPolicy` 验证新 plan 是否仍在公开合法空间。Tool 失败或 post Observation 变化后，PlanEvaluator 产生 keep/revise/complete/abandon 结果和公开摘要，下一轮作为反馈进入 Context。程序不会擅自替模型选择新的语义行动，但会阻止已失效计划继续执行。

**本项目依据：** Runtime `_prepare_next_goal()`、`_apply_proposal()`；PlanEvaluator。

### Q41：如何防止 LLM 乱执行？

**面试官考察：** 是否只靠 Prompt guardrail。

**推荐回答：** 防线是结构化的：公开 View 隔离隐藏事实；Pydantic 验证 Schema；GoalPlanPolicy 校验规划；两次 alignment 保证 repair 前后 Action 与 active step 一致；Action Contract 校验 Tool/target/args；Authority 管确认；Executor 再解析参数；Engine 验证领域规则；只有成功 commit 才改变 world。任何上游文本都不能绕过这些代码边界。

**本项目依据：** Runtime 主链；Policy/Contract/Authority/Executor/Engine。

### Q42：Policy、Contract、Authority 分别是什么？

**面试官考察：** 安全层是否职责重叠。

**推荐回答：** `GoalPlanPolicy` 检查目标和计划是否合法、与公开候选一致；`PublicActionContractValidator` 检查最终 ToolCall 的名称、target、arguments 和 evidence 是否属于当前 Observation；`NPCAuthorityPolicy` 判断当前 Action 是否有权自主执行、只能提案、需要确认或禁止。Policy 管意图结构，Contract 管动作合法性，Authority 管执行许可。

**本项目依据：** 三个 application 模块及 Runtime 调用顺序。

### Q43：Schema 通过就安全吗？

**面试官考察：** 结构正确与语义正确的区别。

**推荐回答：** 不安全。Schema 只证明字段、枚举和类型正确；模型仍可能选当前不存在的 target、引用未发现 evidence、让 Action 脱离 active Plan，或者选择需要确认的 Tool。项目把 Schema 作为第一层，后面还有 Planning、alignment、Contract、Authority 和 Engine。

**本项目依据：** parser validators；`PublicActionContractValidator`；`CaseEngine`。

### Q44：Tool 执行失败怎么办？

**面试官考察：** 错误分类和状态污染防护。

**推荐回答：** Engine rule 或 Tool argument failure 在保存前转为稳定错误结果，不产生 world event；Runtime 写入安全 feedback，并让 PlanEvaluator 以 `tool_succeeded=False` 处理。如果存储返回 world commit unknown，则抛专用异常并阻断盲目重放。如果 world 已提交但 Observation/PlanEvaluator 后处理失败，标记 committed follow-up incomplete，同 operation 也不会重放 Tool。

**本项目依据：** MultiCase receipt；`CooperativeCommitUncertainError`；`CooperativePostCommitError`；Clinic history lifecycle。

### Q45：如何处理并发和幂等？

**面试官考察：** 是否夸大 exactly-once。

**推荐回答：** 同 state root + session ID 使用进程内 `RLock` 串行化；cooperative operation 有稳定 fingerprint 和 SQLite started/prepared/completed/recovery record，completed 可重放结果，payload 冲突被拒绝；Agent State 有 revision 检查。但锁不跨进程，world JSON 保存不是数据库 CAS，也没有全链 exactly-once，所以多进程并发仍是明确限制。

**本项目依据：** `JsonStateStore.session_write_lock()`；`SQLiteCooperativeHistoryRepository`；commit consistency 文档。

### Q46：为什么不用 LangGraph？

**面试官考察：** 是否理解框架能力与自研成本。

**推荐回答：** 当前运行单位是一请求一 turn、单 Agent、最多一个 Tool，关键复杂度是领域 Authority 和 commit semantics，不是动态图。自研使安全顺序直接可读、依赖少。但 Runtime 已超过千行，如果出现多个 durable node、并行分支、多次 human interrupt 或跨重启内部恢复，我会评估 LangGraph。迁移也不会删除 Engine/Contract/Authority。

**本项目依据：** Runtime 规模与单 turn 主链；第 11 份 Trade-off 文档。

### Q47：为什么不用 AutoGen 或 Multi-Agent？

**面试官考察：** 是否把模块都 Agent 化。

**推荐回答：** 当前只有一个真实自主主体；Planner、Memory、Executor 没有独立目标和私有权限，做成 Agent 会把函数调用变成昂贵消息通信，并增加状态冲突、termination 和评估变量。只有未来出现不同私有 context、真实冲突目标、专家并行或跨组织 handoff，并由 paired eval 证明收益时才引入。

**本项目依据：** README 明确 single `GameNPCAgent`；无 Agent message bus。

### Q48：为什么不用 MCP？

**面试官考察：** 是否读过真实代码。

**推荐回答：** 这个问题的前提不对：项目已经使用 MCP，提供 `xuanyi-mcp-stdio`，依赖固定为 `mcp==2.0.0`。没有做的是把 MCP 当 Web Agent 内部总线。内部 Tool 同进程且依赖强类型 Engine/receipt，直接调用更简单；MCP 用于外部 client 接入。MCP 路径不经过完整 Cooperative Runtime/Memory/Campaign 后链，因此两者保证不能混说。

**本项目依据：** `pyproject.toml`、`mcp_server/`、`application/mcp_facade.py`、MCP tests。

### Q49：项目入口和核心 Class 是哪些？

**面试官考察：** 是否能现场打开代码。

**推荐回答：** `pyproject.toml` 将 `yiwen-xinglu` 指向 `clinic/server.py::main()`；用户协作输入在 `ClinicRequestHandler.do_POST()`；Service 是 `ClinicService`；Runtime 是 `CooperativeRuntime`；Agent 是 `GameNPCAgent`；Context 是 `ContextAssembler`；Tool Executor 是 `CaseToolExecutor`；Engine 是 `CaseEngine`；JSON Store 是 `JsonStateStore`；Memory 是 retrieval/coordinator/repository 三组服务。

**本项目依据：** 第 10 份工程实现文档和对应源文件。

### Q50：你如何测试一个 Agent 系统？

**面试官考察：** 是否只做 prompt demo。

**推荐回答：** 我把随机模型和确定性系统分开测：用 fake adapter 测 Agent request/parse/repair/fallback；用 scripted/fake Agent 测 Runtime 的 Policy、Authority、Tool 和 State 分支；Engine 做纯规则/事件回放；Storage 做 revision、隔离和故障注入；Web/MCP 做入口集成；Context 做冻结等价与 token budget；Memory/Reflection 做来源、隔离、检索和 lifecycle；真实模型用冻结场景、grader 和 request ledger。当前完整回归 674 项通过，但真实模型效果要看单独评测，不能用单测数替代。

**本项目依据：** `tests/` 的 M1–M5、P、CE、commit、MCP、eval 测试；`src/xuanyi_npc/evaluation/`。

## 第七部分：递进追问链（10 条）

### 追问链 1：Runtime 与 Agent

**面试官：你的 Agent 怎么运行？**  
回答：每个玩家贡献触发一个 `CooperativeRuntime.handle()`，它恢复 State/Observation、构造 Context、调用 `GameNPCAgent`、验证 Proposal、最多执行一个 Tool，然后更新状态。

**追问：为什么不是 Agent 自己维护循环？**  
回答：模型不应该拥有副作用生命周期。Runtime 必须控制 Tool 上限、权限、提交顺序和失败语义，才能在模型出错时保证无副作用。

**继续：那这还算自主 Agent 吗？**  
回答：算。自主性在合法行动空间内的 Goal/Plan/Action 选择，而不是绕过系统。就像操作系统进程有调度和权限边界，并不等于程序没有自主逻辑。

**继续：一请求一 turn 会不会太弱？**  
回答：它适合当前 human-in-the-loop 游戏节奏，跨 turn 有持久状态。若未来要求无人值守多步任务，会增加 bounded internal step loop 或图式 runtime，但仍保留每步验证和 receipt。

### 追问链 2：State 与 Prompt

**面试官：为什么不把聊天历史都放 Prompt？**  
回答：Prompt 是临时视图，不具备 ownership、revision、生命周期和写权限；完整历史还会过期、污染并超预算。

**追问：那 Context 和 State 有重复吗？**  
回答：有意重复一小部分。Context 是从权威 State 投影出的模型视图；重复是为了让模型决策，但权威性仍只在 State。

**继续：模型输出新 Goal 后，State 不是还是被模型改了吗？**  
回答：模型只提出 Goal/Plan intent。`GoalPlanPolicy` 检查合法性，Runtime 才应用并以 expected revision 保存；World State 完全不由这个 proposal 直接修改。

**继续：并发写怎么办？**  
回答：当前单进程同 Session 用 `RLock`，Agent State 有 revision check；但跨进程 JSON CAS 未完成，我会明确这是限制，不宣称完全并发安全。

### 追问链 3：结构化输出

**面试官：你的 Agent 怎么决策？**  
回答：A1 把公开上下文发送给 LLM，要求返回含 Goal/Plan/Decision 的 `GameNPCTurnProposal`，解析后进入确定性验证链。

**追问：LLM 输出错误怎么办？**  
回答：initial 失败最多一次 format repair；仍失败则 safe fallback，不执行 Tool。

**继续：Schema 通过但业务错误怎么办？**  
回答：GoalPlanPolicy、Plan alignment 和 Action Contract 检查语义合法性；Contract 错误可做一次安全 repair。

**继续：repair 把动作改了怎么办？**  
回答：Runtime 在 repair 后重新做 final alignment，只有最终 Action 与 active PlanStep 匹配才进入 Authority。这正是第二次 alignment 存在的原因。

### 追问链 4：Tool 与 World

**面试官：LLM 怎么调用工具？**  
回答：它不直接调用，只在 `AgentAction` 中提出 `ToolCallRequest`。Runtime 批准后交给 Executor。

**追问：Executor 为什么不能直接执行函数？**  
回答：它先把 JSON arguments 解析成严格模型，并把 Tool 映射为 typed Engine command，避免动态字符串直接改状态。

**继续：谁保证 Tool 结果正确？**  
回答：`CaseEngine` 是规则权威，验证调查前置、证据、诊断和处置，生成新 State/events。成功结果还能通过事件回放核对。

**继续：Store 写失败呢？**  
回答：区分确定未提交和提交结果未知；unknown 时阻断自动重放，避免重复副作用。不能统一回答“捕获异常后重试”。

### 追问链 5：Authority 与 Human-in-the-loop

**面试官：玩家说“我同意”就算授权吗？**  
回答：不算任意授权。确认必须匹配 pending confirmation、decision、player、case、session 和当前 world revision。

**追问：为什么需要这么多绑定？**  
回答：防止旧确认、其他案件确认或普通自然语言被复用到新的高风险动作。

**继续：重启后 pending 怎么办？**  
回答：当前 pending 在内存，重启后失效，这是安全但体验不完整的实现；不会从历史文本恢复授权。

**继续：怎么改进？**  
回答：将 pending 作为 durable state，保存 action digest、authority mode、revision、expiry 和 consumed status，并与 operation ledger 做原子/可对账更新。

### 追问链 6：Memory

**面试官：Memory 怎么影响决策？**  
回答：检索结果变成 `AgentMemoryContext` 注入 A1 Context，模型声明 used IDs，Runtime 记录 accepted attribution。

**追问：检索到了就等于使用了吗？**  
回答：不等于。项目区分 candidates、selected、declared 和 accepted，动作被拒绝时声明也不会被接受。

**继续：记忆和当前观察冲突怎么办？**  
回答：当前 Observation 优先；冲突 Memory 降 confidence，文本明确标为不一致历史经验，不能变成事实或权限。

**继续：Memory 提高了成功率吗？**  
回答：目前只能说持久化、隔离、检索和曝光机制已验证；V2.1 M 配对没有观察到任务成功收益，不能宣传为已证明提升。

### 追问链 7：Planning

**面试官：为什么需要 Plan？**  
回答：让跨 turn 调查具有显式目标和步骤，便于解释当前 Action 为什么发生，也能在环境变化后评估/修订。

**追问：Plan 是模型生成的，可靠吗？**  
回答：它是 intent，不是事实或权限；`GoalPlanPolicy` 检查 shape/target/tool，Action 必须与 active step 对齐。

**继续：模型说步骤完成就完成吗？**  
回答：不。Tool 后重读 Observation，由 deterministic evaluator 判断；模型自述不改变 Plan 状态。

**继续：证明 Planning 有收益了吗？**  
回答：尚未充分证明。现有 A0/A1 比较有接口不对称混杂，需要修正后重新冻结 paired evaluation。

### 追问链 8：安全与 Prompt Injection

**面试官：怎么防 Prompt Injection？**  
回答：用户文本只作为贡献字段，不能声明 Tool authority；模型只看公开 view；输出经程序 gate；Engine 独占 world mutation。

**追问：如果用户诱导模型输出合法 Schema 呢？**  
回答：合法 Schema 仍需通过 target/argument/plan/authority 检查。注入最多影响候选语义，不能凭文本获得隐藏 target 或确认。

**继续：那就是绝对安全吗？**  
回答：不是。尚未完成充分攻击轨道、公网认证、多租户、OS/container sandbox 和系统性红队，只能说当前代码边界降低了特定风险。

**继续：下一步验证什么？**  
回答：冻结 injection/authority/replay attack suite，覆盖跨 turn、Memory poisoning、旧 pending、MCP 参数和提交不确定场景，并用 event/state invariants 判分。

### 追问链 9：框架取舍

**面试官：为什么不用 LangGraph？**  
回答：当前一 turn 主链有限，核心复杂度是领域提交和权限，自研更直接。

**追问：但 Runtime 已经很大，不是重复造轮子吗？**  
回答：这个质疑成立。初始选择适合当时规模，但现在 1300+ 行说明应拆 typed stages，并评估 LangGraph 的 checkpoint/interrupt/trace；选择可以随规模变化。

**继续：迁移后哪些代码可以删？**  
回答：可能替换阶段调度、checkpoint 和 interrupt plumbing；不能删 Contract、Authority、Engine、receipt 和领域状态，因为框架不提供本项目业务安全。

**继续：如何验证迁移没有改语义？**  
回答：用现有 fault-injection、alignment、authority、commit consistency 和 golden event replay suite 做双轨等价测试。

### 追问链 10：真实性与个人贡献

**面试官：这些都是你做的吗？**  
回答：我会按真实提交区分架构设计、核心实现、协作/既有代码和 AI 辅助，不会把整个仓库归为个人独立完成。

**追问：AI 写了多少？**  
回答：说明 AI 用在检索、样板、测试草案或重构建议的具体范围；强调自己负责需求拆解、边界决策、代码 review、故障验证和最终验收，并举一个亲自定位的 failure window。

**继续：你最熟的代码是哪一段？**  
回答：选择真实负责模块，例如 `CooperativeRuntime.handle()`，现场解释 State load、Agent call、两次 alignment、Authority、Tool receipt 和 post-commit 分支。

**继续：不熟的模块呢？**  
回答：明确接口级理解和未深入部分，给出如何通过 tests、call graph 和 failure reproduction 接手，而不是装作全部熟悉。

## 第八部分：项目亮点总结

### 亮点 1：Proposal 与执行权彻底分离

- **是什么**：`GameNPCAgent` 只能产生 `GameNPCTurnProposal`，没有 Store/Engine 引用。
- **为什么重要**：模型幻觉或注入不会直接成为副作用；可以分别测试智能层与执行层。
- **如何实现**：Schema → GoalPlanPolicy → initial alignment → Action Contract/repair → final alignment → Authority → Executor → Engine。

### 亮点 2：以真实提交结果驱动 Planning 和 Memory

- **是什么**：Plan 完成依赖 post Observation；普通 Memory 由已提交 Engine event 投影，Reflection 也必须引用真实 evidence。
- **为什么重要**：阻止“模型说完成了”或“模型总结了一条经验”被提升为权威事实。
- **如何实现**：world-first `V1MemoryCoordinator`、`DeterministicPlanEvaluator`、Reflection grounding/consolidation、reconciliation。

### 亮点 3：把可靠性拆成可测试的控制链

- **是什么**：除了 Prompt，还有 strict models、公开 View、token budget、有限 repair、Authority、revision、ledger、commit receipt 和故障恢复状态。
- **为什么重要**：能定位首个失败阶段，区分安全拒绝、执行失败、提交未知和已提交后续失败。
- **如何实现**：Pydantic contracts、`BoundedAttemptTelemetry`、`SQLiteCooperativeHistoryRepository`、fault-injection tests；当前完整回归 674 项通过。

## 第九部分：项目不足与改进

### 9.1 当前限制

| 限制 | 当前事实 | 面试表达 |
|---|---|---|
| 多 Agent | 当前不是 Multi-Agent | “没有真实多主体需求，未强行拆分；未来需用收益证据决定” |
| Runtime 规模 | `CooperativeRuntime` 1300+ 行，分支复杂 | “控制链清楚，但阶段化/图化重构已接近阈值” |
| Tool 扩展 | metadata 分散，没有统一 registry | “新增 Tool 易漏配，需统一 ToolSpec” |
| 并发 | 单进程 Session 锁；无跨进程 CAS | “不能宣称生产级多实例并发安全” |
| 多存储一致性 | JSON + 多 SQLite，无全局事务 | “有 ledger/reconciliation，但 recovery 未闭环” |
| Pending | 进程内，不可跨重启恢复 | “安全失效，但用户体验和 durable HITL 不完整” |
| 可观测性 | 有结构化 traces/history，无集中日志平台 | “可审计证据多，但生产 trace/metric/alert 不足” |
| Memory | 机制验证，稳定行为收益未证明 | “不把向量检索存在等同于效果提升” |
| Reflection | lifecycle/grounding 已实现，下游收益未证明 | “不能称持续自我进化” |
| Planning | A1 已实现；A0/A1 比较有混杂 | “不能宣称显式 Planning 已优于 baseline” |
| Security | 无公网认证、多租户、完整 sandbox/红队 | “当前是 loopback 本地产品，不冒充生产安全平台” |

### 9.2 如果继续开发

#### 短期

- 修正 README 和旧面试材料中的测试数字；
- 将 Runtime 拆成 typed phases，但保持现有执行顺序；
- 建立统一 `ToolSpec`，生成 Contract、Authority 和 MCP metadata；
- 增加统一 trace ID、结构化日志、latency/token/repair/commit metrics；
- 修正 A0/A1 接口不对称，重新跑 Planning、Memory、Reflection 配对评测。

#### 中期

- 将 pending confirmation 持久化；
- 核心状态迁入具备事务/CAS 的数据库，或建立 durable outbox/recovery worker；
- 做跨进程并发、crash window、restart recovery 和 prompt injection 红队；
- 外部知识建立独立 Knowledge RAG，不与 Agent Memory 混库；
- 评估 LangGraph 对 durable interrupt/checkpoint 的实际收益。

#### 长期

- 在真实需要下扩展远程 MCP tools 和多 host；
- 只有出现独立目标/私有 context/专家并行并有 paired eval 增益时引入 Multi-Agent；
- 建立生产级身份、租户、审计、sandbox、SLO 和持续评测；
- 将 benchmark 与真人体验、线上任务成功和安全事件指标打通。

## 第十部分：如何回答“这是你做的吗？”

### 推荐模板

“这个仓库是完整项目成果，但我不会把所有模块都说成自己独立完成。我个人主要负责 **[填入真实模块]**：包括 **[架构/数据结构/代码/测试/评测]**。例如我可以现场从 **[具体文件和函数]** 解释一个请求如何进入、失败在哪里被拦截、状态何时提交，以及对应测试怎样验证。

项目开发过程中使用过 AI 辅助，主要用于 **[代码检索、样板生成、测试草案、文档整理等真实范围]**。我负责的是需求和约束定义、架构选择、对生成代码的 review、运行测试、故障注入和最终验收。对于 **[未亲自实现部分]**，我掌握接口与调用关系，但不会声称是个人原创。”

### 必须准备的证据

面试前为自己的真实贡献准备三组证据：

1. 一个你能逐行解释的核心函数；
2. 一个你亲自定位并修复的失败案例，包括复现、原因和验证；
3. 一个你主动做出的 trade-off，包括放弃方案和后续代价。

不要用“整个项目都是我做的”代替证据，也不要因为使用 AI 辅助就否认自己的工程判断；关键是如实划分 ownership。

## 第十一部分：如何回答不知道的问题

### 模板 1：项目目前没有实现

“这个能力当前项目没有完整实现。现在已有的是 **A**，缺少的是 **B**，所以我不会说已经支持。若扩展，我会先在 **边界/状态/评测** 上这样设计……，再用 **具体测试** 验证。”

### 模板 2：记不清具体代码

“我不想猜具体函数名。根据我对边界的理解，它应该位于 **某层**，输入是 **X**，输出是 **Y**。我会从入口 call graph 和对应测试确认；如果现场可以看代码，我先定位这个符号再给准确答案。”

### 模板 3：理论知道，但项目没做

“理论上可以使用 **方案 X**，但这个项目当前选择了 **方案 Y**，原因是 **当前约束**。我没有在本项目中验证 X 的收益，所以只能说明迁移条件和验证方法，不能说已经具备。”

### 模板 4：不确定指标

“我记得有这个评测，但不确定当前冻结版本和分母，不想报错数字。可以确认的是 **机制/结论边界**；精确结果我会以 evaluation artifact 为准。”

### 模板 5：被问到生产能力

“当前是 loopback 本地产品和工程验证，不是公网多租户生产系统。它已经验证 **哪些边界**，但认证、租户隔离、跨进程并发和系统性红队尚未完成。”

好的“不知道”回答应包含：已知事实、未知边界、验证路径；不要只说“没做过”，也不要临场编造。

## 第十二部分：项目真实性检查

### 简历描述 vs 项目真实能力

| 简历描述 | 实际实现 | 面试表达建议 | 风险等级 |
|---|---|---|---|
| Agent 项目 | 有 State、Goal/Plan、Decision、Tool、环境反馈和跨 turn 持续性 | 可以大胆讲，但说明一请求一个 turn | 低 |
| 自研 Agent Runtime | `CooperativeRuntime.handle()` 真实编排完整主链 | 可以讲；同时承认大文件和框架生态代价 | 低 |
| Long-term Memory | SQLite + BGE-M3 + scope/filter/projection/usage trace | 可以讲机制；不能说已证明提高成功率 | 中 |
| Reflection | evidence bundle、LLM proposal、grounding、consolidation、receipt | 可以讲闭环；不能说稳定自我进化或收益已证明 | 高 |
| Planning/Replanning | 持久 Goal/Plan、Policy、alignment、post Observation evaluator | 可以讲实现；不能说 A1 已显著优于 A0 | 中高 |
| Tool-use | 9 个冻结 ToolName；Contract、Authority、Executor、Engine | 可以大胆讲；说明内部无统一 registry | 低 |
| 安全/可靠 | 多层 gate、revision、ledger、fault tests、safe fallback | 可以讲“工程控制链”；不能说绝对安全/生产认证 | 中 |
| 多 Agent | 没有；唯一产品 Agent 是 `GameNPCAgent` | 不要写 Multi-Agent；病例人物不是 Agent | 极高 |
| MCP | 有独立 stdio server 和测试 | 可以说支持 MCP 工具接口；不能说主 Agent 内部由 MCP 编排 | 中 |
| RAG | Memory 使用向量检索，但不是通用知识 RAG | 说“scoped semantic Agent Memory”；若简历写 RAG 要解释差异 | 中 |
| Function Calling | 当前是 JSON mode + Schema instruction，不是 native tool-call event | 不要写成“基于原生 Function Calling” | 高 |
| 并发安全 | 进程内 Session lock + revision；无跨进程 JSON CAS | 说“单进程受控入口串行”；勿写高并发安全 | 高 |
| 持久化/恢复 | JSON 原子替换、SQLite ledger、部分 reconciliation | 说有限幂等/保守恢复；勿写全局事务/exactly-once | 高 |
| Benchmark | 有冻结场景、grader、request ledger 和多个历史实验 | 可以讲评测体系；不要合并不存在的 V2.1 总成功率 | 中高 |
| 测试 | 当前完整回归 `674 passed in 54.40s` | 可作为代码回归证据；不是模型/线上成功率 | 低 |

### 可以大胆讲

- 单 Agent + 显式 Runtime；
- Proposal/Validation/Executor/Engine 权限分层；
- 显式 State 与公开 Observation；
- 严格结构化输出、有限 repair、safe fallback；
- Tool/Action/Authority 的工程边界；
- Memory 的持久化、隔离、检索和曝光机制；
- 674 项当前代码回归。

### 必须谨慎讲

- Memory、Reflection、A1 Planning 的行为收益；
- 并发、跨重启恢复、exactly-once；
- Prompt injection/生产安全；
- MCP 与正式 Agent 主链的能力等价性；
- 个人贡献比例；
- 历史 benchmark 数字和“成功率”。

### 不能讲成已实现

- Multi-Agent；
- 通用 Agent 平台；
- 完整分布式 Runtime；
- 公网多租户安全系统；
- 全局事务或全链 exactly-once；
- 已被证明的持续自我进化。

## 第十三部分：最终背诵版

### 13.1 1 分钟版本

“《异闻行录》是一个 Human-Agent Cooperative Game NPC 项目。玩家用自然语言和一个调查搭档共同处理六个案件，NPC 会评价玩家意见、维护 Goal/Plan、选择调查工具，并根据环境结果调整计划。

架构上我没有让 LLM 直接执行。一次请求由 `CooperativeRuntime` 读取公开 Observation、Agent State、History 和 scoped Memory，`GameNPCAgent` 只输出结构化 Proposal。Proposal 经过 Planning Policy、Plan 对齐、Action Contract 和 Authority 后，才由 `CaseToolExecutor` 转成 typed command，交给 deterministic `CaseEngine` 修改 world。world 提交后再评估 Plan、投影 Memory 和 Reflection。

项目亮点是把概率型决策与确定性执行分开，既保留开放自然语言能力，又能控制权限和状态污染。当前完整回归 674 项通过；限制是多存储恢复、跨进程并发和 Memory/Planning 的效果证据仍需补强。”

### 13.2 3 分钟版本

“这个项目产品上是本地古风志怪调查游戏，技术上是一个单 Agent、显式 State、受约束 Tool-use 的 Cooperative NPC。传统脚本 NPC 很稳定，但难以理解玩家开放的假设、反驳和证据组合；普通 Chatbot 又通常只有对话，没有真实目标、行动和环境反馈。所以我做的是 Agent 与 deterministic workflow 的混合。

玩家文本先变成 `PlayerContribution`。`ClinicService` 记录 operation 和协作历史，然后调用 `CooperativeRuntime.handle()`。Runtime 从 `CaseSessionState`、`PlayerState`、`CooperativeAgentState` 恢复公开 Observation、Goal/Plan，检索同玩家但排除当前 session 的长期 Memory，再构造 `GameNPCAgentInput`。

`ContextAssembler` 只注入公开事实、有限历史、Goal/Plan、Authority 和经过隔离的 Memory。最终请求会把完整 Schema、framing、输出额度和安全余量纳入 token budget；History 和 Memory 可裁剪，必选内容超限则不调用模型。

`GameNPCAgent` 输出 `GameNPCTurnProposal`，包含贡献评价、Goal/Plan intent 和当前 Action。它只是 Proposal。Runtime 先做 GoalPlanPolicy 和 Plan—Decision alignment，再做 Action Contract；Contract repair 可能改变 Action，所以还会做第二次 alignment；最后 Authority 决定自主执行、只提案、需要确认还是禁止。

合法 Tool 进入 `CaseToolExecutor`，转换成 typed Engine command；`CaseEngine` 是病例规则和 world transition 的唯一权威。提交成功后系统重读 Observation，由 deterministic PlanEvaluator 判断步骤是否完成。普通 Memory 从已提交事件投影；Reflection 也必须基于真实 evidence，经过 validator 才能写入。

工程上我重点强调两点：第一，LLM 没有直接状态写权限；第二，失败语义被细分为执行前拒绝、Tool failure、commit unknown 和 committed follow-up failure，避免危险重放。当前完整回归 674 项通过，但这不是线上成功率。项目还没有跨存储事务、跨进程 CAS 或 durable pending，Memory、Reflection 和 A1 Planning 的行为收益也没有完全证明。”

### 13.3 5 分钟版本

“我介绍一个我做过深入架构和工程验证的 Agent 项目——《异闻行录》。它是一个本地运行的志怪调查游戏，玩家不是点固定菜单，而是用自然语言和 NPC 搭档分析案件。技术目标是让 NPC 真正具有目标、计划、工具行动、状态和长期经验，同时又不能偷看隐藏答案或越权改变世界。

我先讲核心边界：这是单 Agent，不是 Multi-Agent；每次请求执行一个 cooperative turn，不是在单请求里无限自循环。连续性由显式 State、History 和 Memory 提供。

入口在 `clinic/server.py::main()`。玩家从 Web 提交建议后，`ClinicService` 先用 operation ID 和 SQLite history 做 started/prepared/completed 账本，再组装 `CooperativeRuntime`。Runtime 负责整个 turn 的生命周期，但不负责智能判断，也不负责案件规则。

State 分成几个权威域：`CaseSessionState` 是 world，记录线索、诊断、处置、行动历史和 revision；`CooperativeAgentState` 保存 Goal、Plan 和评价，只代表 Agent 意图；Player、Campaign、History 和 Memory 各有自己的生命周期。Prompt 只是这些状态的只读投影，所以模型说‘已经完成’不会修改 world。

Context 构造时，`AgentContextFilter` 先生成公开 PlayerView 和 CaseObservation；CE-2A builder 选择同 scope 的已完成历史和有效 pending；Memory service 做作用域检索；Runtime 再加入 Goal/Plan、当前贡献和 Authority。`ContextAssembler` 生成 A1 initial 或 repair request。最终 DeepSeek payload 在完整 Schema 加入后做 tokenizer-aware budget，避免只按字符数估算。

决策侧，`GameNPCAgent.propose_turn()` 输出顶层 `GameNPCTurnProposal`。LLM 负责理解玩家贡献、提出 Goal/Plan 更新、在公开候选里选 Action 并解释；它没有 Store 或 Engine。输出不合法时只允许有限 repair，失败进入 safe RESPOND。

执行侧是最关键的控制链：先 `GoalPlanPolicy`，再检查 Action 是否匹配 active PlanStep；然后 `PublicActionContractValidator` 验证 Tool、target、arguments 和 evidence；repair 后重新对齐；最后 `NPCAuthorityPolicy` 控制调查、诊断和高风险处置。只有通过后，`CaseToolExecutor` 才把 ToolCall 转成 `InvestigationCommand`、`SubmitDiagnosisCommand` 或 `ExecuteTreatmentCommand`，交给 `CaseEngine`。Engine 产生新的 Session 和连续事件，应用层保存。

Memory 采用 world-first：先保存权威 world，再从已提交事件投影到 SQLite；失败可以从 world 对账，不回滚真实行动。检索使用 BGE-M3，但不是普通向量 RAG：还要按玩家、来源 session、type、lifecycle 和冲突过滤，并记录 selected、declared、accepted，避免把‘检索到’说成‘真的使用了’。Reflection 也只生成候选经验，需要 evidence grounding 和 conservative consolidation。

可靠性不是靠一句 system prompt，而是公开视图、Pydantic Schema、Planning Policy、两次 alignment、Action Contract、Authority、Executor、Engine、revision、Session lock、operation ledger 和 fault tests 的组合。当前完整回归是 674 项通过。

我也会主动讲不足：`CooperativeRuntime` 已超过 1300 行，Tool metadata 分散；pending confirmation 不持久；JSON 与多个 SQLite 没有全局事务；跨进程 CAS 和生产 observability 尚未完成；Memory、Reflection 和 A1 Planning 的行为收益仍需更严格评测。如果继续做，我会先拆 typed stages、统一 ToolSpec、补 durable pending/outbox 和 trace，然后在流程真正变成长任务图时评估 LangGraph，而不是先盲目拆 Multi-Agent。”

### 13.4 10 分钟版本

“我会从产品问题、Agent 闭环、工程控制链、Memory/Planning，以及不足和演进五个层次介绍。

第一，产品问题。《异闻行录》是一个本地调查游戏，玩家和一个 NPC 搭档共同处理六个案件。传统脚本 NPC 可以保证规则稳定，但对开放自然语言和证据组合适应性差；普通 Chatbot 会聊天，却没有可验证的行动和世界反馈。这个项目要同时解决开放语义与可靠执行。

第二，为什么它是 Agent。系统有显式 World 和 Agent State，有 Goal、Plan、Decision、Tool Action、Environment feedback 和跨 turn Memory。`GameNPCAgent` 不只是回复，它会评价 `PlayerContribution`，提出 Goal/Plan 变更，在公开 Action Space 中选择下一行动。每个请求只运行一个 turn，但状态会持久化，因此下一轮能继续任务。这是 request-scoped turn 和 persistent continuity，而不是一个无限 loop。

第三，整体架构。我采用的是单 Agent + deterministic workflow。用户输入进入 `ClinicRequestHandler.do_POST()`，变成 `ClinicContributionInput`；`ClinicService` 校验 player/case/session ownership，获取 Session lock，并在 cooperative history 中写 started。若启用 CE-2A，会从同 scope 的 completed 历史构造 snapshot。随后创建 `CooperativeRuntime`。

Runtime 先调用 MultiCase 恢复 public Observation，再读取 `CaseSessionState`、`PlayerState` 和 `CooperativeAgentState`。它会让失效 Plan 失效、准备下一个 Goal，并通过 `GameNPCMemoryRetrievalService` 获取 Memory。这里 World State 和 Agent State 严格分开：world 是已提交案件事实，Agent State 是目标和计划意图；Plan 永远不是 Permission。

Context 也不是把全部数据库倒进 Prompt。`AgentContextFilter` 去掉隐藏真相；cooperative context 只使用同 player/case/session 且在当前 operation 之前完成的 turn；Memory 先按玩家、来源 session、类型、生命周期和冲突过滤。`GameNPCAgentInput` 包含 current contribution、public views、Goal/Plan、last evaluation、Authority view、pending、safe feedback、Memory 和有限历史。`ContextAssembler` 生成 initial 或 repair request，并记录每个 block 的 source。DeepSeek adapter 会在完整 JSON Schema 和 provider framing 加入后重新计算 token budget；可选 History/Memory 按策略裁剪，必选内容仍超限时 fail closed，不发送网络请求。

Agent 层由 `GameNPCAgent.propose_turn()` 负责。它通过最小 `LLMAdapter` 调 DeepSeek，temperature 为 0，输出 JSON object。A1 Proposal 同时包含 Goal/Plan intent、贡献评价、capability/action 和 Memory used IDs。一次 initial 后最多一次 format repair；仍失败返回 safe fallback。这里我不会说模型‘决定了世界’，因为它只提出候选。

Runtime 接到 Proposal 后进入确定性控制链。首先 `GoalPlanPolicy` 检查 Goal/Plan transition、step shape、公开 target 和 suggested tool；接着第一次 Plan—Decision alignment 确保 Action 与 active step 一致。然后 `PublicActionContractValidator` 校验最终 Tool、target、arguments 和 evidence；如果失败，可以给模型一个不泄露隐藏答案的安全 feedback，做一次专用 repair。因为 repair 可能替换 Action，Runtime 必须再做一次 final alignment。最后 `NPCAuthorityPolicy` 决定自主、proposal-only、confirmation-required 或 forbidden。

RESPOND 不调用 Tool；诊断或高风险处置可能产生 `PendingActionConfirmation`。确认不能只靠玩家说‘同意’，必须匹配 pending ID、decision、player、case、session 和 current revision。当前 pending 在进程内，重启会安全失效，这是尚未完成的 durable HITL。

合法 Tool 进入 `MultiCaseEpisodeService.submit_action_with_receipt()`。`CaseToolExecutor` 用严格 arguments model 解析 JSON，并转成 typed command。`CaseEngine` 验证调查前置、技能、证据、诊断和处置，返回新的 `CaseSessionState`、事件、消息和评分，不直接写磁盘。应用层根据 receipt 语义保存 world。

提交顺序很重要。启用 Memory 时，`V1MemoryCoordinator` 先保存 world，再把已提交 event 投影成 `AuthoritativeMemoryRecord`；索引失败只标记 pending，不把已发生的 world action 说成失败。Runtime 确认 world committed 后重读 post Observation，再由 `DeterministicPlanEvaluator` 推进、修订、完成或放弃 Plan，保存 Agent State，最后运行 Reflection。Reflection 从真实结果构造 evidence bundle，模型只生成 candidate，validator 和 write policy 决定是否 consolidation；合法 `no_write` 也是结果。

Memory 的读取链是 query builder → scoped retriever → projection policy → `AgentMemoryContext` → Prompt。项目使用 BGE-M3 dense retrieval，但与普通 RAG 不同：Memory 表示过去经历，必须有事件来源、玩家范围、时间、生命周期和冲突语义。系统还记录 candidate、selected、declared、accepted/rejected，只有最终合法决策中的声明才可能被接受。尽管机制已实现并测试，我不会说 Memory 已提高成功率，因为当前 V2.1 M 配对没有观察到这项收益。

可靠性方面，最重要的不是某句 Prompt，而是控制链和提交语义。Schema 正确不代表业务正确，所以后面还有 Policy、Alignment、Contract、Authority 和 Engine。模型或 Tool 执行前失败应该零 world write；world commit unknown 时不能盲目重试；world 已提交但 post Observation/PlanEvaluator 失败时，应记录 committed follow-up incomplete。同 Session 有进程内 `RLock`，Agent State 有 revision，cooperative operation 有 SQLite started/prepared/completed/recovery ledger。当前完整回归是 674 项通过，包括 Context budget、alignment、authority、Memory isolation、MCP、故障注入和 evaluation infrastructure。

最后讲取舍和不足。我没有采用 Multi-Agent，因为只有一个真实自主主体；Planner、Memory、Executor 作为确定性模块更合适。我没有把 LangGraph 放进初始主链，因为当前是 bounded one-turn，核心复杂度是领域权限与 commit，而不是动态图。但 `CooperativeRuntime` 现在超过 1300 行，说明阶段化或图化评估已经有价值。项目确实有 MCP stdio 接口，不过它是外部工具 adapter，不经过完整 Web Cooperative Runtime，所以不能把两条入口的保证混为一谈。

最大的技术债是跨存储一致性：World/Agent/Campaign 是 JSON，Memory/History 是不同 SQLite，pending 还在内存，没有全局事务和跨进程 CAS；可观测性也没有生产级统一 tracing。能力证据上，Reflection 下游收益和 A1 Planning 优于 A0 都尚未充分证明。

如果继续演进，我会保持 LLM Proposal + deterministic Engine 这个核心，先把 Runtime 拆成 typed stages，建立统一 ToolSpec，补 durable pending、outbox/recovery worker 和 trace；修正评测混杂后再决定 Memory/Planning 是否值得复杂度。只有出现多个 durable node、并行分支和多次 human interrupt 时才引入 LangGraph；只有有真实多主体和 paired eval 增益时才引入 Multi-Agent。”

## 第十四部分：最终项目知识地图

```text
                         《异闻行录》Agent System
                                      |
          ----------------------------------------------------------------
          |                         |                                  |
     Entry / Runtime           Intelligence                       Execution
          |                         |                                  |
  ClinicService             GameNPCAgent                       CaseToolExecutor
  CooperativeRuntime        LLMAdapter / DeepSeek                      |
          |                         |                             CaseEngine
          |                 Structured Proposal                       |
          |                         |                           Domain Events
          |               Goal / Plan / Decision                      |
          |                         |                                  |
          ---------------- Policy / Contract / Authority --------------
                                      |
             --------------------------------------------------
             |                       |                        |
           State                  Context                  Memory
             |                       |                        |
   CaseSessionState          AgentContextFilter     V1MemoryCoordinator
   Player/Campaign           ContextAssembler       Scoped Retriever
   CooperativeAgentState     Token Budget           Reflection Lifecycle
             |                       |                        |
             ------------------- Observation -----------------
                                      |
                           Post-result PlanEvaluator
                                      |
                   JSON World/Agent + SQLite Memory/History
```

### 一句话记忆每条主线

- **Runtime 主线**：恢复 → 决策 → 验证 → 执行 → 重读 → 更新。
- **智能主线**：公开 Context → 结构化 Proposal，不直接写世界。
- **执行主线**：Contract/Authority → Executor → Engine → committed events。
- **State 主线**：World 是事实，Agent State 是意图，Context 是视图。
- **Memory 主线**：已提交事实投影，作用域检索，非权威注入，使用要归因。
- **安全主线**：Schema 不够；还要 Policy、Alignment、Contract、Authority、Engine 和 commit semantics。
- **取舍主线**：当前单 Agent/自研 Runtime 适合规模，但一致性、可观测性和效果证据仍需补强。

---

## 面试前最后检查

1. 能否不看文档讲出 30 秒、1 分钟和 3 分钟版本？
2. 能否在 5 分钟内打开 Runtime、Agent、Executor 三个文件解释主链？
3. 能否清楚说出 Policy、Contract、Authority 的差别和顺序？
4. 能否主动说出“一个请求一个 turn”“单 Agent”“MCP 已存在但不是主链”三项事实？
5. 能否解释一次 commit unknown 为什么不能重试 Tool？
6. 能否区分 Memory 机制已实现与 Memory 效果已证明？
7. 能否用自己的真实提交说明个人贡献，而不是复述整个仓库？
8. 能否说出当前最大技术债和下一步验证计划？

如果以上任一项只能背术语、不能定位代码或解释失败路径，应回到对应专题文档继续准备。
