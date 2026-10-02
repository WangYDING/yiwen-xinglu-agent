# 《异闻行录》Final Agent Architecture & Interview Guide

审计日期：2026-08-26  
审计对象：当前工作树源码、当前测试、`runtime_data` 中 production acceptance artifacts 及现有 Phase B/C 报告  
审计原则：运行代码优先于 README/旧设计；后到且可复核的 production artifact 优先于较早报告；Code Exists、Test Proven、Production Proven 严格分开。

> **CRITICAL TRUTH DRIFT: NONE**
>
> 没有发现会推翻项目核心定性的重大架构漂移。但存在重要的**证据/文档时序漂移**：较早的 `archive/reflection/PHASE_C_REFLECTION_PRODUCTION_AUDIT.md` 说 Reflection 未接入 production，随后 `archive/reflection/PHASE_C_REFLECTION_IMPLEMENTATION_REPORT.md` 记录首次真实生成失败；当前 composition root 已接入 Reflection，且更晚的 `runtime_data/phase_c_*final_acceptance` artifacts 已证明真实 DeepSeek proposal、canonical Learning Memory、SQLite、BGE-M3、重启 reconciliation 与后续使用链。旧结论不能继续代表当前版本。

## 1. Executive Summary

《异闻行录》当前最准确的定义是：**一个由 LLM 驱动、由确定性 Runtime 约束并带跨局语义记忆与受验证 Reflection 的有状态智能游戏 NPC Agent 系统**。

它不是“LLM 直接调用函数改世界”，也不是普通聊天机器人。玩家的自然语言先成为 `PlayerContribution`；NPC 对贡献作评价，提出 Goal/Plan/Action；Runtime 再依次执行 Goal/Plan policy、Action contract、NPC authority 和 plan alignment；`CaseToolExecutor` 把合法动作翻译为 domain command；只有 `CaseEngine` 计算新的 `CaseSessionState` 与权威事件。世界提交后，确定性 `PlanEvaluator` 更新独立的 Agent state，Memory 从已提交事件投影，Reflection 在生命周期边界后置运行且失败不回滚世界。

最终审计结论：

- **产品正式入口**：`yiwen-xinglu.exe`，映射到 `xuanyi_npc.clinic.server:main`。
- **默认生产模式**：`--npc-mode llm`；必须显式 `--confirm-paid-agent` 和正数预算，否则 fail closed。LLM 模式未显式指定 memory 时默认 semantic，并因此启用 Reflection。
- **Agent 定性**：可以称为“智能游戏 NPC Agent”；更具体是 constrained、planning、stateful、memory-augmented、reflection-enabled hybrid agent。
- **production-proven**：真实 DeepSeek NPC、Goal/Plan/Action loop、CaseEngine 执行、SQLite Memory、production BGE-M3、跨 session/restart 检索、输入投影、accepted-used attribution，以及一次可审计的行为影响；Phase C 后到 artifacts 还证明真实 Reflection proposal、B2/确定性派生 lesson、canonical Learning Memory、receipt/index reconciliation。
- **未证明**：Memory 对玩法或任务表现的统计提升；大规模、多案例、多玩家 production 稳定性；任意工具使用；自主 diagnosis/treatment；multi-agent。
- **求职判断**：已足以作为 Agent 应用开发岗位的核心简历项目；没有投递前必须修改的架构级 blocker。

### 证据优先级

1. 当前源码与实际 composition root；
2. `runtime_data/phase_c_receipt_final_acceptance`、`phase_c_incremental_index_acceptance`、`phase_b_smoke_v2` 等 raw artifacts；
3. 当前 469 项 pytest 回归；
4. Phase B/C implementation/audit 文档；若与 1/2 冲突，视为历史记录。

## 2. Official Production Entry

### 2.1 正式入口与对象职责

| 文件 | class/function | 真实职责 |
|---|---|---|
| `pyproject.toml` | `[project.scripts] yiwen-xinglu` | 安装后生成 `yiwen-xinglu.exe`，指向 `xuanyi_npc.clinic.server:main` |
| `src/xuanyi_npc/clinic/server.py` | `main()` | composition root：校验参数，组装 NPC、Memory、Reflection、`ClinicService` 和 loopback HTTP server |
| 同上 | `build_game_npc()` | `llm` 注入 `GameNPCAgent(DeepSeekChatAdapter)`；`offline` 注入 `DeterministicCooperativeNPC` |
| 同上 | `build_production_memory()` | 组装 SQLite repository、BGE-M3 adapter、index、retrieval、memory coordinator |
| 同上 | `build_production_reflection()` | 仅在 `llm + semantic` 下，复用同一个 DeepSeek adapter、SQLite repository 与 index service 组装 Reflection |
| 同上 | `ClinicRequestHandler.do_POST()` | `/cases/natural`、`/cases/cooperate` 进入 Agent cooperative turn；`/cases/chat` 进入角色对话；`/cases/action` 是 manual/baseline |
| `src/xuanyi_npc/application/clinic.py` | `ClinicService.submit_player_contribution()` | 构造 `PlayerContribution`，实例化 `CooperativeRuntime`，管理 pending confirmation |
| `src/xuanyi_npc/application/cooperative_runtime.py` | `CooperativeRuntime.handle()` | 一次 Agent turn 的编排、策略、authority、执行前后状态与 telemetry |
| `src/xuanyi_npc/agents/game_npc.py` | `GameNPCAgent.propose_turn()` | 调用 LLM，产生结构化 Goal/Plan/Decision/MemoryUsage proposal；最多一次 repair 后保守 fallback |
| `src/xuanyi_npc/application/multicase.py` | `MultiCaseEpisodeService.submit_action_with_receipt()` | 调用执行器，提交状态，协调 Memory projection/index 并返回 receipt |
| `src/xuanyi_npc/application/case_tools.py` | `CaseToolExecutor.execute()` | 校验工具参数并把 `AgentAction` 翻译为确定性 command |
| `src/xuanyi_npc/engine/case_engine.py` | `CaseEngine.execute()` | 执行规则，返回新 session、权威事件、消息/评分；不原地修改输入 |
| `src/xuanyi_npc/storage/json_store.py` | `JsonStateStore` | 持久化 player、case session、cooperative Agent state 等 JSON 状态 |
| `src/xuanyi_npc/storage/sqlite_memory.py` | `SQLiteMemoryRepository` | Memory、source receipt、embedding、Reflection lifecycle receipt 的 SQLite source of truth |

### 2.2 六个直接答案

1. **official/default path**：`yiwen-xinglu.exe → clinic.server:main → loopback HTTP UI → ClinicService → CooperativeRuntime`；默认 `npc-mode=llm`。
2. **`xuanyi-play`**：当前不是另一条可用 CLI；`pyproject.toml` 未注册，旧 `src/xuanyi_npc/cli/play.py` 在工作树中已删除。`xuanyi-clinic` 仍是指向同一 composition root 的 deprecated compatibility alias，不是另一产品。
3. **`/cases/chat`**：不是 cooperative Agent turn。它调用 `case_chat_message()` 处理案中人物对话。Agent cooperative turn 是 `/cases/natural` 与 `/cases/cooperate`；approval/rejection 走 `/cases/cooperate/respond`。
4. **非生产入口**：`tests/`、`evaluation/real_agent_benchmark.py`、semantic holdout/benchmark runners、MCP stdio 和 `demo_case.py` 都不能冒充正式玩家入口。
5. **历史 deterministic 路径**：仍存在 `--npc-mode offline → DeterministicCooperativeNPC`，另有页面中的 manual/baseline `/cases/action`；两者都不是默认 LLM Agent 路径。
6. **`--npc-mode llm` 注入**：经 model discovery 验证、受显式费用预算约束的 `DeepSeekChatAdapter`，包装为 `GameNPCAgent`；若 memory 默认/显式为 semantic，还注入 production BGE-M3/SQLite pipeline 和共享 adapter 的 Reflection lifecycle。没有授权或预算时启动失败，不静默换成 offline。

