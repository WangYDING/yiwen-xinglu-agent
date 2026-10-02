# 提交一致性与失败安全审计：第一步

日期：2026-09-26。范围仅限写入同一 case session 的普通行动、协作行动、MCP 工具入口，以及它们的直接后提交链。本记录不宣称完整 crash recovery、outbox、跨文件事务或跨进程 CAS 已完成。

## 已核实的调用链与入口

实际主链为：Engine 产生纯结果 → JSON world 原子替换 → 普通 Memory 投影 → Memory 索引 → 重读 Observation → PlanEvaluator → Cooperative Agent State → Reflection → 协作 operation 结果落账。

入口差异如下：

| 入口 | world 写路径 | operation 依据 | 本轮保护范围 |
|---|---|---|---|
| 普通页面行动 `ClinicService.submit_case_action` | `MultiCaseEpisodeService.submit_action_with_receipt` | 页面 `operation_id`；结果仅进程内缓存 | 同进程、同 state root、同 session 串行；同进程相同 operation 精确重放、冲突 payload 拒绝 |
| 协作行动 `ClinicService.submit_player_contribution` | `CooperativeRuntime` → `MultiCaseEpisodeService` | SQLite cooperative turn ledger | 上述同进程 session 锁；完成结果可跨服务重建重放；未知或已提交但未完成会持久阻断同 operation |
| 直接 `MultiCaseEpisodeService` | 自身 | `AgentAction.action_id` + 完整请求，仅进程内缓存 | 同进程 session 串行和相同完整请求重放；兼容历史调用，不把相同 action ID、不同 payload 当作全局冲突 |
| MCP 工具 | `MCPApplicationService.execute_tool` 直接 Engine + JSON save | 无 operation ID | 仅同进程 session 串行；不能提供请求幂等或重启判断 |

锁是基于规范化 state root 与 session ID 的进程内 `RLock`。它覆盖 CooperativeRuntime 的读取、决策、world 提交与 Agent State 后处理，并允许嵌套进入 MultiCase 提交。它不是跨进程锁；JSON 的“先读 revision 再写”也不是 CAS。

## 故障注入结果

| 故障点 | world 状态 | 调用者反馈 | operation / recovery | 相同 operation 重试 |
|---|---|---|---|---|
| 规则、参数或 Engine 在保存前拒绝 | 确定未提交 | 原有稳定拒绝码 | 协作回合可记录为完成的拒绝；普通调用进程内缓存 receipt | 不再执行 Tool，返回原 receipt（适用有 operation 的入口） |
| `save_case_session` 在原子替换前或后抛异常 | 未持久 commit receipt，统一视为未知 | `world_commit_uncertain`；协作为 `operation_recovery_uncertain` | 协作写 `recovery_required/runtime_result_uncertain` | 同进程缓存阻断；协作重建服务后仍阻断；普通页面重启后不能可靠判断；MCP 无 ID |
| world 已保存，Memory 投影抛异常 | 确定已提交 | 成功结果 + `projection_pending/memory_projection_failed` | Memory 可用现有 reconciliation 重建 | Tool 不重放 |
| world 已保存，索引失败 | 确定已提交 | 成功结果 + `index_pending` | 已有 Memory/索引 reconciliation 负责后续补齐 | Tool 不重放 |
| world 已保存，Observation 重读失败 | 确定已提交、后续未完成 | `operation_committed_followup_incomplete` | 协作写 `recovery_required/committed_observation_reload_failed` | 重建服务后仍明确阻断，不重放 Tool |
| world 已保存，PlanEvaluator 失败 | 确定已提交、后续未完成 | 类型化 `CooperativePostCommitError(plan_evaluator)`；Clinic 映射为已提交后续未完成 | 协作记录 `committed_plan_evaluator_failed` | 不重放 Tool |
| world 已保存，Agent State 保存失败 | world 确定已提交；Agent 投影 pending | `ACTION_EXECUTED` + `agent_state_projection_pending` | 完整协作结果仍可落账 | 已完成 operation 重放结果，不重放 Tool |
| Reflection 失败 | world 与 Agent State 保持已提交 | `FAILED_SAFE/reflection_runtime_failed_safe` | Reflection 自身 lifecycle/receipt 机制保持独立 | 不改变 world 提交边界 |
| 同 session 两个不同 operation 受控交错 | 修复前可由两个 stale snapshot 各写 revision 1，后写静默覆盖前写；修复后 revision 2、两条 action history 均保留 | 两次均得到与各自提交一致的结果 | 进程内 session 锁 | 不发生静默覆盖 |

