# Phase C：Reflection Production-Readiness Audit

> 历史接入前审计。其 PARTIAL 判定和待修项保留为当时证据；当前实现与后续真实评测边界见 [`../../architecture/REFLECTION_DESIGN.md`](../../architecture/REFLECTION_DESIGN.md)。

审计日期：2026-08-25  
审计范围：当前仓库源码与现存测试；未依据 README 或架构图推断运行行为。  
结论：**PARTIAL**

## 结论摘要

当前仓库不是“没有 Reflection”。它已经实现了结构化 trigger、公开 evidence projection、受约束 LLM proposal、closed-world validator、候选 lesson、保守 write policy、SQLite projection、Runtime lifecycle hook、失败隔离和测试级的未来检索验证。但是这些能力没有进入正式 `yiwen-xinglu --npc-mode llm` composition root：production 不构造 `ReflectionProposalGenerator`、`ReflectionMemoryConsolidationService` 或 `ReflectionLifecycleService`，`ClinicService.reflection_service` 保持 `None`，所以正式玩家路径不会触发 Reflection。

即使只把现有 lifecycle service 注入 production，也仍未形成目标闭环：reflection memory 写入 SQLite 后没有自动调用 production `MemoryIndexService`，当前进程内不能立刻语义检索；trigger 完成记录仅保存在进程内字典，重启后不能阻止再次调用 LLM；lesson grounding 还需要收紧为由 authoritative public evidence 本身支持，而不只是证据集合里“存在某条 authoritative ref”。

因此当前状态是：**实现主体存在、测试中可工作、production wiring 与若干安全/恢复语义尚未完成。**

## 1. 当前已有组件

| 层 | 当前源码组件 | 实际职责 | 状态 |
|---|---|---|---|
| Domain | `ReflectionTriggerType`, `ReflectionTrigger`, `stable_reflection_trigger_id()` | 定义 lifecycle trigger 和稳定 identity | 已实现 |
| Domain | `EvidenceRef`, `ReflectionEvidenceBundle` | 只承载带 episode/case ownership 的公开 evidence ref | 已实现 |
| Domain | `ReflectionFinding`, `ReusableLessonProposal`, `ReflectionProposal` | 结构化 finding/lesson/proposal；禁止额外字段 | 已实现 |
| Domain | `ReflectionMemoryCandidate`, `ReflectionMemoryWriteDecision`, `ReflectionConsolidationResult` | 候选、审计结果与写入结果 | 已实现 |
| Domain | `ReflectionLifecycleResult` | completed/fallback/failed-safe/idempotent replay 状态 | 已实现 |
| Application | `ReflectionEvidenceBuilder` | 从 Goal/Plan/evaluation/decision/public outcome/public observation delta/player contribution/memory trace/assessment 构造 evidence bundle | 已实现 |
| Application | `ReflectionProposalGenerator` | 通过任意 `LLMAdapter` 生成 `ReflectionProposal`；一次原始请求、一次 repair、再空 proposal fallback | 已实现 |
| Application | `ReflectionProposalValidator` | 校验 trigger、证据引用、lesson 类型和文本 grounding | 已实现，但需收紧 |
| Application | `ReflectionMemoryCandidateBuilder` | 只把 validated reusable lessons 转成候选；findings 不自动写入 | 已实现 |
| Application | `ReflectionMemoryWritePolicy` | ownership、confidence、provenance、scope、belief、conflict、duplicate 等保守门禁 | 已实现，但需收紧事实 grounding |
| Application | `ReflectionMemoryConsolidationService` | 通过现有 `DeterministicMemoryProjector` 和 repository 写 authoritative memory | 已实现 |
| Application | `ReflectionLifecycleService` | evidence → generation → consolidation；进程内 replay 防重；异常 failed-safe | 已实现，但 restart 不完备 |
| Runtime | `CooperativeRuntime._attach_reflection()` | 在世界与 Agent state 处理之后识别 trigger，并调用注入的 reflection service | 已实现，默认 dormant |
| Production composition | `build_clinic_service()` / `main()` | 当前不构造、不传入 Reflection service | **未接入** |

