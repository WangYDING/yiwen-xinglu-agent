# 《异闻行录》面向 Agent 应用开发岗位的工程架构审计

> 审计日期：2026-09-02  
> 审计对象：当前仓库可执行代码（`src/xuanyi_npc`）、正式入口（`pyproject.toml`）与测试基线  
> 验证结果：`535 passed in 38.87s`  
> 原则：项目文档不作为“已经实现”的证据；只有真实类、函数、调用链和正式组合入口算实现。

## 0. 先给结论

这个项目已经包含一套相当完整的 Agent 应用工程骨架，只是代码里的名字偏业务化，容易让作者没有把它们映射到通用工程概念：

- `PlayerState`、`CaseSessionState`、`CooperativeAgentState`、`CampaignState`、`CaseDialogueState` 是不同 owner、不同生命周期的 State Management。
- `JsonStateStore` 和 `SQLiteMemoryRepository` 是两类 Persistence；前者是原子快照，后者是事务型、带唯一约束和幂等 receipt 的持久化。
- `CooperativeRuntime.handle()` 是同步、单轮、至多执行一个动作的 Agent Runtime orchestration，不是后台自治循环。
- `AgentContextFilter`、`CaseObservation`、`PlayerView`、`AgentMemoryContext` 是 Context Management 与 least-privilege projection。
- `GameNPCAgent` 只提出结构化 Goal/Plan/Decision；`GoalPlanPolicy`、`PublicActionContractValidator`、`NPCAuthorityPolicy`、`CaseEngine` 才有最终约束权。这是“LLM proposal / deterministic commit”边界。
- Memory 是条件启用的正式能力：LLM 模式默认 `semantic`，离线模式默认关闭；正式 Web 入口会组合 SQLite、BGE-M3、检索、索引、Reflection。
- 项目有结构化修复、动作契约修复、安全 fallback、投影补偿、Reflection receipt 和正常单进程 Session 写串行化，但没有网络自动重试、统一日志/Tracing 后端、全局事务、跨进程数据库 CAS 或真正认证。

最重要的架构判断是：**`CaseSessionState` 是世界状态的 source of truth；`CooperativeAgentState` 是 Agent 意图投影；Memory 和 Campaign 是世界提交后的派生投影。LLM 从来不是 source of truth。**

## 1. 审计范围与正式运行路径

### 1.1 正式入口

`pyproject.toml` 注册了三个 console script：

| 入口 | 代码 | 是否包含 Agent Runtime | 说明 |
|---|---|---:|---|
| `yiwen-xinglu` / `xuanyi-clinic` | `xuanyi_npc.clinic.server:main` | 是 | 当前完整 Web 产品路径；可选真实 DeepSeek Agent、语义 Memory、Reflection |
| `xuanyi-mcp-stdio` | `xuanyi_npc.mcp_server.stdio:main` | 否 | MCP 工具服务器，只暴露确定性病例工具，不负责 Agent 规划循环 |

正式 Web 主路径为：

`ClinicRequestHandler.do_POST()` → `ClinicService.submit_player_contribution()` → `CooperativeRuntime.handle()` → `GameNPCAgent.propose_turn()` → 确定性校验/权限 → `MultiCaseEpisodeService.submit_action_with_receipt()` → `CaseToolExecutor` → `CaseEngine` → 状态/Memory/Campaign/Agent 投影持久化。

另外，Web 页面中的手动调查/诊断/处置入口也是正式可访问路径，但它绕过 LLM 规划，直接构造受校验的 `AgentAction`，属于 manual/baseline 路径。

### 1.2 正式组合但条件启用

- `GameNPCAgent + DeepSeekChatAdapter`：`--npc-mode llm`，并要求 `--confirm-paid-agent` 和正预算。
- `DeterministicCooperativeNPC`：`--npc-mode offline`，是正式离线降级模式，不只是测试 double。
- 语义 Memory：`--memory-mode semantic`；LLM 模式默认开启，offline 默认关闭。
- Reflection：只有“真实 LLM + semantic Memory”同时满足时才正式组合。

### 1.3 非产品主路径

- `src/xuanyi_npc/evaluation/*`、`tools/experiments/*`：评测/实验 harness；不是在线请求路径。例外：生产 `DeepSeekChatAdapter` 复用了 `evaluation.costing` 的计价函数，这是一个层级泄漏。
- `src/xuanyi_npc/agents/fake_llm.py`：测试 double。
- `src/xuanyi_npc/demo_case.py`：演示脚本。
- `src/xuanyi_npc/engine/replay.py`：事件重放工具，测试与校验有用，但 Web/MCP 正式请求不靠它恢复病例状态；正式恢复直接读取 JSON 快照。
- `tests/*`：验证实现，不算生产能力本身。

## 2. 二十个工程主题逐项审计

## 2.1 State Management

**概念。** State Management 是识别系统有哪些可变状态、每种状态由谁拥有、谁能修改、如何做状态转换、版本控制、持久化与恢复，而不只是“前端状态库”。

**结论：已实现，而且是多状态模型；正常单进程 Session 并发已串行化，跨进程保护只部分实现。**

| 状态 | 代码 | owner / source of truth | 如何变化与恢复 |
|---|---|---|---|
| 玩家档案 | `domain/player.py:11` `PlayerState` | `MultiCaseEpisodeService` / JSON | 创建时保存；当前生产路径基本不再更新。`handled_case_ids` 没有被正式路径维护 |
| 病例世界状态 | `domain/cases.py:268` `CaseSessionState` | `CaseEngine` 是转换规则 owner，JSON 快照是持久 source of truth | Engine 基于旧状态返回新对象，revision +1；成功后保存；启动/请求时按 session_id 加载 |
| Agent 意图状态 | `domain/cooperative_planning.py:265` `CooperativeAgentState` | `CooperativeRuntime` | 首轮懒初始化；Goal/Plan/evaluation 每轮投影，带 revision 和 optimistic expected revision；按 session 恢复 |
| 跨案状态 | `domain/campaign.py:193` `CampaignState` | `CampaignProjector/Coordinator` | 从已完成 `CaseSessionState` 确定性投影，可 reconcile；事件历史与派生字段互相校验 |
| 对话 UI 状态 | `application/case_dialogue.py:59` `CaseDialogueState` | `ClinicService` / `CaseDialogueStore` | 保存最近 16 条对话、当前对象和 revision；原子 JSON 替换 |
| 待确认动作 | `ClinicService.cooperative_pending` | Web 进程内 `ClinicService` | dict 增删；不持久化，重启丢失 |
| HTTP 幂等结果 | `ClinicHTTPServer.operation_results` | Web 进程内 server | token→redirect；不持久化、不设上限 |
| 长期记忆 | SQLite 中 authoritative memory + embeddings + receipts | `SQLiteMemoryRepository` | 事务写入、幂等投影、按 player 读取；可重建索引/补投影 |

状态对象多数使用 Pydantic 严格模型、`extra="forbid"`、冻结模型和 `model_copy`，属于 **immutable state transition + typed aggregate/snapshot** 模式。病例 action history 和 Campaign event history还带有 **event-sourced flavor**，但正式恢复通常读快照，不是每次从事件流重放，因此不能笼统说整个系统是纯 Event Sourcing。

当前边界：正常单进程产品入口通过按 state root + session_id 共享的 `RLock` 把完整读改写链放进同一临界区，两个受控线程不会同时读取旧 revision 并覆盖；并发测试已证明两个不同 operation 最终保留两条 action history。`save_case_session()` 本身仍没有 expected revision，锁也不跨进程，因此多进程或直接 Store 写仍不是数据库级原子 CAS。

**高频追问。**

1. 项目里到底有哪些 state，生命周期分别是什么？
2. 世界状态的 source of truth 在哪里？AgentState 能否改世界？
3. 谁能修改各类 state，revision 有什么作用？
4. 两个请求同时修改同一 session 会怎样？
5. LLM 输出错误是否会污染 state？

**20 秒回答。**

项目不是一个 state，而是分成玩家档案、病例世界状态、Agent Goal/Plan 状态、Campaign 跨案投影、对话状态和长期记忆。世界状态的 source of truth 是持久化的 `CaseSessionState`，只能由确定性 `CaseEngine` 产生新状态；LLM 只能提案。AgentState 按病例 session 单独持久化并带 revision；正常单进程入口再以 Session `RLock` 串行化，但 JSON 层仍没有跨进程 CAS。

**1 分钟回答。**

我现在会把项目的状态管理解释为分 owner 的聚合状态。`CaseSessionState` 保存线索、行动历史、诊断、处置、结局和 revision，是世界权威状态；`CooperativeAgentState` 保存 episode goal、current goal、plan 和上次 plan evaluation，是 Agent 的意图状态；`CampaignState` 是已完成病例的跨案投影；`PlayerState` 当前主要是静态档案；对话和待确认动作另有状态。领域模型不原地修改，`CaseEngine` 和 Runtime 都返回新模型。JSON 保存使用临时文件、fsync 和 `os.replace`，AgentState 还做 expected revision 检查；正常单进程写入口再以共享 Session `RLock` 串行化。因此线程级 lost update 已被覆盖，剩余边界是多进程/直接 Store 写无数据库 CAS，以及跨存储部分提交恢复。

**深挖回答。**

