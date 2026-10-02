# Agent 状态管理设计（State Management）

> 目标：用于 Agent 岗位面试。本文严格区分四层：**通用 Agent 概念、项目设计意图、真实代码实现、当前未实现能力**。结论以当前工作区代码为准，而不是以历史文档或理想架构为准。

## 0. 先给结论

本项目的状态管理不是“把聊天历史塞进 Prompt”，而是把不同 owner、不同权限、不同生命周期的数据拆成多个显式状态。病例事实由 `CaseDefinition + CaseSessionState` 表示，Agent 的任务运行状态由 `CooperativeAgentState` 表示，跨案结果、长期记忆、人物对话和协作回合记录分别独立持久化。`CooperativeRuntime` 在每个请求中加载这些状态，先生成安全 `Observation`，再构造一次性 `Context`；LLM 只能提出结构化 Proposal，确定性策略、权限、工具和 `CaseEngine` 决定 Proposal 能否形成新的世界状态。世界写入由应用服务提交，AgentState、Memory、Campaign 等随后作为独立投影保存，因此系统有清晰的事实边界，但没有跨 JSON/SQLite 存储的全局事务。

### 面试时的一句话版本

> 我的项目把权威世界状态、Agent 的 Goal/Plan 状态、跨案 Campaign、长期 Memory 和对话状态分开管理；Runtime 每轮从持久状态生成最小权限 Observation 和临时 Context，LLM 只生成 Proposal，只有通过契约、权限和领域规则后，由 CaseEngine 计算、应用服务提交的新 `CaseSessionState` 才能成为事实。

---

## 1. 盘点项目中的全部 State

### 1.1 状态总表

| State 类型 | 项目中的真实名称 | 数据结构 / Class | 文件路径 | 作用 |
|---|---|---|---|---|
| 世界规则/静态真相 | Case Definition | `CaseDefinition` | `src/xuanyi_npc/domain/cases.py` | 保存案件隐藏真相、公开候选、调查规则、治疗结果和计分规则；加载后冻结 |
| 世界状态/案件会话状态 | Case Session | `CaseSessionState` | `src/xuanyi_npc/domain/cases.py` | 保存某玩家某案件当前已发现线索、行动历史、诊断、处置、结局、分数和 revision |
| 玩家状态 | Player | `PlayerState`、`SkillState` | `src/xuanyi_npc/domain/player.py`、`domain/skills.py` | 保存玩家身份、已处理案件和技能可用性 |
| Agent 状态 | Cooperative Agent State | `CooperativeAgentState` | `src/xuanyi_npc/domain/cooperative_planning.py` | 保存 episode goal、current goal、current plan、最近计划评估和 Agent revision |
| Goal 状态 | Agent Goal | `AgentGoalState` | 同上 | 保存目标类型、状态、优先级、完成条件、来源 turn 和 revision |
| Plan 状态 | Agent Plan | `AgentPlan`、`PlanStep`、`PlanEvaluation` | 同上 | 保存 2～4 步短计划、当前步骤、步骤状态、环境版本依据和评估结果；嵌入 AgentState，不是独立文件 |
| 跨 Session/跨案状态 | Campaign | `CampaignState` | `src/xuanyi_npc/domain/campaign.py` | 从已完成案件投影完成摘要、公开事实、知识解锁和事件历史 |
| 长期记忆状态 | Authoritative Memory | `AuthoritativeMemoryRecord` 及 SQLite 表 | `src/xuanyi_npc/memory/contracts.py`、`storage/sqlite_memory.py` | 保存按玩家隔离、带来源与生命周期的 episodic/learning 记忆；向量是可重建派生索引 |
| 记忆索引状态 | Memory Index | `MemoryIndexState`、`RepresentationIndexState` | `src/xuanyi_npc/memory/embeddings.py` | 表示当前玩家的向量是否完整、缺失、过期或表示版本陈旧；是检查结果而非单独核心快照 |
| 人物对话 UI 状态 | Case Dialogue | `CaseDialogueState` | `src/xuanyi_npc/application/case_dialogue.py` | 保存当前对话对象、偏题次数、最近 16 条公开消息和 revision |
| 协作操作状态 | Cooperative Turn History | `CooperativeTurnRecord`、`cooperative_turns` | `src/xuanyi_npc/storage/sqlite_cooperation.py` | 保存 operation 的 started/prepared/completed/failed/recovery_required 生命周期，用于幂等与保守恢复 |
| 待确认状态 | Pending Confirmation | `PendingActionConfirmation` | `src/xuanyi_npc/domain/cooperation.py`；活体存储在 `ClinicService.cooperative_pending` | 保存待确认的 decision、action、owner 和 case revision；当前只在进程内 |
| 单轮输入/结果 | Turn Protocol | `PlayerContribution`、`GameNPCTurnProposal`、`GameNPCDecision`、`CooperativeTurnResult` | `domain/cooperation.py`、`domain/planning_contract.py` | 描述某一轮的输入、候选决策和结果；部分会进入协作历史，但不是统一 Runtime State |
| Observation | Agent-safe Projection | `CaseObservation`、`PlayerView`、`MemoryView` | `src/xuanyi_npc/application/views.py` | 从真实状态过滤得到的只读公开视图；不持久化为事实源 |
| Context | Per-turn LLM Input | `GameNPCAgentInput`、`LLMRequest`、`CooperativeContextSnapshot`、`AgentMemoryContext` | `agents/game_npc.py`、`agents/llm.py`、`domain/cooperative_context.py`、`domain/cooperative_memory.py` | 每轮临时组装给 LLM；不是长期权威状态 |

### 1.2 明确不存在的状态抽象

- 项目当前**不存在独立的 `WorldState` class**。世界由不可变 `CaseDefinition`、玩家 `PlayerState` 和可变 `CaseSessionState` 共同构成；其中当前案件进度的权威快照是 `CaseSessionState`。
- 项目当前**不存在独立的 `SessionState` class**。病例 Session 就是 `CaseSessionState`，其他状态通过同一个 `session_id` 归属到它。
- 项目当前**不存在独立的 `TaskState` class**。任务/Episode 进度由 `CaseSessionState` 和 `CooperativeAgentState.episode_goal/current_goal` 共同表达。
- 项目当前**不存在专门的 ShortTermMemory class**。短期信息由当前 AgentState、当前 Observation、可选最近协作消息和单轮 Context 承担。
- 项目当前**不存在统一 checkpoint manager、统一 State 容器或跨存储 Unit of Work**。
- 产品 Runtime 中没有 `thread_id`。真正使用的是 `player_id`、`case_id`、`session_id`、`operation_id/contribution_id/turn_id`。

---

## 2. World State：什么才是权威事实源

### 2.1 它是什么

本项目没有名为 `WorldState` 的对象。面试时应把世界状态分成两部分：

1. `CaseDefinition`：案件规则和真相，是加载后冻结的静态世界定义。
2. `CaseSessionState`：某一病例 Session 已经真实发生了什么，是运行中的权威可变快照。

若讨论整个产品，还要补充 `PlayerState`；若讨论跨案世界，还可加入 `CampaignState`，但 Campaign 是完成案件后的确定性投影，不应反过来覆盖当前案件事实。

### 2.2 `CaseDefinition` 保存什么

真实字段包括：

- `case_id`、`title`、`synopsis`、`difficulty`
- `patient`，其中同时有公开资料和 `hidden_information`
- `root_cause`、`causal_chain`
- `clues`
- `investigations`、`investigation_requirements`
- `diagnosis_candidates`、私有正确集合 `valid_diagnosis_ids`
- `treatments`，内部含真实 `outcome` 和前置线索
- `hints`、`scoring`

它使用 `ConfigDict(frozen=True)`，设计意图是：一个 Session 中案件真相不随 LLM 或玩家表达变化。

### 2.3 `CaseSessionState` 保存什么

| 字段 | 含义 |
|---|---|
| `session_id` | 病例进度实例 ID |
| `case_id` | 所属案件 |
| `player_id` | 所属玩家 |
| `status` | `active` 或 `completed` |
| `discovered_clue_ids` | 已被领域事件揭示的线索集合 |
| `action_history` | 连续编号的 `ActionRecord`；调查、诊断和处置的可审计历史 |
| `submitted_diagnosis_id` | 已提交诊断 |
| `selected_treatment_id` | 已执行处置 |
| `outcome` | `resolved/suppressed/worsened` |
| `score` | 完成后分数 |
| `revision` | 世界动作提交版本；每个成功领域事件推进 |

模型校验器还要求：行动序号连续；`discovered_clue_ids` 必须精确等于行动历史揭示的线索并集；completed 必须同时具备诊断、处置、结果和分数；active 不允许提前有最终结果。

### 2.4 谁可以读 World State

这里要区分“代码能加载”与“LLM 能看到”。

| 模块 | 实际读取方式 | 能否看到隐藏真相 |
|---|---|---:|
| `MultiCaseEpisodeService` | 从 catalog/store 加载 case、player、session | 是，服务端可信代码 |
| `CaseEngine` | 接收完整 `CaseDefinition/PlayerState/CaseSessionState` | 是，用于裁定 |
| `CaseToolExecutor` | 接收完整对象，转换 Action 为 Command | 是，但只按允许逻辑使用 |
| `AgentContextFilter` | 接收完整对象并生成安全视图 | 输入侧能读，输出侧过滤 |
| `CooperativeRuntime` | 直接加载 player/session；通过 service 获得公开 observation | 能读 player/session，但不把完整 case 真相交给 Agent |
| `GameNPCAgent/LLM` | 只收到 `PlayerView + CaseObservation + MemoryContext + AgentState` | 否 |

### 2.5 谁可以修改 World State

精确答案不是简单一句“CaseEngine 写数据库”：