### 2.3 正式调用链

```text
玩家
↓ HTTP POST /cases/natural 或 /cases/cooperate
ClinicRequestHandler
↓ ClinicContributionInput
ClinicService.submit_player_contribution
↓ PlayerContribution（不是 ToolCall）
CooperativeRuntime.handle
↓ safe Observation + persisted AgentState + semantic Memory context
GameNPCAgent / DeepSeek
↓ structured Goal/Plan/Decision/AgentAction proposal
GoalPlanPolicy + plan alignment + PublicActionContractValidator
↓
NPCAuthorityPolicy（自主 / 仅建议 / 需确认 / 禁止）
↓ 合法且获权后
MultiCaseEpisodeService.submit_action_with_receipt
↓
CaseToolExecutor（AgentAction → domain command）
↓
CaseEngine（规则执行，产生新 CaseSessionState + authoritative event）
↓
JsonStateStore world commit + SQLite Memory projection/index
↓
post Observation → DeterministicPlanEvaluator → AgentState projection
↓
可选 post-commit Reflection → Learning Memory/index
↓
CooperativeTurnResult → HTTP redirect/render → 返回玩家
```

## 3. Overall Architecture

以下分层完全映射当前源码；“deterministic”表示在给定输入下由 Python 规则决定，不表示其中所有 I/O 都不会失败。

| 层 | 主要对象 | 输入 → 输出 / 核心职责 | 可改 world state | 依赖 LLM | Deterministic |
|---|---|---|---:|---:|---:|
| Interface/API | `ClinicHTTPServer`, `ClinicRequestHandler` | HTTP form → application DTO/HTML；只绑定 127.0.0.1 | 否 | 否 | 是 |
| Application | `ClinicService`, `MultiCaseEpisodeService` | 用例编排、ownership/context、提交与 receipt | 间接提交 | 否 | 是 |
| Agent Runtime | `CooperativeRuntime` | Observation/Contribution/AgentState/Memory → turn result；闭环编排 | 不直接 | 否（但调用 Agent） | 是 |
| LLM Agent | `GameNPCAgent`, `DeepSeekChatAdapter` | `GameNPCAgentInput` → bounded structured proposal | 否 | 是 | 否 |
| Goal/Plan/Policy | `AgentGoalState`, `AgentPlan`, `GoalPlanPolicy`, `DeterministicPlanEvaluator` | proposal + Observation → validated/persisted state/evaluation | 否 | proposal 可来自 LLM | policy/evaluation 是 |
| Action Contract/Authority | `AgentAction`, `PublicActionContractValidator`, `NPCAuthorityPolicy` | proposal → reject/pending/authorized | 否 | 否 | 是 |
| Tool/Executor | `CaseToolExecutor` | authorized ToolCall → typed domain command → execution result | 仅通过 engine | 否 | 是 |
| Game World | `CaseEngine`, `CaseDefinition`, `CaseSessionState`, domain events | command + state → new state + event | **是，唯一规则 authority** | 否 | 是 |
| Agent State | `CooperativeAgentState`, Goal, Plan, evaluation | 跨 turn 的 NPC 工作状态 | 否 | 部分提议来自 LLM | 持久化/推进规则是 |
| World State | `CaseSessionState`, `PlayerState`, `CampaignState` | 案件事实、线索、诊断、处置、完成状态 | 是（受 engine/application commit） | 否 | 是 |
| Semantic Memory | `GameNPCMemoryRetrievalService`, projection policy, `MemoryUsageTrace` | query/index → scoped candidates → safe bounded context/attribution | 否 | 检索否；使用声明来自 LLM | 检索/验收规则是 |
| Reflection/Learning | `ReflectionLifecycleService`, generator, validator, renderer, write policy | evidence → bounded proposal → verified canonical lesson | 否；只写 Memory | proposal 是 | validation/render/write policy 是 |
| Persistence/SQLite | `SQLiteMemoryRepository` | Memory/embedding/receipt 持久化、迁移、幂等 claim/replay | 否 | 否 | 是 |
| BGE-M3 Index | `BgeM3LocalEmbeddingAdapter`, `MemoryIndexService`, cosine retriever | text → 1024d derived vectors → similarity candidates | 否 | 非生成式 embedding 模型 | 模型推理/排序配置固定 |
| Telemetry/Lifecycle receipts | `CooperativeTurnResult`, `ReflectionLifecycleResult`, SQLite receipts | attempts/status/error/index reconciliation/usage trace | 否 | 记录 LLM 结果 | 是 |

关键边界：JSON case/session 是游戏世界状态；SQLite Memory/embedding/Reflection receipt 是长期记忆与审计状态；`CooperativeAgentState` 是 NPC 工作状态。三者不能混称。

## 4. Agent Turn Runtime

### 4.1 当前真实 sequence

```text
Player natural language
→ ClinicContributionInput
→ PlayerContribution
→ resume_episode() 生成安全 CaseObservation
→ load CaseSessionState / PlayerState
→ load-or-initialize CooperativeAgentState
→ deterministic invalid-plan marking / next-goal preparation
→ player-scoped semantic retrieval（先排除 current session）
→ AgentMemoryContext + initial MemoryUsageTrace
→ GameNPCAgentInput
→ DeepSeek GameNPCAgent.propose_turn()
→ GoalUpdate + PlanUpdate + GameNPCDecision + MemoryUsageDeclaration
→ GoalPlanPolicy.validate()
→ Runtime 应用 Goal/Plan proposal
→ Memory accepted-used 第一阶段归因（goal/plan）
→ plan/action alignment
→ PublicActionContractValidator（失败时一次 repair，再 fallback）
→ Memory accepted-used 第二阶段归因（decision/tool/communication）
→ NPCAuthorityPolicy
→ RESPOND / pending confirmation / reject / authorized execute
→ MultiCaseEpisodeService
→ CaseToolExecutor
→ CaseEngine
→ authoritative world event/new CaseSessionState commit
→ committed-event Memory projection → SQLite → index
→ reload post Observation
→ DeterministicPlanEvaluator
→ CooperativeAgentState save（失败仅标 projection pending）
→ possible deterministic Reflection trigger
→ evidence → LLM proposal → validation → canonical Learning Memory → index
→ CooperativeTurnResult → response
```

### 4.2 A–J 结论

