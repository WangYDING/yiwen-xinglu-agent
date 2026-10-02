# Agent Planning 系统设计

> 面试口径：本文基于当前工作区的真实代码、测试和架构文档。全文严格区分：通用 Planning 理论、项目设计意图、当前代码实现、尚未实现能力。
>
> 核心结论：本项目有真实的、跨回合持久化的短视野 Planning，但没有独立 `Planner`、没有自动执行整份计划的 `PlanExecutor`，也没有独立自动 `Replanner`。A1 Agent 在一次结构化 LLM 调用中同时提出 Goal/Plan 更新与本轮 Decision；确定性 Runtime、Policy、Authority、Tool Executor 和 Evaluator 决定提案能否成为状态、能否执行以及如何推进。

## 0. 先给结论

本项目的 Planning 不是一个“先规划完整任务、再由 Executor 连续跑完”的开放式 Planner，而是一个**会话级、2～4 步、每回合只执行一步的受约束短计划**。程序先根据病例阶段创建 Episode Goal 和当前阶段 Goal；支持 A1 的 `GameNPCAgent.propose_turn()` 读取当前 Goal、已有 Plan、最近评价、Observation、Memory 和玩家贡献，在一次模型调用中提出 `goal_update + plan_update + decision`。提案经 `GoalPlanPolicy` 校验后，Runtime 才生成权威 ID、状态和 revision；随后只执行本回合 Action，重读 World Observation，再由 `DeterministicPlanEvaluator` 更新 Step、Plan 和 Goal。

必须同时说明当前边界：

- Plan 是真实持久状态，不是 Prompt 中的一段自然语言；但正常 Plan 生成没有独立 Planner 类，而是 Agent 决策的一部分。
- Plan 不含可直接执行的 `ToolCallRequest.arguments`，只保存意图、建议工具和公开目标；真正 Action 在同回合 Decision 中产生。
- Runtime 不会自动循环执行剩余步骤；一次用户请求最多推进一个 Step。
- Evaluator 能根据 Goal 完成条件、工具成败和下一步是否仍可执行来推进状态；但当前**没有读取 `PlanStep.completion_signal` 的语义**，成功工具或非工具 `RESPOND` 会直接完成当前 Step。
- `REVISE_PLAN` 只表示“下一轮需要修订”；新计划由下一轮 LLM 提出，程序不会立即自动重规划。

---

## 一、本项目为什么需要 Planning

### 1.1 如果没有 Planning

案件协作是多回合任务。没有显式 Goal/Plan 时，模型每轮只能围绕当前玩家输入和 Observation 选一个 Action，容易出现：调查目标反复改变、连续选择无关线索、已经承诺诊断却长期只回复、不知道当前走到哪一步、工具失败后继续重复旧动作。项目早期评测也出现过 diagnosis-ready 后持续 `RESPOND`、Action 与 active Step 不一致导致停滞等现象。

### 1.2 本项目中的 Planning 解决什么

1. 用 Episode Goal 和阶段 Goal 明确“完成病例”与“当前收证、诊断或治疗”的不同时间尺度。
2. 用 2～4 步 Plan 给多个回合提供连续方向，同时只暴露当前 active Step 给执行链。
3. 用 Plan/Decision 对齐和可执行步骤承诺，避免模型声称在执行一个计划、实际却做另一个 Action。
4. 用真实 World 结果和确定性 Evaluator 推进状态，避免让模型自己宣布完成。
5. 在环境变化或工具失败后把 Plan 标为 `needs_revision`，让下一轮基于反馈重新规划。

### 1.3 面试一句话版本

> 我的项目实现的是受约束的短视野 Planning：程序维护持久化 Goal 和 2～4 步 Plan，LLM 每轮提出 Plan 更新与当前 Action，Policy 校验一致性，Runtime 只执行 active Step 对应的一步，再根据真实 Observation 和执行结果确定性推进、完成或标记待修订。

---

## 二、项目是否真的存在 Planning

| 能力 | 是否存在 | 文件 | Class / Function |
|---|---:|---|---|
| Goal | 是 | [`cooperative_planning.py`](../../src/xuanyi_npc/domain/cooperative_planning.py) | `AgentGoalState`, `GoalCondition` |
| Plan | 是 | 同上 | `AgentPlan` |
| Plan Step | 是 | 同上 | `PlanStep` |
| 进度状态 | 是 | 同上 | `AgentPlanStatus`, `PlanStepStatus`, `current_step_index` |
| Planning proposal | 是 | [`planning_contract.py`](../../src/xuanyi_npc/domain/planning_contract.py) | `GameNPCTurnProposal`, `PlanDraft` |
| 独立 Planner | **否** | [`game_npc.py`](../../src/xuanyi_npc/agents/game_npc.py) | `GameNPCAgent.propose_turn()` 同时规划与决策 |
| 独立 Plan Executor | **否** | [`cooperative_runtime.py`](../../src/xuanyi_npc/application/cooperative_runtime.py) | `handle()` 编排当前 Action；Tool 由案件服务执行 |
| Plan Evaluator | 是 | [`plan_evaluator.py`](../../src/xuanyi_npc/application/plan_evaluator.py) | `DeterministicPlanEvaluator` |
| 独立 Replanner | **否** | Agent + Runtime | 下一轮 LLM 通过 `PlanUpdateKind.REVISE` 提案 |
| Plan 持久化 | 是 | [`json_store.py`](../../src/xuanyi_npc/storage/json_store.py) | `save/load_cooperative_agent_state()` |

因此最准确的描述是：**项目有 Planning 状态、Planning proposal、Policy 和 Evaluator，但没有独立 Planner/Executor/Replanner 服务。**

---

## 三、Goal 是什么

### 3.1 它是什么

`AgentGoalState` 是 Agent 的权威意图状态，不是世界事实，也不是自然语言待办列表。

| 字段 | 含义 | 修改者 |
|---|---|---|
| `goal_id` | 权威身份 | Runtime |
| `goal_type` | `resolve_case`、`gather_evidence`、`validate_hypothesis`、`form_diagnosis`、`select_treatment`、`discuss_risk` | 初始化规则或经 Policy 接受的 LLM draft |
| `public_description` | 可公开目标描述 | 规则或 LLM draft |
| `status` | `active/completed/blocked/abandoned` | Runtime/Evaluator；LLM只能提更新意图 |
| `priority` | 0～100 | 规则或 LLM draft |
| `evidence_requirements` | 目标证据要求 | LLM draft；当前 Evaluator 不逐项判定 |
| `completion_condition` | 确定性目标完成条件 | 规则或 LLM draft，Evaluator 判定 |
| `blocked_reason` | 有限阻塞原因 | 经 Policy 接受后由 Runtime 设置 |
| `source_contribution_id` | 来源玩家贡献 | Runtime |
| turn/revision 字段 | 生命周期与并发版本 | Runtime |

### 3.2 谁创建 Goal