- LLM：不能修改，只能生成 Proposal。
- Agent：不能修改，只能把模型输出封装为结构化 Proposal/Decision。
- Runtime：不直接构造任意 `CaseSessionState`；它选择是否把已验证 Action 交给应用服务。
- `CaseToolExecutor`：验证参数并把 Action 映射成领域 Command；不直接持久化。
- `CaseEngine`：拥有**领域状态转换权**，校验规则后从旧状态计算出新的不可变 `CaseSessionState + domain events`；不直接写文件。
- `MultiCaseEpisodeService` / `V1MemoryCoordinator`：拥有**提交编排权**，把 Engine 返回的新 Session 写入 `JsonStateStore`。
- `JsonStateStore`：拥有物理持久化能力，但不决定业务状态应该是什么。

因此最严谨的面试表达是：

> 只有经 `CaseEngine` 接受的领域转换，才有资格成为新的权威 `CaseSessionState`；应用服务负责提交，Store 负责落盘。Engine 是业务修改权，Service/Store 是提交与物理写入权。

### 2.6 为什么它是事实源

- LLM 输出可能包含不存在的线索、错误 diagnosis id 或虚构结果；它只是假设。
- Prompt 历史是经过裁剪的文本，既不完整也不具备结构不变量。
- Memory 是从已提交事实或受验证 Reflection 派生的长期信息，可能过期、冲突或被失效。
- AgentState 表示目标与计划，即“Agent 打算做什么”，不是“世界已经发生什么”。
- `CaseSessionState` 经过 Pydantic 不变量校验、Engine 领域规则和持久化边界，是后续 Observation 重建的依据。

---

## 3. Agent State：Agent 自己的运行状态

### 3.1 它是什么、为什么需要、项目如何实现

**是什么：** `CooperativeAgentState` 是某一病例 Session 下 Agent 的持久任务控制状态。

**为什么需要：** 如果只依赖聊天文本，系统无法可靠知道当前 Goal、哪一步正在执行、计划基于哪个世界 revision、上轮为何要 revise，也无法做结构化恢复和确定性测试。

**项目实现：** `CooperativeRuntime._load_or_initialize()` 在首轮懒初始化，后续从 `cooperative_agents/<session_id>.json` 加载；每轮由 Runtime 应用经过 `GoalPlanPolicy` 验证的 Goal/Plan Proposal，并在环境结果后由 `DeterministicPlanEvaluator` 推进。

### 3.2 真实字段

- `schema_version`
- `player_id`、`case_id`、`session_id`
- `episode_goal`
- `current_goal`
- `current_plan: AgentPlan | None`
- `last_plan_evaluation: PlanEvaluation | None`
- `revision`
- `updated_turn_id`

它的 validator 保证 episode goal 必须是 `RESOLVE_CASE`；current plan 必须属于 current goal；active plan 必须对应 active goal；计划工具必须在 Goal 类型允许范围内；最近 evaluation 必须属于当前 plan。

### 3.3 它是谁的状态

它是**Agent 对当前任务的运行状态**，不是世界的 belief 副本，更不是隐藏事实缓存。它表达：当前追求什么、采用什么步骤、上轮环境反馈如何改变计划。

当前实现也没有一个独立 `belief_state`。Agent 对线索的可见认知主要来自每轮重新生成的 Observation 与检索 Memory，而不是在 AgentState 中复制一份世界。

### 3.4 谁修改、何时修改

`CooperativeRuntime` 是 AgentState 的写入 owner：

- 首轮初始化 episode/current goal；
- 每轮开始时标记已经失效的 plan，或准备下一目标；
- 将 LLM 提议的 Goal/Plan 更新通过 policy 后应用；
- 对 RESPOND 型非工具步骤做确定性推进；
- 工具失败后写入 `REVISE_PLAN/REQUESTED_TOOL_UNAVAILABLE`；
- 世界提交成功后重新生成 Observation，再用 `DeterministicPlanEvaluator` 完成/推进/废弃步骤；
- 每轮把 AgentState revision 精确推进一次并保存。

LLM 可以提出 Goal/Plan draft，但不能自己写 AgentState，也不能仅凭一句“完成了”让目标完成。完成条件由 `CaseObservation` 上的确定性条件判断。

### 3.5 持久化和恢复

`JsonStateStore.save_cooperative_agent_state()` 以 `session_id` 保存 JSON，并验证：

- 对应 CaseSession 必须存在；
- player/case/session ownership 不得变化；
- 初次写入必须是 revision 1；
- 已存在时 `existing.revision == expected_revision`；
- 新 revision 必须恰好 `existing + 1`。

下一轮 Runtime 依据同一 `session_id/player_id/case_id` 加载。因此 Goal/Plan 跨 Turn 保存，但按 Case Session 隔离；它不会自动跨 Session 继承。

正常单进程受控路径会把 AgentState 的加载、世界执行和 AgentState 保存包在按 `state root + session_id` 共享的 `RLock` 中，因此线程间不会同时进入这一读改写链。重要限制是：revision 检查与 `os.replace` 仍不是跨进程数据库原子 CAS；直接调用 Store 也不会自动取得 Session 锁。

---

## 4. World State vs Agent State

| 对比项 | World State（核心为 `CaseSessionState`） | Agent State（`CooperativeAgentState`） |
|---|---|---|
| 描述什么 | 世界已经发生的事实与案件进度 | Agent 当前目标、计划、步骤和评估 |
| 是否权威事实源 | 是，案件进度的 source of truth | 否，是 Agent 运行意图投影 |
| 谁负责修改 | `CaseEngine` 计算合法转换；应用服务/Store 提交 | Runtime 应用已验证 Proposal 与确定性评估后保存 |
| LLM 能否直接修改 | 不能 | 不能；只能提议 Goal/Plan 更新 |
| 生命周期 | 单病例 Session | 单病例 Session |
| 是否跨 Turn 保存 | 是 | 是 |
| 是否跨 Session 保存 | 当前 Session 完成后快照仍在，但不作为新 Session 运行状态 | 不跨新 Session 自动继承 |
| 是否进入 Context | 只通过 Observation 的公开投影进入 | current goal/plan/evaluation 直接以安全结构进入 |
| revision 含义 | 成功世界事件版本 | cooperative Agent turn 投影版本；不是同一个版本时钟 |
| 错误后果 | 事实污染、非法动作、错误结局，严重 | 计划漂移、重复/停滞，可依据世界状态重新评估或重建 |

### 为什么不合成一个统一 State

1. **权限边界：** Engine 需要隐藏真相，LLM 只能看到公开投影；合并后容易把私有字段误注入 Prompt。
2. **事实与意图区分：** “计划调查 X”不能等同于“已经调查 X”。
3. **失败隔离：** 世界提交成功而 AgentState 写失败时，系统仍应承认世界事实，并把 Agent 投影标为待恢复，而不是回滚真实结果。
4. **测试性：** Engine 可作为纯确定性状态转换单测；Runtime 可单独测试 plan lifecycle。
5. **生命周期不同：** Memory 跨 Session，AgentState 只在 Session 内，Context 只在单轮内。
6. **恢复来源清楚：** AgentState 有问题时应以 World State/Observation 为准修复，而不是让错误计划覆盖事实。

工程上可以有统一的 Unit of Work 协调多个聚合，但不等于把它们变成一个模型或同一权限域。当前项目尚未实现该 Unit of Work。

---

## 5. Observation 到底是不是 State

### 5.1 项目中的定义

`CaseObservation` 是当前世界在 Agent 权限下的**不可变、只读、即时投影**。它包含：

- 案件标题、简介和患者公开资料；
- `session_status`、`session_revision`；
- 已发现线索的公开描述；
- 当前可用调查；
- 公开诊断候选；
- `can_submit_diagnosis`；
- 已提交 diagnosis id；
- 当前可用、但不暴露结果的 treatment。

它明确排除 `hidden_information`、`root_cause`、`valid_diagnosis_ids`、treatment outcome、隐藏前置和计分真相。

### 5.2 生成链

```text
CaseDefinition + PlayerState + CaseSessionState
                    ↓
          AgentContextFilter
                    ↓
  CaseToolExecutor.case_observation()
  （可再叠加 diagnosis readiness policy）
                    ↓
             CaseObservation
```

代码入口是 `AgentContextFilter.case_observation()`；`CaseToolExecutor.case_observation()` 可进一步把 runtime diagnosis policy 反映到 `can_submit_diagnosis`。

### 5.3 它是否持久化、能否修改世界

- `CaseObservation` 本身不作为事实源持久化。
- 每轮都从当前权威状态重新生成。
- 它不能修改 World State。
- `session_revision` 让消费者知道该投影基于哪个世界版本。

所以概念上 Observation 可以称为“某一时刻的观测状态”，但在本项目的数据架构中应更精确地称为 **derived view / projection**，不要把它与持久权威 State 混为一谈。

### 5.4 为什么 Agent 不直接读完整世界

- 防止正确 diagnosis、隐藏线索和 treatment outcome 泄漏；
- 只暴露当前合法动作空间，减少幻觉 ID；
- 隔离玩家、Session 和 Memory 范围；
- 保证模型无法根据不该知道的规则反向“猜答案”；
- 让同一套 Engine 真相可以服务不同角色视角。

---

## 6. Context 到底是不是 State

### 6.1 项目实际构造

Runtime 构造 `GameNPCAgentInput`，主要来源是：

```text
Persistent State
  - CaseSessionState → CaseObservation
  - PlayerState → PlayerView
  - CooperativeAgentState → Goal / Plan / last evaluation
  - SQLite Memory → AgentMemoryContext
  - SQLite cooperative history → bounded recent messages（CE-2A）
  - in-process pending confirmations → public pending views（CE-2A）
        +
Current PlayerContribution
        +
Authority View / public action surface
        ↓
GameNPCAgentInput
        ↓
ContextAssembler.build_planning_request()
        ↓
LLMRequest / Prompt Messages
```