- `CaseDefinition` 是冻结的世界真相配置，不属于会话可变 state。
- `CaseEngine.execute()` 校验上下文和规则，再生成新 `CaseSessionState + domain events`；输入对象不变。
- 世界提交成功后 Runtime 会重新读取公开 observation，再更新 AgentState，明确保证世界先于 Agent 投影。
- Pydantic validator 保证 action sequence 连续、discovered clues 必须等于历史 reveal 的并集、完成态字段齐全。
- `CooperativeAgentState` 的 revision 是“每个 cooperative turn 一次”，和 `CaseSessionState` 的“每个成功 world action 一次”不是同一个版本时钟。
- 当前没有统一 Unit of Work 或数据库行锁；已有的 Session mutex 是进程内 `RLock`，不跨进程，这个边界不能包装成数据库级 CAS。

## 2.2 Session Management

**概念。** Session Management 管理一次连续交互的身份、范围、生命周期、恢复、过期和隔离。

**结论：病例 session 已实现；Web 登录 session、过期与可靠待确认 session 当前没有。**

`UUIDSessionIdFactory` 创建 `session_<uuid>`；`start_episode()` 扫描已有快照，保证同一玩家同一病例最多一个 active session，完成后不允许重开。每次请求显式携带 `player_id/case_id/session_id`，`_load_context()` 验证三者一致，并从 JSON 恢复。AgentState 与 dialogue 都以同一 case session 为作用域。

这不是典型 cookie/login session。Web 没有登录、cookie、token 认证或服务端用户会话；知道 player_id/session_id 就能请求本地数据。`PendingActionConfirmation` 只存在内存，进程重启后批准链失效；其有效性还要求 player/case/session、decision_id 和 case revision 都匹配。

**高频追问。**

1. session 是怎么创建、恢复和结束的？
2. Agent session 和用户 session 是同一个概念吗？
3. pending confirmation 重启后还能恢复吗？
4. session 是否过期、是否能清理？

**20 秒回答。**

项目实现的是病例级 session，不是登录 session。每案进度有 UUID session_id，世界状态、AgentState 和对话都按它隔离并可从 JSON 恢复；病例处置后进入 completed。当前没有登录态、过期清理，待确认动作只在内存里，重启后不能恢复。

**1 分钟回答。**

`MultiCaseEpisodeService.start_episode()` 创建 `CaseSessionState`，并检查玩家、病例和已有 active/completed 进度。后续请求都显式传三个 ID，应用层重新加载 player、case、session 并校验 owner。`CooperativeAgentState` 和 `CaseDialogueState` 也绑定同一个 session，所以 Agent 的计划和人物对话能恢复。完成状态由 `CaseEngine` 在 treatment 后设置。局限是 Web 没有真正用户认证 session，pending confirmation 是进程内 dict，也没有 TTL 或清理任务。

**深挖回答。**

- “一个玩家一案一个 active session”靠全目录扫描检查，不是数据库唯一约束；并发 start 可能破坏该不变量。
- 已完成 session 可读不可继续写；`SessionClosedError` 是领域保护。
- Pending approval 使用 case revision 防止基于旧世界状态批准，但它并不持久化。
- 当前没有 session revoke、logout、租约、心跳或后台 garbage collection。

## 2.3 Context Management

**概念。** Context Management 是为每轮模型调用选择、裁剪、分类和标注输入，控制哪些信息进入 prompt，哪些是权威事实，哪些只是历史或用户观点。

**结论：正式实现较强；对话历史上下文当前未真正接入 cooperative Runtime。**

核心入口是 `GameNPCAgentInput` 和 `GameNPCAgent._planning_request()`。Runtime 每轮组装：

- `PlayerView`：只含公开玩家字段和已解锁技能；
- `CaseObservation`：只含公开病例资料、已发现线索、当前可用动作和 session revision；
- current Goal/Plan/evaluation；
- 当前玩家 contribution，明确标记为 untrusted belief；
- authority view 和 pending confirmation；
- 经过筛选的 `AgentMemoryContext`，明确标记为 historical non-authoritative；
- 精确 public action space。

`AgentContextFilter` 是 anti-corruption/least-privilege projection 层，隐藏 `root_cause`、causal chain、hidden patient information、treatment outcome 和未发现 clue。Memory 另外限制为同 player、排除当前 session、允许类型白名单。

`GameNPCAgentConfig.recent_message_limit=6` 和 `GameNPCAgentInput.recent_messages` 虽然存在，但 `CooperativeRuntime` 创建 input 时没有传 recent messages；所以正式 cooperative Agent 当前没有多轮自然语言 chat history，只依赖持久 Goal/Plan、当前 contribution、环境反馈和 Memory。案中人物 `CaseDialogueState` 也没有进入 Game NPC prompt。

**高频追问。**

1. 每轮 prompt 里放了哪些 context？
2. 如何避免把隐藏答案泄露给模型？
3. 如何区分当前事实、用户输入和长期记忆？
4. context window 如何做预算？
5. 是否保留完整对话历史？

**20 秒回答。**

Runtime 不把领域对象原样塞给模型，而是通过 `AgentContextFilter` 生成最小公开视图，再加入 Goal/Plan、权限、当前用户贡献和最多 4 条、900 字符的长期记忆。Prompt 明确区分 authoritative world、constraints、player belief 和 non-authoritative memory。当前 cooperative 对话历史没有接入，只保留结构化状态。

**1 分钟回答。**

Context 的 owner 是 Runtime 和 projection 层，不是 LLM。`CaseObservation` 从世界状态派生，只暴露已发现线索和当前合法 action；`PlayerView` 只暴露可用技能。规划 prompt 把输入分为权威世界、权威约束、Agent intent、历史非权威 Memory 和玩家观点，冲突时要求以世界状态为准。动作空间还预先投影成 exact tool name/arguments，减少模型自造 ID。语义 Memory 先做 player/session/type 过滤，再按相似度和字符预算选最多 4 条。当前缺口是 `recent_messages` 没有在 Runtime 里填充，所以不是完整 chat-history 管理。

**深挖回答。**

- Prompt 标注不是唯一防线；模型输出之后仍由 schema、GoalPlanPolicy、ActionContract、AuthorityPolicy 和 CaseEngine 重验。
- `CaseObservation` 的 `session_revision` 让 plan 绑定到观察版本，并用于确认动作防陈旧。
- Memory query context 有 `top_k=8/min_similarity=.35`，最终 Agent projection 默认 `max_selected=4/char_budget=900`。
- 当前没有通用 token estimator 或按模型 context length 动态裁剪；预算主要是固定条数、固定字符和 max output tokens。

## 2.4 Memory Management

**概念。** Memory Management 是从经历生成长期记忆、持久化、索引、检索、筛选、注入、归因、纠错和失效；它不同于当前 session state。

**结论：已实现正式的跨 session semantic Memory，但为条件启用；不是所有模式都开启。**

正式 LLM+semantic 路径包含：

1. `V1MemoryCoordinator.commit_engine_result()` 在世界 JSON 成功提交后，把 domain event 确定性投影为 verified source + authoritative memory；
2. `SQLiteMemoryRepository` 在事务中写 source receipt 和 memory event；
3. `MemoryIndexService` 用本地 BGE-M3 建 embedding；
4. `BasicCosineMemoryRetriever` 检索当前 player 的 active memory；
5. `GameNPCMemoryProjectionPolicy` 排除当前 session、冲突或越权记录，并做 4 条/900 字预算；
6. Runtime 把 `AgentMemoryContext` 注入 prompt，并用 `MemoryUsageTrace` 区分 candidate/selected/declared/accepted；
7. Reflection 在生命周期边界生成候选 lesson，经保守 consolidation 写回并建索引。

Memory source 以已提交公开事件为基础，不允许 LLM 直接写 authoritative memory。Reflection 候选由 LLM 产生，但 consolidation 会验证 evidence/provenance 和写入策略。Memory 支持 correction/invalidation/hard delete/tombstone，不过这些生命周期 API 当前没有 Web 产品入口，主要是 repository capability 与测试覆盖，不能说用户已经能在线管理记忆。

**高频追问。**

1. Memory 和 AgentState 有什么区别？
2. 记忆何时写、写什么、谁决定？
3. 如何防止跨用户或当前 session 泄漏？
4. 检索结果如何进入 prompt，如何做预算？
5. 错误记忆如何纠正或删除？

**20 秒回答。**

长期 Memory 只在 semantic 模式启用。世界事件先提交，再被确定性投影进 SQLite，BGE-M3 建索引；每轮按 player 检索、排除当前 session，最多选 4 条、900 字符进入 prompt。Memory 是非权威历史参考，不能覆盖当前世界；Reflection 可以生成经验候选，但写入仍走证据和策略校验。

**1 分钟回答。**

我把 Memory 分成 authoritative record、derived embedding 和 per-turn context。病例 action 成功后，`V1MemoryCoordinator` 先保存 `CaseSessionState`，再从 committed event 生成稳定 source ID 和 memory record；SQLite 用 receipt 和唯一约束保证重复投影幂等。检索时只读取同 player 的 active memory，排除当前 session，并经过相似度、类型、冲突和字符预算过滤。模型必须声明用了哪些 selected memory，Runtime 只在 Goal/Plan/Decision 实际对应变化时接受归因。Reflection 只在完成目标、完成案件、放弃或反复修订计划等边界触发。offline 默认没有这套 Memory。

**深挖回答。**