- **A. PlayerContribution 是 ToolCall 吗？** 不是。它是包含自然语言、贡献类型、ownership、可选引用/回应关系的 domain input。
- **B. “去检查纸伞”等于玩家直接执行 `inspect_object` 吗？** 不等于。它只成为 suggestion/general contribution；NPC 可以接受、部分接受、拒绝或另提方案。只有 NPC 结构化 action 经 plan/contract/authority 后才执行。
- **C. 谁最终决定 Action？** LLM/离线 Agent提出候选；Runtime 拥有是否采纳和是否执行的最终决策 authority。具体 world outcome 由 CaseEngine 规则决定。
- **D. LLM 可直接修改 `CaseSessionState` 吗？** 不可以。LLM 只返回 Pydantic 约束的 proposal。
- **E. 谁执行工具/动作？** `CaseToolExecutor`，由 `MultiCaseEpisodeService` 调用。
- **F. 谁修改 world state？** `CaseEngine` 计算新状态/事件，application/store 提交；不是 LLM。
- **G. Goal 谁提出/维护？** 初始/阶段切换 Goal 由 Runtime 确定性创建；LLM 可提 KEEP/REPLACE/BLOCK/ABANDON；`GoalPlanPolicy` 校验；Runtime 持久化维护。
- **H. Plan 谁生成？** production LLM 生成 draft；Runtime 分配稳定 step identity/status 并持久化。offline Agent 走确定性实现。
- **I. Plan 是否完成由谁评价？** `DeterministicPlanEvaluator` 依据 pre/post Observation 和工具成功状态评价；不是 LLM 自报。
- **J. AgentState 与 World State 分离吗？** 是。`CooperativeAgentState` 与 `CaseSessionState` 分库存储、不同 revision/失败语义。

## 5. LLM vs Deterministic Runtime

| 行为/决策 | LLM | deterministic Runtime | 最终 authority |
|---|---:|---:|---|
| interpret player contribution | 评价语义与合作 disposition | 构造/校验 contribution、ownership | Runtime contract |
| goal proposal | 是 | phase/terminal/policy 校验并应用 | `GoalPlanPolicy` + Runtime |
| plan generation | 是 | step schema、公开 target、phase、authority 校验 | Policy + Runtime |
| action proposal | 是 | plan alignment + contract + authority | Runtime |
| dialogue | 是 | schema/长度/安全上下文边界 | Runtime 返回合法 proposal |
| tool selection | 候选 | allowlist、公开 action surface、plan alignment | Runtime |
| tool execution | 否 | 是 | `CaseToolExecutor` |
| diagnosis | 可提出 | readiness、proposal-only、CaseEngine 规则 | Runtime + 玩家确认/协商 + CaseEngine |
| treatment | 可提出 | confirmation-required、CaseEngine 规则 | 玩家确认 + Runtime + CaseEngine |
| world mutation | 否 | 是 | CaseEngine/application commit |
| observation creation | 否 | safe projection | `AgentContextFilter`/executor |
| plan evaluation | 否 | 是 | `DeterministicPlanEvaluator` |
| memory retrieval | 否 | query、cosine、scope/filter/budget | Memory runtime |
| memory selection | 否 | score + filter + projection policy | Memory runtime |
| memory attribution | 声明 used IDs/影响类型 | 只接受 selected 且与实际 accepted state/action 一致者 | Runtime `MemoryUsageTrace` |
| reflection proposal | 是，bounded finding/lesson structure | evidence builder、schema/grounding validation | Validator |
| reflection grounding | 只能引用 refs | closed-world 验证 | `ReflectionProposalValidator` |
| canonical lesson generation | 否（最终 prose 不受信） | 从 verified refs 确定性派生/渲染 | `DeterministicLessonRenderer` |
| memory write | 否 | write policy + repository | Runtime/repository |
| embedding/index | 否 | BGE adapter/index/reconciliation | Memory runtime |
| trigger/replay | 否 | lifecycle boundary、SQLite claim/receipt | Reflection lifecycle |

避免 LLM 直接控制世界的核心不是一句 prompt，而是不可绕过的对象边界：LLM 没有 state store/CaseEngine 引用；输出必须先变为 `GameNPCTurnProposal`/`AgentAction`；随后经过 plan、public contract、authority；执行器重新解析参数；CaseEngine 再按 domain rule 生成不可由模型伪造的事件与新状态。

## 6. Goal / Plan / Action

当前真实对象名：`GameNPCAgent`、`AgentGoalState`、`AgentPlan`、`GoalPlanPolicy`、`DeterministicPlanEvaluator`、`AgentAction`、`PublicActionContractValidator`、`NPCAuthorityPolicy`、`CaseToolExecutor`、`CaseEngine`。当前代码**没有**名为 `ActionContract` 或 `V0ToolExecutor` 的主路径类；对应实际组件是 `AgentAction`/`PublicActionContractValidator` 与 `CaseToolExecutor`。

1. Goal 不是一次性 prompt 文本；它是 `CooperativeAgentState.current_goal` 中有 identity、type、status、completion condition、revision 的持久化状态。
2. Plan 跨 turn 存在于 `current_plan`；每轮带入 `GameNPCAgentInput`。
3. 工具成功后 evaluator 将 active step 置 completed，若还有兼容的下一步则推进 `current_step_index`；否则 revise/complete/abandon。
4. `complete_goal` 由 `DeterministicPlanEvaluator.condition_met()` 对 post Observation 判断，Runtime 也会在行动前完成已满足条件的 Goal。
5. LLM 说“完成”不算完成；proposal schema甚至不赋予它直接提交 `PlanEvaluationOutcome` 的权力。
6. 非 RESPOND action 必须匹配 active plan step 的 tool 与 public target；否则 `action_outside_active_plan`。
7. invalid action 先触发 safe repair feedback；再次失败变为 fallback/respond，或以明确 error/status 被拒绝，不执行 world mutation。
8. NPC 权限由 tool allowlist + authority mode 限制；诊断需协商，处置需确认，未知工具 forbidden。

```text
Goal（持久化、有确定性完成条件）
↓
Plan（LLM draft → Policy 验证 → Runtime 状态）
↓
当前 PlanStep
↓
Action proposal
↓ plan alignment + public contract + authority
Executor → CaseEngine
↓
Environment Feedback / post Observation
↓
DeterministicPlanEvaluator
↙ keep/advance   ↓ revise   ↘ complete/abandon
下一 Turn       新 Plan       下一阶段 Goal / Reflection trigger
```

## 7. Authority Boundary

当前规则：

- dialogue/explain/ask/hint 等 `RESPOND`：autonomous social action，不改世界；
- investigation tools（observe/question/inspect/observe_qi/investigate_location）：autonomous，理由是可逆的信息动作；
- `submit_diagnosis`：proposal-only，必须有与原 decision/revision 匹配的协商确认；
- `execute_treatment`：confirmation-required，必须有匹配确认；
- 缺少 ToolCall、未知工具、超出公开 action surface、错误 target/argument：forbidden/rejected。

为什么需要 Contract + Authority + Executor + CaseEngine：Contract 证明“这是此刻公开存在且参数正确的动作”；Authority 证明“NPC 此刻有权执行”；Executor 证明“结构化 proposal 能安全翻译为已知 command”；CaseEngine 证明“状态转换满足游戏规则”。任一层都不能替代其他层。

真实形态示例：玩家说“去检查纸伞” → `PlayerContribution(SUGGESTION)` → NPC 评价为 accept 并提出 plan step/`inspect_object(investigation_id=inspect_umbrella)` → policy 验证该 target 在当前 Observation 且与 plan 对齐 → authority 判定为 autonomous investigation → `CaseToolExecutor` 构造 `InvestigationCommand` → `CaseEngine` 产生 `investigation_completed` event 和新线索。玩家没有直接调用工具，LLM 也没有直接写 session。

