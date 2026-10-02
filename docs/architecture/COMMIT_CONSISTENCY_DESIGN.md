# 提交一致性与失败安全模块主文档

> 状态：当前实现说明。本文是理解 world 提交、后提交投影、同进程并发保护、operation 重试和失败反馈的统一入口。

## 1. 模块定位与当前状态

本模块提供的是**失败安全与有限并发保护**：受控产品入口能够区分确定未提交、确定已提交和提交结果未知；同一进程内对同一 Session 的读—计算—写进行串行化；已知危险重试会返回既有结果或被保守阻断。

当前没有跨 JSON/SQLite 的原子事务，没有跨进程 CAS，也没有自动恢复闭环。world、Memory、Campaign、Cooperative Agent State、Reflection 与 cooperative History 仍属于不同持久化边界。

第一阶段已经完成：故障窗口被显式分类，单进程核心入口的静默覆盖得到修补，未知结果不再被描述为“状态未改变”。第二阶段目前暂缓，不是默认待办；只有[重新启动条件](#8-剩余限制风险排序与重新启动条件)出现时才重新评估 durable receipt、outbox、单写者或 CAS。

本文不属于 [Context Engineering](CONTEXT_ENGINEERING_DESIGN.md)。Context Engineering 管理模型请求的选择、预算与快照；本模块管理确定性写路径的提交边界。协作 History 同时为两者提供回合身份，但两份设计的保证不能互相替代。

## 2. 实际提交链

下面是**成功执行一个会修改 world 的协作 Tool** 时的主路径。非 Tool 回复、校验拒绝和普通/MCP 入口会跳过其中部分阶段。

```mermaid
flowchart LR
  Begin[History begin] -. cooperative only .-> Prepared[prepared decision]
  Engine[CaseEngine<br/>EngineResult] --> World[(CaseSession world JSON)]
  World --> Memory[(ordinary Memory projection)]
  Memory --> Index[Memory index]
  Index --> Campaign[Campaign projection<br/>completed episode only]
  Campaign --> Observation[reload public Observation]
  Observation --> Evaluator[PlanEvaluator]
  Evaluator --> AgentState[(Cooperative Agent State)]
  AgentState --> Reflection[post-commit Reflection]
  Reflection --> Complete[History completed result]
  Prepared -. authority / Tool gate .-> Engine
```

实际顺序和边界如下：

1. `CaseEngine` 只产生新的不可变 Session、事件和公开结果，不直接写存储。
2. [`MultiCaseEpisodeService.submit_action_with_receipt`](../../src/xuanyi_npc/application/multicase.py) 在 Session 锁内加载上下文、执行 Engine，并先保存 `CaseSessionState`。
3. 启用普通 Memory 时，[`V1MemoryCoordinator`](../../src/xuanyi_npc/application/memory_coordination.py) 明确先保存 world，再逐事件写 Memory；随后 MultiCase 尝试更新索引。
4. 仅当 Episode 已完成时，MultiCase 再投影 Campaign。Campaign 失败返回 `campaign_projection_pending`，不撤销已提交 world；已有 `reconcile_campaign` 可从完成 Session 对账。
5. 协作 Runtime 在确认 world receipt 为 committed 后重读公开 Observation，再运行 `PlanEvaluator`，最后保存 `CooperativeAgentState`。
6. Reflection 位于 Agent State 之后，只消费已提交结果和公开 evidence；失败以 failed-safe 状态返回。
7. 启用 cooperative recording 时，History 在 Runtime 前写 `started`，最终 decision 在 Tool 前写 `prepared`，完整结果在所有上述运行时阶段返回后写 `completed`。History 完成写失败会转为 `recovery_required`，不会自动重发 Tool。

普通页面行动和直接 MultiCase 没有 Observation → PlanEvaluator → Agent State → Reflection 这条协作后链。MCP 直接调用 Engine 并保存 world，也不经过普通 Memory、Campaign 或协作后链。不能把协作入口的完整顺序强行推广到其他入口。

`CaseSessionState` world 是已提交案件事实、action history 与 revision 的权威来源，但不是所有状态的总账。玩家贡献、当前 Goal/Plan、pending authorization、Memory lifecycle 和 Reflection receipt 分属其他权威域；尤其玩家目标和计划意图不能假定能从 world 完整重建。

## 3. 并发保护范围

[`JsonStateStore.session_write_lock`](../../src/xuanyi_npc/storage/json_store.py) 使用模块级锁表，实际键为：

```text
(str(state_store.root.resolve()), validated session_id)
```

值是进程内共享的 `threading.RLock`。`RLock` 允许 Clinic、Cooperative Runtime 与 MultiCase 的嵌套调用复用同一把锁，避免内部再次进入时死锁。

| 入口 | 锁覆盖的实际范围 |
|---|---|
| 普通案件操作 `ClinicService.submit_case_action` | 从普通 operation receipt 查询、payload 校验、Tool 请求构造，到嵌套 MultiCase 的上下文加载、Engine 计算、world/Memory/索引/Campaign 写入和 receipt 缓存 |
| 协作入口 `ClinicService.submit_player_contribution` | cooperative recording 启用时，live-operation claim 在锁前完成以便并发同 operation 立即得到 `operation_in_progress`；History begin、上下文构造、整个 Runtime、world 与后提交处理在 Session 锁内 |
| `CooperativeRuntime.handle` | 装饰器覆盖 Runtime 的初始 Observation/Agent State 读取、Agent 决策、Tool 提交、post Observation、PlanEvaluator、Agent State 与 Reflection |
| 直接 `MultiCaseEpisodeService.submit_action_with_receipt` | operation cache 查询、上下文读取、Engine 执行、world/Memory/索引/Campaign 处理和 receipt 缓存 |
| `MCPApplicationService.execute_tool` | MCP 上下文读取、Engine 执行与 world 保存 |

这项保证严格限于：同一 Python 进程、使用规范化到同一 root 的 `JsonStateStore`、并通过上述受控入口写同一 `session_id`。直接调用 `save_case_session()` 或 `_write()` 不会自动取得 Session 锁，不属于已验证保证。

锁不是数据库 CAS，也不跨进程。`save_case_session(state)` 没有 `expected_revision` 参数，只做临时文件写入、文件 `fsync` 和 `os.replace`。`save_cooperative_agent_state(..., expected_revision=...)` 会在写入前读取并检查 revision，但“读取—检查—替换”不是跨进程原子 CAS；它在受控单进程 Session 锁内才得到本轮证明的线程串行语义。

## 4. 提交状态与故障反馈

`MultiCaseActionReceipt.world_commit_status` 是内部编排状态：

| 状态 | 含义 | 判定依据 |
|---|---|---|
| `not_committed` | 确定没有提交此次 world 修改 | 请求上下文、规则、Action Contract 或 Engine 在保存前拒绝；receipt 默认状态且不携带事件 |
| `committed` | world 保存调用已成功返回 | world-first 保存完成；即使后续 Memory、索引、Campaign、Agent State 或 Reflection pending/失败，也不能把行动描述为未执行 |
| `unknown` | 保存调用抛错，缺少 durable world commit receipt，无法判断 `os.replace` 是否已发生 | 返回 `world_commit_uncertain`；不得改写为确定成功或“状态未改变” |

主要后提交反馈如下：

| 阶段 | 当前反馈 | 是否撤销 world |
|---|---|---|
| 普通 Memory 投影 | `memory_commit_status="projection_pending"`，错误通常为 `memory_projection_failed` 或存储错误码 | 否；可从 committed Session reconciliation |
| Memory 索引 | `memory_commit_status="index_pending"` / `memory_index_failed` | 否；索引是可重建派生层 |
| Campaign | `campaign_status=PENDING` / `campaign_projection_pending` | 否；仅完成 Episode 触发，可从完成 Session 对账 |
| Observation 重读 | `CooperativePostCommitError("observation_reload")`；Clinic 映射 `operation_committed_followup_incomplete` | 否；协作 History 写 `committed_observation_reload_failed` |
| PlanEvaluator | `CooperativePostCommitError("plan_evaluator")`；Clinic 映射同上 | 否；协作 History 写 `committed_plan_evaluator_failed` |
| Agent State | 协作结果保持 `ACTION_EXECUTED`，`error_code="agent_state_projection_pending"` | 否 |
| Reflection | `FAILED_SAFE` / `reflection_runtime_failed_safe` | 否 |
| cooperative completed result 写入 | `operation_recovery_uncertain`，History 尝试记录 `completion_write_failed` | 否；禁止自动重放 |

这些状态的持久性不同：

- world JSON、Memory/Reflection 自身 SQLite receipt、Campaign JSON 和 cooperative History 是持久存储；
- `MultiCaseActionReceipt`、普通页面 `_ORDINARY_OPERATION_RECEIPTS` 和直接 MultiCase `_ACTION_RECEIPTS` 仅在进程内；
- cooperative History 持久保存 operation fingerprint、`started/prepared/completed/failed_before_reply/recovery_required`、失败码和 completed result，因此协作入口能在重建服务后重放已完成结果或阻断危险重试；
- `world_commit_status` 本身没有作为所有入口统一的 durable receipt 持久化。

## 5. 入口保证对照

| 入口 | operation 身份 | 同进程重复 / payload 冲突 | 持久 receipt / recovery | 重启后识别 | unknown 时行为 |
|---|---|---|---|---|---|
| 普通页面行动 | `ClinicActionInput.operation_id` | 相同 ID + 相同请求返回进程内 receipt；同 ID + 不同 payload 为 `operation_payload_conflict` | 无；普通 receipt 仅内存 | 不能可靠识别同一 operation | 返回 `world_commit_uncertain`；当前进程内缓存阻止同请求再次执行，重启后无此保证 |
| 协作入口（recording 启用） | player/case/session/operation + 稳定请求 fingerprint | 活跃重复为 `operation_in_progress`；payload 冲突被拒绝；completed 返回持久结果 | SQLite cooperative History；未知或已提交后链失败进入 `recovery_required` | 能重放 completed；能阻断 started/prepared/recovery_required；不能自动完成恢复 | `operation_recovery_uncertain` 或 `operation_committed_followup_incomplete`，不重放模型或 Tool |
| 协作入口（recording 关闭） | contribution ID，但无 durable ledger | Runtime/MultiCase 仍有同进程锁与精确请求 cache；不具备完整协作 replay 语义 | 无 | 不能 | 只能依赖进程内边界；不应当作 production recording 保证 |
| 直接 MultiCase | `AgentAction.action_id` + 完整序列化请求共同组成 cache key | 完全相同请求返回内存 receipt；为兼容既有调用，相同 action ID + 不同 payload 不在此层声明冲突 | 无 | 不能 | 返回 receipt `unknown/world_commit_uncertain` 并在当前进程缓存该精确请求 |
| MCP | 无请求级 operation ID；内部 action ID 只是按 Tool 名生成 | 无请求级幂等或 payload conflict 保证 | 无 | 不能 | 返回 `world_commit_uncertain`；调用方不得盲目重发写请求 |

协作入口的 SQLite 保护不能推广到普通、MultiCase 或 MCP。反过来，MultiCase 的进程内 cache 也不能描述为 durable receipt。

## 6. 恢复与重试边界

`recovery_required` 的当前作用是**保守阻断**：它告诉后续请求“该 operation 不可安全重演”，不表示系统已经自动补齐 Observation、PlanEvaluator、Agent State、Reflection 或公开回复，也不表示最终一致性已经达成。

当前重试规则：

- 对 `not_committed` 的确定性拒绝，可以修正请求并使用新的 operation ID；相同 operation 的语义由对应入口的 receipt 规则决定。
- 对 `committed` 但后续 pending/failed 的结果，不能重新执行 Tool；应使用现有 reconciliation 或未来的显式恢复流程处理派生状态。
- 对 `unknown`，不得自动重发写操作。普通入口跨重启、直接 MultiCase 跨重启和 MCP 都缺少可靠请求归因。
- 不得依据动作相似、目标相同、revision 恰好增加一次或最终 world 看似符合预期，推断某个 operation 已成功提交。
- 当前没有 provider/world exactly-once，也没有跨 world、Memory、Campaign、Agent State、Reflection、History 的 exactly-once。

故障注入中的“保存成功后抛异常”模拟调用方不确定，不等于真实进程崩溃；“重建服务”测试证明 SQLite/JSON 重新打开后的特定阻断行为，不证明断电、目录项持久性或任意指令点 crash recovery。

## 7. 验证证据

| 保证或边界 | 主要实现 | 代表性证据 |
|---|---|---|
| Session 锁键与进程内 `RLock` | [`storage/json_store.py`](../../src/xuanyi_npc/storage/json_store.py) | [`test_same_session_different_operations_are_serialized_without_lost_update`](../../tests/test_commit_consistency_faults.py) |
| world commit 三态与进程内 replay | [`application/multicase.py`](../../src/xuanyi_npc/application/multicase.py) | 保存后抛错、成功 replay 两项聚焦测试 |
| 普通入口 replay / payload conflict | [`application/clinic.py`](../../src/xuanyi_npc/application/clinic.py) | `test_ordinary_entry_replays_same_operation_and_rejects_payload_conflict` |
| 协作 durable replay / conservative recovery | [`storage/sqlite_cooperation.py`](../../src/xuanyi_npc/storage/sqlite_cooperation.py)、[`application/clinic.py`](../../src/xuanyi_npc/application/clinic.py) | 聚焦测试中的 known/unknown 重建服务场景；[`test_context_engineering_ce2a.py`](../../tests/test_context_engineering_ce2a.py) |
| Memory world-first 与 reconciliation | [`application/memory_coordination.py`](../../src/xuanyi_npc/application/memory_coordination.py) | Memory 异常聚焦测试；[`test_memory_coordination.py`](../../tests/test_memory_coordination.py) |
| post Observation / PlanEvaluator / Agent State / Reflection | [`application/cooperative_runtime.py`](../../src/xuanyi_npc/application/cooperative_runtime.py) | 聚焦测试、[`test_m2_cooperative_runtime_planning.py`](../../tests/test_m2_cooperative_runtime_planning.py)、[`test_m4_cooperative_runtime_reflection.py`](../../tests/test_m4_cooperative_runtime_reflection.py) |
| MCP unknown 反馈 | [`application/mcp_facade.py`](../../src/xuanyi_npc/application/mcp_facade.py) | [`test_mcp_p0.py`](../../tests/test_mcp_p0.py) |

[第一步审计报告](COMMIT_CONSISTENCY_FAILURE_SAFETY_AUDIT_STEP1.md)保留修复前反例、故障矩阵和当轮结论，不能用本主文档改写其历史口径。该报告记录：新增 8 项故障测试、当轮 665 项全量离线回归通过；这些数字只属于第一步审计轮次，本轮没有重跑。

后续交接信息另称“21 项相关测试通过”，但当前仓库未找到独立结果 artifact 或可引用报告。本主文档将其标为**交接报告结果**，不与 8 项或 665 项相加，也不把它记成本轮执行证据。

验证应优先阅读测试证明的行为：确定性交错没有丢更新、unknown 不重放、协作重建后仍阻断、已提交后的投影失败不回滚。测试数量本身不证明多进程、真实 crash 或跨存储原子性。

## 8. 剩余限制、风险排序与重新启动条件

当前风险排序：

1. **跨存储部分提交后的完整自动恢复尚未闭环。** 当前可标记 pending、对部分派生层做 reconciliation、或用 `recovery_required` 阻断，但不能自动恢复全部玩家意图、计划与公开回复。
2. **多进程或绕过受控入口时仍缺少原子并发保护。** Session `RLock` 不跨进程；Case Session 无 expected revision；Agent State revision 检查也不是数据库 CAS。
3. **单进程正常产品入口的线程并发已有覆盖。** 受控普通、协作、MultiCase 和 MCP 入口共享 Session 锁，因此它不再是首要未解决问题；这不扩大为“所有写路径绝对安全”。

风险排序不等于实施承诺。当前本地单进程产品接受明确降级、pending 状态和安全阻断，暂不建设 outbox、全局事务、通用自动恢复框架或存储迁移。

仅在出现以下需求时重新评估第二阶段：

- 进程重启后必须自动继续未完成 operation；
- 无人值守运行要求自动恢复而不能等待人工判断；
- 多个进程需要同时写入同一 state root/session；
- 对外承诺跨重启幂等，或客户端/网关会自动重试写请求。