`CooperativeContextSnapshot` 也不是数据库主状态，它是对已记录完成历史和当前有效 pending 的一次不可变、安全、受预算限制的单轮快照，并在初次请求与 repair 中复用。

### 6.2 State 与 Context 的根本区别

| 概念 | 本项目含义 |
|---|---|
| State | 系统必须跨调用维护、能恢复、具有 owner 和更新规则的结构化信息 |
| Context | 为某一次模型决策，从 State、当前输入和权限规则中选择、裁剪、序列化出的临时信息集合 |

Context 可以包含 State 的投影，但不是事实副本。它可能被裁剪、限长、遗漏历史，也可能因 Memory 服务不可用而降级；这些都不应改变真实状态。

### 6.3 哪些信息只存在单轮

- 当前 `PlayerContribution`
- 当前 `GameNPCAgentInput`
- 当前 `AgentMemoryContext`
- 当前 `CooperativeContextSnapshot`
- 当前 LLM request/response、repair feedback
- pre/post `CaseObservation`
- Runtime 局部变量和校验结果

其中决策和结果可能被协作历史记录下来用于审计，但当轮 Context 本身不会作为一个可恢复 checkpoint 保存。

---

## 7. Session State / Turn State

### 7.1 一个 Session 何时开始

`MultiCaseEpisodeService.start_episode()`：

1. 加载玩家与案件；
2. 扫描已有 Session；
3. 若同一玩家同案有 active Session，则返回已有进度；
4. 若已经 completed，则拒绝重开；
5. 创建新的 `CaseSessionState(session_id, case_id, player_id)`；
6. 保存 JSON。

### 7.2 Session 保存什么

核心病例 Session 是 `CaseSessionState`。同一个 `session_id` 还关联：

- `CooperativeAgentState`
- `CaseDialogueState`
- 协作历史记录
- Memory 的 `source_session_id`
- 进程内 pending confirmation

它不是登录 Session。当前 Web 没有 cookie/login session、TTL、logout 或 revoke；这是本地产品作用域的病例 Session。

### 7.3 一个 Turn 何时开始和结束

- `ClinicService.submit_player_contribution()` 接到带 `operation_id` 的请求时开始协作 Turn。
- `PlayerContribution.contribution_id = operation_id`。
- Runtime 使用同一值作为 `turn_id`；decision/action ID 由它稳定派生。
- 有记录模式下，SQLite lifecycle 从 `started` 到 `prepared`，最后到 `completed`；异常可能进入 `failed_before_reply` 或 `recovery_required`。
- Runtime 返回一个终态 `CooperativeTurnResult` 时，该请求的 Turn 结束。

项目没有在一次 HTTP 请求里运行 `while task_not_finished`。每次请求只完成一个受控决策 Turn，跨 Turn 自主性由持久 Goal/Plan、下一次 Observation 和新请求延续。

### 7.4 Turn 后保留与销毁

保留：成功世界快照、AgentState、Memory/Campaign 投影、对话、启用记录时的协作 turn/result。

销毁：当轮 Python 局部变量、完整 Prompt 对象、pre/post observation、检索排序中间量。pending confirmation 是例外：它跨下一请求保留，但只在内存中，重启丢失。

### 7.5 ID 的真实作用

| ID | 作用 |
|---|---|
| `player_id` | 玩家所有权与长期 Memory/Campaign 隔离 |
| `case_id` | 案件定义范围 |
| `session_id` | 某玩家某案件进度及 AgentState/Dialogue 的主范围 |
| `operation_id` | UI 请求提供的幂等操作 ID |
| `contribution_id` / `turn_id` | 在 cooperative path 中与 operation_id 同值，关联 Proposal/Decision/Plan update |
| `decision_id` | 具体 Agent 决策，pending confirmation 与它绑定 |
| `run_id` | 主要出现在 evaluation/benchmark，不是生产世界状态 ID |
| `thread_id` | 生产 Runtime 不存在 |

### 7.6 一次请求一个 Turn 会不会“不像 Agent”

不会。Agent 的判定核心是它能否基于环境观测维护目标/计划、作出决策、执行工具并根据结果更新状态，而不是必须在单次请求中无限循环。当前设计更适合有人参与、存在确认门和成本控制的交互式 Agent：每个 Turn 都是明确的安全与持久化边界。

要诚实说明 trade-off：它不是无人值守长任务执行器；没有新请求就不会自行继续跑。如果岗位场景需要后台自治，应在现有单 Turn 原语外增加 scheduler/orchestrator，而不是把当前实现包装成连续 loop。

---

## 8. Plan State

### 8.1 Plan 是否独立

`AgentPlan` 是独立领域模型，但持久化上嵌在 `CooperativeAgentState.current_plan` 内，没有单独 plan repository/file。

### 8.2 Goal、Plan、Step 的真实字段

`AgentGoalState` 保存 goal id/type/description/status/priority、evidence requirements、completion condition、来源 contribution、blocked reason、turn IDs 和 revision。

`AgentPlan` 保存：

- `plan_id`、`goal_id`
- `status`
- 2～4 个 `PlanStep`
- `current_step_index`
- `based_on_observation_revision`
- `source_contribution_id`
- created/updated turn IDs
- `revision`

`PlanStep` 保存 ordinal、intent、capability、suggested tool、public target、summary、expected information、completion signal 和 status。

### 8.3 当前步骤和已完成步骤如何记录

- `current_step_index` 指向当前步骤。
- active plan 必须恰好有一个 `ACTIVE` step，且就是 current index。
- 已完成步骤标为 `COMPLETED`。
- 不再适用的后续步骤标为 `OBSOLETE`。
- 工具失败的当前步骤可标为 `BLOCKED`，计划进入 `NEEDS_REVISION`。

### 8.4 谁判断 Plan 完成

LLM 可以提出 plan update，但不能自行宣布环境条件已经满足。`DeterministicPlanEvaluator` 根据 pre/post `CaseObservation` 判断：

- Goal condition 是否满足；
- Tool 是否成功；
- 下一步在新 Observation 中是否仍兼容；
- Case 是否已完成。

它输出 `KEEP_PLAN / REVISE_PLAN / COMPLETE_GOAL / ABANDON_PLAN` 和结构化 reason code。Runtime 将 transition 写回 AgentState。

### 8.5 生命周期

```text
Goal 已存在
   ↓
LLM 提出 Plan draft / keep / revise / abandon
   ↓ GoalPlanPolicy 校验
Runtime 应用为 current_plan
   ↓
active PlanStep 约束本轮 Action
   ↓
ActionContract + Authority + Engine
   ↓
成功/失败后的 Observation
   ↓
DeterministicPlanEvaluator
   ↓
推进步骤 / 要求修订 / 完成 Goal / 废弃 Plan
   ↓
保存 CooperativeAgentState
```

---

## 9. Memory State

### 9.1 不要硬套短期/长期分类

项目没有一个名为 ShortTermMemory 的模块。面试可这样说：

- **短期工作信息的等价物：** 当前 Observation、AgentState 的 Goal/Plan、last evaluation、当前 Contribution、受限近期协作消息。它们来自不同结构，不应统称成一个 Memory Store。
- **长期 Memory：** SQLite 中按玩家隔离的 authoritative memory records、来源 receipts、生命周期事件和 embeddings。

### 9.2 MemoryType 与生产可读范围

领域枚举有 `episodic/relationship/learning/commitment/reflection`。但生产 V1 SQLite schema 的普通 memory event 只允许 `episodic` 和 `learning`，Agent 侧 `V1_READABLE_MEMORY_TYPES` 也只允许这两类。Reflection 生成的可复用经验最终必须通过受控 consolidation/write policy 进入可检索安全类型，而不能据枚举名推断所有类型都在当前路径可用。

### 9.3 写入时机

普通 Memory：`V1MemoryCoordinator.commit_engine_result()` 先校验 Engine transition，先保存新的 CaseSession JSON，再把已提交 domain events 确定性投影成 Memory。若投影失败，世界仍已提交，返回 `memory_projection_pending`，可从 committed action history 重建。

Reflection Memory：仅在 episode completed、goal completed、plan abandoned、plan repeatedly revised 等确定性 lifecycle trigger 上触发。LLM 参与提出 reflection candidate，但 write policy 会检查 ownership、证据、范围、冲突、重复和 memory usage attribution，失败时 fail-safe，不改变世界。

### 9.4 读取和进入 Context

Runtime 调用 memory service，范围由可信代码给出：当前 player、排除当前 session、允许类型和生命周期过滤。检索生成有数量/字符预算的 `AgentMemoryContext`，其中每条有 relevance、confidence、来源 episode、verification time 和冲突标志。该 Context 是单轮投影，不是权威 memory database。

### 9.5 Memory 是否属于 AgentState

不属于。它们只在 Context 中汇合：

- AgentState：Session 内任务控制状态；
- Memory：玩家级、可跨 Session 的长期经验；
- AgentMemoryContext：某轮从长期 Memory 中选择的临时视图。

### 9.6 Memory 能否改变世界

不能直接改变。它只能影响 LLM 的 Goal/Plan/Decision Proposal；后者仍需走相同的 schema、policy、authority、tool 和 Engine 链。因此错误 Memory 的主要风险是误导决策与计划，不是直接污染 `CaseSessionState`。

---

## 10. 其他真实状态

### 10.1 PlayerState

保存玩家身份、`handled_case_ids`、skills 与 revision。Engine 用 skills 判断调查、辨证、处置能力；Observation 只投影解锁技能。它跨多个案件长期保存。

### 10.2 CampaignState

保存 `event_history`、`completed_cases`、`active_facts`、`unlocked_knowledge_ids` 和 revision。其 validator 要求 revision 等于事件数，派生集合必须与事件历史精确一致。`CampaignCoordinator` 可从已完成 `CaseSessionState` reconcile，所以它是可验证、可回放的跨案投影，不是当前案件事实的上游。

