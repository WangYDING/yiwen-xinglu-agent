# 上下文工程 CE-2 详细设计：协作历史与当前待确认事项

> 当前模块总览与统一状态见[上下文工程模块主文档](../../architecture/CONTEXT_ENGINEERING_DESIGN.md)。本文保留 CE-2A/CE-2B 的详细设计演进，不作为当前状态的唯一入口。

状态（2026-09-25）：CE-2A 已按本文收紧后的边界实施；CE-2B 仍仅为设计，未实施。实施证据见 [`context_engineering_ce2a_implementation_report.md`](context_engineering_ce2a_implementation_report.md)。

CE-2A replay 顺序修补：记录模式必须在当前 pending 可用性检查之前，以完整 scope/operation 和稳定 payload 读取或建立 turn。completed/conflict/in-progress/recovery 状态先处理；只有新建的 operation 才检查当前 pending。详见 [`context_engineering_ce2a_replay_fix.md`](context_engineering_ce2a_replay_fix.md)。

状态：修订后的详细设计；CE-2A 已实施并完成有限修补，CE-2B 尚未实施。日期：2026-09-25。

本设计只覆盖同一玩家、案件、会话内的近期协作对话，以及当前有效待确认事项的公开上下文。它不设计意图识别、讨论回合规则、持续暂停/拒绝、自动摘要、持久行动排除、记忆检索调整或 Goal/Plan 语义变更。CE-1.1 与行动修复后的计划复核是已完成前置，见 [`context_engineering_ce11_implementation_report.md`](context_engineering_ce11_implementation_report.md) 和 [`action_contract_repair_plan_alignment_fix.md`](action_contract_repair_plan_alignment_fix.md)。

## 1. 阶段拆分与边界

CE-2 拆成两个可独立回滚的阶段：

- **CE-2A：协作历史与 pending 公开投影。** 持久化 completed 协作回合，给 A0/A1 注入近期完整回合；从现有进程内 pending 源读取“当前仍有效”的公开投影并注入。CE-2A 不改变 pending 的授权来源、领取/消费语义，也不声称 pending 可跨重启恢复。
- **CE-2B：durable pending 与授权消费。** 用 durable repository 取代 `ClinicService.cooperative_pending` 作为授权来源，引入原子 claim、消费/拒绝、重启恢复和不确定恢复状态。

拆分的依据是当前代码中历史上下文与授权并非同一安全边界：历史只是非权威输入；pending 会改变工具权限。CE-2A 可在不迁移授权的前提下交付上下文收益，CE-2B 必须单独接受故障注入与权限回归。两阶段可以共用 SQLite repository，但 SQLite transaction 只覆盖该 repository 内的 turn/pending 行，绝不等同于与 JSON 世界状态或 Agent state 的跨存储原子事务。

三个概念必须始终分开：

1. **上下文注入**：决定模型看到什么，不授予权限。
2. **协作历史持久化**：记录应用已确定的公开回复，不能成为事实或授权。
3. **授权持久化**：保存 pending 状态并由确定性权限层消费，模型文本不能创建或恢复授权。

## 2. 已核对的当前实现事实

- `ClinicService.cooperative_pending` 是进程内 `dict[confirmation_id, PendingActionConfirmation]`；新 pending 只按 ID 加入，现有项不会被新提案自动替换。因此同一 session 可以同时保留多个 pending。案件 revision 改变后，旧项虽仍在 dict 中，但 Runtime 的 scope/decision/revision 校验使其不能授权。
- Clinic 收到带 pending ID 的协作请求后，在 Runtime 返回后移除该项；当前代码没有 durable claim，也没有进程重启恢复。
- Runtime 目前只把一个已匹配 pending 的 **decision ID** 写入名为 `pending_confirmation_id` 的 Agent 输入；这不是完整 pending 投影。
- `CaseDialogueStore` 保存的是玩家与患者/证人等案中人物聊天，角色、事实来源和生命周期不同，不能复用为协作历史。
- `JsonStateStore.save_case_session()` 是原子替换，但没有 case-session expected-revision CAS。`save_cooperative_agent_state()` 的 revision 校验不能替代世界状态并发控制。
- 权威世界 mutation 不只来自协作 Runtime：`MultiCaseEpisodeService.submit_action[_with_receipt]` 可由 Clinic 的直接案件行动调用；`MCPApplicationService` 也会执行工具并直接保存 case session；`V1MemoryCoordinator.commit_engine_result()` 是另一条提交包装路径。`start_episode()` 还会创建 session。当前没有覆盖这些入口的共享 session lock。
- `ActionRecord`/领域事件没有 durable `operation_id`，所以“revision 恰好 +1 且动作内容相似”不能证明提交属于某个协作 operation。

