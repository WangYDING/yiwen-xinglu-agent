# 行动契约修复后的计划对齐修复记录

日期：2026-09-25。此项是独立 Runtime 行为修复，不属于 CE-1.1 请求审计等价变更。

## 1. 缺口确认

实际调用顺序为：A1 proposal 通过 `GoalPlanPolicy` -> Runtime 应用 Goal/Plan -> `_action_matches_plan()` -> `_resolve_contract()`。后者可能用 `repair_action_contract()` 替换 `GameNPCDecision.proposal.action`。修改前，最终 action 直接进入 authority/tool 分支，没有第二次 Plan 对齐。

现有 `GameNPCAgent._parse_turn()` 会提前验证公开行动契约，所以正常模型 A1 输出常在模型边界被挡住；但 Runtime 的 Agent 协议并不保证所有实现都做这层预校验，而且 Runtime 自己仍公开支持 action repair。这不是有效的执行前防护。

离线反例沿真实 `CooperativeRuntime.handle()` 构造：

1. 原 proposal 创建 active Plan，目标为 `ask_about_memory`；
2. 原 action 使用同一 tool/目标，且首个 argument value 正确，所以通过旧 `_action_matches_plan()`；同时添加一个多余 argument，因此被 `PublicActionContractValidator` 拒绝；
3. repair 返回另一项公开合法调查 `inspect_umbrella`；
4. 修改前结果为 `action_executed`，case revision 从 0 增至 1，action history 记录 `inspect_umbrella`，而 Plan 仍指向 `ask_about_memory`。

因此缺口已复现，不能归类为纯理论风险。

## 2. 修复

Runtime 在 `_resolve_contract()` 返回之后、memory trace 最终化和任何 authority/tool 执行之前，对 A1 的**最终 decision**重新生成 alignment telemetry 并调用 `_action_matches_plan()`。

- 不匹配：沿用既有 `action_outside_active_plan` 机制，写入 `ACTION_OUTSIDE_ACTIVE_PLAN` recovery evaluation、推进并保存 Agent state、拒绝 memory influence、返回 `ACTION_REJECTED/FORBIDDEN`；不调用工具，不推进世界 revision。对外 decision 被确定性改为 `RESPOND` 且明确“未执行”，避免 Clinic 的 `npc_reply` 显示被拒绝动作原先的执行口吻；原尝试仍由 alignment telemetry 审计。
- 匹配：继续原 authority/tool 路径。
- final action 是 fallback `RESPOND`：按既有规则返回，不被误拒绝。
- A0：只有 `turn_proposal is not None` 才做复核，因此无显式规划的 A0 行为不变。

没有自动改写 Plan，没有放宽公开行动契约，没有改变 Goal/Plan、权限、确认、工具提交语义。相关 post-repair 契约中，公开 action contract 已由 `_resolve_contract()` 二次验证；本次只补因 action 被替换而失效的 Plan 对齐，没有扩展到其他架构差异。

## 3. 回归证据

新增实际 Runtime 测试证明：

- 公开合法但与已应用 Plan 不同的 repaired action 返回 `action_outside_active_plan`，event sequences 为空，case revision/action history 不变；
- repaired action 仍匹配 active step 时正常执行，revision 增 1；
- repair 解析失败时返回安全 RESPOND fallback，不执行工具；
- 已做格式 repair 的 decision 跳过第三次模型调用并 fallback；
- A0 repair 为另一合法动作时仍正常执行，不受 Plan 复核影响。

请求边界测试同时确认该行为修复没有改变 A1 repair 的 A0 request shape、默认输出上限、schema 或调用次数。真实模型行为未评测，也不需要用模型实验来证明这个确定性执行前不变量。