- authoritative memory 与 embedding 分表；embedding 是可重建派生索引，content hash/space/dimension 必须匹配。
- JSON world commit 和 SQLite memory projection不是同一事务；失败返回 pending，可在启动时 `reconcile_committed_session()` 补齐。
- Memory retrieval 失败被降级为 `FAILED_SAFE`，Agent 仍可仅用当前世界继续。
- correction/invalidation/hard delete 有事务和 tombstone 语义，但没有正式 UI/API 生命周期管理入口。
- `MemoryUsageTrace` 是外部可审计归因，不声称能证明模型内部因果。

## 2.5 Persistence

**概念。** Persistence 是进程退出后仍保存状态，并定义存储格式、原子性、版本、恢复和损坏处理。

**结论：已实现双存储；JSON 快照与 SQLite 的可靠性等级不同。**

`JsonStateStore` 保存 players、case_sessions、cooperative_agents、campaigns。写入使用同目录临时文件、flush、fsync、`os.replace`，因此单文件替换是原子的；读取时重新做 Pydantic 校验并区分 not found、corruption、storage failure。`CaseDialogueStore` 使用类似原子替换，但错误类型与 revision CAS 更弱。

`SQLiteMemoryRepository` 保存 memory receipts/events/lifecycle/tombstones/embeddings/reflection receipts，显式初始化 schema，使用 `PRAGMA user_version` 做 v1→v2→v3 migration，每次写 `BEGIN IMMEDIATE / commit / rollback`。

恢复方面：病例、Agent、Campaign、dialogue 直接从快照恢复；Memory 索引和 projection 可 reconcile。当前没有备份、远程数据库、多实例共享存储、JSON schema migration 框架或 crash-safe 跨文件事务。

**高频追问。**

1. 为什么同时用 JSON 和 SQLite？
2. 写一半崩溃会怎样？
3. schema 如何升级？
4. 状态损坏如何处理？

**20 秒回答。**

业务主状态用原子 JSON 快照，长期 Memory 用 SQLite 事务。JSON 写入是 temp+fsync+replace，读取重新做严格模型校验；SQLite 有 schema version、migration、唯一约束和 rollback。单文件和单 SQLite 事务可靠，但跨 JSON、Memory、Campaign、AgentState 不是一个全局事务。

**1 分钟回答。**

`JsonStateStore` 适合当前本地单机规模，按 namespace 和 ID 存快照，路径 ID 先经过严格校验，防止路径注入。`CaseSessionState`、AgentState 和 Campaign 都能直接恢复。Memory 因为有检索、唯一约束和生命周期，使用 SQLite，显式初始化并校验 schema version。世界状态永远先提交，Memory/Campaign/Agent 是后续投影；后续失败会暴露 pending 或安全错误，并有部分 reconcile。当前没有把所有聚合放进同一数据库，所以不能承诺跨聚合 ACID。

**深挖回答。**

- JSON `os.replace` 防止出现半个 JSON，但不能防两个并发 writer 的最后写覆盖。
- `PlayerState` 有对旧字段的边界兼容删除；其他 JSON 模型主要靠严格校验，没有通用 migration registry。
- SQLite 每次连接开 foreign keys，写锁 timeout 5 秒。
- Memory database 启动会核对表集合和 metadata version，异常 fail closed。

## 2.6 Agent Runtime / Execution Loop

**概念。** Agent Runtime 是把观察、模型推理、计划、工具选择、权限、执行、反馈和状态更新串起来的控制器；Execution Loop 是这一过程如何反复推进。

**结论：正式实现同步 one-turn runtime；当前没有后台自治循环或并行 tool loop。**

`CooperativeRuntime.handle()` 每个 HTTP contribution 执行一次完整循环：恢复世界→恢复/初始化 AgentState→修正陈旧计划→检索 Memory→调用 Agent→验证 Goal/Plan→验证动作契约→权限判定→最多执行一个工具→重载世界 observation→评估计划→保存 AgentState→按边界触发 Reflection→返回结果。

它是 **request-driven bounded agent loop**：每次用户请求最多一个 `AgentAction`，没有 `while` 自主运行，没有后台 worker，没有 tool chaining，也没有多个工具并行执行。下一轮必须由新的用户请求触发。

**高频追问。**

1. 一轮 Runtime 的完整步骤是什么？
2. Agent 会不会连续调用多个工具？
3. tool 执行后如何反馈给规划？
4. 世界状态和 AgentState 谁先提交？

**20 秒回答。**

核心 Runtime 是 `CooperativeRuntime.handle()`。它每个请求恢复世界和 AgentState，组装 context，让 LLM 提一个 Goal/Plan/Decision，经过策略、动作契约和权限校验后最多执行一个工具，再重读世界、评估计划并保存 AgentState。它是同步单步循环，不是后台持续自治。

**1 分钟回答。**

Runtime 先通过 `resume_episode` 获得公开 observation，同时读取 player、session 和 session-owned AgentState。它在模型前处理已完成目标和陈旧计划，并检索 Memory。真实 Agent 输出一个结构化 turn proposal；确定性 `GoalPlanPolicy` 和 public action contract 再验证。诊断/处置还要经过 authority policy，必要时产生 pending confirmation。工具成功后，世界状态先由应用/领域层保存；Runtime 再重新加载 post observation，用 `DeterministicPlanEvaluator` 更新 Goal/Plan，最后持久化 AgentState。每轮最多一个 action，下一轮由玩家再次触发。

**深挖回答。**

- 如果 current goal 的确定性 completion condition 在调用模型前已经满足，本轮直接完成 goal，不再启动新目标或工具。
- action 与 active PlanStep 不一致时，保存 recovery evaluation 并拒绝执行。
- world commit 成功但 AgentState 保存失败时，世界仍算成功，结果标记 `agent_state_projection_pending`；当前没有专门的 AgentState 重建任务。
- Reflection 是 turn 尾部的同步附加阶段；失败不会回滚世界动作。

## 2.7 Tool Management / Tool Lifecycle

**概念。** Tool Management 包括工具注册、schema、可见性、参数校验、权限、执行、结果处理、重试/取消和生命周期。

**结论：静态工具生命周期已实现；没有动态 registry、插件发现、tool 并行或取消。**

工具由 `ToolName` 枚举冻结。Agent path 中，公开 action space 从 `CaseObservation` 投影；LLM 产生 `ToolCallRequest` 后依次经过 `PublicActionContractValidator`、`NPCAuthorityPolicy`、`CaseToolExecutor`、`CaseEngine`。工具本身不拥有状态，执行器把工具调用翻译成不可变 domain command。

MCP path 在启动时从 `FROZEN_MCP_TOOL_NAMES` 构建 9 个 structured tools，Pydantic input model 是 schema owner；dispatch 调 `MCPApplicationService`。MCP path 和 Agent Runtime 共用 `CaseToolExecutor/CaseEngine`，但 MCP 不调用 LLM。

**高频追问。**

1. 工具是怎么注册和发现的？
2. LLM 能否自造工具或参数？
3. 谁决定工具是否有权限执行？
4. 工具失败后 state 是否变化？
5. 是否支持动态工具或并行调用？

**20 秒回答。**

工具是静态枚举和严格 schema，不是动态插件。模型只能从当前公开 action space 选择；调用先过参数契约和权限，再由 executor 翻译成 domain command，最终 `CaseEngine` 执行。失败不保存世界状态。当前每轮只允许一个工具，没有动态注册、并行调用或取消机制。

**1 分钟回答。**

Tool lifecycle 分为 propose、validate、authorize、execute、commit、observe。`ToolName` 冻结工具集合，Runtime 把 exact tool/arguments 提供给模型。输出之后 `PublicActionContractValidator` 检查当前 observation 中是否真的存在该 action，`NPCAuthorityPolicy` 把调查设为 autonomous、诊断设为 proposal-only、处置设为 confirmation-required。`CaseToolExecutor` 只负责适配，真正业务规则在 `CaseEngine`。MCP 暴露的是同一批领域工具，但没有 Agent 规划层。当前没有动态 tool registry、remote tool health、取消或并行调度。

**深挖回答。**

- Tool name 与 investigation action type 必须一致，参数 key 也要求精确集合。
- 诊断 evidence 只能引用 discovered clue；处置只能选 observation 当前可见项。
- 读工具在 MCP facade 中也走安全 view 返回；Agent Runtime主要使用应用层直接恢复 view。
- DeepSeek adapter/client 有显式 close 生命周期；领域工具都是无资源、短生命周期对象。

## 2.8 Agent Lifecycle

**概念。** Agent Lifecycle 是 Agent 实例的创建、初始化、每轮激活、状态恢复、暂停/确认、完成和资源释放。

**结论：基础生命周期已实现；没有 Agent 删除、TTL、暂停队列或后台恢复。**

Web 启动时构造一个共享 `GameNPCAgent` 或 `DeterministicCooperativeNPC`。每个请求临时构造 `CooperativeRuntime`；某 session 第一次协作时懒创建 `CooperativeAgentState`。后续按 session 恢复 Goal/Plan。病例完成时 episode goal 被置为 completed；adapter 在 server 关闭时 close。诊断/处置可能进入 pending confirmation，但 pending 只在进程内。

没有显式 `Agent.start/stop/delete`，没有 idle timeout、状态归档、后台任务、崩溃后 pending work queue。Reflection 有独立 receipt 生命周期和一次受限恢复。

**高频追问。**

1. Agent 是每个用户一个实例还是共享实例？
2. AgentState 何时初始化、何时完成？
3. 服务重启后能恢复到哪里？
4. 资源何时释放？

**20 秒回答。**