### 10.3 CaseDialogueState

保存人物对话的 `current_target`、`off_track_count`、`recent_messages` 和 revision；以 Session JSON 原子替换保存。它服务 UI/人物问答，与 cooperative Agent 的 SQLite turn history 不是同一个系统，也不具备 AgentState 的 expected revision 校验。

### 10.4 Cooperative Turn History

启用记录后，SQLite 记录稳定请求 fingerprint、Contribution JSON、prepared decision、final result 和 lifecycle。它解决 operation_id 重放与“崩溃后结果不确定”的保守处理，但不是世界事实源；历史 result 不能作为新的 authorization。正式 CLI 当前默认启用记录和 CE-2A，程序化 `build_clinic_service()` 的参数默认仍是 `False`，调用者必须显式组合。

### 10.5 PendingActionConfirmation

它包含 action、decision、player/case/session ownership、authority mode 和 `case_revision`。批准时不仅要匹配 owner，还要匹配当前 revision 和原 decision/action。真实缺口是 `ClinicService.cooperative_pending` 只是带进程锁的 dict；重启后全部丢失，历史结果只会返回 `pending_action=None`，不会把旧确认当授权恢复。

---

## 11. 各类 State 生命周期

| State | 创建 | 读取 | 更新 | 持久化 | 销毁/终止 |
|---|---|---|---|---|---|
| `CaseDefinition` | catalog 加载资源 JSON | Observation/Executor/Engine | 运行时不更新 | packaged case JSON | 随版本/资源替换 |
| `PlayerState` | `create_player()` | 每次加载上下文/Engine | 当前主线少量玩家聚合更新 | `players/<id>.json` | 无产品删除流程 |
| `CaseSessionState` | `start_episode()` | 每次 resume/action | Engine 成功事件后 | `case_sessions/<session>.json` | treatment 后转 completed；快照仍保留 |
| `CooperativeAgentState` | 首次 cooperative turn 懒初始化 | 每个 cooperative turn | Runtime Proposal/评估后 | `cooperative_agents/<session>.json` | 无删除流程；Session 完成后保留 |
| Goal/Plan | 初始化或 LLM 合法 proposal | 每轮 Context/对齐/评估 | Runtime + PlanEvaluator | 嵌入 AgentState | completed/abandoned/obsolete，历史仅保留当前及 last evaluation |
| `CampaignState` | 首次读取/投影 | home/跨案上下文 | 完成案件后投影/reconcile | `campaigns/<player>.json` | 无删除流程 |
| Long-term Memory | 已提交事件或有效 Reflection | 跨 Session 检索 | projection/correction/invalidate/delete | SQLite | 生命周期可 supersede/invalidate/hard delete |
| Memory index | 写 Memory 后构建 | 检索前检查 | index/reconcile | SQLite embeddings | 可删除并从 authoritative memory 重建 |
| `CaseDialogueState` | 首次 load 时空状态 | 人物对话页面 | 每条消息 | `case_dialogues/<session>.json` | 无自动清理；只保留最近 16 条 |
| Cooperative history | 新 operation `begin()` | 幂等重放/CE-2A history | lifecycle transitions | SQLite | 无自动清理 |
| Pending confirmation | Runtime 遇到 proposal-only/confirmation-required | 下一次回应 | consume/replace/invalidate | 不持久化 | 使用后、世界 revision 变化或重启后失效 |
| Observation/Context | 每 Turn 构造 | 当轮 Agent/validator | 不原地更新；需要时重建 | 不作为事实源持久化 | Turn 结束后释放 |

按作用域总结：

- 单函数级：Command、EngineResult、校验中间量。
- 单 Turn 级：Contribution、Observation、Context、Proposal、Decision、Memory retrieval context。
- 单 Session 级：CaseSessionState、CooperativeAgentState、Plan、Dialogue、pending。
- 跨 Session 级：PlayerState、CampaignState、长期 Memory。
- 长期持久化：JSON snapshots、SQLite memory/history；项目当前没有自动 retention/GC。

---

## 12. 状态读写权限模型

这里是**代码调用路径形成的逻辑权限**，不是 OS/RBAC 权限系统。

| 模块 | World 读 | World 写 | AgentState 读 | AgentState 写 | Memory 写 |
|---|---:|---:|---:|---:|---:|
| LLM | 仅 Observation 投影 | 否 | 仅 Context 中 Goal/Plan 投影 | 否，只提 Proposal | 否，只可能提 Reflection candidate |
| `GameNPCAgent` | 仅接收安全输入 | 否 | 接收当前状态 | 否 | 否 |
| `CooperativeRuntime` | 读 player/session 和公开 observation | 不直接构造/提交案件转换；调用 service | 是 | 是，应用 policy/evaluator 后保存 | 触发检索/Reflection，不直接绕过 repository policy |
| `GoalPlanPolicy` / Action validator / Authority | 读 Proposal、Observation、Authority view | 否 | 读 Goal/Plan | 否 | 否 |
| `CaseToolExecutor` | 是 | 不持久化；调用 Engine | 否 | 否 | 否 |
| `CaseEngine` | 是，包括隐藏规则 | 计算新的 Session + events，不落盘 | 否 | 否 | 否 |
| `MultiCaseEpisodeService` | 是 | 提交 Engine 结果 | 否 | 否 | 通过 coordinator 触发普通投影 |
| `JsonStateStore` | 物理读取 | 物理写入，不决定业务内容 | 物理读取 | 物理写入并做 Agent revision 检查 | 否 |
| Memory coordinator/repository | 读 committed world/event receipt | 否 | 否 | 否 | 是，受来源/唯一约束/生命周期控制 |

状态修改权限比读取更严格，因为写入会产生不可逆业务后果、跨轮次传播和恢复义务。读错最多导致一次决策偏差；写错会把虚构事实变成下一轮 Observation、再进入 Plan 和 Memory，形成级联污染。

---

## 13. 一轮完整状态流

实际成功工具 Turn 的顺序如下；注意普通 Memory 投影在应用服务提交世界时发生，早于 Runtime 的 post-observation/PlanEvaluator。

```text
Previous persistent state
  JSON: Player / CaseSession / AgentState / Campaign
  SQLite: Memory / completed cooperative history
  Process: valid pending confirmation
        ↓
ClinicService scope + operation checks
        ↓
Runtime load/resume
        ↓
CaseDefinition + PlayerState + CaseSessionState
        ↓ AgentContextFilter / CaseToolExecutor
CaseObservation
        ↓
Load/init CooperativeAgentState + retrieve Memory
        ↓
GameNPCAgentInput / Context Assembly
        ↓
LLM Goal/Plan/Decision Proposal
        ↓
GoalPlanPolicy → initial Plan/Decision alignment
        ↓
PublicActionContract（可 repair）→ final alignment
        ↓
Authority / pending confirmation
        ↓
CaseToolExecutor → CaseEngine
        ↓
new CaseSessionState + domain events
        ↓
save world JSON first
        ↓
ordinary Memory projection/index（可 pending）
        ↓
reload post CaseObservation
        ↓
DeterministicPlanEvaluator
        ↓
save CooperativeAgentState（失败时 projection_pending）
        ↓
Reflection lifecycle / memory consolidation（fail-safe）
        ↓
complete cooperative history record
        ↓
Next turn reloads persistent truth
```

### 13.1 逐步输入、输出与是否修改状态

| 步骤 | 输入 | 输出 | 负责模块 | 修改持久状态？ |
|---|---|---|---|---:|
| 请求归属/幂等检查 | IDs、operation、pending | contribution/record | `ClinicService`、history repo | 开启记录时写 `started` |
| 恢复案件 | IDs | public service result | `MultiCaseEpisodeService` | 否 |
| 生成 Observation | case/player/session | `CaseObservation` | `AgentContextFilter` | 否 |
| 加载/初始化 AgentState | session + observation | `CooperativeAgentState` | Runtime | 仅局部；稍后保存 |
| 检索 Memory | player/session/goal/plan/input | `AgentMemoryContext` | memory service | 通常只读 |
| Context Assembly | 上述安全视图 | LLM request | Agent/ContextAssembler | 否 |
| LLM Proposal | Prompt | Goal/Plan/Decision draft | LLM adapter | 否 |
| Policy/Contract | Proposal + Observation | accepted/repaired/rejected decision | deterministic validators | 否 |
| Authority | final action + confirmation | mode | `NPCAuthorityPolicy` | 否；可能产生进程内 pending |
| Tool/Engine | action + full trusted state | new session/events | Executor/Engine | Engine 只计算，不落盘 |
| World commit | Engine result | committed session | service/store/coordinator | 是 |
| Memory projection | committed events | memory rows/index status | coordinator/repository | 是；失败不撤销 world |
| Plan evaluation | pre/post observation | updated goal/plan/evaluation | PlanEvaluator/Runtime | 局部更新 |
| Agent commit | updated AgentState | new agent revision | Runtime/store | 是；失败不撤销 world |
| Reflection | lifecycle evidence | accepted/rejected memories | reflection service | 可能写 Memory；失败安全降级 |
| History completion | public result | completed record | history repo | 是 |

---

## 14. 状态更新规则

### 14.1 调查工具成功

- 更新：`CaseSessionState.discovered_clue_ids/action_history/revision`。
- 决策：`CaseEngine._investigate()`。
- 前置：Session active、调查存在、action/target 匹配、未重复、requirement 未完成、技能与线索前置满足。
- 持久化：world JSON；启用 Memory 时再投影事件；Runtime 用新 Observation 推进 Plan 并保存 AgentState。

### 14.2 提交诊断成功