- `episode_goal`：Runtime 固定创建 `RESOLVE_CASE + CASE_COMPLETED`，priority 100。
- 初始 `current_goal`：`_load_or_initialize()` 根据公开病例阶段确定性创建：有调查则 `GATHER_EVIDENCE`；可诊断阶段为 `FORM_DIAGNOSIS`；已提交诊断后为 `SELECT_TREATMENT`。
- 后续阶段 Goal：`_prepare_next_goal()` 在旧 Goal `completed/abandoned` 后根据最新 Observation 确定性创建。
- LLM：每轮可提 `KEEP/REPLACE/BLOCK/ABANDON`；`REPLACE` 只提供 `GoalDraft`，不能提供 ID、revision 或直接设置 `COMPLETED`。
- 用户：玩家贡献会进入 Context，可能影响 LLM 提议，但用户文本不能直接改 Goal。

### 3.3 Goal 什么时候结束

- `COMPLETED`：仅当 `DeterministicPlanEvaluator.condition_met()` 根据公开 Observation 判定 `completion_condition` 成立。
- `BLOCKED`：LLM 提议有限 `blocked_reason` 并通过 Policy，或病例已结束但当前 Goal 条件未满足。
- `ABANDONED`：LLM 提议并通过 Policy；之后 Runtime 可在下一回合准备阶段 Goal。

注意：`PLAYER_RISK_RESPONSE_RECEIVED` 虽在枚举中存在，但 `condition_met()` 没有实现对应分支，当前永远返回 false。

---

## 四、Plan 是什么

### 4.1 权威 Plan 数据结构

```json
{
  "plan_id": "plan_turn_001",
  "goal_id": "goal_session_1_1",
  "status": "active",
  "steps": [
    {
      "step_id": "plan_turn_001_r1_s0",
      "ordinal": 0,
      "intent": "investigate",
      "capability": "use_tool",
      "suggested_tool": "inspect_object",
      "public_target_id": "investigation_ink_stain",
      "public_summary": "检查公开的墨迹线索。",
      "expected_information": "object_trace",
      "completion_signal": {
        "condition_type": "investigation_completed",
        "reference_id": "investigation_ink_stain"
      },
      "status": "active"
    },
    {
      "step_id": "plan_turn_001_r1_s1",
      "ordinal": 1,
      "intent": "analyze_evidence",
      "capability": "explain",
      "suggested_tool": null,
      "public_target_id": null,
      "public_summary": "结合新线索分析证据关系。",
      "expected_information": "evidence_relation",
      "completion_signal": {"condition_type": "minimum_clue_count", "threshold": 3},
      "status": "pending"
    }
  ],
  "current_step_index": 0,
  "based_on_observation_revision": 4,
  "source_contribution_id": "turn_001",
  "created_turn_id": "turn_001",
  "updated_turn_id": "turn_001",
  "revision": 1
}
```

这是按真实 Schema 改写的示例，ID 和具体线索仅用于解释，不代表固定 fixture。

### 4.2 字段职责

| 字段 | 类型/约束 | 含义 | 谁修改 |
|---|---|---|---|
| `plan_id` | Identifier | 计划身份；revision 时沿用 | Runtime |
| `goal_id` | Identifier | 必须归属当前 Goal | Runtime |
| `status` | `active/needs_revision/completed/abandoned` | 整体生命周期 | Runtime/Evaluator |
| `steps` | 2～4 个 `PlanStep` | 有界未来候选步骤 | LLM draft，经 Runtime 权威化；fallback 也可生成安全步骤 |
| `current_step_index` | 0～3 | 当前步骤 | Runtime/Evaluator |
| `based_on_observation_revision` | 非负整数 | 计划所依据的世界版本 | Runtime/Evaluator |
| source/turn 字段 | Identifier | 来源与审计 | Runtime |
| `revision` | 从 1 递增 | Plan 状态版本 | Runtime/Evaluator |

Plan 的强约束包括：步骤必须连续编号且 ID 唯一；active Plan 恰好有一个 active Step，且必须位于 `current_step_index`；Plan 工具必须与 Goal 类型一致。

---

## 五、Goal、Plan、Step、Decision、Action 与 Result 的区别

| 概念 | 解决的问题 | 时间尺度 | 项目真实例子 |
|---|---|---|---|
| Goal | 当前阶段要达到什么可判定结果 | 多回合/阶段 | 收集至少 3 条公开线索 |
| Plan | 准备按什么短路径推进 Goal | 2～4 个未来步骤 | 检查对象 → 分析证据 → 与玩家讨论 |
| Plan Step | 当前或未来一步的意图与约束 | 一个或少数回合 | 检查公开 investigation ID |
| Decision | 本回合如何评价玩家贡献、以何能力行动 | 单回合 | 接受建议，并选择一个 Action |
| Action | 本回合唯一公开行为 | 单次 | `inspect_object(target)` 或 `RESPOND` |
| Execution Result | 环境实际接受/拒绝并产生了什么 | 执行后事实 | 工具成功、产生 clue、返回事件序号 |

为什么它们不能混为一谈：

- `Goal != Plan`：Goal 是可判定终点，Plan 是可修改路径；同一 Goal 可有多个 revision。
- `Plan != Action`：Plan Step 不含完整 Tool arguments，也不直接执行；Decision 才产生唯一 Action。
- `Action != Result`：Action 只是提议，仍可能被 Schema、Plan 对齐、Authority 或环境拒绝。
- `Plan != World State`：写着“调查线索”不代表线索已经获得，只有提交后的 Observation 是事实。

---

## 六、Plan 是谁生成的

### 6.1 正常路径

初始状态只有程序创建的 Goal，`current_plan=None`。A1 `GameNPCAgent.propose_turn()` 在一次 LLM 结构化输出中生成：

```text
GoalUpdateProposal
+ PlanUpdateProposal（CREATE/REVISE 时含 2～4 个 PlanStepDraft）
+ GameNPCDecisionProposal（恰好一个 Action）
+ 可选 MemoryUsageProposal
```

因此正常 Plan 是 **LLM 提议、程序接受并权威化** 的混合方案。

### 6.2 后续更新

- `KEEP`：继续已有 active Plan。
- `REVISE`：LLM 提交全新的 2～4 步 draft；Runtime 保留 `plan_id`、递增 revision、替换 steps、把新第一步置为 active。
- `ABANDON`：Runtime 将 active/pending steps 置为 obsolete，Plan 变 abandoned。
- 模型输出不可用：`_fallback_turn_proposal()` 可能保留安全非工具 Plan，或创建/修订为“核对证据 + 与玩家确认”的两步安全 Plan；若已有未确认的可执行承诺，则安全放弃 Goal/Plan，不执行工具。

### 6.3 程序控制在哪里

`GoalPlanPolicy` 检查阶段、公开引用、2～4 步、Goal/Tool 能力、Authority、重复调查、操作合法性和 Plan/Decision 对齐。`_apply_proposal()` 才创建权威 ID/status/revision。LLM 不能直接写 Store。

---

## 七、Plan 是否由 LLM 完全控制

| LLM 能否 | 结论 | 确定性限制 |
|---|---|---|
| 创建任意长度 Plan | 否 | Schema 限定 2～4 步 |
| 写任意 Tool/target | 否 | 必须在 Goal 可规划工具、公开 action space 与 Authority view 内 |
| 写 ToolCall 参数队列 | 否 | `PlanStepDraft` 没有 `ToolCallRequest/arguments` |
| 修改任意 Step 状态/ID/revision | 否 | draft 不暴露这些字段，Runtime 生成 |
| 跳过当前可执行 Step 并一直回复 | 否 | `GoalPlanPolicy._validate_executable_step_commitment()` 要求执行、revision、abandon 或 block |
| 自己宣布 Goal 完成 | 否 | `GoalUpdateKind` 没有 complete，完成由 Evaluator 判断 |
| 直接完成/推进 Step | 否 | Step 状态由 Runtime/Evaluator 改 |
| 替换/阻塞/放弃 Goal | 可提议 | 必须通过阶段和引用 Policy |
| 修订/放弃 Plan | 可提议 | 必须满足操作和一致性约束 |