上述事实决定：CE-2 可以安全做到“不重放、不伪造”，但在增加权威 operation correlation 之前，不能把 crash 后的不确定操作自动恢复成正常完成。

## 3. 数据契约

### 3.1 Scope、版本与身份

所有记录和查询必须同时包含并重新校验：

```text
player_id + case_id + session_id
```

建议版本：

- `cooperative_turn_record_v1`
- `cooperative_conversation_projection_v1`
- `pending_confirmation_record_v1`（CE-2B）
- `pending_confirmation_view_v1`
- `cooperative_context_strategy_v2`

### 3.2 CooperativeTurnRecordV1

最小字段：

| 字段 | 约束 |
|---|---|
| `schema_version` | 固定为 `cooperative_turn_record_v1` |
| `operation_id` | 与 v1 `contribution_id` 相同；同 scope 唯一 |
| `player_id/case_id/session_id` | 完整隔离键 |
| `turn_sequence` | repository 在 session 内分配的单调序号 |
| `record_revision` | repository 行状态版本 |
| `lifecycle_status` | `started`、`prepared`、`completed`、`failed_before_reply`、`recovery_required` |
| `contribution` | type、原始 `public_text`、decision/confirmation 引用、created_at |
| `case_revision_before` / `agent_state_revision_before` | 诊断与恢复引用，不是授权 |
| `prepared_decision` | decision ID、公开 dialogue/rationale、canonical action fingerprint |
| `completed_result` | 应用层最终确定的版本化 replay snapshot |
| `case_revision_after` / `event_sequences` | 完成后的权威引用 |
| `pending_refs` | 本轮创建、响应或失效的 ID 引用 |
| `started_at/completed_at/failure_code` | 生命周期审计 |

`prepared_decision` 不表示回复已经对外返回。只有 `completed` 且存在 `completed_result` 的记录能投影为历史 assistant reply。“实际对外回复”指 `ClinicService` 已确定并准备返回给调用方的结果；应用无法证明 HTTP 客户端实际收到。

### 3.3 历史消息投影

每个 completed record 只投影一对消息，角色由服务端赋值：

```json
{"source":"historical_player_contribution","schema_version":"cooperative_conversation_projection_v1","operation_id":"...","contribution_type":"question","public_text":"玩家原文"}
```

```json
{"source":"historical_npc_reply_non_authoritative","schema_version":"cooperative_conversation_projection_v1","operation_id":"...","decision_id":"...","historical_turn_status":"responded","public_text":"实际返回的 NPC 回复"}
```

原文只做 JSON 转义，不摘要、不改写、不按意图筛选。历史中的“计划”“已确认”“已经执行”等说法始终是非权威回放，不能覆盖当前 CaseObservation、Goal/Plan 或 pending repository。

### 3.4 PendingConfirmationViewV1

CE-2A 和 CE-2B 使用相同公开 view：

- `confirmation_id`、`decision_id`、scope；
- `authority_mode`；
- 当前公开 `tool_name` 与公开 arguments；
- `public_rationale`、`case_revision`、`created_operation_id`；
- `status`（注入正常请求时只允许 `active`，正在响应项可显式标为 `claimed_approval` 或 `claimed_rejection`）；
- `responding_to_this_item`，只由当前请求显式提供且 exact confirmation/decision/scope/revision 匹配产生。

固定说明必须指出：view 是公开待确认事项，不是授权。CE-2A 的来源仍是进程内 dict；CE-2B 的来源才是 durable record。任何阶段都不能从对话文本或 completed result 重建 pending。