## 8. World State vs Agent State

| 对象 | 类别 | 保存内容 |
|---|---|---|
| `CaseSessionState` | World State | discovered clues、action history、submitted diagnosis、selected treatment、status、revision |
| `PlayerState` / `CampaignState` | World/Product State | 玩家身份、技能/跨案公开进度 |
| `CooperativeAgentState` | Agent State | episode goal、current goal、current plan、last evaluation、revision |
| `AgentGoalState` / `AgentPlan` | Agent State | NPC 的目标与跨 turn 执行计划 |
| episodic/learning Memory | Long-term derived state | 已提交公开事件或已验证 Reflection lesson 的跨 session 投影 |
| Reflection lifecycle receipt | Audit/lifecycle state | trigger claim、attempt、terminal result、index reconciliation |

事务/失败语义：

1. world commit 发生在 `CaseToolExecutor/CaseEngine` 成功后，由 `MultiCaseEpisodeService` 保存权威 session（semantic 模式下与 event→Memory projection 协调）。
2. Agent projection 在 world commit 后、reload post Observation 和 evaluator 之后保存。
3. Reflection 最后运行；失败**不 rollback world**，只返回/persist failed-safe telemetry。
4. Memory projection/index 失败不应把已经发生的 CaseEngine 事实“变成没发生”；projection/index 使用 pending/reconciliation 恢复。当前代码对 world commit 与 Memory projection 有协调 receipt，embedding 明确是可重建派生物。
5. 原因：玩法事实需要强一致、单一 authority；Agent projection、Reflection 和 vector index 是可恢复派生状态。把它们绑成一个大事务会让非关键 LLM/embedding 故障破坏已合法发生的游戏动作。

## 9. Semantic Memory

### 9.1 最终链路

```text
committed authoritative CaseEngine event
→ V1MemoryCoordinator / DeterministicMemoryProjector
→ SQLite memory_events + source receipt（source of truth）
→ EmbeddingDocument（安全 canonical representation）
→ local BGE-M3 1024d vector
→ SQLite memory_embeddings（derived, rebuildable）
→ current-player scoped cosine retrieval
→ pre-ranking player/current-session/type/status filters
→ conflict/hidden-safe projection + char/count budget
→ AgentMemoryContext
→ GameNPCAgentInput.memory_context
→ LLM used declaration
→ Runtime accepted-used attribution
```

### 9.2 十个答案

1. Memory 保存在 state-dir 下 `memories.sqlite3`；不是 prompt 文件。
2. BGE-M3 把 canonical Memory/query 编为 production 1024d 向量，用于语义候选排序；不生成事实、不作 authority。
3. SQLite 保存 authoritative Memory records、source receipts、derived embeddings 和 Reflection receipts，并提供 migration/幂等/reconciliation。
4. embedding 不是 source of truth；content hash/space/dimension 不一致时应重建或 reconciliation。
5. current-session exclusion：在候选排序前排除 `source_session_id == current_session_id`，防止同局事件作为“历史经验”即时回灌。
6. player isolation：repository 查询与投影都绑定 player_id；他人 Memory 不进入候选。
7. Game NPC 可读类型为当前 projection policy 允许的 `EPISODIC` 与 `LEARNING`；inactive/deleted/corrupt/conflicting 项不可读。
8. candidate 是过滤后的相似候选；selected 是预算内安全投影；declared-used 是模型在 structured output 中声称使用；accepted-used 是 Runtime 证明该 ID 来自 selected，且声明的 goal/plan/action/tool/communication 影响与最终接受结果一致。
9. 检索到不等于影响行为；selected 也不等于 used。只有 accepted-used trace 才能做本系统定义下的可审计归因，而且它仍不是对模型内部因果机制的哲学证明。
10. `MemoryUsageTrace` 防止“检索即使用”的夸大，记录 available/candidate/selected/declared/accepted/rejected 与具体影响类型。

### 9.3 Production acceptance

Phase B `phase_b_smoke_v2` 证明：Session A 的 committed investigation Memory 写 SQLite/BGE → 完全停进程 → Session B 检索相同 ID → safe projection → 进入真实 `GameNPCAgentInput` → 模型声明并被 Runtime accepted-used；新 Session B Memory 被 current-session exclusion 排除。

Phase C 后到 acceptance 进一步形成：Session A → `Learning` Memory（canonical text 明示“不是当前世界事实”）→ SQLite receipt/index → restart → Session B → exact Learning Memory retrieval → `GameNPCAgentInput` → accepted-used → goal/plan/action/tool priority 或 communication 中至少一项被 Runtime 验收为 influence。可写为“一次 production acceptance 证明行为受 Memory 影响”，不可写为“Memory 提升成功率/体验”。

## 10. Reflection Learning

### 10.1 最终真实链路

```text
post-commit experience
→ deterministic lifecycle trigger
→ ReflectionEvidenceBuilder → ReflectionEvidenceBundle
→ DeepSeek ReflectionProposal（bounded findings + structured lesson proposals）
→ schema repair（最多一次）/ fallback telemetry
→ ReflectionProposalValidator（closed-world EvidenceRef + type-specific grounding）
→ reusable lesson structural validation
→ B2 deterministic derived lesson
→ DeterministicLessonRenderer（canonical prose/scope/limitations）
→ ReflectionMemoryWritePolicy
→ Learning Memory
→ SQLite + lifecycle receipt
→ BGE-M3 incremental index/reconciliation
→ future-session retrieval
```

LLM 负责：从公开 evidence bundle 中提出 finding 和有限 `ReusableLessonProposal` 结构（lesson type、scope type/tags、evidence refs、confidence）；失败时允许一次结构化 repair。它不写最终 Memory 文本、不选择数据库 ID、不执行 action、不修改世界。

Python Runtime 负责：trigger、evidence projection、closed-world ref 校验、finding/lesson grounding、accepted-memory helpfulness 校验、B2 派生、canonical renderer、write policy、identity/duplicate、SQLite write、index/reconciliation、receipt/replay。

最终未采用“LLM 自由 lesson → 直接写 Memory”，因为自由文本无法可靠区分玩家观点、NPC rationale 与权威 world fact，也容易写入 hidden/过宽/永久正确的经验。当前方案只信任 LLM 提出的有限结构；Python 从已验证 EvidenceRef 重新渲染 canonical lesson，并固定加入“历史经验，不是当前世界事实”“只在相同公开结构且不冲突时参考”“不保证相同结果”。

污染防护：

- 玩家观点必须有 contribution evaluation，不能单独晋升为事实；
- NPC dialogue/rationale 不是 authoritative outcome；
- evidence bundle 来自 safe public projections，不接收 raw hidden `CaseSessionState` truth；
- memory helpfulness 必须引用 `accepted_used_memory_ids`，selected-but-unused 不可宣称有帮助；
- scope 有有限 enum、tag 上限和 canonical limitation，拒绝无边界经验。

## 11. Production Evidence

### 11.1 分级矩阵