这就是 Proposal 与 authoritative state 的边界。

---

## 八、Plan 的真实执行流程

```text
World Observation + persisted CooperativeAgentState
                    ↓
Runtime 校验旧 Plan 是否仍兼容，并准备阶段 Goal
                    ↓
Memory 检索 + Context Assembly
                    ↓
GameNPCAgent.propose_turn()
  → Goal update + Plan update + one Decision/Action
                    ↓
GoalPlanPolicy.validate()
                    ↓
Runtime._apply_proposal()：生成权威 Goal/Plan 状态
                    ↓
Action Contract + Plan Alignment + Authority
                    ↓
一次 RESPOND 或一次 Tool Execution
                    ↓
重读 post Observation（Tool 成功路径）
                    ↓
DeterministicPlanEvaluator.evaluate()
                    ↓
更新 Step / Plan / Goal / last_plan_evaluation
                    ↓
保存 CooperativeAgentState；下一请求再继续
```

| 阶段 | 输入 | 输出/状态修改 | 负责者 |
|---|---|---|---|
| 恢复 | session/player/case | Observation + Agent State | Runtime/Store |
| 预检查 | active Plan + Observation | 不兼容则 `needs_revision` | Runtime + Evaluator compatibility |
| 提案 | Context | Goal/Plan/Decision proposal | LLM Agent |
| 校验 | proposal + Observation + Authority | 接受或拒绝 | GoalPlanPolicy |
| 权威化 | 合法 draft | IDs/status/revision | Runtime |
| 执行 | 当前 Action | Tool result 或公开回复 | Authority + Case service |
| 评价 | pre/post Observation + success flag | transition | DeterministicPlanEvaluator |
| 保存 | 新 Agent State | JSON snapshot | JsonStateStore |

没有 `while plan_not_finished` 的内部循环。外层循环由后续用户请求驱动，一次 `handle()` 最多执行一个 Action。

---

## 九、Plan 与 Decision 的关系

| 维度 | Planning | Decision |
|---|---|---|
| 时间尺度 | 2～4 步、跨回合 | 当前回合 |
| 输入 | Goal、Plan、评价、Observation、Memory、玩家贡献 | 同一次 Context，并受 resulting active Step 约束 |
| 输出 | Goal/Plan 更新提案 | 对玩家贡献的评价、能力、唯一 Action、解释 |
| 更新频率 | 每轮都可 KEEP/CREATE/REVISE/ABANDON | 每轮产生一次 |
| 负责模块 | `propose_turn` + Policy + Runtime | `propose_turn` + Action Contract + Runtime |

### 面试追问：每轮重新规划，还是执行已有计划？

准确回答：**两者结合。** 每轮模型都必须显式给出 Plan update，但已有 active Plan 时通常 `KEEP` 并执行当前 active Step；只有评价、玩家输入或环境变化表明路径不再合适时才 `REVISE/ABANDON`。它不是每轮丢弃旧计划，也不是忽略新环境机械执行旧计划。

---

## 十、Plan 与 Action 的关系

```text
Active PlanStep（意图、建议 Tool、公开 target）
                    ↓
Decision 中的一个 Action Proposal
                    ↓
Plan alignment + Action Contract + Authority
                    ↓
Executor / RESPOND
```

Plan Step **不包含完整工具调用**：它只有 `suggested_tool` 和 `public_target_id`，不保存通用 `arguments`。真正的 ToolCall 在 Decision 的 Action 中。Runtime `_action_matches_plan()` 要求 Tool 名与 active Step 相同，且当前实现用 Action arguments 的第一个 value 与 `public_target_id` 比较；诊断/治疗还由 `GoalPlanPolicy._validate_tool_decision_alignment()` 做字段级同目标检查。

`RESPOND` 在 Runtime 对齐函数中总是返回 true，但已有可执行 active Step 时，Policy 会阻止 `KEEP + plain RESPOND`，除非正在等待确认，或模型明确 revision/abandon/block。

---

## 十一、Plan 如何判断完成

### 11.1 Goal 完成

由 `DeterministicPlanEvaluator.condition_met()` 对 post Observation 判定：最少线索数、调查/公开要求完成、可提交诊断、诊断已提交、治疗可用、病例完成。LLM 不能直接完成 Goal。

### 11.2 Step 完成——当前真实实现

- Tool Action 成功：当前 active Step 无条件变 `COMPLETED`。
- Tool Action 失败：当前 Step 变 `BLOCKED`，Plan 变 `NEEDS_REVISION`。
- 非工具 Step：Runtime 把 `RESPOND` 作为成功执行，pre/post Observation 相同，当前 Step 无条件完成。
- Goal 已满足时：Plan 变 `COMPLETED`，后续 active/pending Step 变 `OBSOLETE`。

关键事实：虽然 `PlanStep` 有 `completion_signal`，但 Evaluator 当前没有读取该字段。也没有核验 `expected_information` 是否真的得到；新 clue 数量只用于选择评价 reason，不决定当前 Step 是否完成。

### 11.3 为什么不让 LLM 自己说“完成了”

因为模型只能生成 Proposal，不能证明工具已执行或世界已变化。完成必须来自提交后的权威 Observation 和受控执行结果；否则模型可以幻觉完成、跳过确认或污染状态。当前架构在 Goal 层实现了这个原则，但 Step 层仍需要进一步把 `completion_signal` 接入 Evaluator。

---

## 十二、Plan Evaluation 机制

| 输入 | Evaluator 实际使用 | 输出 |
|---|---|---|
| pre/post `CaseObservation` | 是：Goal 条件、session status、新 clue、下一步兼容性 | `PlanEvaluationTransition` |
| 当前 Goal/Plan | 是 | 更新后的 Goal/Plan |
| `tool_succeeded` | 是 | Step completed 或 blocked |
| `executed_action` | **否，入口即丢弃** | 无动作语义判断 |
| `environment_message` | **否** | 无错误类型细分 |
| `event_sequences` | **否** | 无事件级判定 |
| `pending_confirmation` | **否** | 不影响评价 |
| `PlanStep.completion_signal` | **否** | 当前未验证 |

输出 outcome：

- `KEEP_PLAN`：完成当前步并激活下一步。
- `REVISE_PLAN`：当前失败/无剩余步/下一步不兼容，Plan 变 `needs_revision`。
- `COMPLETE_GOAL`：Goal 条件满足，Plan completed。
- `ABANDON_PLAN`：病例已经结束但当前 Goal 未满足，Goal blocked、Plan abandoned。

`PlanEvaluationReason` 枚举比当前实现更宽；`EXPECTED_EVIDENCE_MISSING`、`PLAYER_CONTRIBUTION_CHANGES_PRIORITY` 等不会由当前 Evaluator 产生。

---

## 十三、Plan 更新机制

