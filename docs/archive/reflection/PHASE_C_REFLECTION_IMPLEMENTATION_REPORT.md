# Phase C Reflection Production Loop Implementation Report

> 历史实施与首次 production smoke 记录。Reflection 当前设计及 E11–E13 后续证据统一见 [`../../architecture/REFLECTION_DESIGN.md`](../../architecture/REFLECTION_DESIGN.md)。

## 结论

`PHASE C REFLECTION: FAIL`

Phase C 的 production wiring、权威来源约束、Memory consolidation/index、持久化幂等收据和失败隔离已完成，并通过 targeted tests 与全量回归。但真实 `yiwen-xinglu --npc-mode llm` smoke test 中，`GOAL_COMPLETED` trigger 到达 Reflection lifecycle 后，production DeepSeek reflection generation 返回 `fallback_empty`。没有产生 structured lesson、reflection Memory 或对应 embedding，因此不能宣称 production loop 已闭环。

按验收约束，首次真实 smoke 失败后已停止继续修改架构，也未用测试替代真实运行结果。

## 实现范围

### Production composition

- `src/xuanyi_npc/clinic/server.py`
  - production `llm + semantic memory` 组装 `ReflectionProposalGenerator`、`ReflectionMemoryConsolidationService` 和 `ReflectionLifecycleService`。
  - Reflection 复用 GameNPCAgent 的同一个 production DeepSeek adapter。
  - Reflection consolidation 复用 production SQLite Memory repository 与 BGE-M3 `MemoryIndexService`。
  - lifecycle 被显式注入 `CooperativeRuntime`；启动日志和页面展示真实 enabled/disabled 状态，不做 silent fallback。
- `src/xuanyi_npc/application/cooperative_runtime.py`
  - Reflection 保持在权威 world event commit 之后执行。
  - Reflection failure 只形成 telemetry，不回滚或改写 CaseEngine 已提交状态。

### Grounding 与安全边界

- `src/xuanyi_npc/application/reflection.py`
  - lesson 必须由 trigger 对应的允许 provenance 直接支撑。
  - Outcome 只接受 tool outcome、observation delta、assessment。
  - Planning 接受 plan evaluation 与权威公开 outcome。
  - Cooperation 只接受 contribution evaluation。
  - Memory helpfulness 接受 memory trace 及公开 outcome/observation/assessment。
  - Agent 台词、玩家信念或无关文本不能被包装成世界事实。
- Reflection 不具有 CaseSessionState 写权限；它只能产生受验证的长期 Memory candidate。
- proposal Memory 类型与现有 schema/policy 对齐，仅允许 `EPISODIC` / `LEARNING`，未增加平行 taxonomy。

### Consolidation、embedding/index 与 telemetry

- `src/xuanyi_npc/application/reflection_memory.py`
  - validated candidate 写入既有 SQLite Memory repository。
  - 成功写入后调用共享 `MemoryIndexService.index_player()`，不建立独立向量管线。
  - 明确报告 `complete` / `pending` 及 index error。
  - candidate/source identity 对同一 player、trigger、ordinal 稳定。
- `src/xuanyi_npc/domain/reflection_memory.py`、`reflection_lifecycle.py`、`cooperation.py`
  - 增加 index 状态、repository/index failure 和 runtime-facing error telemetry。

### Restart idempotency

- `src/xuanyi_npc/storage/sqlite_memory.py`
  - schema version 升至 3。
  - 新增持久化 `reflection_lifecycle_receipts`，以 `trigger_id` 为主键。
  - 在 LLM 调用之前 atomic claim；terminal receipt 可跨进程 replay，避免重复 LLM 和重复 Memory。
  - 支持一次受限的 interrupted-owner recovery；达到上限后显式 interrupted，不无限重试。
- `src/xuanyi_npc/application/reflection_lifecycle.py`
  - lifecycle 的所有 terminal result 均尝试持久化。
  - receipt replay 返回 `IDEMPOTENT_REPLAY`，不再次调用 LLM 或写 Memory。
  - repository/index/generation failure 均显式反映，不影响已提交游戏 Turn。

## 测试证据

Targeted suite 覆盖 Reflection、Phase B Memory、Runtime、SQLite migration 和 production wiring：

- `130 passed`
- 包含：
  - 不允许用无关 Agent dialogue 支撑 lesson；
  - 写入后自动 BGE index；
  - 新 lifecycle 实例读取同一 SQLite receipt，零额外 LLM 调用、单一 Memory；
  - production Reflection 复用同一 adapter/repository/index；
  - schema v1/v2 到 v3 migration；
  - world-state commit 与 Reflection failure 隔离。

全量回归：

- `429 tests collected`
- `429 passed`，pytest exit code `0`
- 修改的 production Python 文件通过 `py_compile`。

这些结果证明实现和回归边界成立，但不能覆盖或替代下面的真实 production smoke 结果。

## Real Production Smoke Test

### 启动配置

- executable：`runtime_data/phase_b_smoke_venv/Scripts/yiwen-xinglu.exe`
- state-dir：`runtime_data/phase_c_reflection_smoke`
- 参数：`--npc-mode llm --memory-mode semantic --memory-device cpu --confirm-paid-agent --agent-budget-cny 1.00`
- HTTP：`200`
- production 启动证据：
  - `NPC mode=llm`
  - `Memory mode=semantic`
  - `Reflection mode=enabled`
  - 页面显示 LLM GameNPCAgent、semantic Memory 与 Reflection 均已启用。