| 能力 | Production | Test | 严格结论 |
|---|---|---|---|
| GameNPCAgent real LLM | PROVEN | PROVEN | 正式 exe、DeepSeek、`runtime_kind=real_llm` |
| Goal/Plan | PROVEN | PROVEN | production turn 持久化 plan/evaluation |
| constrained action execution | PROVEN | PROVEN | real proposal → CaseEngine event |
| ordinary Memory write | PROVEN | PROVEN | SQLite source receipt/memory rows |
| BGE-M3 index | PROVEN | PROVEN | verified space、1024d、4096-byte vectors |
| Reflection generation | PROVEN（后到 acceptance） | PROVEN | real provider request/usage，valid proposal |
| B2 deterministic derived lesson | PROVEN | PROVEN | canonical Learning rows来自最终 renderer |
| canonical renderer | PROVEN | PROVEN | persisted text与 renderer contract一致 |
| Learning Memory write | PROVEN | PROVEN | `memory_type=learning`, `reflection_memory_v1` |
| restart | PROVEN | PROVEN | 完全重启后的 repository/index/receipt 状态 |
| receipt reconciliation | PROVEN | PROVEN | pending→complete reconciliation metadata |
| trigger idempotency/replay | PROVEN（bounded acceptance） | PROVEN | SQLite terminal receipt，重启不重复 LLM/write |
| cross-session retrieval | PROVEN | PROVEN | exact prior-session ID进入新 session |
| safe projection | PROVEN | PROVEN | bounded public summary，无 raw hidden state |
| GameNPCAgentInput entry | PROVEN | PROVEN | production trace/response attribution |
| accepted-used attribution | PROVEN | PROVEN | selected→declared→Runtime accepted |
| behavior influence | PROVEN（单次 acceptance） | PROVEN | 至少一类 accepted output 变化；非统计收益 |
| statistical gameplay/task improvement | **NOT PROVEN** | **NOT PROVEN** | 无足够 A/B、多 seed、多 case benchmark |

### 11.2 “五级证据”准确说法

当前 production acceptance 已覆盖：`AVAILABLE → RETRIEVED → ENTERED INPUT → ACCEPTED_USED → BEHAVIOR_INFLUENCED`。最后一级含义是 Runtime 对一次实际输出中的 goal/plan/decision/tool priority/communication 影响进行了契约验收；它**不等于**“整体 gameplay/task performance improved”。

## 12. Failure Recovery

| 机制 | 解决的问题 |
|---|---|
| Reflection empty fallback | 无有效 proposal 时不编造 lesson，不破坏 turn |
| bounded structured output repair | JSON/schema/grounding 首次失败时仅一次受限修复，避免无限重试 |
| failure telemetry | 保留 stage/code/exception/finish reason/token/request ID，区分生成、验证、repository、index 故障 |
| restart-safe trigger receipt | LLM 前 atomic claim，terminal result 跨进程 replay，避免重复费用/写入 |
| Reflection failure isolation | Reflection 后置，失败不 rollback CaseEngine event/world state |
| incremental embedding reconciliation | 只补缺失/不一致 embedding，避免全量重建导致冲突与成本 |
| index-pending recovery | Memory 已写但向量失败时显式 pending，启动/服务 reconciliation 可恢复 |
| receipt/index reconciliation | 已终态 receipt 的 index 状态可从 pending 修复为 complete，不重做 LLM |
| idempotent replay | 同 trigger 返回持久化 terminal result，保持单一 Memory identity |
| Memory query bounding | 长 Observation/Plan 不超过 schema/embedding query budget，保留高优先级字段 |

这是一套本地单进程 production reliability 设计，不应包装成“分布式系统”。

## 13. Remaining Technical Debt

| 项目 | 事实/风险 | Severity | 阻塞秋招 | 现在建议修改 |
|---|---|---:|---:|---:|
| legacy naming | package `xuanyi_npc`、`clinic.server`、`ClinicService`、`xuanyi-clinic` alias 仍在；只属内部实现命名 | LOW | NO | NO |
| DeepSeek adapter wording | 通用 `_chat_payload()` 仍无条件附加 `AgentAction` wording/example；Reflection request 虽有自己的 schema，也收到该措辞，可能增加歧义/token | MEDIUM | NO | NO（冻结后专项） |
| ApplicabilityScope tags | `similar_*` 的 tag 当前主要是 EvidenceRef ID；是强 provenance anchor，但不是真正 learned semantic pattern label | MEDIUM | NO | NO |
| smoke case range | 核心 Phase C 最终 smoke 主要围绕 `old_paper_umbrella`，后续 acceptance 有 `gray_hearth_inn`，仍非六案统计覆盖 | MEDIUM | NO | NO |
| Memory effect benchmark | 有单次 production influence 与 test A/B；缺少多 seed、多 case、counterfactual statistical benchmark | MEDIUM | NO | NO |
| canonical renderer boundedness | 刻意只重放 authoritative public facts + fixed scope/limitation，泛化能力保守 | LOW | NO | NO |
| observability | HTTP UI 暴露主要 turn telemetry；完整 proposal/attempt/receipt/index reconciliation 仍需 SQLite/raw artifacts 审计 | MEDIUM | NO | NO |
| test-production gap | 469 tests 广于 smoke；provider/model/case组合的 production 样本有限 | MEDIUM | NO | NO |
| runtime framework scope | 自研轻量单 Agent runtime，缺成熟框架的图编排、分布式执行、生态集成 | LOW | NO | NO |
| trigger coverage | domain enum 多于 production 主路径实际四类 trigger；repeated revision 的命中语义较窄 | LOW | NO | NO |

没有 HIGH 项，也没有需要在投递前重构的 blocker。上述项目应进入 future improvements，不应再次打开核心链无限重构。

## 14. Architecture Diagrams

### A. Overall System Architecture

```text
Player / Browser
      ↓
Loopback HTTP Interface
ClinicRequestHandler
      ↓
Application: ClinicService / MultiCaseEpisodeService
      ↓
CooperativeRuntime ──────────────── Agent State (JSON)
      │                                  Goal / Plan / Evaluation
      ├─ safe Observation
      ├─ semantic Memory context ← SQLite Memory ← BGE-M3 index
      ↓
GameNPCAgent → DeepSeek
      ↓ structured proposal only
GoalPlanPolicy → Plan alignment → ActionContract → AuthorityPolicy
      ↓ authorized action
CaseToolExecutor
      ↓ typed command
CaseEngine
      ↓
World State + authoritative event (JSON commit)
      │
      ├→ event Memory projection → SQLite → BGE-M3
      │
      └→ post Observation → PlanEvaluator → Agent State
                                      │
                                      └→ lifecycle trigger
                                          → Reflection evidence
                                          → DeepSeek bounded proposal
                                          → validator/B2/canonical renderer
                                          → Learning Memory → SQLite/BGE
```

### B. Single Agent Turn Sequence

```text
玩家一句自然语言
→ PlayerContribution
→ resume safe Observation
→ load/init AgentState
→ retrieve prior-session Memory
→ GameNPCAgentInput
→ DeepSeek: evaluate contribution + propose Goal/Plan/Action
→ GoalPlanPolicy
→ plan/action alignment
→ PublicActionContractValidator（必要时 repair/fallback）
→ NPCAuthorityPolicy
   ├─ respond → save AgentState → response
   ├─ needs confirmation → pending → response
   ├─ forbidden → reject → response
   └─ autonomous/confirmed
       → CaseToolExecutor → CaseEngine
       → world commit + authoritative event
       → Memory projection/index
       → post Observation
       → DeterministicPlanEvaluator
       → AgentState projection
       → possible post-commit Reflection
       → response
```

### C. Reflection Cross-Session Learning Loop