主要源码：

- `src/xuanyi_npc/domain/reflection.py:20-298`
- `src/xuanyi_npc/domain/reflection_memory.py:20-82`
- `src/xuanyi_npc/domain/reflection_lifecycle.py:12-39`
- `src/xuanyi_npc/application/reflection.py:40-397`
- `src/xuanyi_npc/application/reflection_memory.py:42-369`
- `src/xuanyi_npc/application/reflection_lifecycle.py:29-130`
- `src/xuanyi_npc/application/cooperative_runtime.py:427-568`

## 2. 哪些是真的实现，哪些是 dormant

真的实现并有测试证据：

- structured proposal parsing、repair 和 empty fallback；
- closed-bundle evidence refs；
- lesson candidate/write policy；
- SQLite `write_projection()`；
- repository-level duplicate/idempotent disposition；
- Runtime trigger detection 与 post-commit failure isolation；
- 手工 index 后由 M3 retrieval 取回 lesson；
- 测试 Agent 因 lesson 改变合法 tool priority，同时不改变 authority。

本次运行 `tests/test_m4_reflection_proposal.py`、`test_m4_reflection_memory.py`、`test_m4_reflection_lifecycle.py`、`test_m4_cooperative_runtime_reflection.py`、`test_m4_experience_memory_behavior_ab.py`、`test_m4_cooperative_web_reflection.py`，结果 **40/40 passed**。

Dormant 或仅测试组装：

- `ReflectionLifecycleService` 没有 production constructor call；全仓 `src/` 中不存在 `ReflectionLifecycleService(...)`、`ReflectionProposalGenerator(...)`、`ReflectionMemoryConsolidationService(...)` 的 composition；
- production 没有 Reflection LLM adapter 选择；
- production 没有 reflection memory 的当轮 indexing；
- Web 层已有 Reflection telemetry/rendering，但正式页面明确显示“Reflection 未启用”（`src/xuanyi_npc/clinic/server.py:513-574`）；
- A/B 行为测试显式使用 `ScriptedAdapter`、`DeterministicFakeEmbedding` 并手动调用 `MemoryIndexService.index_player()`，不是 production 证据（`tests/test_m4_experience_memory_behavior_ab.py:26-85`）。

## 3. 当前 production 是否会触发 Reflection

**不会。**

真实 composition chain：

```text
src/xuanyi_npc/clinic/server.py:main
→ build_game_npc(args)
→ build_production_memory(args, ...)
→ build_clinic_service(...)
→ ClinicService(reflection_service 默认 None)
→ ClinicService.submit_player_contribution()
→ CooperativeRuntime(reflection_service=None)
→ CooperativeRuntime._attach_reflection()
→ 立即返回 base result
```

证据：

- `build_clinic_service()` 的参数没有 `reflection_service`，构造 `ClinicService` 时也不传入：`src/xuanyi_npc/clinic/server.py:113-132`；
- `main()` 只组装 Game NPC 和 semantic memory：`src/xuanyi_npc/clinic/server.py:609-655`；
- `ClinicService.reflection_service` 默认 `None`：`src/xuanyi_npc/application/clinic.py:80-94`；
- Runtime 收到该值：`src/xuanyi_npc/application/clinic.py:261-287`；
- `_attach_reflection()` 在 `None` 时直接返回：`src/xuanyi_npc/application/cooperative_runtime.py:427-442`。

## 4. Reflection 输入来自哪里

如果 service 被注入，Runtime 只在一次 Turn 完成后传入当前 Turn 的公开/Agent 记录：