### 3.5 PendingConfirmationRecordV1（CE-2B）

字段包括 view 所需公开字段、canonical action fingerprint、`created_turn_sequence`、`created_operation_id`、`resolved_operation_id`、`record_revision`、时间戳和状态：

```text
active
  -> claimed_approval -> consumed | execution_failed | recovery_required
  -> claimed_rejection -> rejected
  -> invalidated_revision
```

不得定义“新提案自动 supersede 旧提案”。repository 的 `list_valid_pending()` 返回同 scope、当前 revision 下的全部 active 项，按创建序号和 confirmation ID 稳定排序。若案件 revision 变化，所有 revision 不匹配项分别转为 `invalidated_revision`。

## 4. Repository 与接口

新增独立 `CooperativeConversationRepository`，推荐使用标准库 SQLite，放在 runtime state root 下；不要塞进 `SQLiteMemoryRepository`，也不要复用 `CaseDialogueStore`。

CE-2A 需要：

```text
begin_turn(contribution, case_revision_before, agent_revision_before)
get_turn(scope, operation_id)
mark_prepared(scope, operation_id, prepared_decision, expected_record_revision)
complete_turn(scope, operation_id, completed_result, result_refs, expected_record_revision)
mark_failed_before_reply(...)
mark_recovery_required(...)
list_recent_completed(scope, before_turn_sequence, limit)
```

另定义只读 `PendingContextSource.list_valid_views(scope, current_case_revision)`：CE-2A 由当前进程内 dict 适配器实现；CE-2B 切换为 repository 实现。这样注入层不暗含授权迁移。

CE-2B 增加：

```text
create_pending(...)
list_valid_pending(scope, current_case_revision)
claim_pending(scope, confirmation_id, decision_id, operation_id,
              contribution_type, current_case_revision)
resolve_claim(scope, confirmation_id, operation_id, final_status)
invalidate_stale_pending(scope, current_case_revision)
```

`begin_turn` 对相同 scope/operation 返回既有记录；若文本、type 或 responds-to 引用不同，返回 `operation_payload_conflict`。SQLite 内可把 turn 与 pending 状态一起提交，但世界仍由 `JsonStateStore`/`CaseEngine` 提交，二者没有原子事务。

`responding_to_this_item` 的输入必须显式包含当前请求的 confirmation ID 和 decision ID；两者都匹配同一 pending，且 scope/revision 有效时才为 true。不能只比较 decision ID，也不能从历史文本推断任一 ID。该字段只影响公开上下文标记，不参与权限判定。

## 5. 写入、重复操作与恢复

CE-2A 另有一个**同进程操作执行归属表**，其键为 repository 身份与完整 scope/operation，值为稳定请求 fingerprint：

- 原请求仍在运行时，相同 payload 的重复请求返回 `operation_in_progress`；不同 payload 返回 `operation_payload_conflict`。重复请求不改原 turn 生命周期，也不启动第二次模型/工具调用。
- 已完成记录安全 replay。
- 当前进程没有执行归属、但 SQLite 留有 `started/prepared` 时，视为重启/中断遗留并转 `recovery_required`，不自动重放。

这个表不是跨进程锁，也不提供 world mutation exactly-once。多进程共享同一 state root 不在 CE-2A 保证范围内。

### 5.1 CE-2A 正常 turn

1. Clinic 校验 player/case/session ownership，读取当前 case/Agent revisions。
2. `begin_turn()`；completed 走 replay，payload 冲突直接拒绝，运行中/恢复状态按既有规则处理；这些分支不要求历史请求引用的 pending 仍存在。
3. 仅当 `begin_turn()` 新建 operation 后，校验请求引用的当前 pending；无效时写 `failed_before_reply`，不留伪 `started`。记录关闭时仍使用原先的先校验 pending 路径。
4. 读取早于当前 `turn_sequence` 的 completed 历史，并从 `PendingContextSource` 读取当前有效公开 views。
5. 构造一次不可变 context snapshot；首次请求和所有 repair 共用它。
6. 在任何可能执行工具前写 `prepared`。
7. Runtime 按现有规则执行、提案或拒绝。
8. 重读权威 revisions，写 `completed_result`；只有完成写成功的记录进入后续历史。
9. 返回与持久 snapshot 一致的结果。