```text
Session A authoritative experience
→ deterministic trigger
→ public ReflectionEvidenceBundle
→ DeepSeek bounded proposal
→ closed-world validation
→ Python B2 derivation + canonical renderer
→ write policy
→ Learning Memory in SQLite
→ BGE-M3 embedding/index
→ persistent trigger receipt
→ process stop / restart
→ startup index + receipt reconciliation
→ Session B semantic query
→ same-player / prior-session / safe filters
→ exact Learning Memory selected
→ GameNPCAgentInput
→ LLM declares use
→ Runtime accepted-used attribution
→ bounded behavior influence
```

## 15. Resume Positioning

### 15.1 项目类型定义

**一句话**：`《异闻行录》是一个 LLM 驱动、确定性 Runtime 掌权，并具备 Goal/Plan、受限行动、跨局语义记忆和可验证 Reflection 的智能游戏 NPC Agent。`

**30 秒**：`我做的是《异闻行录》的智能调查搭档。玩家说自然语言后，DeepSeek NPC 会评价建议并提出 Goal、Plan 和 Action，但模型不能直接改世界；自研 Runtime 会校验计划、公开动作契约与 NPC 权限，再由确定性 CaseEngine 执行。系统还把已提交事件投影到 SQLite+BGE-M3，在跨 session 重启后检索，并通过 accepted-used trace 区分“检索到”和“确实影响输出”；Reflection 也采用 LLM 提结构、Python 验证并生成 canonical lesson。`

**2 分钟**：`《异闻行录》是六个志怪异案上的单 NPC Agent 系统。正式入口是本地 Web executable。玩家输入首先是 PlayerContribution，不是 ToolCall；Runtime 生成安全 Observation，并加载持久化 Goal/Plan 与跨局 Memory，交给 DeepSeek GameNPCAgent 产生结构化 proposal。Proposal 必须经过 GoalPlanPolicy、PlanStep 对齐、PublicActionContract 与 AuthorityPolicy：调查可自主，诊断只可提议，处置必须确认。通过后，CaseToolExecutor 把 action 转成 domain command，CaseEngine 才能产生权威 event 和新 CaseSessionState。世界提交后，deterministic PlanEvaluator 根据环境反馈推进计划。已提交事件写入 SQLite，并由本地 BGE-M3 建索引；player isolation、current-session exclusion 与 safe projection 防止历史经验污染当前事实。Reflection 位于 commit 之后：DeepSeek 只能提出 bounded structure，Python 用 closed-world evidence 验证，再确定性渲染带适用范围和限制的 Learning Memory。真实 production acceptance 已走过写入、重启、跨 session 检索、accepted-used 和一次行为影响，但我不会宣称已有统计性能提升。`

### 15.2 简历项目名称候选

1. **《异闻行录》——受约束、可审计的智能游戏 NPC Agent**（推荐）
2. **《异闻行录》——具备跨局语义记忆与 Reflection 的游戏 NPC Agent**
3. **《异闻行录》——LLM 驱动的 Goal/Plan/Action 游戏 Agent Runtime**

避免使用“玄医”或 `xuanyi-clinic` 作为产品名；它们只可在解释 legacy package naming 时出现。

## 16. Resume Bullets

### A. 3 条极简版

- 自研轻量 Agent Runtime，将玩家自然语言转为 NPC 的 Goal/Plan/Action proposal，并以计划对齐、动作契约与权限策略隔离 LLM 和游戏世界。
- 基于 SQLite + BGE-M3 实现跨 session 语义记忆，加入玩家隔离、当前局排除、安全投影和 accepted-used trace，生产链验证到一次行为影响。
- 构建 post-commit Reflection：LLM 提出有限结构，Python 完成证据校验、canonical lesson、幂等 receipt 与增量索引；失败不回滚游戏状态。

### B. 4 条标准推荐版

- 设计并实现《异闻行录》单 NPC Agent Runtime：将玩家自然语言建模为 `PlayerContribution`，驱动 DeepSeek NPC 形成持久化 Goal、跨 Turn Plan 与结构化 Action，而非把输入直接映射成工具调用。
- 建立 LLM 与确定性游戏世界的权力边界：通过 Goal/Plan policy、PlanStep 对齐、公开 Action contract、NPC authority 与 `CaseToolExecutor` 分层校验，最终仅由 `CaseEngine` 提交权威事件和状态变更。
- 使用 SQLite + 本地 BGE-M3 构建跨局语义 Memory，落实 player isolation、current-session exclusion、冲突过滤和安全上下文投影，并用 `MemoryUsageTrace` 区分 candidate、selected、declared-used 与 accepted-used。
- 实现可恢复的 Reflection/Learning 链：DeepSeek 仅提出 bounded evidence structure，Python 做 closed-world grounding、B2 派生与 canonical lesson；配套 structured repair、持久化 trigger receipt、增量 index reconciliation 和 failure isolation，并以正式 executable 完成真实 LLM/BGE/重启验收。

## 17. Tech Stack

| 分类 | 真实使用 |
|---|---|
| Language | Python 3.11/3.12 |
| LLM | DeepSeek `deepseek-v4-flash`，直接 HTTP adapter |
| Agent | Pydantic structured contracts；自研 `CooperativeRuntime`、Goal/Plan/Policy/Authority loop |
| Memory/RAG | semantic retrieval、cosine similarity、safe projection、usage attribution |
| Storage | SQLite（Memory/embedding/receipt）、JSON state store（world/agent/campaign） |
| Embedding | BGE-M3，本地 `sentence-transformers`/PyTorch，可选 CPU/CUDA，production 1024d |
| API/Runtime | Python standard-library `ThreadingHTTPServer`、loopback HTTP、httpx、MCP stdio（非正式玩家入口） |
| Testing | pytest，当前 469 tests passed；fake/scripted adapters、contract/integration/production-wiring tests |

未使用：LangChain、LangGraph、AutoGen。不得为了匹配 JD 写入。

## 18. Interview Questions

### 基础

1. 为什么这是 Agent，而不是聊天机器人？
2. 玩家说一句话后到底怎么执行？

### 架构

3. LLM 可以直接操作游戏世界吗？
4. 为什么不直接用 function calling？
5. LLM 与 Runtime 如何分工？
6. World State 和 Agent State 为什么分开？

### Agent

7. Goal 和 Plan 怎么维护，谁判断完成？
8. NPC 的 diagnosis/treatment 权限如何限制？

### Memory

9. Memory 如何跨 session 和重启？为什么 SQLite+BGE？
10. 怎么证明 Memory 真的影响 Agent？
11. 如何避免历史 Memory 污染当前世界事实？

### Reflection

12. Reflection 如何避免幻觉？为什么 Learning Memory 不是 LLM 自由文本？

### 工程可靠性

13. 为什么 embedding 要增量 reconciliation？Reflection 失败为何不 rollback world？
14. 你遇到过最复杂的 production bug 是什么？

### 挑战题

15. 这个项目和 LangGraph 有什么区别？是不是全是 mock 单测？

## 19. Interview Answers

### 1. 为什么这是 Agent？

**30 秒**：它不是只生成回复。一次 turn 中，NPC 接收玩家贡献和环境 Observation，维护跨 turn Goal/Plan，选择 Action，经 Runtime 在游戏环境执行，再根据 post Observation 由 evaluator 更新 Plan，并把经验写入 Memory/Reflection 影响未来 turn。这是实际的 observation–reasoning/planning–action–environment feedback loop。