- 当前 `AgentGoalState`；
- 当前 `AgentPlan` 及全部 steps；
- 当前 `PlanEvaluation`；
- 当前 `GameNPCDecision`，其中 action dialogue 与 proposal explanation 属于 Agent history，不是 world fact；
- CaseEngine 返回给玩家的 `environment_message`，包装为 `PublicOutcomeEvidence`；
- pre/post `CaseObservation.discovered_clues` 的新增公开 description，包装为 `PublicObservationDeltaEvidence`；
- 当前 `PlayerContribution.public_text`，属于 user belief；
- `PlayerContributionEvaluation.explanation`；
- 当前 `MemoryUsageTrace`；
- episode completed 时生成的固定公开 assessment。

Runtime 构造位置：`src/xuanyi_npc/application/cooperative_runtime.py:488-536`。Evidence projection 位置：`src/xuanyi_npc/application/reflection.py:79-170`。

这里保持了概念边界：Observation delta 是公开环境投影；Agent State 是 Goal/Plan/evaluation；episodic Memory 是 CaseEngine committed-event 的长期投影；Reflection lesson 是 LLM 提议、经 validator/policy 后才可能写入的 learning/episodic memory。Reflection 没有接收或返回 `CaseSessionState` mutation。

## 5. 实际生命周期 trigger

Domain enum 声明了七类 trigger（`src/xuanyi_npc/domain/reflection.py:20-27`），但 Runtime 主路径实际只产生四类：

1. `EPISODE_COMPLETED`：公开 observation 的 session status 为 completed；
2. `GOAL_COMPLETED`：PlanEvaluator outcome 为 `COMPLETE_GOAL` 且 goal_changed；
3. `PLAN_ABANDONED`：evaluation 为 `ABANDON_PLAN`，或 plan 进入 abandoned 且 plan_changed；
4. `PLAN_REPEATEDLY_REVISED`：evaluation 为 `REVISE_PLAN`、plan revision 恰为 3 且 plan_changed。

实际检测在 `src/xuanyi_npc/application/cooperative_runtime.py:443-475`。

`GOAL_BLOCKED`、`SAFETY_OR_AUTHORITY_BLOCK`、`EVALUATION_OUTCOME_AVAILABLE` **存在于 domain enum，但不在 production Runtime trigger path 中**。另外 repeatedly revised 使用 `revision == 3`，不是 `>= 3`；之后 revision 不会再次命中，属于当前明确但较脆弱的阈值语义。

## 6. Reflection 调用哪个 LLM

`ReflectionProposalGenerator` constructor 只要求通用 `LLMAdapter`，没有固定供应商或模型：`src/xuanyi_npc/application/reflection.py:311-318`。

当前 production 没有实例化 generator，所以答案不是 DeepSeek、mentor LLM 或 GameNPCAgent LLM 中任何一个：**当前没有 production Reflection LLM 调用。** 现存 tests 使用 `ScriptedAdapter`。Phase C 最小 wiring 可复用 `build_game_npc()` 已创建并验证的 `DeepSeekChatAdapter`，使 Reflection 与 GameNPCAgent 明确共享同一 production adapter、费用预算和关闭生命周期；不得误接 mentor LLM，也不应静默创建第二套未申明模型配置。

## 7. 输出是否结构化

是。请求携带 `ReflectionProposal.model_json_schema()`；响应必须经 `ReflectionProposal.model_validate_json()` 和 `ReflectionProposalValidator.validate()`：`src/xuanyi_npc/application/reflection.py:320-364`。

Proposal 最多包含 12 findings、5 reusable lesson candidates；candidate builder 进一步最多取 3 条，consolidation 每次最多写 3 条。Schema `extra="forbid"`，没有 tool call、authority override 或 world mutation 字段。无法解析/验证时只 repair 一次，之后生成空 findings/lessons 的 non-assertive fallback。

## 8. Reflection lesson 如何验证

已有两层验证：