若模型调用后、prepared 前失败，记录保持 `started`；同 operation 不再次调用模型，返回稳定 interrupted/recovery 错误。若 completed 写失败，不能把未保存的模型回复投影为历史。

### 5.2 工具成功但历史保存失败

世界提交优先，绝不为了补历史而重放工具。未完成 operation 标为 `recovery_required`；同 operation 重试只返回明确的 `operation_recovery_uncertain`，并提供刷新后的公开世界状态，不伪造原 NPC 回复或“正常完成”。

禁止使用以下推断把它升级为 completed：

- case revision 恰好增加一次；
- 最新 ActionRecord 的 type/reference/target 与 prepared fingerprint 相同；
- 进程内 receipt 曾存在但未 durable 保存。

这些信息不能证明 mutation 属于当前 operation。若未来要自动恢复正常结果，前置条件是把 durable `operation_id`（或等价 commit token）写入权威 action receipt/ActionRecord，并让**所有** mutation 入口执行唯一性校验。该工作单独列为 operation-correlation 存储演进，不在 CE-2A/2B 默认范围内。

### 5.3 锁的边界

仅在 `submit_player_contribution()` 外加 session lock 不足，因为直接 Clinic action、`MultiCaseEpisodeService.submit_action[_with_receipt]`、MCP application 保存以及 memory-coordinated commit 都能修改同一 case session。若实施单进程 session lock，它必须位于这些入口共享的 mutation/commit boundary；并覆盖 load-check-execute-save 整段。多进程共享 state root 仍不受保护。

锁可以减少并发，却不能替代 operation correlation，也不能把 SQLite 与 JSON 变成原子事务。因此 CE-2 的安全恢复基线仍是“不确定即不重放、不授权、不伪造完成”。

## 6. Pending claim、执行与消费（CE-2B）

消除“执行后领取”与“执行前领取”的歧义，统一时序如下：

1. 收到 approval/rejection 后，先校验 scope、confirmation ID、decision ID、status 与当前 case revision。
2. repository transaction 中将目标从 `active` 原子转为对应 claimed 状态，并绑定 `resolved_operation_id`；同一 pending 的第二个 operation 失败。
3. `claimed_rejection` 不授予工具，完成 turn 后转 `rejected`。
4. `claimed_approval` 连同 exact pending action 传给 Runtime 权限层；模型新生成的不同 action 不能借用该授权。
5. 工具权威提交成功且 turn 完成持久化后转 `consumed`；确定性工具拒绝转 `execution_failed`。为兼容当前“一次响应即移除”，两者都不回到 active。
6. claim 后出现无法确认是否调用/提交工具的崩溃或跨存储写失败，转 `recovery_required`。不得释放为 active，不得自动重放。

进程重启时：active 且 scope/revision 仍匹配的 durable pending 可恢复；claimed/recovery-required 项 fail-closed。旧存档中的进程内 pending 不存在 durable row，必须视为失效，不能从历史回复、query 参数或 decision ID 复活。

## 7. 注入策略

### 7.1 完整回合与超长历史

查询只选同 scope、`completed`、`turn_sequence < current` 且 operation 不等于当前项。按新到旧取完整 turn，再恢复为时间正序；一个 turn 的 user/assistant 必须同时进入或同时省略。

第一版预算：最多 3 个完整回合，历史 projection 的 message-content 总字符上限 12,000。该数字是精确字符限制，不是 token 数。

选择算法：

1. 从最新 completed turn 向旧扫描；
2. 下一个完整 turn 会超限时，省略该 turn 以及所有更旧 turn，保证已选内容是连续后缀；
3. 在当前 user context 加固定、小型 `history_omission` 标记，只含同 scope、当前 operation 之前的 completed turn 精确省略数量、原因与重述提示；不放摘要，也不把有限查询窗口数量冒充全部历史数量；
4. 如果最新 turn 单独超限，注入零个历史 turn 加 omission 标记，当前及后续请求仍可继续，不进入永久失败。