**继续追问**：指出 `GameNPCAgentInput`、`GameNPCTurnProposal`、`CooperativeAgentState`、`CaseToolExecutor`、`CaseEngine`、`DeterministicPlanEvaluator` 和 `MemoryUsageTrace`；强调单 Agent，不是 multi-agent。

### 2. 玩家一句话后怎么执行？

**30 秒**：输入先成为 `PlayerContribution`，Runtime 获取安全 Observation、AgentState 和 prior-session Memory；LLM 提 Goal/Plan/Action；Runtime 校验 plan、action surface 和 authority；合法 action 才由 executor 转 command，CaseEngine 提交事件；最后根据 post Observation 推进 Plan并返回结果。

**继续追问**：玩家建议不是 ToolCall；`/cases/chat` 也不是 cooperative Agent 路径；approval 必须匹配 decision ID 和 case revision。

### 3. LLM 可以直接操作世界吗？

**30 秒**：不可以。LLM 只有 structured proposal 输出，没有 store 或 engine 引用。最终 state mutation 只能经 contract、authority、executor 到 CaseEngine。

**继续追问**：说明 action repair/fallback、plan target 对齐、unknown tool forbidden、CaseEngine immutable-input/new-state 语义。

### 4. 为什么不直接用 function calling？

**30 秒**：function calling 只解决“模型以结构化格式选择函数”，不解决这个项目最关键的三件事：动作是否与持久化 Plan 对齐、NPC 是否有 authority、执行后世界规则与状态转换是否有效。即使 provider function calling 可用，我仍需 Runtime/Policy/Engine；当前 JSON contract 让 provider adapter 与 domain authority 解耦。

**继续追问**：function call 可以作为 transport，但不能成为 authority；诊断 proposal-only、治疗 confirmation-required 是业务策略而非 schema 能单独表达。

### 5. LLM 和 Runtime 如何分工？

**30 秒**：LLM 做开放语义判断：评价玩家、提 Goal/Plan/Action、写对话、提出 Reflection 结构；Runtime 做可验证决策：状态、policy、权限、工具执行、world mutation、plan completion、Memory filter/attribution 和 Reflection grounding/write。

**继续追问**：一句话概括：“LLM proposes; Runtime validates and authorizes; CaseEngine commits.”

### 6. World State 与 Agent State 为什么分开？

**30 秒**：world state 是线索、诊断、处置等权威事实；Agent state 是 NPC 当前 Goal/Plan/evaluation。Agent projection 保存失败不应否定已发生的游戏事实，Reflection/index 更不能反向控制世界，因此分离存储、revision 和恢复语义。

**继续追问**：world JSON commit 在前；post Observation/evaluator 后写 AgentState；Reflection 最后执行。

### 7. Goal/Plan 如何维护，谁判断完成？

**30 秒**：初始和阶段 Goal 由 Runtime 确定性创建；LLM 可提更新，`GoalPlanPolicy` 校验后持久化。Plan 跨 turn 保存，工具执行后 `DeterministicPlanEvaluator` 根据 post Observation 推进、修订或完成；LLM 自称完成不生效。

**继续追问**：completion condition、PlanStep status/current index、terminal Goal 下一 turn 的 phase transition。

### 8. diagnosis/treatment 权限如何限制？

**30 秒**：调查是可逆信息动作，可自主；diagnosis 是 proposal-only；treatment 必须确认。确认绑定 decision、player/case/session 和 case revision，过期或跨 owner 的确认无效。

**继续追问**：公开 action contract 仍会校验 diagnosis/treatment candidate；CaseEngine 再做 domain rule。

### 9. Memory 如何跨 session？为什么 SQLite+BGE？

**30 秒**：权威 event 先投影为 SQLite Memory；BGE-M3 只生成可重建向量。新 session 用当前公开上下文编码查询，先按 player、source session、类型/状态过滤，再做 cosine 检索和 safe projection。SQLite负责事实、幂等与审计，BGE负责相似性召回。

**继续追问**：embedding space/content hash/dimension、1024d、current-session exclusion、startup reconciliation。

### 10. 怎么证明 Memory 真被用了？

**30 秒**：我不把 retrieved 当 used。系统记录 candidate、selected、LLM declared-used，再由 Runtime 检查 ID 确实在 input 且声明的 Goal/Plan/Action/tool/communication 变化被最终接受，才记 accepted-used。production acceptance 已跨 restart/new session 走到一次 behavior influence，但没有证明统计性能提升。

**继续追问**：`MemoryUsageTrace` 是外部可审计 attribution，不声称读取模型隐藏思维；要证明性能需多 seed/case 的 counterfactual benchmark。

### 11. 如何避免历史 Memory 污染当前事实？

**30 秒**：Memory context 明示历史经验而非当前事实；按玩家隔离，排除当前 session，过滤 inactive/deleted/conflicting 项，只暴露 safe public summary，并要求与当前 Observation 不冲突。

**继续追问**：embedding 不是真相；CaseObservation/CaseEngine 才是当前世界 authority。

### 12. Reflection 如何避免幻觉？为什么不用自由文本？

**30 秒**：LLM 只提出有限 lesson type、scope 和完整 EvidenceRef；validator 做 closed-world/type-specific grounding。最终文本由 Python 从权威 refs 确定性渲染，并加入适用范围和“不保证相同结果”的限制，所以模型 prose 不会直接落库。

**继续追问**：玩家观点需 contribution evaluation；memory helpfulness 需 accepted-used；selected-but-unused 不算 helpful；hidden raw state不进 bundle。

### 13. 为什么增量 reconciliation？Reflection 失败为何不 rollback？

**30 秒**：Memory 是事实记录，embedding 是派生索引；索引失败只应标 pending 并补缺失/冲突向量，不该重写全部 Memory。Reflection 是 world commit 后的学习副作用，供应商或索引故障不能撤销已合法发生的游戏事件，所以记录 receipt/telemetry 后独立恢复。

**继续追问**：content hash/space/dimension 冲突、pending→complete、terminal receipt replay 不重复 LLM。

### 14. 最复杂的 production bug？

**30 秒**：可讲 embedding bitwise conflict：Reflection Memory 已写，但一次全量 index/upsert 与既有向量字节不一致，receipt 卡在 `index_pending`。根因不是 semantic Memory 错，而是派生索引更新策略把已有行当作应重写。改为增量 reconciliation，只生成缺失/失配项，并让 receipt 独立从 pending 升 complete，既不重调 LLM也不重复 Memory。

**继续追问**：展示 raw receipt 的 previous status/error、reconciled IDs；强调没有篡改 source-of-truth Memory。

### 15. 与 LangGraph 的区别？是不是全是 mock？

**30 秒**：没有使用 LangGraph，我自己实现了轻量 runtime/state/policy loop，目标是把游戏 authority 和失败语义做成显式 domain code，而不是追求通用图编排。测试有 mock 以穷举边界，但不是只有 mock：当前 469 tests 全过，且正式 installed executable 真实调用 DeepSeek、BGE-M3、SQLite，经过停进程、重启、新 session、exact Memory ID 和 accepted-used attribution。

**继续追问**：LangGraph 可提供通用节点/状态/checkpoint/生态；本项目优势是边界短、domain authority 可读，缺点是通用编排、可视化和生态不如成熟框架。