| 触发 | 当前 Step | 后续 Step | Plan | Goal |
|---|---|---|---|---|
| 成功且下一步兼容 | completed | 下一步 active | active, index+1 | 保持 |
| 成功且 Goal 完成 | completed | obsolete | completed | completed |
| Tool 失败 | blocked | obsolete | needs_revision | 保持 active |
| 成功但无剩余步 | completed | 无 | needs_revision | 保持 active |
| 下一步与新 Observation 不兼容 | completed | obsolete | needs_revision | 保持 active |
| 病例结束但 Goal 未完成 | 依 success 结果 | obsolete | abandoned | blocked |
| LLM 合法 REVISE | 旧 steps 被当前 Plan 新 steps 替换 | 新第一步 active，其余 pending | active, revision+1 | 通常保持 |
| LLM ABANDON | active/pending → obsolete | obsolete | abandoned | 依 Goal update |

注意：Plan revision 会递增，但 Agent State 只保存当前 Plan 快照，旧 step 列表不会作为专门的不可变 Plan history 保留。

---

## 十四、Replanning

项目支持动态 Replanning，但方式是**跨回合、LLM 驱动、Policy 约束**，不是同步自动 Replanner。

触发信号包括：

- Tool 执行失败；
- 下一 Step 对最新 Observation 已不兼容；
- 本轮开始发现 active Step 已因环境变化失效；
- Plan 已走完但 Goal 尚未完成；
- 玩家新贡献改变方向；
- Action 与 active Plan 不一致，反馈 `action_outside_active_plan`。

实际流程：

```text
Evaluator/Runtime 标记 needs_revision 或写入公开反馈
                         ↓
保存到 CooperativeAgentState
                         ↓
下一轮进入 Context
                         ↓
LLM 提 PlanUpdateKind.REVISE + 新的 2～4 步 draft
                         ↓
Policy 接受后 Runtime 替换 steps
```

不存在“Evaluator 当场调用 Planner 自动生成新 Plan”，也不存在自动重试同一 Tool。

---

## 十五、Plan 失败处理

| 情况 | 真实行为 | 是否自动重试 |
|---|---|---:|
| Planning schema/Policy 失败 | fail-closed，返回安全 RESPOND，不执行工具 | 否；最多一次格式修复发生在模型边界 |
| Action 与 Plan 不一致 | 拒绝 Action，保存公开 feedback/evaluation；active Plan 保持权威 | 否 |
| Action Contract repair 后仍不一致 | 再次对齐校验并拒绝 | 否 |
| Authority forbidden | 不执行，保存 authority feedback；Plan 通常保持 | 否 |
| 需要用户确认 | 保存 Plan，返回 pending；不运行 Evaluator | 否，等下一请求携带有效批准 |
| Tool 返回失败 | 当前 Step blocked，剩余 obsolete，Plan needs_revision | 否，下一轮 revise |
| World commit 不确定 | 抛出 commit-uncertain，禁止危险 replay | 否 |
| post-commit Observation/Evaluator 失败 | 抛 `CooperativePostCommitError` | 无自动恢复；世界可能已提交 |
| Agent State 保存失败（World 已提交） | 返回 `agent_state_projection_pending` | 当前没有通用重建/对账器 |
| 用户拒绝 | 没有独立“拒绝 → Step 状态”规则；拒绝作为新玩家贡献影响下一轮 proposal | 否 |

用户确认对象目前由 Clinic 的进程内字典保存，不具备跨进程恢复能力；Plan 本身则已持久化。

---

## 十六、Plan 与 Memory 的关系

```text
长期 Memory repository
        ↓ 检索、scope/冲突/预算过滤
AgentMemoryContext（非权威）
        ↓ 注入 Planning Context
GameNPCTurnProposal
        ↓ 可声明 affected_plan + used_memory_ids
MemoryUsageTrace 审计 selected/declared/accepted
```

Memory 能影响 Plan，但不能直接修改 Plan：

- `memory_context` 与 Goal/Plan/Observation 一起进入 Planning Prompt。
- LLM 若声明 Memory 影响 Plan，必须引用本轮最终保留的 Memory ID，且 `plan_update` 不能是 `KEEP`。
- Runtime 只有在 Plan 确实变化时才把这类使用归因为 accepted。
- 冲突时 World/Authority/当前 Goal-Plan 约束优先，Memory 不能证明当前诊断、公开隐藏 target 或授予工具权限。

当前没有规则型“过去失败自动禁止相同 Plan”；这只能通过检索到的经验影响 LLM，效果仍需行为评测证明。

---

## 十七、Plan 与 World State 的关系

Plan 是 Agent 意图投影，World State 是事实源。同步原则是：

```text
Plan 提议调查 X
      ≠ X 已调查
Action 通过所有边界并提交 World
      ↓
Runtime 重读新的公开 Observation
      ↓
Evaluator 才更新 Step/Plan/Goal
```

World 先提交，Agent State 后投影。这样不会因 Plan 写着“诊断已提交”就污染病例事实。但这也产生提交窗口：World 已成功而 Agent State 保存失败时，会返回 `agent_state_projection_pending`，目前没有从 World 自动重建 Plan 的通用机制。

---

## 十八、Plan 与 Agent State 的关系

Plan 是 `CooperativeAgentState.current_plan` 的组成部分，不是单独 repository。

| 维度 | CooperativeAgentState | Plan State |
|---|---|---|
| 保存内容 | episode/current Goal、current Plan、last evaluation、feedback、revision | steps、current index、状态、基于的 Observation revision |
| 生命周期 | 一个 case session | 当前阶段 Goal 内；revision/terminal 后可被下一阶段清空 |
| 修改者 | Runtime/Evaluator | Runtime/Evaluator；LLM仅提 draft |
| 持久化 | JSON，按 session_id | 随 Agent State 一起持久化 |
| 是否世界事实 | 否，Agent 意图投影 | 否 |

把 Plan 放入 Agent State 的原因是它描述“这个 NPC 接下来打算怎样推进”，且必须和 current Goal、last evaluation、state revision 一致更新。

---

## 十九、Plan 持久化

- `JsonStateStore.save_cooperative_agent_state()` 将 Plan 随 Agent State 原子替换到 `cooperative_agents/{session_id}` 对应快照，并校验 session ownership 与 expected revision。
- 新 Store 实例可读回，因此正常进程重启后能恢复该 Session 的 Plan。
- Plan **不跨新的 Session 迁移**；跨 Session 经验由 Memory 负责。
- revision check 是读后校验加文件替换，不是数据库级跨进程原子 CAS；同一进程有 per-session 串行锁，但多进程并发仍有覆盖风险。
- World 与 Agent State 是两个存储提交，跨存储没有全局事务；World 成功后 Agent State 失败会留下 projection pending。

---

## 二十、Plan 与用户确认

诊断是 proposal-only，治疗需要 confirmation。流程是：

```text
active Step 指向 diagnosis/treatment
        ↓
Decision 产生匹配 Tool Action
        ↓
Authority 返回 proposal_pending / confirmation_required
        ↓
Plan 状态保存，但 Step 不推进，Evaluator 不运行
        ↓
玩家下一请求携带有效 approval 和 pending action
        ↓
模型再次给出相同 ToolCall → Authority 放行 → 执行 → Evaluate
```

Pending 时 `GoalPlanPolicy` 暂时允许 plain `RESPOND`，避免把等待玩家误判为模型拖延。批准必须匹配 player/case/session、decision ID、ToolCall 和 case revision。当前 pending confirmation 是进程内状态，重启后不可继续；这与 Plan 的 JSON 持久化能力不同。

