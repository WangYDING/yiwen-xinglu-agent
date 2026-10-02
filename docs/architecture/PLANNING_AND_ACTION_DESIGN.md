# Planning 与行动契约模块主文档

> 状态：当前实现说明。本文统一描述 Goal/Plan、模型输出契约、公开行动空间、Plan—Decision 对齐、Authority、修复与计划评估。

## 1. 模块定位与当前状态

本模块把模型的自由判断约束为“可解释但不可越权的候选行动”。Agent 可以创建、保持、修订、阻塞或放弃 Goal/Plan，并在公开行动空间中选择行动；确定性策略验证结构、一致性和权限，最终由案件引擎执行。

P0–P5 修复链已进入当前实现：有限 structured repair 与 safe fallback、诊断/处置公开 action surface、Plan/Decision 对齐、修复后二次对齐和可执行步骤承诺均已实现。它们是逐步暴露和修复同一行为链的历史，不是六个可相加的独立效果实验。

## 2. 核心领域对象

[`domain/cooperative_planning.py`](../../src/xuanyi_npc/domain/cooperative_planning.py) 定义：

- `AgentGoalState`：目标类型、状态、完成条件和 revision；
- `AgentPlan`：有序步骤、当前步骤、状态和版本；
- `PlanStep`：intent、capability、公开 target、建议 Tool、完成信号和状态；
- `PlanEvaluation`：保持、修订、完成或放弃的结果与原因；
- `CooperativeAgentState`：当前 Goal、Plan、最后评估及 Agent revision。

模型侧 draft/schema 位于 [`domain/planning_contract.py`](../../src/xuanyi_npc/domain/planning_contract.py)。持久 Plan 是意图与顺序，不是授权令牌。

## 3. 决策与验证链

```mermaid
flowchart LR
  Obs[Public Observation] --> Surface[Public Action Projection]
  Surface --> Request[GameNPCAgent request]
  Request --> Proposal[Goal/Plan + Decision]
  Proposal --> Schema[Schema / bounded repair]
  Schema --> Policy[GoalPlanPolicy]
  Policy --> Align[Plan—Decision alignment]
  Align --> Contract[PublicActionContract]
  Contract --> Repair[bounded action repair]
  Repair --> FinalAlign[final Plan alignment]
  FinalAlign --> Authority[NPCAuthorityPolicy]
  Authority --> Tool[bounded Tool / CaseEngine]
  Tool --> Evaluate[DeterministicPlanEvaluator]
```

顺序很重要：格式正确不代表行动合法；公开 action 合法不代表与当前计划一致；与计划一致也不代表已经得到高风险授权。

## 4. 公开行动空间

[`application/action_contract.py`](../../src/xuanyi_npc/application/action_contract.py) 从当前 Observation 投影：

- 可执行调查及其精确 Tool/arguments；
- 当前公开诊断候选及 `submit_diagnosis` 调用形状；
- 当前公开处置及 `execute_treatment` 调用形状。

投影不携带候选正确性、隐藏线索或结局。Validator 拒绝未知 Tool、未知 target、多余/缺失参数、重复或当前不可用行动。修复反馈只公开允许的 shape 和候选，不泄露正确答案。

## 5. Goal/Plan 策略

[`GoalPlanPolicy`](../../src/xuanyi_npc/application/goal_plan_policy.py) 验证：

- Goal 是否适合当前调查/诊断/处置阶段；
- Goal/Plan 更新操作是否允许，terminal/blocked Goal 是否被非法保持；
- PlanStep 的 intent、Tool、target 和 capability 是否结构一致；
- 诊断/处置的同回合 PlanStep 与 Decision 是否使用相同 Tool 和公开 target；
- 已持久化的可执行 active step 是否被 plain `RESPOND` 无限拖延。

对可执行步骤，合法选择是执行匹配 Tool，或显式修订/放弃 Plan，或阻塞/放弃 Goal；Runtime 不替模型选择动作。

## 6. 修复与 fallback

[`GameNPCAgent`](../../src/xuanyi_npc/agents/game_npc.py) 要求结构化 proposal。初始格式/规划契约失败可进行一次有限修复；行动契约失败走专门的有限修复，沿用 A0 request shape。失败后返回安全 `RESPOND`/拒绝，不执行 Tool。

关键边界：