CE-2 不做意图识别，所以不能判断当前输入是否依赖被省略文本，也不能声称保留了完整语义。公开恢复路径是提示玩家在当前 contribution 中重述必要内容；安全决策不得依赖历史文本，权威状态与授权仍来自当前区块。

### 7.2 必需 pending 与容量

历史是可选上下文；当前有效 pending 是授权相关的必需公开上下文，不参与历史裁剪。所有 active 项和当前 claimed 响应项必须完整、稳定排序注入，不能只留最新。

若必需当前上下文无法满足 `PromptText`/provider 静态限制，返回 `required_context_too_large`，不调用模型、不执行工具。

**CE-2A 禁止为腾容量提前消费 rejection、删除 pending、只留最新项或改变现有移除时机。** 它没有 claimed 状态机；所有当前有效项必须保留。claimed-rejection/claim/consume 属于 CE-2B，只有 CE-2B 的 durable 状态迁移设计与权限回归另行验收后才可启用。approval 同样不能通过丢弃其他 active pending 来腾空间。

### 7.3 消息顺序与权威性

A0/A1 首次请求统一为：

```text
system prompt
历史 turn 1 user envelope
历史 turn 1 assistant envelope
...
当前 user context（当前权威状态、全部有效 pending、当前 contribution）
```

当前 contribution 不进入历史查询且只在当前 user context 出现一次。system 固定说明历史全部非权威；当前 CaseObservation、Goal/Plan、权限和 pending view 优先。CE-2 不把模型话语转成案件事实或长期记忆。

### 7.4 A0/A1 与 repair 对称性

- A0 首次请求：近期完整回合 + 全部 pending views + 既有 A0 当前字段。
- A1 首次请求：同一 history/pending snapshot + 既有 A1 Goal/Plan/memory/action-space 字段。
- A0/A1 格式修复：复用 `original.messages`，不重新读库。
- 行动契约修复：使用同一 snapshot 重建既有 **A0 request shape**，但保留 `origin_architecture`；不趁 CE-2 把它改成 A1 shape。

两种架构必须在同一 rollout 条件下获得协作历史和 pending；输出 schema、调用次数、A1 initial 2048、repair 默认 512 以及 fallback 上限不变。

## 8. Replay 与当前状态

completed operation 的重复提交返回 historical result snapshot，但 replay 本身不得再次执行模型、工具、pending create/claim/consume side effects。

尤其是旧 completed result 中曾包含 `pending_action` 时：

- repository 保存原始 historical result 供审计；
- 对外 replay 的“历史结果”与“当前可操作 pending”必须是两个字段/视图；
- 只有当前 pending source/repository 仍返回同一 active record 时，UI 才展示可确认控件；
- pending 已 consumed/rejected/invalidated/missing 时，replay 不重新插入 dict/表，不把历史 pending 标成 active。

若为保持旧返回类型而必须返回 `CooperativeTurnResult`，replay adapter 应清除其中过期 `pending_action`，另从当前 pending view 渲染 UI；禁止调用正常 turn 的“把 result.pending_action 加回 store”代码。

## 9. 兼容、fixture 与 rollout

- 新输入字段均可选且默认空；旧存档没有 turn rows 时返回空历史。
- `recent_messages` 和 legacy `pending_confirmation_id` 在迁移期保留，但 v2 builder 不把 decision ID 当完整 pending。
- CE-0 v1 永久保留为历史快照，不能覆盖成 CE-2 预期；CE-1 pre-change v1 仍是 CE-1.1 请求等价基线。
- CE-2 新建 `ce2_requests_v1`（或目录型版本），同时保存未启用 v2 时仍匹配 CE-1 基线的证明。
- 分离开关：实现名为 `cooperative_record_enabled`、`cooperative_context_v2_enabled`；CE-2B 未来才增加 durable pending authority 开关。合法组合是 `false/false`（旧行为）、`true/false`（只记录与幂等保护）、`true/true`（CE-2A）；`false/true` 启动即拒绝。记录模式不是“零行为影响”的 shadow-write：数据库不可用、重复 operation 或 payload 冲突会返回稳定错误。
- durable pending 一旦成为授权源，不得回退为进程内 dict；回滚时权限 fail-closed。context v2 可独立回滚，历史数据保留。