进程里共享一个 Agent adapter，每个请求创建 Runtime，但 AgentState 按 case session 持久化隔离。首轮懒初始化 Goal，后续恢复 Plan；病例完成后 episode goal 完成，服务退出时关闭 HTTP adapter。当前没有 Agent TTL、删除和持久 pending queue。

**1 分钟回答。**

Agent 的“行为实现”和“会话状态”是分开的：`GameNPCAgent` 是进程级共享服务，`CooperativeAgentState` 才是每个 session 的状态。Runtime 每轮恢复它，必要时初始化 episode goal 和当前阶段 goal。诊断/处置权限不足时生成 pending action，等待下一次用户 approval。世界完成后 Runtime 更新 episode goal。JSON 能恢复 Goal/Plan，但内存 pending confirmation 和 HTTP operation cache 会丢失。DeepSeek client 在 server shutdown 时显式关闭。

**深挖回答。**

- Agent 共享实例内部只有 adapter、策略和 thread-local 的最近 planning execution；业务 Goal/Plan 不存在 Agent 对象字段里。
- Reflection service 是共享实例，带进程 owner token 和持久 receipt，可识别 replay/in-progress/一次恢复。
- 当前没有每用户模型连接，也没有独立资源配额；预算 guard 是整个 adapter 共享的进程级预算。

## 2.9 Error Handling / Retry / Fallback

**概念。** Error Handling 区分可预期业务拒绝、存储/网络故障和未知异常；Retry 处理瞬时失败；Fallback 保证降级时不越权、不污染状态。

**结论：分层错误和安全 fallback 已实现；网络 retry 当前明确没有，未知异常的诊断性偏弱。**

主要机制：

- `CaseEngine` 抛稳定 `RuleViolation.code`，应用层映射为安全中文错误；拒绝不保存 state。
- `BoundedStructuredOutput`：初次模型调用；若 JSON/schema/确定性校验失败，最多一次 format repair；仍失败则无工具 fallback。
- `CooperativeRuntime._resolve_contract()`：若最终 action 不符合当前 public contract，再调用一次 action-contract repair；仍失败转 `RESPOND`。
- `DeepSeekChatAdapter` 对 auth/rate limit/timeout/transport/provider/truncated/usage/budget 分类；类注释明确 no implicit retry。
- Memory、Reflection 检索失败多数 fail-safe，不阻止当前世界推理；投影失败标 pending。
- Web/MCP 顶层大量 `except Exception` 返回安全错误，避免泄露内部信息，但正式运行没有日志 sink，根因可能丢失。

**高频追问。**

1. LLM 返回非法 JSON 怎么办？
2. 429/timeout 是否重试，为什么？
3. fallback 会不会执行错误工具？
4. tool 已成功但后续保存失败怎么办？
5. 如何区分业务错误和系统错误？

**20 秒回答。**

模型结构输出最多修复一次，动作契约还能做一次定向修复，最终 fallback 一定是 `RESPOND`，不会调用工具。领域拒绝有稳定 error code 且不改状态。DeepSeek 网络层当前不自动重试，Memory/Reflection 多数 fail-safe。缺口是顶层异常虽然安全，但没有正式日志后端，排障信息不够。

**1 分钟回答。**

项目把错误分为领域规则、工具契约、模型输出、provider、存储和派生投影。结构输出先 schema+policy 校验，失败最多再请求一次修复；如果动作仍不在最新公开 action space，就进行 action-contract repair，最后降级成不执行工具的解释响应。领域错误如重复调查、证据未发现、session closed 都映射为稳定 code。DeepSeek 对 401、429、timeout、5xx、截断和预算分别分类，但没有隐式网络 retry，避免未知计费重复。世界提交后的 Memory/Campaign/Agent 投影失败不会伪装成全事务回滚，而是 pending 或 error code。

**深挖回答。**

- Budget 或 usage 不可确认会 `abort_episode=True`，防止在费用状态不明时继续调用。
- 格式 repair 与 action-contract repair 是不同阶段；极端情况下不是简单“总共最多两次所有 LLM 调用”的统一上限，需要按路径解释。
- `except Exception` 保证不泄露 prompt/secret，但因没有 logger，当前也没有 request stack trace 留存。
- 当前没有 exponential backoff、jitter、circuit breaker 或 dead-letter queue。

## 2.10 Concurrency

**概念。** Concurrency 关注多个请求/线程同时读取和修改同一资源时的锁、CAS、事务、竞争和共享资源安全。

**结论：HTTP 层确实并发，正常单进程业务写已完成按 Session 的线程串行化；多进程与跨存储恢复才是当前主要风险。**

`ClinicHTTPServer` 继承 `ThreadingHTTPServer`，`daemon_threads=True`。SQLite 写使用 `BEGIN IMMEDIATE`，因此 Memory repository 的单事务写有数据库级序列化；Reflection claim 也使用事务/CAS。`GameNPCAgent._planning_execution` 使用 `threading.local()`，避免每线程诊断串线。

并发边界需要分开看：

- 正常 Cooperative Runtime、MultiCase、Clinic 普通操作和 MCP 写路径共享 `JsonStateStore.session_write_lock()`，按 state root + session_id 串行；
- `ClinicService.cooperative_pending` 有单独的 `Lock`；
- 相同 operation 另有 live claim/receipt 机制，防止同进程重复执行；
- Session 锁不跨进程，直接 Store 写可以绕过；
- Campaign 的 player 级 load-project-save、start session 的 scan-then-create 等不是同一个 Session world action 临界区，仍需独立约束。

因此，正常单进程受控入口的同一 Session 并发 action 不会再同时基于旧 revision 写回；测试证明两个不同 operation 被串行并最终形成 revision 2。项目仍不能声称支持多进程安全业务写，因为底层 JSON 没有跨进程锁或数据库 CAS。

**高频追问。**

1. Web 是单线程还是多线程？
2. 两个请求同时修改一个 session 会怎样？
3. optimistic locking 是否真的原子？
4. SQLite 和 JSON 的并发语义有什么不同？

**20 秒回答。**

Web 用 `ThreadingHTTPServer`，正常写入口以共享 per-session `RLock` 串行化，因此同进程线程级 lost update 已有确定性保护。Agent revision 检查仍不是跨进程原子事务，CaseSession 也没有数据库 CAS；SQLite Memory 使用 `BEGIN IMMEDIATE`。当前待补的是多进程/直接 Store 写边界，而不是普通单进程线程串行化。

**1 分钟回答。**

系统有真实线程并发，因为每个 HTTP 请求可能在不同线程。核心世界状态仍是 JSON，但受控入口已把 load、execute、replace 包在同一个 keyed Session `RLock` 中；Memory SQLite 写通过 immediate transaction 串行化，Reflection receipt 有生命周期约束。问题变成了这把锁只在一个 Python 进程有效，且底层 Store 不强制调用者持锁。因此我会把当前定位为“单进程核心写路径已串行化，但尚不是多进程生产级并发状态机”。

**深挖回答。**

- 已完成的最小修复是 keyed Session lock 和同进程 operation receipt/claim；对应并发与故障注入测试已存在。
- 下一步应把主聚合迁到支持事务/CAS 的数据库，或采用跨进程单写者，并给所有写入口统一 durable operation receipt/outbox。
- 预算 guard 若共享 adapter，应锁住 reserve/settle，或改成数据库/原子计量。
- 不能只给 `dict` 加锁而忽略跨 world/Agent/Campaign 的顺序一致性。

## 2.11 Multi-user / Session Isolation

**概念。** Multi-user / Session Isolation 要保证 A 用户无法读取、影响或复用 B 用户的状态、Memory、确认动作和资源配额。

**结论：数据模型和 Memory 查询有逻辑隔离；身份认证和强安全隔离当前没有。**

所有主要状态都显式带 `player_id` 和 `session_id`。`CaseEngine`、`AgentContextFilter`、`MultiCaseEpisodeService._load_context()`、AgentState load/save、pending confirmation 都验证 player/case/session owner。SQLite Memory 的查询按 player 过滤；source、memory、embedding、reflection receipt 的 owner 冲突会抛 `MemoryPlayerIsolationError`。检索还排除当前 session。

但 Web 只绑定 `127.0.0.1`，采用的是本地可信使用假设。没有账户认证、密码、cookie、ACL 或 tenant key；首页能列出所有 player，URL/form 里直接携带 player_id。MCP 也由调用方提供 player/session IDs。因此这是 **logical data partitioning**，不是 production multi-tenant security isolation。

**高频追问。**

1. 如何保证一个玩家看不到另一个玩家的 Memory？
2. player_id 是否等同身份凭证？
3. 当前能否部署成公网多租户服务？
4. 共享 Agent 实例会不会串状态？

**20 秒回答。**

状态和 Memory 都按 player/session 建模并做 owner 校验，Agent 业务状态不放在共享 Agent 对象里，所以正常路径不会串档。但当前没有认证，player_id 只是定位符，不是凭证；服务只绑定 loopback，因此不能直接宣称支持公网多租户。

**1 分钟回答。**

隔离做了两层：领域/应用层检查 session.player_id、case_id 与请求一致；Memory repository 的所有 read/write 都要求 player scope，跨 player 的 source、memory 或 embedding collision 会失败。AgentState 也以 session 文件隔离，模型共享实例只持 adapter 和策略。与此同时，Web 没有登录系统，首页会列档案，知道 ID 就可以请求，所以安全边界依赖本机 loopback。要做真正多用户，需要认证主体、授权检查、tenant-scoped repository 和持久幂等/审计。