- 更新：`submitted_diagnosis_id`、action history、revision。
- 前置：公开候选存在、引用证据已发现、诊断 readiness policy 允许、Authority/confirmation 满足。
- 注意：提交 diagnosis 不等于模型知道正确答案；正确性最终由处置/计分规则验证。

### 14.3 执行处置成功

- 更新：selected treatment、outcome、score、status completed、history/revision。
- 前置：已有 diagnosis、treatment 存在、前置线索满足、权限确认匹配。
- 后续：Campaign completion projection、Agent episode goal 完成、Reflection episode trigger。

### 14.4 Tool/Engine 拒绝

- World：不更新。
- AgentState：若有 active plan，PlanEvaluator 用 `tool_succeeded=False` 把步骤标 blocked、Plan 标 `NEEDS_REVISION`；Agent revision 仍可推进并保存。
- Decision feedback：保存固定公开 Tool 失败分类；Observation revision 未变化时下一轮注入一次后清除。
- Memory：没有 committed domain event，不做普通事实投影；Reflection 是否触发取决于 lifecycle 条件。

### 14.5 Proposal/Policy/Alignment 拒绝

- World：不更新、工具不执行。
- AgentState：可能保存当前 Goal/Plan proposal 或 recovery evaluation，具体分支以 Runtime 为准；这体现“Agent 投影可变化，但世界不变”。
- Decision feedback：预算、模型、Planning、Alignment、Action Contract 和 Authority 等主要拒绝保存为独立 `last_decision_feedback`，不伪装成 World State 或 PlanEvaluation，也不授予权限。
- History：启用 cooperative record 时仍记录安全拒绝结果，但下一轮拒绝可见性不再依赖 CE-2A 历史开关。

### 14.6 用户确认

- pending 必须匹配 player/case/session、decision/action 和创建时 `case_revision`。
- 确认只把 authority 变为允许继续，不直接写世界；Action 仍必须再次通过后续执行链。
- consumed 后从进程内 dict 删除。

### 14.7 RESPOND/non-tool step

- World：不更新。
- 若 active step 是非工具步骤，PlanEvaluator 以同一个 pre/post Observation、`tool_succeeded=True` 推进步骤。
- AgentState：保存新 plan/evaluation/revision。

### 14.8 Memory/Reflection 写入

- 只有 committed engine events 或通过严格 provenance/write policy 的 Reflection 可写。
- 检索结果、玩家观点、LLM 声明本身不直接成为事实 Memory。

---

## 15. 失败情况下的一致性

### 15.1 单文件原子性

`JsonStateStore._write()` 在目标目录写临时文件，`flush + fsync` 后用 `os.replace` 替换。因此单个 JSON 文件不会正常暴露半写内容。

但这只保证**单文件替换原子性**，不等于：

- compare-and-swap 原子；
- 多文件事务；
- JSON 与 SQLite 的全局事务；
- 跨进程并发请求严格串行。正常单进程受控入口另有 Session `RLock`，这项能力来自应用层临界区，而不是 `_write()` 本身。

### 15.2 revision/CAS 的真实边界

- AgentState 有 `expected_revision` 校验；正常单进程 Runtime 路径还由 Session `RLock` 包住完整读改写链，所以两个受控线程不会同时通过并写入。
- CaseSession 保存没有 `expected_revision` 参数；正常单进程应用入口依靠同一 Session 锁避免旧快照覆盖，但多进程或直接 Store 写仍可能绕过保护。
- Campaign、Player、Dialogue 也没有严格数据库 CAS。
- SQLite memory/history 内部使用事务和唯一约束，但无法覆盖 JSON store。

因此不能说“项目已实现严格 CAS”，也不能继续说“同进程受控入口没有串行化”。准确表述是：版本字段、AgentState 乐观检查、单文件原子替换和应用层 Session 锁共同保证正常单进程入口的线程串行语义；跨进程、直接 Store 写及数据库级 CAS 仍未解决。

### 15.3 LLM Proposal 已通过、执行中失败时

| 失败点 | World | AgentState/Plan | Memory | Runtime 可见结果 |
|---|---|---|---|---|
| Tool/Engine 规则拒绝 | 不变 | 可被评估为需要 revise 并保存 | 不写普通事实 Memory | `ACTION_REJECTED` + error code |
| World JSON 保存抛错 | 提交前失败时旧快照仍为准；若异常发生在原子替换后则结果未知 | Runtime 不进入成功后的 post-observation 保存 | 不把该操作当作已知成功继续投影 | `world_commit_uncertain`，同 operation 不盲目重放 |
| World 已保存、Memory projection 失败 | 已改变 | 继续按已提交世界评估 | `projection_pending`，可 reconcile | 成功结果带 memory error |
| World 已保存、AgentState 保存失败 | 已改变 | 内存中算出，但未持久化 | 普通 Memory 可能已写 | 返回 `ACTION_EXECUTED` + `agent_state_projection_pending` |
| Reflection 失败 | 已提交 | 已提交或已有结果 | reflection memory 不写/部分 lifecycle fail-safe | 世界成功，reflection 标 failed-safe |
| 最终 history complete 失败 | 可能已经提交 | 可能已提交 | 可能已提交 | operation 标 recovery_required，不自动重放 |

### 15.4 为什么不做“失败就全部 rollback”

当前项目把 `CaseSessionState` 视为上游事实，把 Memory/AgentState 视为可对账或可重建投影。世界成功后再因为下游投影失败而回滚，会产生新的副作用和不确定性。当前选择是 **world-first + derived projection pending + reconciliation**。

### 15.5 什么是全局事务，项目需要吗

全局事务是把 world JSON、AgentState JSON、SQLite Memory、Campaign、history 等多个写操作视为一个原子提交：要么全部成功，要么全部不发生，并具备隔离与恢复语义。

当前项目没有它，而且跨文件系统与 SQLite 做传统 ACID 分布式事务成本很高。项目确实需要更完整的**跨存储一致性方案**，但不一定需要强行做数据库式全局事务。更适合当前架构的演进是：

1. 保留已实现的单进程 Session 串行化，并将边界升级为跨进程单写者或带原子 CAS 的数据库；
2. 建立 durable outbox/commit receipt，记录 world commit 后必须完成的 AgentState/Memory/Campaign 投影；
3. 启动时按 receipt 幂等 reconcile；
4. 明确每个投影的重建来源和完成标记。

这会得到最终一致性与可恢复性，复杂度通常低于跨 JSON/SQLite 的全局两阶段事务。

---

## 16. 为什么不能让 LLM 直接改 State

1. **输出不可靠：** 自然语言可能缺字段、格式错误或自相矛盾。
2. **会幻觉：** 模型可能生成不存在的 clue/tool/diagnosis/treatment ID。
3. **业务合法性：** 模型不能可靠保证调查前置、技能、证据、Session status 和评分规则。
4. **权限：** diagnosis/treatment 需要 proposal/confirmation 语义，计划不能扩大权限。
5. **一致性：** 模型不了解 revision、并发写、原子替换和跨存储提交次序。
6. **审计：** 直接写状态无法区分模型建议、验证结果、真正领域事件。
7. **测试：** 确定性 Engine 可以针对相同输入稳定复现；自由文本写入不可建立严格回归。
8. **隐藏信息：** 允许模型直接操作完整 world 会破坏 least-privilege 边界。

### 面试推荐回答

> 我把 LLM 放在 proposal 层，而不是 commit 层。模型负责语义判断、Goal/Plan 和候选 Action；程序用 schema、GoalPlanPolicy、ActionContract、Authority 和 CaseEngine 做逐层约束。只有 Engine 根据旧状态算出的合法新 Session 才能由服务提交。这样即使模型幻觉或被注入，最坏是 Proposal 被拒绝，而不是把虚构内容写成下一轮事实。

---

## 17. 状态持久化

| State | 存储 | 保存时机 | 保存者 | 恢复方式 |
|---|---|---|---|---|
| Player | `players/*.json` | 创建/玩家聚合更新 | `JsonStateStore` | `load_player()` |
| CaseSession | `case_sessions/*.json` | start、成功 Engine result | episode service / memory coordinator | `load_case_session()` / resume |
| AgentState | `cooperative_agents/*.json` | cooperative turn 结束分支 | Runtime → Store | `_load_or_initialize()` |
| Campaign | `campaigns/*.json` | completed case projection/reconcile | campaign coordinator | `load_campaign()` 或重建 |
| Dialogue | `case_dialogues/*.json` | 每次人物对话 | `CaseDialogueStore` | `load()`；过滤旧 private message |
| Memory/source/lifecycle/index | `memories.sqlite3` | committed event、reflection、index | SQLite repository/services | 按 player 查询；缺失可 reconcile/index |
| Cooperative history | `cooperative_conversation.sqlite3` | begin/prepared/completed/failure | history repository | 按 operation replay或保守 recovery |
| Pending confirmation | 内存 dict | proposal/confirm flow | `ClinicService` | 不能跨重启恢复 |

### 保存失败策略

- JSON：包装成 `StorageError`，保留原目标文件；临时文件尽力清理。
- Memory：world 已成功则返回 pending，由 committed history 补投影。
- AgentState：world 已成功时不否认执行结果，返回 projection pending。
- Cooperative history：prepared 后失败或 complete 写失败进入 recovery_required，不盲目重放工具。
- Reflection：fail-safe，不影响已经提交的世界结果。

项目不是 event-sourcing-only：`CaseSessionState` JSON 快照是主要读取源，`action_history`/domain events 提供审计和派生重建；Campaign 自身更接近“事件历史 + 严格派生字段”的可回放模型。

---

## 18. 状态恢复与重启

### 18.1 可以恢复

- Player、CaseSession、AgentState、Campaign JSON 快照；
- CaseDialogue JSON；
- SQLite authoritative Memory、embeddings、lifecycle receipts；
- SQLite completed cooperative results；
- 从 committed CaseSession/action history 补投普通 Memory；
- Campaign 可从 completed Session reconcile；
- Memory index/部分 Reflection index 可重建或对账。