---

## 二十一、Planning 与 Workflow 的区别

| | Workflow | Agent Planning |
|---|---|---|
| 路径 | 节点和迁移由代码预先定义 | LLM 根据 Goal/环境提出短步骤 |
| 可变性 | 固定或有限分支 | 每轮可 keep/revise/abandon |
| 决策主体 | 程序规则 | LLM 提议，程序约束 |
| 适合 | 权限、提交、恢复、安全顺序 | 调查路径、沟通顺序、证据分析策略 |

本项目是混合架构：

- **确定性 Workflow**：读取状态 → Context → Proposal → Policy → Contract → Authority → Execute → reload → Evaluate → save；病例阶段切换也由规则决定。
- **Agent Planning**：选择 Goal 是否调整、生成 2～4 个 Plan steps、决定保留还是修订、选择当前 Action。

因此不能说整个 Runtime graph 都是 Planning，也不能说项目只是固定 Workflow。

---

## 二十二、Planning 与 ReAct 的区别

ReAct 通常是 `Thought → Action → Observation` 的逐步循环；Planning 是 `Goal → Plan → Execute → Evaluate → Update`。本项目有二者的部分特征，但不是标准裸 ReAct：

- 类 ReAct：每回合根据公开 Observation 产生一个 Action，下回合再观察结果。
- Planning：显式持久 Goal/Plan/Step/evaluation，Action 必须对齐 active Step。
- 不同点：不保存或暴露自由文本 Thought，不让模型自行无限循环；Runtime 每请求最多一个 Action，执行和状态推进由确定性边界负责。

可称为“受约束的 interleaved planning-and-acting”，不要称为完整 ReAct scratchpad 实现。

---

## 二十三、Planning 与 Reflection 的区别

- Planning：面向未来，决定接下来做什么。
- Reflection：基于已发生公开经历提炼可能复用的 lesson。
- Memory：保存通过证据与写入策略的历史经验。

项目真实链路是：

```text
Committed Result → Reflection proposal → validated long-term Memory
                                           ↓ future retrieval
                              future Planning Context → new Plan proposal
```

Reflection 在执行后发生，不会在同一回合反向修改已经执行的 Plan；以后检索到的 Memory 才可能影响新 Plan。不存在一个独立 Reflection 节点直接触发 Replan。

---

## 二十四、Plan 代码级调用链

```text
CooperativeAgentRuntime.handle()
  ↓ _load_or_initialize()
  ↓ _mark_invalid_plan()
  ↓ _prepare_next_goal()
  ↓ _retrieve_memory_context()
  ↓ GameNPCAgent.propose_turn()
       ↓ ContextAssembler.build_planning_request()
       ↓ BoundedStructuredOutput.run()
       ↓ parse GameNPCTurnProposal
  ↓ GoalPlanPolicy.validate()
  ↓ _apply_proposal()
  ↓ _associate_decision() / _action_matches_plan()
  ↓ _resolve_contract()
  ↓ NPCAuthorityPolicy.evaluate()
  ↓ ClinicService.submit_action_with_receipt()（Tool path）
  ↓ _resume() 重读 post Observation
  ↓ DeterministicPlanEvaluator.evaluate()
  ↓ _advance_state_revision()
  ↓ JsonStateStore.save_cooperative_agent_state()
```

非工具 `RESPOND` 分支不会进入 CaseEngine，但若当前是 non-tool active Step，会直接调用 Evaluator 将该 Step 视为成功。Planning 不支持的 M1/manual Agent 只调用 `decide()`；Runtime 会初始化 Agent State，却不会凭空制造 Plan。

---

## 二十五、Plan 状态机

### 25.1 Step 状态

```text
创建：first → ACTIVE；others → PENDING

ACTIVE ──执行成功──> COMPLETED
ACTIVE ──工具失败──> BLOCKED
PENDING ──前一步成功且仍兼容──> ACTIVE
ACTIVE/PENDING ──Goal完成、Plan修订/放弃/失效──> OBSOLETE
```

没有 `FAILED` Step；执行失败用 `BLOCKED` 表达。

### 25.2 Plan 状态

```text
ACTIVE ──继续推进──> ACTIVE
ACTIVE ──失败/走完但Goal未完成/下一步失效──> NEEDS_REVISION
ACTIVE ──Goal完成──> COMPLETED
ACTIVE ──放弃或病例终止──> ABANDONED
NEEDS_REVISION ──下一轮合法 REVISE──> ACTIVE（同 plan_id，新 revision/steps）
```

### 25.3 Goal 状态

```text
ACTIVE → COMPLETED / BLOCKED / ABANDONED
COMPLETED 或 ABANDONED → 下一回合 Runtime 创建下一阶段 Goal
```

`BLOCKED` 不会被 `_prepare_next_goal()` 自动替换，需要新的合法 Goal update。

---

## 二十六、计划一致性约束

一致性至少有四层：

1. Pydantic Schema：2～4 步、字段封闭、状态形状。
2. `GoalPlanPolicy`：Goal 阶段、公开 target、工具/能力/权限、重复调查、Plan 操作合法性、可执行 Step 承诺。
3. Plan/Decision alignment：诊断/治疗的 first/current Step 与同回合 Tool/target 必须一致。
4. Runtime final alignment：初次检查后若 Action Contract repair 改了 Action，执行前再检查一次。

不一致时 Tool 不执行，Runtime 保存安全反馈。当前 active Plan 保持权威，下一轮模型必须与其对齐或先合法 revision。

---

## 二十七、Plan 安全边界

不能让 LLM 直接写 Plan 状态，因为它可能目标漂移、引用隐藏对象、把治疗当自主动作、跳过 active Step、伪造 revision，或自行宣布完成。

本项目的边界是：

```text
LLM untrusted Goal/Plan/Action Proposal
              ↓ strict schema
GoalPlanPolicy + Action Contract
              ↓ Plan alignment
Authority Policy
              ↓
World Executor
              ↓ authoritative Observation
DeterministicPlanEvaluator
              ↓
Runtime-owned IDs/status/revisions + Store
```

Prompt 只是行为指导；这些程序边界才是可测试、fail-closed 的控制面。

---

## 二十八、Plan 测试

本次核验运行了 10 个 Planning 专项测试文件，共 **80 tests passed**。

| 测试能力 | 是否存在 | 代表文件/验证 |
|---|---:|---|
| Goal/Plan Schema | 是 | `test_m2_goal_plan_domain.py`：长度、唯一 active、Goal 工具对齐 |
| Proposal 合同 | 是 | `test_m2_planning_contract.py`：公开 target、禁止权威字段、单 Action |
| 创建并执行一步 | 是 | `test_m2_cooperative_runtime_planning.py` |
| non-tool Step 推进 | 是 | 同上：`RESPOND` 解锁后续 Tool Step |
| Goal 完成 | 是 | 同上：确定性完成且同回合不启动下一 Goal |
| 失败/needs_revision | 是 | 同上：Evaluator 标记修订但不执行下一步 |
| Replan | 是 | 同上：下一回合由玩家贡献触发 Plan revision |
| 持久化/重启 | 是 | `test_m2_cooperative_state_store.py` |
| Plan/Decision 对齐 | 是 | `test_p2_plan_decision_alignment.py`, `test_p2a_alignment_telemetry.py` |
| 可执行 Step 承诺 | 是 | `test_p5_executable_step_commitment.py` |
| fallback | 是 | `test_e5_structured_fallback_policy.py` |
| Planning 输出预算 | 是 | `test_m5_planning_output_budget.py` |