**深挖回答。**

- 共享 DeepSeek budget 是进程级，不是 per-user quota。
- `cooperative_pending` 是进程内 dict，使用单独 `Lock` 并检查 player/case/session owner；仍缺持久化和跨进程共享。
- JSON namespace 是同一个 state root，不是文件系统 tenant 隔离。
- 当前没有数据加密 at rest 或用户级删除工作流。

## 2.12 Idempotency

**概念。** Idempotency 保证同一操作因重试、重复提交或恢复而执行多次时，结果等价于执行一次。

**结论：派生投影幂等较强；recorded cooperative operation 有持久 SQLite lifecycle，普通页面/MultiCase receipt 仍主要是进程内，MCP 没有 operation ID。**

已实现：

- Web `operation_id` 缓存在 `operation_results`，重复 POST 重定向到第一次 location；但只在内存、无锁、无 TTL，进程重启失效。
- Memory projection 以 `(player_id, source_event_id, projection_version, ordinal)` receipt 和唯一约束识别 identical replay，冲突则拒绝。
- Campaign projector 根据 completed session receipt 返回 `changed=False`，可 reconcile。
- Reflection 以稳定 trigger ID + SQLite receipt claim/replay 保证至多一次语义，并允许一次中断恢复。
- Memory lifecycle operation 有 operation_id receipt，重复操作返回已有结果。

未实现/不足：`AgentAction.action_id` 没有作为世界事件幂等键持久化；重启后重复 diagnosis 可能再次追加 action。调查重复会被业务规则拒绝，但那是 duplicate detection，不是返回同一成功结果。HTTP cache 的 check-then-act 也有竞争。

**高频追问。**

1. 浏览器重复提交会不会执行两次？
2. 服务重启后 operation_id 还有效吗？
3. Memory 重放为什么不会重复写？
4. 幂等和乐观锁有什么区别？

**20 秒回答。**

Memory、Campaign 和 Reflection 有持久 receipt/稳定 ID，重复投影能幂等 replay。recording 开启的 cooperative POST 把 operation lifecycle 持久化到 SQLite，可重放 completed 并对 uncertain operation 禁止盲重试；普通页面/MultiCase action receipt 仍是进程内，MCP 无 operation ID，端到端统一 durable 幂等尚未完成。

**1 分钟回答。**

项目的幂等能力是不均匀的。派生层最好：Memory source receipt 加唯一约束，完全相同的投影返回 idempotent，payload 不同则 conflict；Campaign 根据已完成 session 去重；Reflection trigger 有持久 claim/result receipt。Web 请求层只是把 operation_id 存在 server dict，再次提交时重定向，这个缓存不持久也没锁。领域 action history 没有 operation_id，所以服务重启后同一个 diagnosis 请求可能再次写入。要做生产级，需要把 request id 与结果放进和世界状态同一个事务。

**深挖回答。**

- Investigation 的“already completed”是安全拒绝，不等同于幂等成功 replay。
- Treatment 因第一次后 session closed，重复会拒绝，也不是返回原响应。
- Reflection 的 trigger ID 从确定性 lifecycle source hash 生成，receipt owner token 用于区分同进程 in-progress 与重启 recovery。
- 幂等键必须绑定 player/session/action payload，防止同 key 不同 payload 被误复用。

## 2.13 Transaction / Consistency

**概念。** Transaction 保证一组写入原子提交；Consistency 定义多个聚合和派生投影在部分失败时如何保持、检测或恢复一致。

**结论：单 SQLite 事务强；跨聚合采用 world-first + eventual projection/reconciliation，不是全局 ACID。**

关键提交顺序：

1. `CaseEngine` 先纯计算新 world state；
2. `V1MemoryCoordinator` 先保存 `CaseSessionState`，再逐 event 投影 Memory；失败标 `memory_projection_pending`；
3. 若案件完成，再保存 Campaign projection；失败保留 world success 并标 pending；
4. Runtime 重读 world observation，再保存 AgentState；失败不回滚 world，标 `agent_state_projection_pending`；
5. Reflection 最后执行，失败同样不回滚 world。

这属于 **authoritative write + derived projections / saga-like compensation**，但不是完整 Saga，因为没有统一 durable workflow state 和对所有步骤的自动补偿。Memory 与 Campaign 有 reconcile；AgentState projection 当前没有正式 reconciliation job。

`CaseSessionState` 自身通过 revision、连续 action sequence、history-derived clues 保持内部一致。Campaign 强制 revision=event count 且所有派生字段必须等于 event history。SQLite Memory 的 receipt+record 在同一事务中写，correction/invalidation 也完整 rollback。

**高频追问。**

1. 一次 action 涉及哪些写，是否一个事务？
2. Memory 写失败会不会让世界动作失败？
3. 为什么 world 要先于 AgentState 提交？
4. 如何检测和修复部分成功？

**20 秒回答。**

单个 SQLite Memory 操作是 ACID，但完整 turn 不是全局事务。项目采用 world-first：先提交 `CaseSessionState`，再投影 Memory、Campaign 和 AgentState；派生失败不回滚已经发生的世界动作，而是标 pending 并对 Memory/Campaign 做 reconcile。AgentState 目前缺专门补偿任务。

**1 分钟回答。**

世界状态被设计成权威提交，派生系统不能反向否定它。`CaseEngine` 纯计算，JSON 保存成功后事件才允许投影 Memory。Memory 的 source receipt 和 record 在 SQLite 同一事务里；如果投影失败，world 已经成功，返回 pending，启动时可从 committed action history 重建。案件完成后的 Campaign 同理可 reconcile。Runtime 之后重新读取 world，再做 plan evaluation 和 AgentState 保存，确保 Agent 投影建立在已提交 observation 上。局限是 JSON world 本身没有数据库事务/CAS，跨系统也不是 atomic commit。

**深挖回答。**

- `V1MemoryCoordinator._validate_transition()` 校验 revision 增量、history 前缀不可修改、event sequence 与新增 record 一致。
- Campaign 投影会重验整个公开 action receipt，防止源快照后来被篡改。
- `MCPApplicationService` 没有接 Memory/Campaign coordinator，只保存 case session；MCP 与完整 Web 的副作用范围不同。
- 当前 consistency model 应描述为“单聚合校验强、正常单进程 Session 写串行、跨进程 JSON 并发较弱、派生投影最终一致”。

## 2.14 Logging / Tracing / Observability

**概念。** Observability 是通过 logs、metrics、traces 和业务 receipts 判断发生了什么、为何失败、性能/成本如何。

**结论：有丰富的结构化 telemetry 数据模型，但正式运行缺少统一采集和持久化后端。**

已有信号：

- `ModelUsage`：tokens、latency、cost、provider request ID、fingerprint；
- `BoundedAttemptTelemetry`：attempt、repair、failure stage/code/path、finish reason；
- `CooperativeTurnResult`：runtime kind、tool/plan alignment、Memory retrieval/usage、projection/reflection 状态；
- `MemoryUsageTrace`：candidate→selected→declared→accepted；
- domain action history、Memory source receipts、Reflection receipts 是可持久审计记录；
- `diagnostic_hook` 可接收 parser/schema/policy/fallback 事件。

但正式 `build_game_npc()` 没传 `diagnostic_hook`；`ClinicRequestHandler.log_message()` 被直接禁用；顶层异常也没有 logger。多数 turn telemetry 只是通过 URL query 回显到开发 details，没有写结构化日志或 trace store。没有 OpenTelemetry span、metrics exporter、correlation middleware、告警或 dashboard。

**高频追问。**

1. 如何追踪一次模型调用和工具执行？
2. token、成本、延迟在哪里记录？
3. 线上 500 如何定位？
4. Memory 是否真的影响了决策，怎么观察？

**20 秒回答。**

项目已经定义了 token/cost/latency、修复尝试、plan-action alignment 和 Memory 使用链路等结构化 telemetry，也有持久 domain/memory/reflection receipt。但正式 Web 没接日志或 tracing sink，access log 还被关闭，所以现在是“可观测数据已建模、生产采集未完成”。

**1 分钟回答。**

模型层会产生 `ModelUsage` 和 `BoundedAttemptTelemetry`，Runtime 把 repair、fallback、selected tool、plan alignment、Memory retrieval/attribution、reflection 结果汇总到 `CooperativeTurnResult`。世界 action history 和 Memory/Reflection receipts 可做事后审计。问题是这些 telemetry 大多只随当前响应进入页面开发信息，`diagnostic_hook` 在生产 composition 没有 sink，HTTP access log 被覆盖为空，未知异常也没写日志。因此我能展示 observability schema，但不会说已有生产级 tracing。

**深挖回答。**

- turn_id、decision_id、retrieval_id、provider_request_id 可以作为 correlation 字段，但当前没有统一 trace context。
- Prompt/secret 不记录是安全优点；日志实现应做字段白名单和脱敏，而不是直接 dump prompt。
- 可优先补 JSON structured logger + request/turn correlation + latency/error metrics，再接 OpenTelemetry。
- `operation_results` 把较多结果塞进 query string 回显，既不是可靠日志，也可能扩大本地 URL 历史暴露面。

## 2.15 Security / Authority Boundary

**概念。** Security / Authority Boundary 定义谁能看什么、谁能决定什么、外部输入如何验证、模型权限如何被限制。

**结论：LLM 权限边界设计较强；Web 身份安全只符合本地单机威胁模型。**

已实现的边界：