### 实际身份

- player：`player_7d41fa6e339e47c8af7b062ee7e3541a`
- source session：`session_10aab20aff1b4f078c1567524ab15c2f`
- case：`old_paper_umbrella`

### CaseEngine 与普通长期 Memory

真实 investigation 的两个 Turn 均提交了 CaseEngine event，并产生普通 episodic Memory：

- `mem_3c5cb1c36da75da6ba85032a9cee1dd5`
- `mem_b28fa05bc34856efa06dd9d497644f14`

SQLite 直接检查：

- `schema_version = 3`
- `memory_events = 2`
- `memory_embeddings = 2`
- `memory_source_receipts = 2`
- embedding space：`bge_m3_142964af7e05_dense_fp32_d1024_cpu_l512_v1`
- dimension：`1024`
- 每个向量 blob：`4096` bytes

这证明 Phase B 的 committed event → SQLite → production BGE-M3 链在本次 Phase C smoke 中仍然正常。

### Reflection trigger 与失败点

第二个 Turn 真实完成 Goal，产生：

- trigger type：`goal_completed`
- trigger ID：`rtr_2de575344ec24e6f6af77166`
- lifecycle status：`fallback`
- proposal status：`fallback_empty`
- reflection attempt count：`1`
- repaired：`false`
- error code：`reflection_generation_fallback`
- candidate IDs：`[]`
- write outcomes：`[]`
- written reflection memory IDs：`[]`
- index status：`not_required`

触发输入包含公开 provenance：goal、plan/steps、plan evaluation、action、tool outcome、observation delta、contribution/evaluation 和 memory trace。失败发生在 candidate validation/consolidation 之前：production Reflection LLM 没有返回可用 structured proposal。

当前 telemetry 只持久化到 `reflection_generation_fallback`，没有保留 DeepSeek adapter 的底层异常或响应细节，因此不能据此伪造更具体的 API 根因。`repaired=false` 只说明该次记录未完成 structured repair，不足以判断是 transport、model output 还是解析层的具体错误。这是后续定位所需的 observability 缺口，不是本轮继续修改的授权。

### 持久化失败收据与故障隔离

SQLite 中存在一条 `reflection_lifecycle_receipts`：

- trigger：`rtr_2de575344ec24e6f6af77166`
- status：`fallback`
- attempt_count：`1`
- result 持久化了上述 proposal/lifecycle/index/error 状态。

尽管 Reflection 失败，CaseEngine event 和两条普通 Memory/embedding 仍成功提交，证明 Reflection LLM failure 未破坏正常游戏 Turn，也未获得权威 world-state 写权限。

### 因失败而未继续的验收项

按照“真实 smoke 失败后停止，不自动修改其他架构”的要求，以下 production smoke 步骤没有继续执行：

- reflection lesson SQLite write；
- reflection lesson BGE-M3 embedding/index；
- 完全重启后的真实 receipt replay；
- 新 session 对 reflection lesson 的 semantic retrieval；
- safe projection；
- reflection lesson 进入未来 `GameNPCAgentInput`；
- 未来 Turn 行为影响证据。

restart idempotency、projection/isolation 等已有 targeted/regression tests 通过；Phase B 的跨玩家、hidden/private 与 current-session exclusion 回归未被削弱。但因为本次没有生成 reflection Memory，它们不能被表述为 Phase C end-to-end production smoke PASS。

服务已完全停止：原进程不存活，端口不再监听。

## 验收矩阵

| 项目 | 结果 | 证据 |
|---|---|---|
| Production Reflection wiring | PASS | 启动日志与页面 `Reflection mode=enabled` |
| Shared GameNPC DeepSeek adapter | PASS | composition wiring test 与实现审查 |
| Real lifecycle trigger | PASS | `goal_completed`, `rtr_2de575344ec24e6f6af77166` |
| Authoritative grounding input | PASS | runtime provenance refs 已形成 |
| Structured Reflection proposal | FAIL | `fallback_empty` |
| Lesson validation | NOT REACHED | 无 proposal candidate |
| Reflection SQLite Memory write | FAIL | written IDs empty |
| Reflection BGE-M3 index | NOT REACHED | `not_required` |
| Persistent lifecycle receipt | PASS | SQLite receipt status `fallback` |
| World-state/Turn failure isolation | PASS | event、普通 Memory、BGE vectors 均提交 |
| Real restart replay | NOT EXECUTED | smoke 在 generation failure 后停止 |
| Future scoped retrieval | NOT EXECUTED | 无 reflection Memory 可检索 |
| Safe projection to future input | NOT EXECUTED | 无 reflection Memory 可投影 |
| Influence future GameNPCAgent decision | NOT EXECUTED | production loop 未闭合 |

## 最终判断

当前代码已经把 Reflection 的 production 结构接入，并建立了安全 consolidation、索引、持久化幂等和 failure isolation；但真实 production DeepSeek generation 未产生 structured lesson。因此：

`experience → trigger → LLM reflection` 已到达 LLM generation，随后失败；

`structured lesson → validate → consolidate → retrieve → influence future behavior` 未在真实 production smoke 中发生。

最终验收只能是：

`PHASE C REFLECTION: FAIL`