测试证明合同与状态迁移按当前规则工作，不等于证明 LLM 在真实模型、长轨迹和复杂案件上总能生成高质量 Plan。

---

## 二十九、当前 Planning 系统风险

### 29.1 最大风险：Step 完成语义过粗

`completion_signal` 与 `expected_information` 被建模、进入提案，但 Evaluator 不读取它们。任何成功 Tool 都完成当前 Step，任何 non-tool `RESPOND` 也完成当前 Step。这可能出现“动作成功，但没有得到计划期望信息”仍推进，或“一句无关回复”完成讨论步骤。

### 29.2 其他真实风险

1. `PLAYER_RISK_RESPONSE_RECEIVED` 已声明但无 Evaluator 实现；用作 Goal 条件时无法完成。
2. `evidence_requirements` 被保存并校验引用，却不参与 Goal 完成判定。
3. Evaluator 丢弃 `executed_action/environment_message/event_sequences/pending_confirmation`，失败分类和步骤语义较弱。
4. Replanning 要等下一用户回合，`needs_revision` 后没有自动修订或恢复循环。
5. revision 会替换当前 steps，没有专门不可变 Plan revision history；审计主要依赖周边回合记录。
6. World 成功、Agent State 保存失败时只有 `agent_state_projection_pending`，没有通用 Plan 重建器。
7. Pending confirmation 仅进程内保存，重启后无法延续等待确认。
8. Store 的 revision check 不是数据库级跨进程原子 CAS。
9. `_action_matches_plan()` 对一般 Tool 取 arguments 的第一个 value 作为 target，依赖参数顺序；诊断/治疗另有更严格 Policy，但通用实现仍较脆弱。
10. 80 个测试主要验证结构与流程，不足以证明计划质量、任务成功率或 Memory 对 Planning 的因果提升。

优先改进顺序：先让 Step completion 依据 `completion_signal + expected_information + executed_action/result`，再补风险回应条件、post-commit Agent projection 对账和持久 pending，最后增加真实模型长轨迹评测。

---

## 三十、设计文档 vs 真实代码

| 能力 | 文档描述 | 实际代码 | 一致性 |
|---|---|---|---|
| Goal | 显式 Goal、程序控制完成 | `AgentGoalState` + deterministic `condition_met()` | 基本一致 |
| Plan | 2～4 步、可 create/keep/revise/abandon | Schema/Policy/Runtime 已实现 | 一致 |
| Step | 有 expected information 与 completion signal | 字段存在；Evaluator 不使用二者判断完成 | **不完全一致/易误解** |
| Evaluator | 根据前后 Observation、当前步骤、Tool 结果推进 | 用 Observation、Plan 位置和 success flag；丢弃 Action、message、events、pending | **文档表述偏强** |
| RESPOND 推进 | “根据公开回应推进” | 不检查回应内容，只要是 non-tool Step 就以 success=true 完成 | **不一致** |
| Replan | 图中写 `PlanEvaluator / Replan` | Evaluator 仅标 `needs_revision`；下一轮 LLM 才 revise，无独立 Replanner | **图容易误导** |
| Goal/Plan 操作 | 文档称可“创建、保持、修订、阻塞或放弃 Goal/Plan” | Goal 可 block；Plan 没有 block update，只有 needs_revision/abandon | 表述需拆开 |
| Progress | Step/Plan status + evaluation | 已实现，但 completion_signal 未执行 | 部分一致 |
| Persistence | 会话级恢复 | JSON Agent State 可跨进程恢复；pending confirmation 不持久 | Plan 一致，确认链路不完整 |

面试时应主动说明：“架构文档描述的是设计目标；代码当前已实现确定性 Goal 完成和粗粒度 Step 推进，但 Step completion signal 还没有真正接入 Evaluator。”

---

## 三十一、最终面试回答版

### 31.1 30 秒：“你的 Agent 有没有 Planning？”

> 有，但不是独立 Planner 自动跑完整计划。系统为每个病例 Session 持久化 Episode Goal、当前阶段 Goal 和 2～4 步短 Plan。A1 Agent 每轮在一次结构化调用中提出 Goal/Plan 更新与一个 Action；Policy 校验公开目标、权限和 Plan/Action 一致性，Runtime 只执行当前 active Step 对应的一步，再由真实 Observation 和确定性 Evaluator 推进、完成或标记 needs_revision。下一轮再 keep 或 revise，所以它是受约束的 interleaved planning-and-acting。

### 31.2 2 分钟完整回答

> 首先，Goal 和 Plan 分层。程序固定创建“完成病例”的 Episode Goal，并根据公开病例阶段创建收证、诊断或治疗的 current Goal；Goal 有明确 completion condition。Plan 是属于 current Goal 的 2～4 个候选 Step，保存 intent、capability、建议工具、公开 target 和状态。
>
> 正常 Plan 不是规则模板，也不是独立 Planner 生成，而是 `GameNPCAgent.propose_turn()` 在同一次 LLM 调用里连同本轮 Decision 一起提出。LLM 只能给 draft，不能写 ID、revision、Step status，也不能宣布 Goal 完成。`GoalPlanPolicy` 会检查阶段、公开引用、权限、工具能力、重复调查和 Plan/Decision 对齐；Runtime 接受后才把 draft 变成权威 Agent State。
>
> 执行时一次请求只处理一个 Action。Action 还要经过 Action Contract、Plan 对齐和 Authority。Tool 成功后先提交 World，再重读 Observation；`DeterministicPlanEvaluator` 根据 Goal 条件、工具成败和下一步是否仍可执行更新 Step、Plan 和 Goal。失败或环境失效会标成 `needs_revision`，下一轮模型看到评价后提交 `REVISE`。
>
> 这套设计让 LLM 负责策略候选，程序负责事实、权限和生命周期。当前限制是 Step 的 `completion_signal` 虽已建模，Evaluator 还没有真正校验，成功动作或 non-tool 回复会直接完成 Step；这也是下一步最重要的增强点。

### 31.3 “为什么不用每轮让 LLM 直接决定？”

> 单轮 Decision 只回答“现在做什么”，无法表达跨回合承诺、进度和失败后的路径变化。显式 Plan 让 active Step 约束 Action，让下一轮看到之前的意图和评价，也使测试能判断模型是在执行、修订还是逃避计划。与此同时我没有让 Plan 自动越过 Authority；它仍只是 Agent State 中的意图。

### 31.4 “Plan 是谁生成的？”

> 是混合生成。阶段 Goal 主要由程序根据 Observation 创建；正常 Plan steps 由 LLM 在 `propose_turn()` 中提出；Policy 决定能否接受，Runtime 生成 ID、状态和 revision。模型不可用时还有一个只含非工具步骤的安全 fallback，或放弃已有可执行承诺。

### 31.5 “Plan 完成怎么判断？”

> Goal 完成由确定性 Evaluator 对 post Observation 检查 completion condition，模型不能自报完成。Step 当前按执行成功标 completed，失败标 blocked；但我会主动说明现有限制：`completion_signal` 尚未接入 Step 判定，所以 Step 层比 Goal 层粗。