- server 强制只绑定 `127.0.0.1`；
- DeepSeek base URL 必须 HTTPS，API key 用 `SecretStr`，没有默认 credential；
- form body 最大 32 KiB，输出统一 HTML escape；响应有 no-store、nosniff、CSP、frame-ancestors none；
- Identifier 严格校验后才能形成存储路径；
- Pydantic `extra=forbid` 防多余字段；
- `AgentContextFilter` 隐藏世界真相；
- Prompt 把 player contribution 标为不可信；
- LLM 只能 proposal，`NPCAuthorityPolicy` 决定调查/诊断/处置权限；
- `CaseEngine` 最终执行规则，Memory 不能授权或证明当前事实；
- paid Agent 要显式确认预算。

当前没有：用户认证、CSRF token 与 session 绑定、速率限制、角色 ACL、数据加密 at rest、密钥轮换机制。`operation_id` 是幂等 token，不是安全凭证。因只绑定 loopback，风险被限制在本机，但不能直接公网部署。

**高频追问。**

1. 如何防 prompt injection 让 Agent 越权？
2. LLM 能否直接修改 state 或执行 treatment？
3. 隐藏答案如何隔离？
4. 当前服务能否安全暴露公网？

**20 秒回答。**

安全核心是 capability boundary：模型只看权限过滤后的公开投影，只能提出结构化 action；参数契约、authority policy 和 `CaseEngine` 再决定能否执行。诊断要协商、处置要确认，Memory 也是非权威。Web 只适合 loopback，本身没有认证或公网多租户安全。

**1 分钟回答。**

项目不依赖 prompt 自律来做权限。输入前 `AgentContextFilter` 去掉 root cause、hidden information 和不可见 action；prompt 把用户文本和 Memory 分别标成不可信观点和非权威历史。输出后 schema、GoalPlanPolicy、ActionContract 和 AuthorityPolicy 逐层校验，最终 `CaseEngine` 仍按真实 state 重验。调查是可逆 autonomous action，诊断 proposal-only，处置 confirmation-required。传输侧 DeepSeek 强制 HTTPS，secret 不做默认值。局限是 Web 没有用户认证、CSRF 和 rate limiting，只因 loopback 才可接受。

**深挖回答。**

- Confirmation 不只是按钮：Runtime 要匹配 owner、decision_id、tool_call 和未变化的 case revision。
- 模型不能把 Goal 标完成；完成由 deterministic condition/evaluator 决定。
- Memory 的 player/session/type 白名单在模型前再次验证，降低 cross-tenant retrieval 污染。
- MCP 同样需要上层宿主保证谁可调用；当前 facade 只做 ID owner consistency，不做主体认证。

## 2.16 Domain State 与 LLM State 的边界

**概念。** Domain State 是可决定业务事实和副作用的权威状态；LLM State 是模型的意图、计划、解释、历史参考或暂态输出。

**结论：这是项目最成熟、最值得面试强调的架构边界。**

Domain side：

- `CaseDefinition`：不可变世界真相；
- `CaseSessionState`：已发生的权威世界状态；
- `CaseEngine`：唯一业务转移规则；
- `CaseEvent/ActionRecord`：成功提交 receipt。

LLM/Agent side：

- `CooperativeAgentState`：Goal/Plan/evaluation，属于意图投影；
- `GameNPCTurnProposal/GameNPCDecisionProposal`：模型候选；
- `PlayerContribution`：玩家信念，不是事实；
- `AgentMemoryContext`：历史非权威参考；
- dialogue/explanation/confidence：不可直接改变世界。

桥梁是 `CaseObservation`（Domain→LLM 的公开投影）与 `AgentAction/ToolCallRequest`（LLM→Domain 的候选命令）。中间经过 deterministic validator/policy/executor。世界成功后才回投 AgentState；因此 LLM 输出错误最多污染候选或 Agent intent，不能直接污染 world state。注意：合法但质量差的 LLM action 仍可能通过规则并改变世界，这是产品决策质量风险，不是数据完整性越权。

**高频追问。**

1. LLM 输出属于 state 吗？属于哪种 state？
2. source of truth 为什么不是 AgentState？
3. 模型 hallucination 如何被挡住？
4. Agent plan 与 world revision 冲突怎么办？

**20 秒回答。**

Domain State 和 LLM State 是硬分开的：`CaseSessionState` 和 `CaseEngine` 决定真实世界；Goal/Plan、Memory 和模型 decision 只是意图或参考。两边通过公开 `CaseObservation` 和受校验 `AgentAction` 连接。模型不能直接写世界，也不能自行完成目标或提升权限。

**1 分钟回答。**

世界真相在冻结的 `CaseDefinition`，会话事实在 `CaseSessionState`，唯一合法转移由 `CaseEngine` 产生。模型只看到 `AgentContextFilter` 生成的 observation，输出 `GameNPCTurnProposal`。Goal/Plan 可以持久化，但它们是 Agent 对下一步的承诺，不是世界事实；Memory 也明确是历史非权威 context。Runtime 在模型后用 policy、public action contract 和 authority 过滤，再把 action 翻译成 domain command。world commit 后重新读取 observation，再更新 AgentState，所以投影方向清楚。

**深挖回答。**

- `based_on_observation_revision` 和 plan compatibility 用于识别陈旧计划。
- `PlanEvaluator` 只能根据 pre/post observation、tool success 和 deterministic condition 改状态；模型不能直接 `COMPLETED`。
- `CaseObservation` 不是 source of truth，而是可重新生成的 read model。
- `CooperativeAgentState` 保存失败不会回滚已提交世界，这也证明两者权威等级不同。

## 2.17 Configuration Management

**概念。** Configuration Management 管理不同环境、功能开关、secret、模型/预算/路径参数的来源、验证、默认值和启动失败策略。

**结论：已有显式 CLI + env + typed config + resource config；配置分散，没有统一 Settings/profile 系统。**

配置来源：

- CLI：state dir、host/port、npc mode、memory mode、模型目录/device/batch、paid confirmation、预算；
- Env/当前目录 `.env`：DeepSeek key/base/model/timeout/max tokens/pilot budget；只读取白名单字段，不修改环境；
- Pydantic config：`DeepSeekAdapterConfig`、BGE config、retrieval config；
- packaged JSON resources：case definitions、campaign rules、clinic guides、pilot pricing；
- `pyproject.toml`：入口和依赖。

启动采用 fail-fast：state dir 必须存在；LLM 模式需要显式付费授权、正预算、可发现的模型；semantic Memory 必须成功加载本地模型/manifest/SQLite；Reflection 依赖也必须完整。`src/xuanyi_npc/config` 当前没有实际配置模块。

缺口：同一配置可能先从 env 读再被 CLI budget 覆盖；没有一个统一不可变 app settings、环境 profile、配置 provenance 输出、动态 reload 或 secret manager。

**高频追问。**

1. 配置从哪里来，优先级是什么？
2. secret 如何管理？
3. Memory/Reflection 如何开关？
4. 配置错误是启动失败还是运行时降级？

**20 秒回答。**

项目用 CLI 控制运行模式和路径，用 env/`.env` 提供 DeepSeek secret，再用 Pydantic 做严格验证。LLM 付费、预算、模型可用性和 semantic Memory 都在启动时 fail-fast。当前配置比较分散，还没有统一 Settings/profile 或 secret manager。

**1 分钟回答。**

Web parser 决定 `npc-mode`、`memory-mode` 和本地模型参数；`DeepSeekAdapterConfig.from_env()` 从 process env 优先、项目 `.env` 次之读取白名单字段，API key 是 `SecretStr`，base URL 必须 HTTPS。LLM 模式还要求命令行显式确认 paid run 和预算。BGE 模型用固定 manifest hash、embedding space ID 和 typed config 验证。病例与 Campaign 规则是 packaged JSON 并在启动加载时校验。缺点是这些配置没有集中到统一 application settings，也不支持运行时更新。

**深挖回答。**

- offline 默认 memory disabled；llm 默认 semantic，这是组合层策略而不是 model config 字段。
- 正式默认 `npc-mode=llm`，缺 key/付费确认会启动失败，不会静默变 offline。
- Memory retrieval 的 top_k/min similarity 和 projection budget 目前硬编码在 composition/default model 中，不全是外部配置。
- `.env` 取决于当前工作目录，不是安装包固定路径，部署时要说明。

## 2.18 Dependency Management

**概念。** Dependency Management 管理直接/间接库、版本约束、可复现安装、可选重依赖、平台兼容和升级边界。

**结论：有清晰 core/optional 分层和 Windows resolution 文件；没有跨平台 lockfile，且存在生产依赖 evaluation 层的架构泄漏。**

`pyproject.toml` 的 core 依赖只有 `httpx`、`mcp==2.0.0`、`pydantic`、`python-dotenv`；dev 和 local-embedding 分为 optional extras。`requirements/core-win-py312.txt` 固定了 Windows CPython 3.12 的完整 resolution，local embedding/CUDA 文件固定了 torch/numpy/transformers 等，注释明确不证明其他 OS/Python 版本。

构建使用 setuptools src layout，并显式打包 cases/campaign/pilot/clinic resources。当前没有 uv/poetry/pip-tools lock 元数据、hash pinning、SBOM 自动流程或跨平台 CI 证据。`agents/deepseek.py` 从 `evaluation.costing` 引用生产计价逻辑，说明 package layer 边界有反向依赖；更合理的位置应是 infrastructure/pricing。