## 20. Technical Challenge Stories

### Story 1：production wiring drift（约 1–2 分钟）

- **Situation**：代码中已有 `GameNPCAgent` 和大量 Agent tests，但正式玩家入口可能仍走历史 deterministic NPC。
- **Problem**：若 composition root 未注入真实 Agent，所有“production Agent”说法都是假的。
- **Diagnosis**：从 `pyproject` executable 逐层追 `main → ClinicService → CooperativeRuntime`，而不是相信 README/benchmark。
- **Solution**：明确 `--npc-mode llm` 的 fail-closed composition，注入经 model discovery 与费用预算校验的 `GameNPCAgent(DeepSeekChatAdapter)`；offline 只作显式模式。
- **Result**：production artifacts 显示 `runtime_kind=real_llm`，真实 action 进入 CaseEngine；测试覆盖 wiring 和禁止 silent fallback。
- **Learned**：Agent 项目最容易造假的不是算法，而是 composition drift；审计必须从 executable 开始。

### Story 2：strict grounding 与 reusable lesson 冲突（约 1–2 分钟）

- **Situation**：Reflection 要把一次经验用于未来异案，但长期 Memory 又不能把玩家/Agent叙述固化成世界事实。
- **Problem**：要求 LLM lesson 文本严格等于证据会失去复用性；允许自由总结又会引入幻觉、hidden leakage 和无限适用范围。
- **Diagnosis**：把“语义发现”和“最终落库 prose”分开，识别到旧设计把两者都交给模型。
- **Solution**：LLM 只提 bounded structure和 refs；validator 做 closed-world grounding；B2/Python 从权威 public refs 派生，canonical renderer 固定 category/scope/limitation；write policy再拒绝弱证据/玩家观点/未使用 Memory。
- **Result**：真实 DeepSeek proposal 可产生受限 Learning Memory，persisted text 明示不是当前事实并可跨局检索；无支持候选被明确拒绝。
- **Learned**：安全 Reflection 的关键不是更强 prompt，而是减少需要信任的模型输出面。

### Story 3：embedding conflict 与 receipt/index 最终一致性（约 1–2 分钟）

- **Situation**：Reflection lesson 已成功写 SQLite，BGE indexing 却报 `memory_embedding_conflict`。
- **Problem**：若重跑整个 Reflection 会重复费用/Memory；若把 lifecycle 标成功又会让未来检索缺向量。
- **Diagnosis**：Memory 是 source of truth，embedding 是派生物；原更新路径对已存在向量的 bitwise/identity 处理过强，receipt 状态也需要独立恢复。
- **Solution**：引入增量 index reconciliation，只处理缺失/不匹配项；terminal trigger receipt 不重调 LLM，单独记录 previous index status/error 和 reconciled IDs。
- **Result**：后续 acceptance 中 receipt 从 pending 恢复 complete，Memory/embedding 数量一致，重启 replay 无重复 generation/write。
- **Learned**：应按数据权威等级设计恢复：事实记录幂等，派生索引可重建，生命周期状态可协调。

### 对“是不是全是 mock”的自然回答

`不是。mock 测试用于把权限、错误恢复、隔离和幂等边界穷举清楚；但我另外用安装后的 yiwen-xinglu.exe 做了真实 production acceptance。它实际调用 DeepSeek GameNPCAgent 和 Reflection、加载本地 BGE-M3、把 Memory 与 receipt 写入 SQLite，然后完全停止并重启进程，在新 session 中检索同一个历史 Memory ID，把它送入 GameNPCAgentInput，并记录 selected、declared-used、accepted-used 和一次输出影响。当前全量 pytest 是 469 项通过。我要保留的边界是：这证明链路真实，不代表 Memory 已统计提升成功率。`

### 对“项目缺点”的成熟回答

`项目的核心链路是真实闭合的，但我不会说没有缺点。第一，ApplicabilityScope 目前很保守，similar_* tags 更像 provenance anchor，还不是学习出的语义模式抽象；第二，production acceptance 的案例和样本量有限，尚未做多 case、多 seed 的 Memory 效果 benchmark；第三，Runtime 是自研轻量实现，domain authority 很清楚，但通用图编排和生态完整度不如 LangGraph。它们不阻塞当前作为 Agent 应用项目，未来我会优先补可重复的效果评测和可观测性，而不是继续重构核心链。`

## 21. Truth Matrix

| Claim | Code Exists | Test Proven | Production Proven | Resume Safe |
|---|---:|---:|---:|---:|
| real LLM NPC | YES | YES | YES | YES |
| persistent Goal | YES | YES | YES | YES |
| cross-turn Plan | YES | YES | YES | YES |
| Agent feedback loop | YES | YES | YES | YES |
| constrained tool use | YES | YES | YES | YES |
| deterministic world mutation | YES | YES | YES | YES |
| semantic Memory | YES | YES | YES | YES |
| cross-session Memory | YES | YES | YES | YES |
| Reflection | YES | YES | YES | YES |
| reusable Learning Memory | YES | YES | YES | YES |
| production BGE-M3 | YES | YES | YES | YES |
| restart recovery | YES | YES | YES | YES |
| trigger/idempotent replay | YES | YES | YES（bounded smoke） | WITH QUALIFIER |
| accepted-used attribution | YES | YES | YES | YES |
| behavior influence | YES | YES | YES（single acceptance） | WITH QUALIFIER |
| statistical performance improvement | NO | NO | NO | NO |
| multi-agent | NO | NO | NO | NO |
| autonomous diagnosis | NO（被限制） | NO | NO | NO |
| autonomous treatment | NO（需确认） | NO | NO | NO |
| unrestricted/arbitrary tool use | NO | NO | NO | NO |
| self-evolving/autonomous self-improvement | NO | NO | NO | NO |
| LangGraph/LangChain/AutoGen | NO | NO | NO | NO |

## 22. Final Freeze Recommendation

### A. 是否足以作为 Agent 应用开发岗位核心简历项目？

**YES。** 理由不是组件数量，而是有真实 executable/LLM/embedding/storage/restart evidence，且 Agent loop、authority、state、Memory attribution 和 failure isolation 均能从源码讲清。

### B. 投简历前必须修改的架构级 blocker

**NONE。**

### C. POST-RECRUITMENT / FUTURE IMPROVEMENTS

- 建立跨六案、多 seed、with/without Memory 的统计 benchmark，只届时才讨论 performance improvement；
- 把 ApplicabilityScope 从 EvidenceRef anchor 演进为受控的公开语义 pattern taxonomy；
- 将 DeepSeek adapter 的 response-format instruction 按 schema 类型化，去除 Reflection 请求中的 `AgentAction` wording；
- 增加 UI/admin diagnostics，减少必须直接查询 SQLite 的审计项；
- 扩大 production acceptance 的失败注入和长期运行样本；
- 若未来出现复杂并行/长工作流，再评估 LangGraph，而不是为简历引入框架。

### D. 核心生产链是否冻结

- Goal/Plan：**建议冻结**。
- Action/Authority：**建议冻结**。
- Memory：**建议冻结**。
- Reflection：**建议冻结**。

冻结含义是：不再为求职包装改架构、改 prompt 或补功能；只接受明确 correctness/security bug 修复。当前最合适的动作是整理演示与面试叙事，保留 raw acceptance artifacts，并在简历上使用本报告的限定性表述。