1. `ReflectionProposalValidator`：trigger 必须匹配；引用必须是 bundle 中完全相同的 `EvidenceRef`；不同 lesson/finding 类型要求特定 evidence type；memory helpfulness 必须有 accepted-used trace；claim 必须是某条 cited public summary 的规范化子串。
2. `ReflectionMemoryWritePolicy`：player ownership；只允许实际可检索的 `EPISODIC`/`LEARNING`；拒绝 low confidence、少于两条 provenance、无 authoritative outcome evidence、过宽 scope、过短泛化 lesson、未经 contribution evaluation 支持的玩家观点、未被接受使用的 memory helpfulness、显式 conflict 和等价 active memory。

证据：`src/xuanyi_npc/application/reflection.py:190-308`、`src/xuanyi_npc/application/reflection_memory.py:114-236`。

尚不充分之处：validator 的 grounding 是“claim 出现在任一 cited ref”，write policy 只要求 evidence set 中“存在至少一个 authoritative type”。因此 lesson 可以从 Agent dialogue、Plan 或 PlayerContribution 抽取文本，同时再附上一条不直接支持该文本的 authoritative ref，仍可能通过。Phase C 必须要求 persisted lesson 的事实性 claim 由 `TOOL_OUTCOME`、`OBSERVATION_DELTA`、`PLAN_EVALUATION` 或 `ASSESSMENT` 中与 lesson 类型匹配的 authoritative public summary 直接支撑；Agent/player 内容只能形成策略/协作语境，不能被洗成世界事实。

## 9. 如何写入 SQLite Memory

`ReflectionMemoryConsolidationService.consolidate()`：

```text
validated ReflectionProposal
→ ReflectionMemoryCandidateBuilder.build()
→ ReflectionMemoryWritePolicy.evaluate()
→ ReflectionMemoryConsolidationService._project()
→ DeterministicMemoryProjector.project_structured_experience()
→ SQLiteMemoryRepository.write_projection()
```

`_project()` 使用 `projection_version="reflection_memory_v1"`、`reason_code="reflection_generated"`、当前 player、source session/episode、case、proposal/candidate/evidence provenance。`EPISODIC` 映射为 `CASE_EXPERIENCE`，`LEARNING` 映射为 `LEARNING_PATTERN`：`src/xuanyi_npc/application/reflection_memory.py:239-369`。

Domain 的 proposal allowlist 还包含 `MemoryType.REFLECTION`（`src/xuanyi_npc/domain/reflection.py:236-260`），但 write policy 因 production retrieval 只读取 episodic/learning 而拒绝它（`src/xuanyi_npc/application/reflection_memory.py:132-136`；`src/xuanyi_npc/application/views.py:93`）。所以当前真正可写、可检索的 reflection lesson 类型只有 episodic/learning；这是刻意的安全收窄，但命名契约存在不一致，应在 Phase C 明确测试并记录，不能假称 `MemoryType.REFLECTION` 已进入闭环。

## 10. 写入后是否自动 embedding/index

**不会。**

Reflection consolidation 只依赖 repository protocol 的 `list_memories()` 和 `write_projection()`，没有 `MemoryIndexService`：`src/xuanyi_npc/application/reflection_memory.py:48-55,239-253`。

普通 committed event 路径会在 `MultiCaseEpisodeService` 写 Memory 后调用 `memory_index_service.index_player()`（`src/xuanyi_npc/application/multicase.py:700-724`）。Reflection 发生在该步骤之后，写出的新 lesson 不在先前 index build 中。production restart 会在 `build_clinic_service()` 中为全部 player 重新 `index_player()`（`src/xuanyi_npc/clinic/server.py:133-149`），因此重启后可补齐，但“写入 → 当前进程立即可检索”的 production loop 缺失。

## 11. 下一 Turn 能否真的 retrieve lesson

当前 production：不能，因为 Reflection 根本不触发。

仅手工注入 lifecycle：SQLite lesson 已写但无 embedding，下一 Turn 的 production cosine retrieval 不会把它作为有效向量候选；只有显式手工 `index_player()` 或重启后 startup indexing 才能检索。