**高频追问。**

1. 如何保证依赖可复现？
2. 为什么 embedding 不放 core？
3. 支持哪些 Python/OS？
4. 有没有依赖层级反转或循环风险？

**20 秒回答。**

核心依赖很小，本地 embedding 和 dev 依赖用 extras 隔离；Windows Python 3.12 还有精确 resolution 文件。它不是完整跨平台 lock，当前兼容性证据主要是 Windows 3.12。另有一个需要整理的层级问题：生产 DeepSeek adapter 反向引用了 evaluation 的计价模块。

**1 分钟回答。**

安装元数据在 `pyproject.toml`，core 只放 HTTP、MCP、Pydantic 和 dotenv，BGE/torch 栈是可选 extra，避免所有用户都安装重型 CUDA 依赖。仓库保存了 core Windows 3.12 和 CUDA 12.6 的精确解析结果，用于当前环境复现；但文件自己也声明不能证明 Linux/macOS 或其他 Python 版本。package resources 有显式 allowlist。当前缺少带 hash 的通用 lockfile、跨平台 matrix 和自动漏洞治理，生产 adapter 引 evaluation.costing 也需要重构。

**深挖回答。**

- `mcp` 精确 pin，`httpx/pydantic/dotenv` 在 pyproject 用兼容区间；resolution 文件才固定传递版本。
- 本地模型权重不作为 Python 包依赖，而由启动参数+manifest 校验。
- 535 tests 是当前环境行为证据，不等于所有声明的 `>=3.11` 都已验证。

## 2.19 API / Application / Domain / Runtime 各层职责

**概念。** 分层架构要求 transport 只做协议适配，application 编排用例，domain 持有业务不变量，runtime 编排 Agent 推理/工具循环，infrastructure 提供外部系统。

**结论：总体分层真实存在，且核心方向正确；有少量泄漏与重复 composition。**

| 层 | 当前职责 | 代表代码 |
|---|---|---|
| API / Transport | HTTP/MCP 解析、schema、状态码/页面/stdio | `clinic/server.py`、`mcp_server/*` |
| Application | use case、加载上下文、提交顺序、projection/reconcile | `application/multicase.py`、`clinic.py`、`campaign.py`、memory services |
| Agent Runtime | 一轮观察→提案→校验→权限→工具→反馈→AgentState | `application/cooperative_runtime.py` |
| Domain | state、command、event、不变量、权限词汇 | `domain/*`、`engine/case_engine.py` |
| Agent/LLM adapter | prompt、结构化解析、provider HTTP、fallback | `agents/*` |
| Infrastructure | JSON/SQLite、资源物化、本地 embedding | `storage/*`、`resources/*`、`memory/local_bge.py` |

好点：HTTP/MCP 都不直接修改 domain state；`CaseEngine` 不做 I/O；Runtime 不直接写病例字段，而调用 application facade；provider adapter 不执行工具。

泄漏/问题：

- `ClinicService` dataclass 大量字段是 `object`，接口类型弱，并在 `_service()` 每次重建 `MultiCaseEpisodeService` 和重载 Campaign rules；
- `clinic/server.py` 混合 composition、HTTP、HTML 渲染和运行配置，文件职责过重；
- `DeepSeekChatAdapter` 依赖 `evaluation.costing`；
- `load_guides()` 直接按源码相对路径读取，而其他 runtime resource 使用 packaged resource materialization，打包边界不一致；
- `CaseEngine` 放在 `engine` 包而非 `domain`，但语义上仍是 domain service。

**高频追问。**

1. 为什么 Runtime 不直接保存 state？
2. Domain 层是否依赖 LLM 或数据库？
3. HTTP 和 MCP 是否复用同一业务规则？
4. 当前最大的分层问题是什么？

**20 秒回答。**

Transport 只接 HTTP/MCP；application 负责加载和提交；`CooperativeRuntime` 负责 Agent 一轮编排；domain state 和 `CaseEngine` 持有规则；storage/LLM adapter 是基础设施。核心领域不依赖模型和数据库。当前主要问题是 Web server 文件过重、Clinic 的依赖类型较弱，以及生产 adapter 反向引用 evaluation costing。

**1 分钟回答。**

HTTP handler 把 form 转为 typed input，`ClinicService/MultiCaseEpisodeService` 加载 player/case/session 并组织 use case；Agent 协作交给 `CooperativeRuntime`，它只通过 service facade 执行 action。`CaseToolExecutor` 把 tool call 翻译为 command，纯 `CaseEngine` 计算新 state 和 event，持久化由 application/infrastructure 完成。MCP 复用了 tool executor 和 engine，所以协议不同但规则一致。现有分层不是理想图纸，而是代码里真实存在；同时 server.py 承担过多职责、Clinic 重建 service、evaluation costing 被生产引用，都是可指出的改进项。

**深挖回答。**

- `AgentContextFilter` 是 Domain→LLM 的 anti-corruption layer。
- `CaseToolExecutor` 是 Tool contract→Domain command 的 adapter。
- `MultiCaseActionReceipt` 是 application commit receipt，不是 domain event 本身。
- MCP 正式 path 没有完整 Memory/Campaign/Agent Runtime，因此不能把 Web 的全部能力自动算到 MCP。

## 2.20 一次完整请求的数据流和控制流

**概念。** 数据流描述数据从哪里产生、经过哪些形态、最终写到哪里；控制流描述谁决定下一步、哪些分支会停止或继续。

**结论：正式 cooperative HTTP 路径完整；它是同步、单动作、多投影提交。**

### 数据流

1. 浏览器 POST：player/case/session、operation_id、contribution text/type。
2. HTTP handler → `ClinicContributionInput` → 不可变 `PlayerContribution`。
3. Runtime 加载 `PlayerState`、`CaseSessionState`、`CooperativeAgentState`，生成 `PlayerView/CaseObservation`。
4. Memory service 用 observation/goal/plan/contribution 生成 query，SQLite→embedding cosine hits→安全 `AgentMemoryContext`。
5. `GameNPCAgent` 把 authoritative world、constraints、intent、memory、player belief 和 public action space序列化进 prompt。
6. DeepSeek 返回 JSON → `GameNPCTurnProposal` → Pydantic/策略校验。
7. Runtime 将 proposal 投影为新 Agent Goal/Plan，并取得一个 `AgentAction`。
8. Action contract + authority 决定 respond/pending/reject/execute。
9. execute 时，`CaseToolExecutor` 把 tool arguments 转 command；`CaseEngine` 输出新 session + event + message。
10. application 保存 world；可选写 Memory/index；完成案时写 Campaign。
11. Runtime 重载 post observation，PlanEvaluator 更新 AgentState并保存。
12. 若命中生命周期 trigger，Reflection 生成候选、consolidate 到 Memory、保存 receipt。
13. `CooperativeTurnResult` 返回，handler 将部分字段放入 redirect query，GET 页面再加载持久 state 渲染。

### 关键控制分支

- operation_id 已见：直接 redirect，不再执行（仅同进程可靠）。
- state/context 无效：安全错误，停止。
- current goal 已满足：不调用 LLM 工具，先结束 goal。
- 模型/格式失败：一次修复后 fallback respond。
- action 与 plan/public action space 不一致：拒绝并保存 evaluation。
- 诊断/处置未授权：生成 pending，不执行 world command。
- tool rule violation：返回拒绝，world 不变，plan 可记录失败反馈。
- tool 成功：world 先提交；派生失败不反向回滚 world。

**高频追问。**

1. 从 HTTP 请求到落盘经过哪些对象？
2. 哪一步真正产生副作用？
3. 模型调用前后各有哪些 deterministic guard？
4. 返回页面为什么还要重新 GET state？

**20 秒回答。**

一次请求先把玩家文本变成 typed contribution，Runtime 加载 world/Agent state、生成公开 context并检索 Memory；LLM 只提 Goal/Plan/Action。之后经过 policy、action contract 和 authority，最多执行一个 tool。`CaseEngine` 产生新 world，先落盘，再投影 Memory/Campaign/AgentState，最后返回结果。真正世界副作用只发生在确定性 command 提交阶段。

**1 分钟回答。**

POST 进入 `ClinicService` 后创建 `PlayerContribution`，`CooperativeRuntime` 恢复 session 和 AgentState，通过 `AgentContextFilter` 得到公开 observation，并附加按 player 隔离的 Memory。`GameNPCAgent` 生成结构化 turn proposal，schema、GoalPlanPolicy 和 public action contract 先验证，authority policy 再判断自主、提议、需确认或禁止。若允许，application 把 action 交给 executor 和纯 `CaseEngine`，得到新 `CaseSessionState` 和 event。世界保存后 Runtime 重读 observation、评估计划、保存 AgentState；Memory、Campaign、Reflection 都是后续投影。HTTP 使用 POST-redirect-GET，页面最终再次从持久 state 渲染。

**深挖回答。**

- 模型前的 guard 是 context projection/authority view/public action space；模型后的 guard 是 schema/policy/contract/authority/engine。
- Agent plan 更新在 world action 前先形成内存候选，但只有各分支结束时持久化；world 成功后会基于 post observation 再评估。
- MCP 数据流从 strict tool input 直接到 application/executor/engine，不经过 GameNPCAgent、Goal/Plan、semantic Memory 或 Reflection。
- 当前整个链路在请求线程同步执行，本地 embedding、LLM、SQLite 和 Reflection 都会增加响应延迟。

## 3. “代码 → 工程概念”映射表