### 31.6 “Plan 失败怎么办？”

> 不自动重放工具。工具失败会把 active Step 标 blocked、后续 Step 标 obsolete、Plan 标 needs_revision，并把公开反馈带到下一轮；下一轮 LLM 必须提交合法 revision。提交结果不确定时直接阻止 replay，避免重复副作用。

### 31.7 “Planning 和 Workflow 有什么区别？”

> Workflow 是代码固定的控制链，比如 Policy、Authority、执行、重读和保存的顺序；Planning 是 LLM 围绕 Goal 动态提出哪些步骤和当前 Action。项目把两者结合：Planning 提供策略灵活性，Workflow 提供安全与一致性。

### 31.8 白板版

```text
[Observation + Agent State + Memory]
                ↓
[LLM: Goal/Plan update + one Decision]
                ↓
[Schema + GoalPlanPolicy + Alignment]
                ↓
[Authority]
                ↓
[One Action / Tool Execution]
                ↓
[Reload World Observation]
                ↓
[Deterministic Evaluator → Step/Plan/Goal update]
                ↓
[Persist Agent State; next request continues]
```

---

## 三十二、高频面试追问（32 题）

### Q1. 为什么说它真的有 Planning？

- 考察点：是否把 Prompt 话术当架构。
- 推荐回答：因为存在显式、跨回合持久化的 Goal/Plan/Step 状态、状态机、proposal contract、Plan/Action 一致性校验和执行后 Evaluator，而不只是模型说“我的计划是”。
- 代码依据：`AgentPlan`、`PlanStep`、`GameNPCTurnProposal`、`DeterministicPlanEvaluator`。

### Q2. 有独立 Planner 吗？

- 考察点：是否夸大模块。
- 推荐回答：没有。正常规划与本轮决策由 `GameNPCAgent.propose_turn()` 一次生成；独立的是 Policy 和 Evaluator。
- 代码依据：`game_npc.py::propose_turn()`。

### Q3. Goal 和 Plan 最大区别是什么？

- 考察点：目标与路径分层。
- 推荐回答：Goal 是可判定终点，Plan 是达到它的可替换路径；同一 Goal 可经历多个 Plan revision。
- 代码依据：`AgentGoalState.completion_condition`、`AgentPlan.goal_id/revision`。

### Q4. 为什么有 episode_goal 和 current_goal？

- 考察点：不同时间尺度。
- 推荐回答：episode_goal 始终是完成病例；current_goal 表示收证、诊断、治疗等当前阶段，完成后可切换。
- 代码依据：`_load_or_initialize()`, `_prepare_next_goal()`。

### Q5. 初始 Goal 是 LLM 生成的吗？

- 考察点：控制权。
- 推荐回答：不是，Runtime 根据公开病例阶段确定性创建；LLM 后续只能提更新。
- 代码依据：`_load_or_initialize()`。

### Q6. 初始 Plan 是谁生成的？

- 考察点：混合职责。
- 推荐回答：初始状态没有 Plan；A1 首轮 LLM 通常提出 CREATE，Policy 接受后 Runtime 权威化。模型不可用时可生成安全两步 fallback。
- 代码依据：`propose_turn()`, `_fallback_turn_proposal()`, `_apply_proposal()`。

### Q7. 为什么只允许 2～4 步？

- 考察点：bounded planning。
- 推荐回答：减少长计划在动态环境中过时，也限制输出复杂度和攻击面；每轮可以修订。
- 代码依据：`PlanDraft.steps` 与 `AgentPlan.steps` 的 min/max。

### Q8. Plan 是否包含完整 ToolCall？

- 考察点：意图与执行合同分离。
- 推荐回答：不包含，只保存建议 Tool 和公开 target；完整 arguments 在 Decision Action 中。
- 代码依据：`PlanStepDraft` 与 `GameNPCDecisionProposal`。

### Q9. 谁执行 Plan？

- 考察点：是否存在 Executor 幻觉。
- 推荐回答：没有独立 Plan Executor。Runtime 取本轮 Decision 的一个 Action，经边界后交给案件服务；剩余步骤等后续请求。
- 代码依据：`CooperativeAgentRuntime.handle()`。

### Q10. 一次请求会执行几个 Step？

- 考察点：循环边界。
- 推荐回答：最多一个；内部没有自动 plan loop。
- 代码依据：`handle()` 单 Action 分支。

### Q11. 每轮都会重做 Plan 吗？

- 考察点：Plan persistence。
- 推荐回答：每轮都输出 update，但已有 Plan 可 KEEP；只有需要改变时 REVISE/ABANDON。
- 代码依据：`PlanUpdateKind`。

### Q12. LLM 能宣布 Goal 完成吗？

- 考察点：事实权威。
- 推荐回答：不能，Goal update 没有 COMPLETE；Evaluator 读 Observation 判定。
- 代码依据：`GoalUpdateKind`, `condition_met()`。

### Q13. Step 怎么完成？

- 考察点：是否真正读过 Evaluator。
- 推荐回答：当前成功 Tool 或 non-tool RESPOND 会把 active Step 标 completed；这还没有按 `completion_signal` 做语义验证，是已知缺口。
- 代码依据：`evaluate()` lines 119–126；Runtime RESPOND 分支。

### Q14. Goal completion condition 支持哪些？

- 考察点：确定性条件。
- 推荐回答：线索阈值、调查/公开要求完成、诊断 ready/submitted、治疗可用、病例完成；风险回应枚举存在但未实现。
- 代码依据：`GoalConditionType`, `condition_met()`。

### Q15. Tool 失败后会自动重试吗？

- 考察点：副作用安全。
- 推荐回答：不会；Step blocked、Plan needs_revision，下一轮再规划。
- 代码依据：Evaluator `not tool_succeeded` 分支。

### Q16. Replanner 在哪里？

- 考察点：避免虚构组件。
- 推荐回答：没有独立 Replanner；Evaluator 给信号，下一轮同一个 LLM Agent 提 REVISE。
- 代码依据：`PlanEvaluationOutcome.REVISE_PLAN`, `PlanUpdateKind.REVISE`。

### Q17. 环境在两个回合间变化怎么办？

- 考察点：stale plan。
- 推荐回答：每轮开始 `_mark_invalid_plan()` 检查当前 Step 与最新 Observation；不兼容则 needs_revision、steps obsolete。
- 代码依据：`_mark_invalid_plan()` 与 `plan_compatible()`。

### Q18. Action 必须符合 Plan 吗？

- 考察点：一致性。
- 推荐回答：Tool Action 必须匹配 active Step 的 Tool/target；repair 后还会再验。RESPOND 有例外，但既有可执行 Step 不能被 plain RESPOND 无限拖延。
- 代码依据：`_action_matches_plan()`, `_validate_executable_step_commitment()`。

### Q19. 为什么 Plan 校验要在 Authority 前？

- 考察点：不同控制层。
- 推荐回答：先确认它是当前目标允许且内部一致的意图，再由 Authority 判断该 Action 是否可自主、需确认或禁止；两者解决不同问题。
- 代码依据：Runtime `handle()` 顺序。

### Q20. 诊断和治疗为什么仍不能因写入 Plan 就执行？