测试证明的是“写入 + 手工 index 后可以检索”，不是自动 production 闭环：`tests/test_m4_reflection_memory.py:164-202`。A/B 测试进一步证明已投影的 lesson 可进入 memory context 并影响一个测试 Agent 的合法 tool priority，但同样显式手工建索引且使用 fake embedding：`tests/test_m4_experience_memory_behavior_ab.py:26-85`。

另一个既有边界是 current-session exclusion。Reflection `_project()` 把 source session 设为触发 episode；M3 retrieval 排除 current session（`src/xuanyi_npc/application/game_npc_memory.py:227-266,363-391`）。因此同一 episode 的下一 Turn不会读回自己的 reflection lesson；它面向未来 session/episode。这符合 Phase B 的隔离设计，但 Phase C smoke 必须通过新 session 验证，而不能要求同 session 立即命中。

## 12. duplicate reflection / restart 重复问题

已有三层有限防重：

- trigger ID 由 trigger type、episode/case/lifecycle event、goal/plan/turn 生成稳定 hash：`src/xuanyi_npc/domain/reflection.py:30-122`；
- `ReflectionLifecycleService._completed` 在同一 service 实例内按 trigger ID 返回 `IDEMPOTENT_REPLAY`，不再调 LLM：`src/xuanyi_npc/application/reflection_lifecycle.py:42,60-69`；
- repository 的 deterministic projection identity 和 active-memory normalized equality 可返回 `SKIP_DUPLICATE`。

但 production restart 幂等 **不成立**：`_completed` 只是内存 dict，没有 SQLite lifecycle receipt。重启后相同 trigger 会再次调用 LLM；LLM proposal ID、lesson 文本或 scope 可能不同，而 candidate fingerprint 包含 proposal ID 与完整 lesson（`src/xuanyi_npc/application/reflection_memory.py:79-88`），此时 repository identity 和 exact normalized-content duplicate 都不能保证拦截。当前测试的 same-trigger duplicate 使用完全相同 scripted proposal，不能覆盖 nondeterministic restart replay（`tests/test_m4_reflection_memory.py:205-213`）。

Phase C 需要持久化 trigger processing receipt/terminal outcome，或在现有 SQLite repository 中增加等价的稳定 trigger idempotency record；必须在调用 LLM 前检查。不能只依赖最终 content 去重。

## 13. hidden information leakage

直接 hidden-state 泄漏风险目前较低：Runtime 使用 `CaseObservation` 的 discovered clues、public environment message、public contribution、公开 Agent fields 和 memory usage telemetry；没有把 raw `CaseSessionState` 或 hidden case truth 传给 generator。Reflection 也没有 CaseEngine/world-state mutation API。

但仍有两类 production-readiness 风险：

- `ReflectionEvidenceBuilder` 本身相信调用者提供的 `PublicOutcomeEvidence`/`PublicObservationDeltaEvidence`，没有再次调用统一 safe projection policy；未来 wiring 必须继续只从 Runtime 已公开投影构造，不能开放任意 caller 输入。
- 当前 grounding weakness 可能把 LLM/玩家的非权威叙述固化为 lesson。它不一定泄露真正 hidden truth，却可能制造“伪 world fact”，违反长期约束。

结论：现有输入边界方向正确，但在启用 production 前必须补 authoritative-grounding regression，以及 hidden/private sentinel 不能进入 evidence bundle、proposal persistence、embedding document、future `GameNPCAgentInput` 的端到端测试。

## 14. world state 已提交而 Reflection 失败时

世界提交是权威且先发生。Runtime 在工具成功后重新加载公开 observation，运行 PlanEvaluator，保存 Agent projection，构造 base result，最后才 `_attach_reflection()`：`src/xuanyi_npc/application/cooperative_runtime.py:366-425`。