正式 server composition 在启用 Memory 时会遍历已保存 Session 调用 `reconcile_committed_session()`，并执行相关索引 reconcile。

### 18.2 会丢失或不能自动安全恢复

- 进程内 `cooperative_pending`：重启即丢失，必须重新讨论/确认。
- 正在运行但未完成的 Python 调用和单轮 Context。
- history lifecycle 为 `started/prepared` 的操作不能证明工具是否执行；系统标记 recovery uncertain，不自动重放。
- world 已提交但 AgentState 写失败的投影，没有一个完整、通用的自动重建队列；下一轮能从 world 看到最新 Observation，但旧 plan 投影可能落后。
- 多存储写入不存在统一 commit receipt 覆盖所有边界。

### 18.3 重启后 Agent 如何继续

下一请求重新加载 CaseSession 和 AgentState，重新生成 Observation、检索 Memory、构造 Context。如果 AgentState 与世界 revision 不兼容，Runtime 的 `_mark_invalid_plan()` 和确定性 condition 检查会标记/推进部分状态；但这不是覆盖所有跨存储故障的完整恢复协议。

---

## 19. 多用户与并发

### 19.1 已有隔离

- 请求显式携带 `player_id/case_id/session_id`；应用层验证 ownership。
- AgentState 保存时再次验证对应 CaseSession owner。
- Memory 查询和记录按 `player_id` 隔离，并排除当前 source session。
- cooperative history 主键包含 player/case/session/operation。
- pending confirmation 校验 owner 与 case revision。
- 同一个进程内，对相同 operation key 有 live claim；pending dict 有 `Lock`。
- 正常写入口通过 `JsonStateStore.session_write_lock()` 按 state root + session_id 串行化；覆盖 Cooperative Runtime、MultiCase、Clinic 普通操作和 MCP。
- 并发故障测试已证明：同一 Session 的两个不同 operation 在单进程线程池中不会重叠写入，最终 revision/action history 均保留两次提交。

### 19.2 未完整解决

- `start_episode()` 的“同玩家同案只有一个 active session”靠先扫描再创建，不是数据库唯一约束，并发 start 有竞态。
- CaseSession 写入没有 expected revision CAS；受控单进程入口靠 Session 锁防止 lost update，而多进程或直接 Store 写仍可能竞争。
- AgentState 的 revision check + file replace 不是跨进程原子 CAS；在正常单进程 Runtime 中，它们位于同一 Session 临界区。
- `_claim_live_operation` 解决同 operation 幂等/冲突；不同 operation 的线程串行由 Session 锁解决，但两者都不跨进程。
- JSON 与 SQLite 无统一事务隔离。
- `start_episode()` 的 scan-then-create、Campaign/player 级聚合以及绕过受控入口的直接 Store 调用，仍需要分别审计并发边界。

因此面试中应明确：

> 当前实现有玩家/病例/会话级 ownership 隔离、版本字段、单文件原子写、SQLite 局部事务和正常单进程同 Session 串行化；未完成的是跨进程/直接 Store 写的数据库级 CAS，以及跨存储一致性。

正常单进程产品入口下，两个不同 operation 的线程级 lost update 已不再是主要风险。剩余并发风险集中在多进程或绕过受控入口时的旧快照覆盖；更大的状态风险是 world 已提交后 AgentState/Memory/history 等后续边界部分失败，造成需要对账的状态分叉。

---

## 20. State Management 与 Runtime 的关系

**State Management 回答：** 系统保存哪些状态、每类状态的 owner/权限/生命周期/不变量是什么、如何持久化和恢复。

**Runtime 回答：** 某一 Turn 在什么时候加载哪些状态，如何生成 Observation/Context，怎样把 Proposal 送入校验/执行，以及成功或失败后按什么顺序更新各投影。

本项目可概括为：

> State 定义系统在每个时刻“是什么”，Runtime 管理这些状态在一轮决策中的读取、投影、转换与提交顺序；Runtime 自身不是事实源。

一个请求一个 Turn 并不削弱这层关系，反而让每个 Turn 成为清晰的权限、成本和持久化边界。若未来加入连续执行器，它应重复调用同一单 Turn 原语，并在每次提交后重新加载事实，而不是绕过状态边界。

---

## 21. 关键代码证据

### 证据 1：案件进度的权威结构

**结论：** `CaseSessionState` 保存真实发生的案件进度，并用模型不变量约束字段一致性。

**代码位置：** `src/xuanyi_npc/domain/cases.py`

**Class/Function：** `CaseSessionState.validate_session_consistency()`

**说明：** discovered clues 必须由 action history 精确推导；completed/active 字段组合被严格限制。

### 证据 2：LLM 不接触隐藏世界

**结论：** Agent 只看到公开 Observation。

**代码位置：** `src/xuanyi_npc/application/views.py`

**Class/Function：** `AgentContextFilter.case_observation()`

**说明：** 只投影公开患者信息、已发现线索和当前可用选项；不输出正确 diagnosis、治疗 outcome 等隐藏字段。

### 证据 3：领域修改权属于 Engine

**结论：** Tool proposal 必须转换成 Command 并由 Engine 计算新 Session。

**代码位置：** `src/xuanyi_npc/application/case_tools.py`、`src/xuanyi_npc/engine/case_engine.py`

**Class/Function：** `CaseToolExecutor.execute()`、`CaseEngine.execute()`

**说明：** Executor 校验 typed arguments 后调用 Engine；Engine 明确“不修改输入模型”，返回 `EngineResult(session, events)`。

### 证据 4：世界提交和 Memory 顺序

**结论：** World JSON 先提交，Memory 后投影；Memory 失败不撤销世界。

**代码位置：** `src/xuanyi_npc/application/memory_coordination.py`

**Class/Function：** `V1MemoryCoordinator.commit_engine_result()`

**说明：** 先 `save_case_session(result.session)`，再逐事件 `write_projection()`；失败返回 pending source IDs。

### 证据 5：成功世界提交后再更新 AgentState

**结论：** Runtime 以重新加载的 post-observation 评估计划，世界是上游事实。

**代码位置：** `src/xuanyi_npc/application/cooperative_runtime.py`

**Function：** `CooperativeRuntime.handle()`

**说明：** `submit_action_with_receipt()` 成功后调用 `_resume()` 获取新 Observation，再 `plan_evaluator.evaluate()`，最后保存 AgentState。

### 证据 6：AgentState 有 ownership/revision 检查

**结论：** AgentState 不能换 owner，且版本必须单步推进。

**代码位置：** `src/xuanyi_npc/storage/json_store.py`

**Function：** `save_cooperative_agent_state()`

**说明：** 校验 CaseSession 存在、三元 ownership、expected revision 和 `+1`。

### 证据 7：CaseSession 的单进程锁与跨进程 CAS 边界

**结论：** 正常单进程入口已有 Session 串行化，但 World snapshot 本身没有跨进程 CAS。

**代码位置：** `src/xuanyi_npc/storage/json_store.py`、`application/cooperative_runtime.py`、`application/multicase.py`

**Function：** `session_write_lock()`、`save_case_session()`、`_write()`

**说明：** 受控入口在按 root/session 共享的 `RLock` 内完成读改写；`save_case_session()` 仍直接原子替换文件、没有 expected revision，因此锁外调用或多进程写不受保护。`tests/test_commit_consistency_faults.py` 已证明两个不同 operation 在单进程内被串行并保留两次提交。

### 证据 8：Plan 完成不是模型自证

**结论：** Plan/Goal 状态由确定性 Observation 条件评估。

**代码位置：** `src/xuanyi_npc/application/plan_evaluator.py`

**Class/Function：** `DeterministicPlanEvaluator.condition_met()`、`evaluate()`

**说明：** 按线索数、调查可用性、diagnosis/treatment 和 case status 判定完成/修订。

### 证据 9：pending 不持久

**结论：** 待确认权限重启后丢失。

**代码位置：** `src/xuanyi_npc/application/clinic.py`

**Class/Field：** `ClinicService.cooperative_pending`

**说明：** 它是带 `Lock` 的进程内 dict，没有 repository；completed history replay 也必须找到当前 live pending 才返回授权对象。

### 证据 10：协作历史不盲目重放

**结论：** prepared/started 遗留操作进入 recovery uncertain。

**代码位置：** `src/xuanyi_npc/application/clinic.py`、`storage/sqlite_cooperation.py`

**Function：** `submit_player_contribution()`、`begin()/mark_prepared()/complete()/require_recovery()`

**说明：** 重启后无法确认副作用时标记 recovery_required，避免重复调用模型/工具。

---

## 22. 设计文档 vs 真实代码