- 考察点：Plan 非授权。
- 推荐回答：Plan 只是意图。诊断保持 proposal-only，治疗必须确认，最终由 Authority 决定。
- 代码依据：`PlanStep.validate_tool_capability()`, `NPCAuthorityPolicy` 调用。

### Q21. 用户输入能直接改 Plan 吗？

- 考察点：Prompt injection。
- 推荐回答：不能；它是不可信 contribution，只能影响模型提案，仍需 Schema/Policy。
- 代码依据：M1/M2 system prompt 与 `GoalPlanPolicy`。

### Q22. Memory 能直接改 Plan 吗？

- 考察点：非权威记忆。
- 推荐回答：不能；Memory 只是 Context。模型可声明其影响，但要引用 selected ID 且 Plan 确实变化，Runtime 才接受归因。
- 代码依据：`_validate_memory_usage()`, `_accepted_memory_trace()`。

### Q23. Plan 是 World State 吗？

- 考察点：状态边界。
- 推荐回答：不是，是 Agent intent projection；只有 Case Observation 是世界事实。
- 代码依据：World 提交后重读 Observation 再 Evaluate。

### Q24. Plan 能跨重启恢复吗？

- 考察点：持久化。
- 推荐回答：同一 Session 可以，随 JSON Agent State 保存；新 Session 不继承 Plan。
- 代码依据：`save/load_cooperative_agent_state()`。

### Q25. 有并发保护吗？

- 考察点：一致性。
- 推荐回答：同进程 per-session 串行化，加 expected revision；但不是跨进程数据库原子 CAS。
- 代码依据：`_serialize_session`, `save_cooperative_agent_state()`。

### Q26. World 成功而 Plan 保存失败怎么办？

- 考察点：跨存储提交。
- 推荐回答：World 是权威，不回滚；返回 `agent_state_projection_pending`。当前缺少通用重建器，这是风险。
- 代码依据：Runtime post-commit save try/except。

### Q27. 用户确认期间 Plan 会怎样？

- 考察点：长事务/暂停。
- 推荐回答：Plan 保存、Step 不推进；批准请求必须匹配 pending 和 revision，实际执行后才 Evaluate。
- 代码依据：Authority pending 分支、`_validated_pending()`。

### Q28. Planning 和 ReAct 是什么关系？

- 考察点：范式辨识。
- 推荐回答：每回合 Action/Observation 类似 ReAct，但没有自由 Thought 或内部无限循环；显式 Plan 让它更接近受约束的 interleaved planning-and-acting。
- 代码依据：单回合 `handle()` 与持久 Plan。

### Q29. Planning 和 Workflow 怎么划分？

- 考察点：不要把确定性编排说成智能规划。
- 推荐回答：LLM 动态提出 steps 是 Planning；Policy→Authority→Execute→Evaluate 的顺序是固定 Workflow。
- 代码依据：`propose_turn()` 与 `handle()`。

### Q30. Reflection 会立即改 Plan 吗？

- 考察点：时序。
- 推荐回答：不会。Reflection 在结果后写候选经验，未来检索才可能影响新 Plan。
- 代码依据：Runtime `_attach_reflection()` 位于结果路径末尾。

### Q31. 当前最大 Planning 缺陷是什么？

- 考察点：工程诚实度。
- 推荐回答：Step completion 还只基于 success flag/RESPOND，不验证 `completion_signal`、期望信息和动作结果语义，可能过早推进。
- 代码依据：Evaluator 丢弃 action 等输入且未访问 `completion_signal`。

### Q32. 如何改进而不让系统失控？

- 考察点：演进方案。
- 推荐回答：先为每种 `GoalConditionType` 建确定性 Step predicate，并把 Tool receipt/event/Observation delta 映射到它；无法证明时保持 active 或 needs_revision，而不是交给 LLM 自证。再补 projection reconciliation 和持久 pending。
- 代码依据：可扩展点是 `DeterministicPlanEvaluator.evaluate()`。

---

## 三十三、理解检查：20 个问题

如果下面问题答不上来，就说明还没有真正理解本项目 Planning：

1. 为什么 `episode_goal` 和 `current_goal` 不能合并？
2. 初始 Goal 与初始 Plan 分别由谁产生？
3. 为什么 `GoalDraft` 没有 `goal_id/status/revision`？
4. 为什么 `PlanStepDraft` 不保存完整 Tool arguments？
5. `PlanUpdateKind.KEEP` 和 `REVISE` 的语义差异是什么？
6. 一次 `handle()` 最多执行多少个 Action？为什么？
7. active Step 如何约束 Decision？
8. 为什么 Action 通过 Plan 对齐后仍要过 Authority？
9. Tool 成功后为什么必须重读 Observation？
10. 谁能把 Goal 标成 completed？
11. 当前谁把 Step 标成 completed？依据到底是什么？
12. `completion_signal` 当前是否真的被 Evaluator 使用？
13. Tool 失败后 Plan 和各 Step 分别是什么状态？
14. `needs_revision` 是否会立即生成新 Plan？
15. 环境在回合间变化时，哪个函数使旧 Plan 失效？
16. Memory 怎样影响 Plan，又为什么不能成为当前事实？
17. Plan 能否跨进程重启、跨新 Session、跨玩家恢复？
18. pending confirmation 与 Plan 哪一个持久化，哪一个没有？
19. World 成功但 Agent State 保存失败时，哪个状态更权威？
20. 哪些是 Agent Planning，哪些只是固定 Runtime Workflow？

---

## 三十四、最终概念收口

### Goal

当前阶段要达到的、有确定性完成条件的意图；不是执行步骤。

### Plan

围绕 current Goal 的 2～4 步、可修订、跨回合持久化路径。

### Plan Step

一个候选行动意图，带能力、可选建议 Tool、公开 target 和状态；不是完整 ToolCall。

### Decision

当前回合对玩家贡献的判断、使用的能力、唯一 Action 和解释。

### Action

准备在本回合公开回复或提交执行的一个行为；仍是待校验对象。

### Execution Result

Authority 与环境处理 Action 后的真实结果；可能成功、失败、待确认或提交不确定。

### Plan Evaluation

程序根据 Observation、Goal 条件、success flag 和下一步兼容性生成的状态迁移；当前 Step 语义判定仍较粗。

### Replanning

Plan 被标记 `needs_revision` 或收到反馈后，下一轮 LLM 提交 `REVISE` draft，经 Policy 接受后替换 steps；不是独立自动服务。

### Agent State

持久化 NPC 意图：Episode Goal、current Goal、current Plan、last evaluation、feedback 和 revision。

### World State

病例引擎中的权威事实；Plan 不能替代它，执行后必须重读其公开 Observation。

### Memory

跨 Session 的非权威历史经验，通过检索进入 Planning Context，不能授予权限或证明当前事实。

### 最终链路

```text
Goal
  ↓
Plan
  ↓
Active Step
  ↓
Decision
  ↓
Action Proposal
  ↓ Schema / Policy / Alignment / Authority
Execution
  ↓
Authoritative Result + New Observation
  ↓
Plan Evaluation
  ↓
Next Step / Needs Revision / Goal Complete
```

最终面试定性：**这不是一个独立 Planner 驱动的长程自治系统，而是一个 LLM 生成短计划、程序约束与推进、用户请求驱动逐步执行的混合 Agent Planning Runtime。**