`ReflectionLifecycleService.process()` 捕获异常并返回 `FAILED_SAFE`；Runtime 外层又捕获 service exception，并把 Reflection telemetry 标为 failed-safe 后返回原 base result：`src/xuanyi_npc/application/reflection_lifecycle.py:120-130`、`src/xuanyi_npc/application/cooperative_runtime.py:520-546`。

因此 Reflection 失败不会回滚 CaseEngine commit、长期 episodic memory commit 或 Agent state。现有测试验证 world 与 Agent revision 均保留：`tests/test_m4_cooperative_runtime_reflection.py:151-162`。

缺口是可恢复性：失败状态没有持久化，也没有明确的 retry/reconcile 规则。重启可能重新调用 LLM，也可能因为玩家不再重放相同 lifecycle turn 而永久漏掉 reflection。Phase C 需要把“游戏 Turn 成功、Reflection failed-safe/pending”明确记录并可审计；不能把 Turn 判失败，也不能静默宣称已学习。

## 15. Reflection LLM 失败是否影响正常 Turn

按现有 Runtime 设计：**不影响正常游戏 Turn，也不回滚状态。** Generation 最多两次；两次无效则返回 empty fallback、不写 memory。更外层异常则 `FAILED_SAFE`。UI 已有 reflection status/error telemetry 承载位置。

production 启用后必须保持这个边界，但“不 silent fallback”意味着：玩家 Turn 可以成功，Reflection 必须明确显示/记录 `fallback`、`failed_safe`、`repository_failure` 或 `index_pending`，而不能伪装成 learning completed。当前 lifecycle 对 repository write failure 仍把整体 status 标为 `COMPLETED`，只在 decision 内记 `REPOSITORY_FAILURE`；这是需要修正的可观测性语义，否则上层只看 lifecycle status 会误报完成。

## 16. Phase C production 闭环的最小修改范围

### 必须修改

1. `src/xuanyi_npc/clinic/server.py`
   - 在现有 composition root 中复用 GameNPCAgent 的已配置 `DeepSeekChatAdapter` 和 production `SQLiteMemoryRepository`；构造 `ReflectionProposalGenerator` → `ReflectionMemoryConsolidationService` → `ReflectionLifecycleService`。
   - `build_clinic_service()` 接受并显式传入 reflection service。
   - semantic memory/LLM 配置缺失时明确启动失败；不得显示 Reflection 已启用却静默传 `None`。
   - composition 需要能拿到现有 shared repository；当前 `build_production_memory()` 只返回 retrieval/coordinator/index service，需最小幅度暴露同一个 repository，不能创建平行 SQLite 实例/架构。

2. `src/xuanyi_npc/application/reflection_memory.py`
   - 收紧 lesson authoritative grounding：persisted summary 必须由与 lesson 类型匹配的 authoritative public evidence 直接支撑。
   - consolidation 成功写入后接入现有 `MemoryIndexService`，并返回/传播 complete、index-pending、repository-failure 的可审计状态；不要修改 BGE-M3 adapter 或维度。

3. `src/xuanyi_npc/application/reflection_lifecycle.py`
   - 用持久化 trigger receipt 替代仅内存 `_completed` 作为 restart idempotency authority；在 LLM 调用前判重。
   - 明确 generation fallback、repository failure、index failure 的 lifecycle status，不把未完成闭环标为 completed。

4. `src/xuanyi_npc/application/cooperative_runtime.py`
   - 复用现有 `_attach_reflection()`，不重写 Runtime；只接收/传播新增的持久化与 index 状态。
   - 保持 Reflection 在 world/Agent commit 之后运行，并保持失败不回滚 Turn。

5. `src/xuanyi_npc/storage/sqlite_memory.py`（若现有表无法表达 trigger receipt）
   - 最小新增 reflection lifecycle receipt 的持久化读写和唯一约束；key 使用稳定 `trigger_id`。
   - 不修改 authoritative case/session 表，不让 Reflection 成为 world-state repository。