| 能力 | 文档描述 | 真实实现 | 是否一致 |
|---|---|---|---|
| World source of truth | `CaseEngine` 接受的事件/状态是权威 | Engine 计算新 Session，Service/Store 才提交；持久 `CaseSessionState` 是读取 source of truth | 基本一致，但面试需区分“计算权”与“物理写入权” |
| AgentState | 持久 Goal/Plan | 按 Session JSON 保存，带 ownership 与 expected revision 检查 | 一致 |
| Validation 顺序 | 架构图按职责简化为 Schema→Policy→Align→Contract | Agent 内实际为 Schema/identity→ActionContract→Memory usage→GoalPlanPolicy；Runtime 再执行 Policy→apply→Align→Contract/repair→Final Align→Authority | 概念职责一致，精确函数顺序曾被简化；现已在面试文档明确 |
| 成功后状态顺序 | 历史图曾把 PlanEvaluator 放在 Memory 前 | 实际在 service 内 world commit 后立即普通 Memory projection/index；Runtime 随后 reload Observation → PlanEvaluator → AgentState → Reflection | 历史材料不一致；当前文档已同步 |
| JSON revision / 并发 | README 曾容易被理解为所有 JSON 都有 revision CAS | AgentState 有 expected revision；正常单进程入口另有 Session 锁；CaseSession/Player/Campaign/Dialogue 没有数据库原子 CAS | 当前 README 已明确单进程与跨进程边界 |
| 原子性 | JSON 原子写 | 单文件 temp + fsync + replace；不是跨文件/跨 SQLite 事务 | 需限定语义 |
| Session 恢复 | 可恢复玩家、案件、Agent、Campaign | 这些可恢复；pending confirmation 和当轮 Context 不可恢复 | 部分一致；ROADMAP 已明确 pending 缺口 |
| Memory | 从 committed facts 和 validated Reflection 投影 | 普通事实 world-first；Reflection 有独立 policy/lifecycle；检索只暴露安全投影 | 一致 |
| MemoryType | 领域枚举有 5 类 | 当前生产普通 SQLite/read context 仅 episodic/learning | 不能把枚举当成全部已启用能力 |
| Continuous Agent Loop | 部分叙述图容易让人理解成单请求内持续 while loop | `handle()` 每次只执行一个 Turn；跨轮靠请求和持久状态继续 | 表述需纠正，不是实现 bug |
| Cooperative record / CE-2A | 正式 CLI 默认开启 | CLI 为 `BooleanOptionalAction(default=True)`；但程序化 factory 参数默认 false | 分入口条件一致，不能说全局无条件开启 |
| Cooperative history | 可幂等恢复 | completed 可重放；started/prepared 只标不确定，不自动重放 | 一致，属于保守恢复而非 exactly-once 全证明 |
| Campaign | 跨案事件投影可重放 | validator 严格校验 event history 与 derived fields；可 reconcile | 一致 |
| Context | 每轮最小权限构造 | Observation/Memory/history/pending 均为投影，Context 不持久化为事实 | 一致 |
| 测试数 | 旧 README/底稿曾写 590 passed | 当前工作区实测并已同步为 657 passed | 已修正文档，不是运行时能力 |

### 当前最需要避免的三句错误表述

1. 错：“只有 CaseEngine 会写 World State。”
   对：“CaseEngine 决定合法状态转换，应用服务和 Store 提交它。”
2. 错：“所有 JSON State 都有原子 CAS。”
   对：“单文件替换原子；AgentState 有 revision 检查；正常单进程入口另有 Session 锁，但 CaseSession 尚无跨进程数据库 CAS。”
3. 错：“Agent 在一个请求里循环直到任务完成。”
   对：“每请求一个 Turn，Goal/Plan/World/Memory 跨 Turn 持久化；它是交互式 Agent，不是后台无人值守执行器。”

---

## 23. 面试回答版

### 23.1 30 秒回答

> 这个项目没有把状态等同于聊天历史，而是按 owner 拆成世界状态、Agent Goal/Plan 状态、Campaign、长期 Memory 和对话状态。当前病例事实以持久化 `CaseSessionState` 为准；每轮 Runtime 从它生成过滤后的 Observation，再结合 AgentState、Memory 和用户输入构造 Context。LLM 只能提出 Goal/Plan/Action Proposal，真正的世界变化必须经过契约、权限、工具和 `CaseEngine`，由应用服务提交。正常单进程同 Session 写已经串行化；当前主要缺口是跨进程 CAS 与跨 JSON/SQLite 的完整恢复。

### 23.2 2 分钟回答

> 我把状态分成事实、意图和派生信息三层。事实层的核心是 `CaseDefinition + CaseSessionState`：前者是冻结的案件真相和规则，后者记录某玩家该 Session 已发现线索、行动历史、诊断、处置、结果和 revision，是当前案件的 source of truth。意图层是 `CooperativeAgentState`，保存 episode goal、current goal、2 到 4 步计划、当前步骤和最近 plan evaluation，它说明 Agent 想做什么，不说明世界已经发生了什么。长期 Memory、Campaign 和向量索引是世界提交后的派生状态；人物对话和协作回合历史分别服务 UI 与幂等审计。
>
> 每轮 Runtime 先加载 player/session/AgentState，从完整世界通过 `AgentContextFilter` 生成不含隐藏真相的 `CaseObservation`，再检索跨 Session Memory、加入当前 Contribution、权限视图和受限历史，构造临时 Context。LLM 同时提出 Goal/Plan/Decision，但它没有任何 repository 写路径。Proposal 要经过 GoalPlanPolicy、Plan/Decision 对齐、ActionContract、Authority，最后由 ToolExecutor 转成领域 Command，交给 `CaseEngine`。Engine 是纯确定性转换，返回新的 Session 和事件，应用服务先提交 world，再投影普通 Memory；Runtime 重新读取 post-observation，用 PlanEvaluator 推进 AgentState，最后可触发 Reflection。
>
> 一致性上，单 JSON 用 temp、fsync、replace，AgentState 还有 expected revision；正常单进程入口用共享 Session `RLock` 串行化完整读改写链，SQLite Memory/history 有局部事务和唯一约束。但这个锁不跨进程，CaseSession 也没有数据库 CAS；world、AgentState、Memory 仍不在一个全局事务中。所以当前首要风险已从普通线程 lost update 转为跨存储部分提交与恢复缺口，其次是多进程并发。演进方案是 durable outbox/commit receipt + 幂等 reconcile，并把 Session 边界升级为跨进程单写者或数据库 CAS。

### 23.3 白板回答：画 7 个框

```text
┌──────────────────────────┐
│ Persistent State         │
│ World / Agent / Memory   │
└────────────┬─────────────┘
             ↓ load
┌──────────────────────────┐
│ Observation Projection   │
│ hidden truth filtered    │
└────────────┬─────────────┘
             ↓
┌──────────────────────────┐
│ Context Assembly         │
│ input + goal/plan + mem  │
└────────────┬─────────────┘
             ↓
┌──────────────────────────┐
│ LLM Proposal             │
│ Goal / Plan / Action     │
└────────────┬─────────────┘
             ↓
┌──────────────────────────┐
│ Policy / Contract / Auth │
└────────────┬─────────────┘
             ↓
┌──────────────────────────┐
│ Executor → CaseEngine    │
│ new world + events       │
└────────────┬─────────────┘
             ↓
┌──────────────────────────┐
│ Commit & Projections     │
│ World → Memory → Plan    │
└────────────┴─────────────┘
```

现场必须补一句：最后一框当前不是全局事务；成功路径实际是 world → ordinary memory → refreshed observation/plan evaluation → AgentState → reflection。

### 23.4 高频追问（24 题）

#### 1. World State 和 Agent State 最大区别是什么？

- **考察点：** 是否把事实与意图分开。
- **推荐回答：** World 记录已经发生什么，AgentState 记录 Agent 当前想完成什么以及准备怎么做。前者优先级更高，冲突时以 World/新 Observation 为准。
- **项目证据：** `CaseSessionState` vs `CooperativeAgentState`；成功 world commit 后 Runtime 重新读取 Observation 再评估 Plan。

#### 2. 项目真正的权威事实源是什么？

- **考察点：** 能否找到 source of truth。
- **推荐回答：** 静态真相是冻结 `CaseDefinition`，某 Session 当前进度是持久 `CaseSessionState`。Campaign/Memory/AgentState 都不能覆盖它。
- **项目证据：** `domain/cases.py`、`JsonStateStore.load_case_session()`。

#### 3. 为什么不直接把所有 State 放进 Prompt？

- **考察点：** Context 与 State 边界、隐私和 token 成本。
- **推荐回答：** Prompt 是裁剪后的决策输入，不是数据库。完整 case 包含隐藏真相；完整历史和 Memory 也会超长、过期、跨权。项目只把安全 Observation 和限额 Memory 投影进去。
- **项目证据：** `AgentContextFilter`、`AgentMemoryContext.char_budget/max_selected`。

#### 4. Observation 是 State 吗？

- **考察点：** 派生视图概念。
- **推荐回答：** 广义上是某时刻观测状态；工程上不是持久权威 State，而是从 world/player/session 生成的 immutable projection。
- **项目证据：** `CaseObservation` 没有 repository；每次 `case_observation()` 重建。

#### 5. Context 是 State 吗？

- **考察点：** 持久性与单轮性。
- **推荐回答：** Context 是某轮给模型的临时信息集合，由 State、当前输入和权限视图派生；Turn 后释放，不能作为恢复源。
- **项目证据：** `GameNPCAgentInput` 在 `handle()` 内构造，`ContextAssembler.build_planning_request()` 序列化。

#### 6. Memory 是 AgentState 的一部分吗？

- **考察点：** 生命周期拆分。
- **推荐回答：** 不是。AgentState 是 Session 内 Goal/Plan；长期 Memory 是玩家级跨 Session SQLite 数据；当轮 `AgentMemoryContext` 只是检索投影。
- **项目证据：** 独立 `cooperative_agents/*.json` 与 `memories.sqlite3`。

#### 7. Plan 是独立 State 吗？

- **考察点：** 领域模型与持久化结构区别。
- **推荐回答：** `AgentPlan` 是独立领域模型，但作为 `CooperativeAgentState.current_plan` 嵌入保存，没有独立 repository。
- **项目证据：** `domain/cooperative_planning.py`、`save_cooperative_agent_state()`。

#### 8. LLM 能不能宣布计划完成？

- **考察点：** deterministic completion。
- **推荐回答：** 它能提议更新，但真实完成由 PlanEvaluator 对 Observation 的结构化条件判断；模型文本不会改变 world。
- **项目证据：** `DeterministicPlanEvaluator.condition_met()`。

#### 9. 谁拥有最终状态修改权？