- A1 initial 与 format repair 显式使用 2048；A0 initial/format repair 和 A0-shape action-contract repair 显式使用 512；
- 修复不是循环重试，也不自动提高调用上限；
- initial 与 repair 都在发送前执行最终 provider payload 的 tokenizer-aware 预算；完整 Schema、framing 估算、输出预留和安全余量均参与计算，History/Memory 可确定性裁剪，必选内容超限则安全停止；
- 行动契约修复可能替换最终 action，因此 Runtime 在修复后重新执行 Plan 对齐；
- fallback 是安全退化，不是成功行动，也不能被统计为模型遵循契约。

## 7. Authority 与确认

[`NPCAuthorityPolicy`](../../src/xuanyi_npc/application/npc_authority.py) 依据能力和 action 分类：

| 行动 | 当前模式 |
|---|---|
| 公开范围内普通调查 | `AUTONOMOUS` |
| 诊断提交 | `PROPOSAL_ONLY`，需要玩家协商/确认 |
| 高风险或不可逆处置 | `CONFIRMATION_REQUIRED` |
| 越权、结构不合法或上下文不一致 | `FORBIDDEN` |

确认只对绑定的 pending action、decision、player、case、session 与 revision 有效；玩家文本不能被解释成任意 Tool 授权。

## 8. 计划评估与生命周期

[`DeterministicPlanEvaluator`](../../src/xuanyi_npc/application/plan_evaluator.py) 根据执行前后公开 Observation、Goal 条件、当前步骤和 Tool 结果决定：

- 完成当前步骤并推进；
- 保持计划；
- 因公开状态变化要求修订；
- 完成 Goal；
- 放弃不再兼容的计划。

已完成/已放弃 Goal 在下一回合进入 Agent 前会准备新的 active Goal；`BLOCKED` Goal 仍需显式 replace/abandon，不会被运行时悄悄绕过。

## 9. 故障与安全边界

- 任一 schema、policy、alignment、action contract 或 authority 拒绝都必须零 Tool、零世界事件。
- 主要拒绝分支通过 `CooperativeAgentState.last_decision_feedback` 保存固定公开分类，并在 Observation revision 未变化的下一轮一次性注入；它与 `PlanEvaluation` 分离，不泄露内部异常、不恢复授权。
- Plan、Memory、历史消息或 pending 公开描述均不能扩大权限。
- `CaseEngine` 仍会再次验证领域前置条件；上层通过不等于领域命令必然成功。
- structured output 仍需用 repair/fallback telemetry 和真实模型轨迹评估；统一 token 预算与 2048 repair 解决了请求边界问题，但不证明复杂 Proposal 的语义遵循率已经充分。
- A0/A1 的既有真实比较受 action interface 不对称和未完整执行影响，不能据此证明 Planning 因果收益。

## 10. 实现与验证证据

| 能力 | 实现 | 代表性验证/证据 |
|---|---|---|
| Goal/Plan 模型 | [`domain/cooperative_planning.py`](../../src/xuanyi_npc/domain/cooperative_planning.py) | [`test_m2_goal_plan_domain.py`](../../tests/test_m2_goal_plan_domain.py) |
| 模型可见规划契约 | [`domain/planning_contract.py`](../../src/xuanyi_npc/domain/planning_contract.py) | [`test_m2_planning_contract.py`](../../tests/test_m2_planning_contract.py) |
| 公开行动空间 | [`application/action_contract.py`](../../src/xuanyi_npc/application/action_contract.py) | [`test_m5_public_action_space.py`](../../tests/test_m5_public_action_space.py) |
| Plan/Decision 对齐 | [`application/goal_plan_policy.py`](../../src/xuanyi_npc/application/goal_plan_policy.py) | [`test_p2_plan_decision_alignment.py`](../../tests/test_p2_plan_decision_alignment.py) |
| 处置契约 | 同上与 `action_contract.py` | [`test_p4_treatment_action_contract.py`](../../tests/test_p4_treatment_action_contract.py) |
| Authority | [`application/npc_authority.py`](../../src/xuanyi_npc/application/npc_authority.py) | [`test_m1_npc_authority.py`](../../tests/test_m1_npc_authority.py) |
| 计划评估 | [`application/plan_evaluator.py`](../../src/xuanyi_npc/application/plan_evaluator.py) | [`test_m2_cooperative_runtime_planning.py`](../../tests/test_m2_cooperative_runtime_planning.py) |

这些测试证明契约和拒绝链；历史真实运行只支持各自冻结协议下的观察，不证明单一修复的独立因果效果。

## 11. 历史修复链

- [Planning 与行动契约历史目录](../archive/planning_and_action/README.md)：统一导航 P0–P5 审计、修复与 telemetry。

主文档描述当前合并后的契约；历史报告保留当轮失败、修改范围和验证身份。