“保存成功后抛异常”只模拟调用方不确定，不等价于进程崩溃。重启结论使用了重建 `ClinicService` 和重新打开同一 SQLite/JSON 临时存储；没有据普通异常推断 crash recovery 已闭环。

## 修复前反例与修复后证据

- 修复前，Memory repository 抛非 `MemoryError` 时，world revision 与 action history 已增加，但 MultiCase 返回 `internal_error`，协作层继续按 `tool_succeeded=False` 处理。修复后返回成功且标记 `projection_pending`。
- 修复前，不同 operation 可同时从同一 revision 执行并各自替换 JSON，最后只剩一条 action。修复后受控调度得到 revision 2 和两条副作用记录。
- 修复前，JSON replace 后抛异常被表示为“状态未改变”；修复后为 `unknown`，同进程不重放。协作账本把未知状态持久化为 `recovery_required`，重建服务后继续阻断。
- 修复前，Observation/PlanEvaluator 的后提交异常统一落入“结果未知”。修复后在进程内已知 world 成功时明确区分为“已提交、后续未完成”，并把该事实写入协作 recovery record。
- 普通页面相同 operation 的成功重试现在复用原结果，payload 冲突被拒绝；不会再次调用 Tool。
- MCP 保存异常不再谎称状态未改变，但因协议没有 operation ID，只能报告未知，不能安全自动重试。

## 保留限制与第二步

需要第二步，但本轮停止在边界识别和安全阻断：

1. 普通页面 operation receipt 只在进程内。进程重启后，world action history 没有 operation ID，不能用动作相似、revision 或最终状态可靠归因；当前无法保守识别同一普通请求。
2. MCP 写入口没有 operation ID，无法实现幂等重试或对未知提交做请求级阻断。
3. 进程内 session 锁不保护两个服务进程；JSON revision 检查不是原子 CAS。跨进程并发仍可能覆盖。
4. `recovery_required` 只阻断危险重放，不会自动补 Observation、PlanEvaluator、Agent State 或 Reflection。Agent State 中的玩家目标和计划意图也不能假定可由 world 全量重建。
5. 多存储仍无全局事务。Memory reconciliation 和 Reflection receipt 只覆盖各自既有边界，不等于全链路 crash recovery。

第二步最小设计应提供 durable operation receipt（至少绑定 operation ID、请求指纹、session、预期/结果 revision、world commit 状态），让所有写入口先有统一请求身份；随后再决定使用原子 CAS/单写者、后提交 outbox 或显式恢复任务。不得用当前 world 的相似状态猜测某个 operation 已提交。

## 本轮测试

- 新增 `tests/test_commit_consistency_faults.py`：8 项，覆盖 Memory 非预期失败、保存后抛异常、相同 operation 重试、普通入口 payload 冲突、确定性交错、Observation 后提交失败及服务重建、未知提交及服务重建、PlanEvaluator 后提交失败。
- 复用回归：MultiCase、M1/M2/M3/M4 cooperative runtime、Reflection receipt、Phase A/B production wiring、CE-2A operation ledger、MCP application/stdio。
- Reflection 与 Agent State 的既有故障注入分别验证 `FAILED_SAFE` 和 `agent_state_projection_pending`；索引既有故障注入验证 `index_pending`。
- 全量离线回归：665 项全部通过；`compileall` 与 `git diff --check` 通过。

结论分类：

- 已由证据证明安全：单进程同 session 串行；协作 completed replay；Reflection 失败不回滚；Agent State/Memory index 的 pending 反馈。
- 已复现并修复：world 后 Memory 非预期异常误报；保存异常伪装确定未提交；Observation/PlanEvaluator 已提交状态不明确；单进程并发静默覆盖；同进程 operation 重放。
- 已复现但需后续恢复协议：普通入口重启后的 operation 归因、MCP 幂等、跨进程覆盖、后提交阶段自动恢复。
- 尚未验证：真实进程在各机器指令/文件系统时点崩溃、跨进程确定性交错、操作系统级断电与目录项持久性。