6. tests
   - production composition wiring：正式 LLM mode 确实注入 Reflection，offline/disabled 行为明确；
   - post-commit trigger → structured proposal → validation → SQLite → production BGE indexing；
   - restart 后同 trigger 不再次调用 LLM、不重复写；
   - future **new session** semantic retrieval → safe projection → `GameNPCAgentInput` → accepted influence；
   - hidden/private sentinel 端到端不进入 evidence、memory、embedding document、Agent context；
   - player/current-session isolation；
   - generation/repository/index failure 不回滚 world Turn，且 telemetry 不声称完成；
   - authoritative grounding 负例，防止 Agent/player claim 被洗成 world fact。

### 建议修改

- `src/xuanyi_npc/domain/reflection_lifecycle.py`：若需要，增加明确的 persistence/index pending/failure status，而不是依赖字符串 error code。
- `src/xuanyi_npc/domain/reflection.py`：对 `MemoryType.REFLECTION` 是继续禁止 production 写入，还是映射为 readable learning，做单一明确决定；最小方案是继续只写 `LEARNING`/`EPISODIC` 并收紧 schema allowlist，避免“schema 允许但 policy 永拒绝”。
- `src/xuanyi_npc/clinic/server.py`：把页面“Reflection 未启用”改为来自真实 composition 状态，而不是常量；这是 production 行为描述一致性的一部分。

### 暂不修改

- CaseEngine authority、`CaseSessionState`、action/tool policy；
- Phase B player/session isolation 与 hidden-info projection；
- BGE-M3 model identity、dimension、adapter；
- Reflection trigger 类型扩张。先闭合当前四个真实 trigger，不为 enum 中 dormant 类型新建设计；
- LangGraph、并行 Reflection 架构、独立 Reflection 模型供应商或新的 Memory 系统。

## 目标 production 调用链（完成最小修复后）

```text
yiwen-xinglu --npc-mode llm
→ clinic/server.py:main
→ build_game_npc() / build_production_memory()
→ ReflectionLifecycleService(shared DeepSeek adapter, shared SQLite repository, shared MemoryIndexService)
→ ClinicService.submit_player_contribution()
→ CooperativeRuntime.handle()
→ CaseEngine/Tool authoritative commit
→ public post-commit Observation + Agent state/evaluation save
→ CooperativeRuntime._attach_reflection()
→ stable ReflectionTrigger + persistent pre-LLM idempotency check
→ ReflectionEvidenceBuilder.build()
→ ReflectionProposalGenerator.generate()
→ ReflectionProposalValidator.validate()
→ ReflectionMemoryCandidateBuilder.build()
→ ReflectionMemoryWritePolicy.evaluate()
→ ReflectionMemoryConsolidationService.consolidate()
→ SQLiteMemoryRepository.write_projection()
→ MemoryIndexService.index_player()
→ future new-session GameNPCMemoryRetrievalService.retrieve()
→ safe projection
→ GameNPCAgentInput.memory_context
→ GameNPCAgent.propose_turn()
```

Reflection 始终位于 CaseEngine commit 之后，只能产生可拒绝、可审计的 Memory candidate；它不能修改 CaseSessionState、不能执行 Action/Tool、不能覆盖 Policy/Authority，也不能把 Agent/玩家叙述当成世界事实。

## 最终判定

**PARTIAL**

判定理由：核心 Reflection implementation 不是 placeholder，测试中已经能够完成 structured generation、validation、SQLite consolidation、手工 indexing、future retrieval 和行为影响；但正式 production 当前完全未注入 Reflection，且自动 indexing、restart-safe exact-once trigger、authoritative lesson grounding 与失败状态可观测性尚未达到 production-ready。完成上述最小 wiring 和边界修复，并通过 targeted tests、regression 与真实 production smoke test 后，才能判定 `READY`。