- **考察点：** Engine、Service、Store 分工。
- **推荐回答：** 对 World 而言，CaseEngine 有业务转换权，Service 有提交编排权，Store 有物理写入权；只有三者串起来才能形成新事实。AgentState 则由 Runtime 受控更新。
- **项目证据：** `CaseToolExecutor.execute()` → `CaseEngine.execute()` → `submit_action_with_receipt()` → `save_case_session()`。

#### 10. Runtime 会直接修改 World 吗？

- **考察点：** orchestration boundary。
- **推荐回答：** 不直接拼装世界快照；它把 validated Action 交给 service，最终由 Engine 计算并提交。
- **项目证据：** `CooperativeRuntime.handle()` 调 `service.submit_action_with_receipt()`。

#### 11. 状态怎样跨 Turn 保存？

- **考察点：** persistence path。
- **推荐回答：** CaseSession/AgentState/Player/Campaign/Dialogue 是 JSON，Memory/history 是 SQLite；下一请求通过 IDs 重新加载并生成 Context。
- **项目证据：** `JsonStateStore`、`SQLiteMemoryRepository`、`SQLiteCooperativeHistoryRepository`。

#### 12. 世界 revision 和 Agent revision 一样吗？

- **考察点：** 多版本时钟。
- **推荐回答：** 不一样。Case revision 随成功领域事件推进；Agent revision 每个 cooperative turn 投影推进，即使纯 RESPOND 或拒绝也可能变化。
- **项目证据：** Engine 中 session `revision + 1`；Runtime `_advance_state_revision()`。

#### 13. 状态写失败怎么办？

- **考察点：** failure semantics。
- **推荐回答：** world 写失败就不进入后续投影；world 成功而 Memory/AgentState 失败则承认 world，标 projection/index pending 或 error，依靠 reconcile，而不是假装全回滚。
- **项目证据：** `V1MemoryCoordinator.commit_engine_result()`、Runtime `agent_state_projection_pending`。

#### 14. 有事务吗？

- **考察点：** 是否夸大可靠性。
- **推荐回答：** SQLite repository 内有局部事务，JSON 单文件原子替换；没有覆盖 world/AgentState/Memory/history 的全局事务。
- **项目证据：** SQLite `BEGIN IMMEDIATE`；JSON `_write()`；两套存储分开调用。

#### 15. 有 CAS/乐观锁吗？

- **考察点：** 并发精度。
- **推荐回答：** AgentState 有 expected revision 逻辑检查，正常单进程 Runtime 还以 Session `RLock` 包住完整读改写链；CaseSession 本身没有 expected revision，锁也不跨进程。所以可以宣称单进程受控入口已串行化，不能宣称数据库级或多进程 CAS。
- **项目证据：** `save_cooperative_agent_state()` 和 `save_case_session()` 对比。

#### 16. 两个用户会串 State 吗？

- **考察点：** ownership isolation。
- **推荐回答：** 正常路径按 player/case/session 校验，Memory 按 player 隔离；但这不等于认证系统，知道本地 ID 的请求没有 cookie/token 层保护。
- **项目证据：** `submit_player_contribution()` ownership checks；Memory scope filter。

#### 17. 两个请求同时改同一个 Session 呢？

- **考察点：** lost update。
- **推荐回答：** 正常单进程入口不会并发进入：不同 operation 也由共享 Session `RLock` 串行执行，并发测试证明 revision 最终推进两次且无重叠写。多进程或直接 Store 写仍可能发生，因为没有数据库 CAS。
- **项目证据：** `JsonStateStore.session_write_lock()`；各写入口的锁；`test_same_session_different_operations_are_serialized_without_lost_update()`。

#### 18. 崩溃后能完整恢复吗？

- **考察点：** recovery honesty。
- **推荐回答：** 权威快照、Memory/Campaign 对账和 completed operation replay 可恢复；pending confirmation、当轮 Context 和部分跨存储投影不能完整恢复。
- **项目证据：** server startup reconciliation、in-memory pending、history recovery_required。

#### 19. 为什么 completed history 不能恢复 pending 授权？

- **考察点：** replay 与 authorization 区分。
- **推荐回答：** 历史结果证明曾经生成过 proposal，不证明它在当前 world revision 仍有效。代码只在 live dict 中找到完全相等且 revision 当前的 pending 才返回。
- **项目证据：** `ClinicService.submit_player_contribution()` completed replay branch。

#### 20. 错误 Memory 会不会污染世界？

- **考察点：** indirect influence boundary。
- **推荐回答：** 不会直接写 world，但会影响 Proposal。之后仍经过所有 deterministic guards，因此风险被限制为决策偏差；若 Proposal 合法但语义选择差，仍可能造成不佳但合法的结果。
- **项目证据：** Memory 只进入 `GameNPCAgentInput`，无 `save_case_session` 路径。

#### 21. 为什么普通 Memory 要 world-first？

- **考察点：** projection provenance。
- **推荐回答：** 避免把未提交或失败 Action 写成长期记忆。Memory 只从 committed events 投影，失败可由 action history 重建。
- **项目证据：** coordinator 注释和执行顺序。

#### 22. 一请求一 Turn 还是 Agent 吗？

- **考察点：** autonomy definition 与产品 trade-off。
- **推荐回答：** 是交互式、有状态、工具型 Agent；跨 Turn 有持久 Goal/Plan 和环境反馈。它不是后台连续执行 Agent，如需无人值守可在外层加入 scheduler。
- **项目证据：** `CooperativeRuntime.handle()` 单次返回；AgentState 跨请求保存。

#### 23. 为什么不用一个数据库统一保存？

- **考察点：** 架构取舍。
- **推荐回答：** 当前阶段 JSON 提供可读、可调试的聚合快照，SQLite 适合唯一约束、事务和向量元数据；代价是跨存储一致性复杂。规模或并发提升后，应优先把核心 world/Agent state 迁入支持原子 CAS/outbox 的统一事务库。
- **项目证据：** `JsonStateStore` vs two SQLite repositories。

#### 24. 当前状态管理最大风险是什么？

- **考察点：** 能否抓住系统性风险。
- **推荐回答：** 当前最大风险是跨存储 partial commit 后的完整自动恢复尚未闭环；其次是 Session 锁只在单进程有效。单文件完整和线程串行仍不代表 world、AgentState、Memory/history 是一个事务。
- **项目证据：** world-first 提交、projection pending/recovery_required 分支；CaseSession 无跨进程 CAS；多个存储无统一 commit protocol。

---

## 24. 理解检查：15 个答不上来就说明还没真正理解

以下问题不要背本文原句，应能顺着代码调用链回答：

1. 为什么 `CaseDefinition` 和 `CaseSessionState` 都属于世界，却只有后者是运行中的可变进度？
2. 如果 LLM 在回答中说“已经发现 clue_x”，什么条件下 clue_x 才会真的出现在下一轮 Observation？
3. `CaseEngine` 为什么既可以说是状态修改者，又不能说它直接写了数据库？
4. World revision 和 Agent revision 分别在什么事件上增加？为什么不能直接比较大小判断同步？
5. 为什么 Observation 有 `session_revision`，但 Observation 自身不需要 repository？
6. Context 中哪几类信息来自持久状态，哪几类只属于当前 Turn？
7. 如果 Memory 检索服务失败，哪些状态不受影响，Agent 如何降级？
8. 为什么 `AgentMemoryContext` 不是长期 Memory 本身？
9. LLM 提议了一个新 Plan，同轮 Action 却不匹配第一步时，World、AgentState 各会发生什么？
10. Tool 执行成功、world 保存成功，但 AgentState 保存失败时，下一轮应该信谁？可能出现什么恢复问题？
11. 单文件 `os.replace` 与应用层 Session `RLock` 分别解决什么问题？为什么两者仍没有解决多进程 CAS？
12. 为什么 completed cooperative result 可以做幂等响应，却不能自动恢复旧 pending authorization？
13. 当前哪些数据可以从更上游事实重建，哪些数据丢失后只能让用户重新发起？
14. 如果要支持同一 Session 的两个并行请求，最小安全改造应放在哪一层？仅增加 revision 字段为什么不够？
15. 如果要增加真正连续 Agent Loop，怎样复用现有单 Turn Runtime，而不破坏每次 world commit 后重新 Observation 的事实边界？

---

## 25. 最终边界清单

### 已实现

- 显式分离 World、Agent Goal/Plan、Campaign、Memory、Dialogue、Turn history。
- LLM 只见安全投影并只产 Proposal。
- Engine 纯确定性转换，typed command/event/result。
- JSON 单文件原子替换与类型校验。
- AgentState ownership + revision 逻辑检查。
- SQLite Memory/history 局部事务、唯一约束、幂等 receipt。
- world-first Memory projection 和部分启动 reconcile。
- post-world Observation 再评估 Plan。
- pending 与 world revision/owner/decision 绑定。

### 部分实现

- 跨存储恢复：Memory/Campaign/部分 index 有 reconcile，但 AgentState 与所有 store 的统一恢复没有闭环。
- 并发：正常单进程受控入口已有同 Session 串行化和冲突测试；多进程、直接 Store 写及数据库原子 CAS 未覆盖。
- 协作历史：completed 可重放；中途崩溃只保守标不确定。

### 未实现

- 跨 JSON/SQLite 全局事务或统一 durable outbox。
- CaseSession 数据库级原子 CAS。
- 多进程同 Session 锁/租约。
- pending confirmation 持久化与重启恢复。
- 统一 checkpoint manager。
- 单请求内无人值守连续执行 loop。
- 状态自动过期、retention、garbage collection 和完整删除流程。

### 面试时最后一句

> 这个项目状态管理最有价值的地方不是“State 类型很多”，而是它把模型认知、公开观测和世界事实分开，并让事实只能通过确定性提交链产生；我也不会把单文件原子写和 revision 字段夸大成已经解决了并发与跨存储事务。
