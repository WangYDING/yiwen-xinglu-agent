# Phase B：生产语义记忆接入

> 历史实施与 smoke 记录。Memory 当前设计、实现边界和后续证据统一见 [`../../architecture/MEMORY_DESIGN.md`](../../architecture/MEMORY_DESIGN.md)。

当前生产 composition root 已接入长期记忆提交、索引和检索；Reflection 能力保留，但本次 production wiring 未启用：

```text
CaseEngine accepted events
  → V1MemoryCoordinator
  → SQLite authoritative memory
  → BGE/Fake embedding index
  → player-scoped retrieval
  → GameNPCAgent read-only memory context
```

关键边界：

- 权威案件 JSON 先提交，记忆投影可恢复；
- 仅 allowlisted committed events 可写入；
- 向量是可重建派生数据；
- 当前玩家、当前 Episode、inactive/deleted 和不允许类型在排序前过滤；
- 检索失败安全停止，不污染案件状态；
- Reflection 必须引用公开结果证据，并经过独立写入策略。

回归证据位于 `tests/test_phase_b_production_memory.py`、M3/M4 测试和 M4.5 Gold/Holdout。M4.5 的历史失败结论保持有效，不被生产接入改写。

## Production Smoke Test

### 第一轮结果与根因

第一轮正式 smoke test 结果为 **FAIL**。已经跑通的链路是：CaseEngine committed event → SQLite memory write → BGE-M3 1024d embedding/index → 进程重启 → scoped semantic retrieval → safe projection → `GameNPCAgentInput` → 实际 LLM 使用。失败发生在后续 Turn 的检索查询构造阶段：`GameNPCMemoryQueryBuilder.build()` 把不断增长的 Observation、Goal、Plan 和 evaluation 序列化后传给 `GameNPCMemoryQuery`，导致 `text` 超过 `NonEmptyText` 的 2000 字符约束。Pydantic 在进入 `retrieve_scoped()` 之前抛出 `ValidationError`，Runtime 因而记录 `failed_safe`。

同轮暴露的独立 Goal 生命周期问题是：已完成 Goal 在下一 Turn 仍作为 current Goal 提供给 Agent，LLM 的 `KEEP_GOAL` 随后被 `GoalPlanPolicy` 正确拒绝，错误为 `a terminal or blocked goal cannot be kept`。Policy 拒绝行为正确，缺口位于上游 terminal Goal 生命周期处理。

### 最小修复

- `GameNPCMemoryQueryBuilder` 现在显式持有 `max_query_chars=2000`，并在构造阶段保证结果合法，不依赖 schema 最后报错。
- 查询为确定性、公开信息限定的紧凑 JSON。必保留字段依次包含当前 player contribution、当前 Goal、current Plan Step 和最小 case identity；可选公开 Observation 与最近 evaluation 按固定优先级、固定条数和字段内预算加入。
- 字段在加入 JSON 前独立规范化和有界裁剪；低优先级历史先被舍弃，不对完整拼接串做无结构尾部截断；不调用额外 LLM 摘要。
- BGE-M3 的 embedding dimension、生产 adapter、player/session scope 和 hidden-info projection policy 均未修改。
- `CooperativeRuntime` 在下一 Turn 进入 retrieval/Agent 前，将 `COMPLETED` 或 `ABANDONED` 的 current Goal 初始化为与当前案件阶段一致的新 active Goal，同时清除旧 Plan/evaluation。`BLOCKED` Goal 仍必须由既有 Policy 通过 replace/abandon 处理，没有放宽 `GoalPlanPolicy`。

新增回归覆盖：长 Observation/Goal/多步 Plan/长 evaluation 下查询不超过 2000 字符；预算耗尽时保留 contribution、Goal 与 current step；正式 Runtime 长上下文仍调用 scoped retriever；旧 session memory 可成为 candidate 而 current session memory 被排除；completed Goal 下一 Turn 在 Agent 输入前被替换。Phase B 定向测试为 23/23 通过；项目清理后的全量测试为 445/445 通过。

### Smoke v2 实际证据（2026-08-25）

状态目录：`runtime_data/phase_b_smoke_v2`。入口为已安装的正式 `yiwen-xinglu.exe`，参数使用 `--npc-mode llm --memory-mode semantic --memory-device cpu --confirm-paid-agent`。两次启动日志均显示 `NPC mode=llm` 与 `Memory mode=semantic`；网页显示调查搭档为 `LLM GameNPCAgent`、长期 Memory 为语义检索、Reflection 未启用。

Session A：

- player：`player_c0ff97f7a8d44aea81d01b5cd1aaff56`
- source session：`session_619ff292b89e4d0e8b49ef0822425018`
- CaseEngine event：`investigation_completed`，`source_event_id=ce_d5166f1004bb5c95b9def8a603197257`
- Memory A：`mem_e474930a820850429e3827e987ea4a50`
- Runtime write：`memory commit status=complete`
- SQLite：`memory_events`、`memory_source_receipts`、`memory_embeddings` 均存在对应记录；状态 `active`
- embedding space：`bge_m3_142964af7e05_dense_fp32_d1024_cpu_l512_v1`；dimension `1024`；vector blob `4096` bytes

随后完全终止进程，确认 PID 不存在且 8766 端口不再监听；再以同一 state-dir 启动正式程序。SQLite 中的 Memory A 与向量在重启后仍存在。

Session B：`session_109b1cca44ab42898edf07b95c76e422`。

- Turn 1：`memory retrieval status=success`，candidate/selected/declared-used/accepted-used IDs 均为 Memory A；safe projection 后页面显示“参考旧纸伞案例中从契物本身入手的经验”，证明该 ID 已进入 `GameNPCAgentInput` 并被实际 LLM 使用。该 Turn 提交 Memory B：`mem_4f5497977a3550b482ad4a5c5ba48db2`。
- Turn 2：Observation 已包含 Session B 新线索，Plan 有 4 步且已有 evaluation；这是第一轮出现超长查询的增长场景。结果仍为 `memory retrieval status=success`、candidate count `1`、selected count `1`，candidate 仅为 Memory A。Memory B 属于 current session，未出现在 candidate/selected IDs 中，证明排除发生在正式 Runtime 路径，而非底层直接调用。
- Turn 2 产生 Memory `mem_3a046d4a532b581fa237d9b25dbcc594`，同样未污染当轮候选集合。
- Turn 3：上一轮 Goal 已 completed；Runtime 创建新的 `goal_op_3bb95777e159b2c38f79b2ff` 并正常完成 LLM 行为，没有出现 terminal Goal `KEEP_GOAL` 异常。检索继续为 success，候选仍仅为 Memory A。

最终 SQLite 含 4 条 `memory_events`、4 条 `memory_source_receipts` 和 4 条对应 `memory_embeddings`；全部属于同一 player，各向量均为 production BGE-M3 1024d/4096 bytes。写入内容均来自 allowlisted public `investigation_completed` payload。第一轮已经验证的 cross-player isolation 与 hidden/private projection 边界未被本次修复修改；v2 的正式 Runtime current-session exclusion 证据如上。

**PHASE B SMOKE TEST: PASS**