| 代码 | 工程概念 |
|---|---|
| `PlayerState` | Player aggregate / profile state |
| `CaseSessionState` | Authoritative domain session state / aggregate snapshot |
| `ActionRecord` + `CaseEvent` | Append-only audit history / domain event receipt |
| `CaseDefinition(frozen=True)` | Immutable domain configuration / world truth |
| `CooperativeAgentState` | Persistent Agent intent state |
| `AgentGoalState` | Goal state machine |
| `AgentPlan` + `PlanStep` | Bounded plan state machine |
| `PlanEvaluation` | Deterministic feedback / plan transition receipt |
| `CampaignState` | Cross-session projection / event-derived read model |
| `CaseDialogueState` | UI conversation session state |
| `PendingActionConfirmation` | Human-in-the-loop approval state / optimistic confirmation token |
| `JsonStateStore` | Atomic file snapshot persistence / repository |
| `SQLiteMemoryRepository` | Transactional repository / durable idempotency receipts |
| `save_cooperative_agent_state(expected_revision=...)` | Optimistic revision check；受控单进程 Session 锁内有线程串行语义，跨进程仍非原子 CAS |
| `CaseEngine.execute()` | Pure deterministic domain service / state transition function |
| `CaseEventReplayer` | Event replay utility；不是正式恢复主路径 |
| `CooperativeRuntime.handle()` | Agent runtime orchestration / one-turn execution loop |
| `MultiCaseEpisodeService` | Application service / use-case facade |
| `CaseToolExecutor` | Tool adapter / command translator |
| `AgentContextFilter` | Least-privilege context projection / anti-corruption layer |
| `PlayerView`、`CaseObservation` | LLM-safe read models |
| `GameNPCAgentInput` | Per-turn context envelope |
| `GameNPCTurnProposal` | Structured LLM proposal contract |
| `GoalPlanPolicy` | Deterministic planning policy guard |
| `PublicActionContractValidator` | Tool call schema + current-state semantic validator |
| `NPCAuthorityPolicy` | Capability/authority boundary / HITL policy |
| `BoundedStructuredOutput` | Bounded retry + structured output repair executor |
| `_fallback_turn_proposal()` | Safe deterministic fallback |
| `DeepSeekChatAdapter` | LLM provider adapter / infrastructure gateway |
| `DeepSeekRequestBudgetGuard` | Cost guardrail / reserve-settle accounting |
| `V1MemoryCoordinator` | World-to-memory projection coordinator / eventual consistency boundary |
| `VerifiedMemorySource` | Provenance receipt |
| `AuthoritativeMemoryRecord` | Durable long-term memory record |
| `DerivedEmbeddingRecord` | Rebuildable secondary index |
| `MemoryIndexService` | Vector index lifecycle manager |
| `BasicCosineMemoryRetriever` | Semantic retrieval service |
| `AgentMemoryContext` | Bounded non-authoritative retrieval context |
| `MemoryUsageTrace` | Memory attribution telemetry |
| `ReflectionLifecycleService` | Lifecycle-triggered reflection orchestration |
| `reflection_lifecycle_receipts` | Durable idempotency/work receipt |
| `CampaignCoordinator.reconcile()` | Projection repair / reconciliation |
| `materialized_clinic_resources()` | Packaged resource lifecycle / deployment abstraction |
| `ClinicRequestHandler` | HTTP transport/controller |
| `MCPApplicationService` | MCP application facade |
| `FROZEN_MCP_TOOL_NAMES` | Static tool registry |
| `ThreadingHTTPServer` | Thread-per-request concurrency model |
| `operation_results` | In-memory idempotency cache；非 durable |
| `cooperative_pending` | In-memory approval store；非 durable |
| `ModelUsage` / `BoundedAttemptTelemetry` | LLM cost/performance/error telemetry |
| `diagnostic_hook` | Observability extension point；正式 composition 未接 sink |

## 4. 面试风险排名

### P0：极容易被追问住，必须立即掌握

1. **State taxonomy 与 source of truth。** 必须能区分 world、Agent、Campaign、Memory、dialogue、pending。
2. **一次请求完整链路。** 能从 HTTP contribution 讲到 world commit 和派生投影。
3. **Domain State 与 LLM State 边界。** 模型只能 proposal，谁做最终校验和提交。
4. **并发真实边界。** Web 是多线程，正常入口靠 Session `RLock` 串行；JSON CAS 仍不跨进程。不能误答“revision 已解决所有并发”，也不能再误答“项目没有 per-session lock”。
5. **一致性模型。** world-first、Memory/Campaign/Agent projection；不是全局事务。
6. **幂等真实边界。** Memory/Reflection 强，Web action 弱；重启后 operation cache 失效。

### P1：Agent 开发岗位高频

7. Context projection、权威等级与 prompt injection 防线。
8. structured output 修复、action-contract repair、safe fallback 与“没有网络 retry”。
9. Tool lifecycle 与 authority：调查自主、诊断提议、处置确认。
10. Memory 写入、检索、隔离、预算、归因和 Reflection。
11. Session 恢复与 pending confirmation 不持久化。
12. Observability：telemetry model 丰富，但生产 sink 当前没有。
13. Agent 生命周期是共享行为实例 + per-session persistent state。

### P2：进阶问题

14. Campaign 的 event-derived projection 与 replayable invariant。
15. SQLite schema migration、receipt、tombstone 与 embedding consistency。
16. dependency reproducibility 与平台声明边界。
17. MCP path 与 Web Agent path 的能力差异。
18. 分层泄漏：server 过重、Clinic object typing、production→evaluation costing。
19. local-only threat model 与真正 multi-tenant security 的差距。
20. AgentState projection 失败后的补偿缺口。

## 5. 最应该先补的 10 个问题

按优先顺序，建议先把下面十题练到不看稿也能回答：

1. **你的项目有哪些 state？每种 state 的 owner、生命周期和 source of truth 是什么？**
2. **`CaseSessionState` 与 `CooperativeAgentState` 有什么本质区别？为什么后者不能修改世界？**
3. **请完整讲一遍 `CooperativeRuntime.handle()` 的控制流，哪一步真正产生副作用？**
4. **LLM hallucination 或 prompt injection 为什么不能直接执行非法工具？模型前后有哪些 guard？**
5. **两个线程同时修改同一 session 为什么会被串行？为什么这仍不等于跨进程数据库 CAS？**
6. **一次 action 同时涉及 JSON、SQLite Memory、Campaign、AgentState，它们是否一个事务？部分失败如何处理？**
7. **重复请求如何幂等？哪些环节持久幂等，哪些重启后会失效？**
8. **长期 Memory 从哪里写入、如何检索、如何防跨用户泄漏、为什么不是当前事实？**
9. **模型输出非法 JSON、动作不在 action space、provider timeout 分别如何处理？当前有没有 retry？**
10. **当前 observability 到什么程度？哪些 telemetry 已经有，为什么仍不能说有生产级 tracing？**

## 6. 一段可作为总述的真实面试回答

> 《异闻行录》的工程核心是把世界状态、Agent 意图状态和长期记忆分开。`CaseSessionState` 是病例世界的 source of truth，只能由纯确定性的 `CaseEngine` 根据受校验 command 产生新版本；LLM 看到的是 `AgentContextFilter` 生成的公开 observation，只能输出结构化 Goal/Plan/Action proposal。`CooperativeRuntime` 每个请求完成一轮观察、规划、动作契约、权限、至多一个工具执行、世界反馈和 AgentState 持久化。长期 Memory 在 semantic 模式下从已提交事件投影进 SQLite，再做 BGE-M3 检索，属于非权威跨 session 参考。正常单进程写入口使用共享 Session `RLock` 串行化，已有并发冲突测试；完整 turn 仍不是一个全局事务，而是 world-first、随后 Memory/Campaign/Agent projection 的最终一致模型。当前明确缺口是跨进程 CAS、统一 durable operation/outbox、pending confirmation 持久化、认证和生产日志/Tracing，因此还没有达到公网多租户生产级 Agent 应用。

## 7. 审计中发现的“不要误答”清单

- 不要说“项目只有 `AgentState` 一个状态”；实际至少有六类状态。
- 不要说“用了 revision 所以所有部署都并发安全”；线程级安全来自正常入口的 Session 锁，JSON revision check 与 replace 仍不是跨进程原子事务。
- 不要说“整个项目是 Event Sourcing”；病例/Campaign 有事件化历史，但正式恢复主要读取快照。
- 不要说“每轮 Agent 会自动循环到任务完成”；它每个请求最多一个动作。
- 不要说“所有模式都有长期记忆”；offline 默认 disabled，Reflection 只在 real LLM + semantic Memory。
- 不要说“有自动重试”；provider 网络层明确没有，只有结构修复和动作修复。
- 不要说“支持多用户认证”；只有 player/session 逻辑隔离和 loopback 部署。
- 不要说“完整请求是 ACID 事务”；只有 SQLite 内部事务，跨存储是 world-first projection。
- 不要说“有完整 tracing”；有 telemetry schema 和 receipt，但生产 sink 未接。
- 不要说“MCP 就是完整 Agent”；MCP 入口只暴露确定性工具，不包含 GameNPCAgent Runtime。
- 不要说“对话历史已经进入 Agent context”；`recent_messages` 字段存在，但正式 Runtime 没传。
- 不要说“所有 repository capability 都有产品入口”；Memory correction/invalidation/delete 目前没有正式 Web/MCP 管理入口。