## 10. 验证矩阵

离线“正确注入”必须与后续真实模型“确实理解”分开。CE-2 不调用付费模型。

### CE-2A

- A0/A1 连续追问、玩家改口、拒绝后再讨论；历史完整成对且当前输入不重复。
- 同玩家跨 session、不同玩家同 case、不同 case 隔离。
- 旧存档空历史、进程重启恢复 completed history。
- 相同 operation completed replay 不调用模型/工具；不同 payload 冲突。
- started/prepared/completion-write failure；工具可能已成功时同 operation 不重放并返回 uncertain。
- 最新超长 turn 被完整省略并带 marker，后续请求仍可发起；不宣称理解省略内容。
- 多个进程内有效 pending 全部投影；revision 失效项不投影。
- adapter 边界检查 A0/A1 initial、两类 format repair、A0-shape action repair的角色、内容、顺序、schema、配置和调用次数。

### CE-2B

- 多 active pending 均保存/投影，不自动 supersede。
- approval/rejection 原子 claim；重复 claim、ownership/decision/revision mismatch 均 fail-closed。
- claim -> execute -> consumed、确定性失败 -> execution_failed、崩溃/写失败 -> recovery_required。
- 重启只恢复仍 active 且 revision 有效的 row；旧 in-memory pending 不复活。
- completed replay 不创建或复活 pending，历史 UI 与当前授权 UI 分离。
- 所有已知 mutation 入口的并发/锁测试；若 operation correlation 未实施，只验证 uncertain 路径，不能写“自动恢复成功”测试替代。

后续 CE-4 才用固定模型评估指代、改口和拒绝理解；离线构建测试只证明信息正确出现。

## 11. 完成标准、顺序与阻塞条件

### CE-2A 完成标准

- completed history 的来源、scope、幂等、重启和故障注入通过；
- 工具后的持久化失败不会重放或伪造正常完成；
- A0/A1 和 repair 获得设计规定的同一 snapshot；
- 完整回合裁剪与 omission marker 不造成永久失败；
- 当前 pending 公共投影完整，但授权来源和语义保持现状；
- CE-0/CE-1 fixtures 未改写。

### CE-2B 完成标准

- durable pending claim/consume/reject/restart 与多 pending 测试通过；
- replay 不复活授权；恢复不确定项不会重新授权或执行；
- 权限读取切换不存在双源窗口。

推荐实施顺序：

1. CE-2A domain/repository 与 fault-injection tests；
2. shadow-write turn lifecycle，接 completed replay，但不注入；
3. 接 immutable history/pending view snapshot 与 v2 assembler；
4. 完成 CE-2A 全量离线回归并停点；
5. CE-2B pending tables/claim state machine，先 shadow compare；
6. 切换 durable authority，做重启/并发/故障回归；
7. 若需要“自动恢复正常结果”，另行实施 authoritative operation correlation 后再开放，不能用启发式替代。

当前**不阻塞 CE-2A**的限制：没有跨存储事务、没有 operation correlation；它们要求 uncertain fail-closed。**CE-2B 的授权持久化可以在相同保守恢复规则下实施**，但自动恢复成功、跨进程并发支持以及 exactly-once world mutation 仍被 operation correlation/CAS 阻塞。

## 12. 明确不在本阶段

- 新意图识别或讨论回合规则；
- 持久行动排除、自动摘要、统一 token 预算或动态裁剪；
- Memory 检索/写入调整；
- 改正 A1 repair 512 上限或把 action repair 改成 A1 shape；
- 多进程共享 state root 的严格 exactly-once；
- 以旧历史回复恢复 pending 或事实。

这些依赖若未来需要，必须另立设计和基线，不能在 CE-2 实施中顺带扩大。
