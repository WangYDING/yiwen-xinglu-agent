# Agent 可靠性、安全边界与约束设计

> 面试口径：本文基于当前工作区真实代码、架构文档和测试。必须区分：通用安全理论、项目设计意图、当前实现、尚未实现能力。
>
> 核心结论：本项目不把 LLM 当作最终控制器。LLM 只产生不可信 Proposal；结构、当前公开行动、Goal/Plan 一致性、权限、领域规则和持久化由不同的确定性层负责。系统实现的是 **fail-closed、world-authoritative、最多一次有界修复、危险重放阻断**，不是“模型永不出错”、跨存储 ACID、跨进程 exactly-once 或自动恢复闭环。

## 0. 先给结论

本项目的可靠性来自“错误不能直接变成副作用”，而不是期待模型每次回答正确。用户文本、历史 Memory 和 LLM 输出都被视为可能错误或恶意；只有经过 Pydantic Schema、公开 Action Contract、Goal/Plan Policy、Plan 对齐、Authority 和 CaseEngine 规则后，一个 Action 才可能修改案件世界。世界提交后，Runtime 重读公开 Observation，再更新 Plan/Agent State；Memory 和 Reflection 都是后提交投影，失败不回滚世界。

当前已经具备：

- 严格结构化输出与最多一次有界格式修复；
- 当前 Observation 派生的公开行动白名单；
- Planning/Decision、工具参数、权限和领域规则的分层校验；
- 调查自主、诊断协商、治疗确认的确定性 Authority；
- 同 Session 单进程串行化、JSON 原子替换、Agent State revision 检查；
- 协作 operation journal、相同请求 completed replay、payload conflict、未知提交阻止重放；
- world-first Memory 投影、稳定来源 ID、SQLite 局部事务和对账；
- 安全公开错误码、Plan feedback、Memory/Reflection provenance 与测试故障注入。

当前没有：

- 跨 JSON、History、Memory、Agent State、Reflection 的全局事务；
- 世界提交后的通用自动补偿/回滚；
- 跨进程 JSON 锁或数据库级原子 CAS；
- durable pending confirmation；
- 所有入口统一的跨重启 exactly-once；
- 完整生产分布式 Trace 或原始 Proposal/Prompt 的永久审计日志。

---

## 一、为什么 Agent 需要可靠性设计

普通确定性函数在给定输入下通常有固定控制流；Agent 多了自然语言、概率模型、动态 Proposal、外部状态和工具副作用。模型可能输出非法 JSON、错误枚举、过期 target、隐藏 ID、错误证据、与 Plan 不一致的 Action，甚至把“玩家要求我执行”误当授权。即使模型输出结构正确，当前病例也可能已经变化，工具可能失败，世界写入结果可能不确定，Memory/Agent State 的后提交投影也可能失败。

在本项目中，具体风险包括：

- 把玩家猜测或 prompt injection 当世界事实；
- `RESPOND` 与 `USE_TOOL` 形状冲突；
- 调用不存在、过期或与调查类型不匹配的 Tool/target；
- 在诊断尚未开放时提交诊断，或引用未发现证据；
- 未经玩家确认执行不可逆治疗；
- Plan 写调查 A，Decision 却执行 B；
- 模型格式修复后偷换 Action；
- Tool 已提交但网络/存储返回不确定，重试造成重复副作用；
- 失败 Action 被错误写成成功 Memory；
- 历史 Memory 与当前 Observation 冲突；
- 一个 Store 成功、另一个 Store 失败造成投影分叉。

### 面试一句话版本

> 我的项目把 LLM 限制在不可信决策建议层：Proposal 先过严格 Schema、当前公开 Action Contract、Goal/Plan Policy、最终 Plan 对齐和 Authority，只有 CaseEngine 能裁定世界变化；提交后再用 Observation、operation journal、revision、Memory provenance 和故障状态保护后续投影，所以模型可以灵活推理，但不能直接获得执行权或事实修改权。

---

## 二、系统中的不确定性来源

| 来源 | 是否存在 | 主要风险 | 当前约束 |
|---|---:|---|---|
| 用户输入 | 是 | 错误假设、恶意指令、伪造 ID/授权 | `PlayerContribution` 标为不可信；Context 分区；Policy/Authority |
| LLM 推理 | 是 | 误解 Goal、幻觉事实、选择错误策略 | Proposal-only；Plan/Action 对齐；Evaluator |
| LLM 输出格式 | 是 | 非 JSON、字段缺失、多余字段、类型错误 | Pydantic + JSON Schema + 一次 repair + fallback |
| Memory 内容 | 是 | 过期、冲突、错误召回、错误经验 | committed provenance、player scope、status/tombstone/conflict/filter |
| Plan 生成 | 是 | 隐藏 target、越权 Tool、目标漂移 | `GoalPlanPolicy` + Runtime-owned lifecycle |
| Tool 参数 | 是 | 参数名/类型/值错误、过期 action | `PublicActionContractValidator` + Engine 再校验 |
| 外部模型服务 | 是 | 超时、限流、认证、截断、usage 不可用 | typed adapter errors、无隐式 retry、安全 fallback/中止 |
| 外部环境/世界 | 是 | 状态在回合间变化、业务前置条件不满足 | 每轮重读 Observation、session lock、Engine rules |
| 持久化 | 是 | 部分提交、写入不确定、状态损坏 | 原子文件替换、SQLite transaction、receipt 三态、journal |
| 并发 | 有限存在 | 同 Session 丢失更新、重复执行 | 单进程 RLock、live claim、SQLite unique；跨进程仍有限制 |

### 2.1 模型不确定性

内容、格式、Plan、Action、Memory 使用声明和 Reflection lesson 都可能错误。模型输出永远不是权限、世界事实或写入凭证。

### 2.2 环境不确定性

Tool/Engine 可以拒绝动作；写 world 时可能成功、失败或结果未知；写后 Observation、Agent State、Memory、Reflection、History 仍可能分别失败。

### 2.3 用户不确定性

玩家输入是建议、假设、问题、批准或拒绝，不是直接 Command。批准还必须绑定 pending decision、完整 ToolCall、owner scope 和 case revision。

### 2.4 系统状态不确定性

Plan 可能过期，pending 可能失效，Memory 可能 inactive，operation 可能停在 `started/prepared/recovery_required`。Runtime 必须读取权威快照和生命周期，而不能从聊天文本猜状态。

---

## 三、完整安全控制链

项目的真实顺序比“Schema → Contract → Policy”单线图更复杂，因为模型边界先做一次确定性解析校验，Runtime 又在副作用前重复关键检查：

```text
Clinic request Schema / ownership / operation claim
                         ↓
Public Observation + Agent State + scoped Memory + History
                         ↓
Context Assembly + tokenizer-aware provider budget
                         ↓
LLM raw response
                         ↓
Pydantic GameNPCTurnProposal Schema
                         ↓
parser-side deterministic checks:
Decision identity → PublicActionContract → Memory usage → GoalPlanPolicy
                         ↓ invalid: at most one format repair / safe fallback
Runtime repeats GoalPlanPolicy
                         ↓
Runtime applies authoritative Goal/Plan draft
                         ↓
initial Plan–Decision alignment
                         ↓
PublicActionContract recheck / at most one dedicated action repair
                         ↓
final Plan alignment after repair
                         ↓
History prepared decision
                         ↓
NPCAuthorityPolicy
       ┌─────────────────┼──────────────────┐
   RESPOND            PENDING           AUTONOMOUS TOOL
       ↓                 ↓                    ↓
save Agent State   save pending intent   CaseToolExecutor
                                             ↓
                                         CaseEngine
                                             ↓
                                      world JSON commit
                                             ↓
                               Memory projection / index
                                             ↓
                                  reload public Observation
                                             ↓
                             PlanEvaluator + Agent State save
                                             ↓
                                      Reflection (optional)
                                             ↓
                                History completed/recovery state
```

### 3.1 各层职责

| 层 | 输入 | 检查/输出 | 失败行为 |
|---|---|---|---|
| Clinic request | API 请求 | Pydantic shape、owner、operation fingerprint、pending identity | 稳定错误，不调用 LLM/Tool |
| Context boundary | World/Agent/Memory/History | 只公开投影、scope、长度/token budget | 必选上下文过大则 fail-closed |
| LLM | 已过滤请求 | 不可信 Proposal | 无执行权 |
| Schema | raw JSON | 严格字段、枚举、类型、跨字段 shape | 最多一次 repair；失败 fallback |
| Action Contract | Action + 当前 Observation | 精确 Tool、参数、公开候选、业务阶段 | 有界 repair 或安全 RESPOND |
| GoalPlanPolicy | Goal/Plan proposal + Observation + Authority view | 阶段、target、capability、update、一致性 | 拒绝本轮，无 Tool |
| Plan alignment | final Decision + active Step | Tool/target 必须一致 | 拒绝 Action，写公开 feedback |
| Authority | final Action + valid confirmation | 是否可自主、只可提案、需确认、禁止 | pending 或拒绝；零副作用 |
| Executor/Engine | 合法 ToolCall + state | 领域前置条件、事件与新不可变 Session | typed rejection；不保存新 world |
| Commit boundary | Engine result | world commit 三态 | unknown 时阻止自动 replay |
| Post-commit projections | committed world/result | Memory、Plan、Agent State、Reflection、History | pending/recovery；不回滚 world |

---

## 四、LLM 的真实权限边界

| 能力 | LLM 是否拥有 | 真实边界 |
|---|---:|---|
| 理解/评价用户意图 | 是，作为建议 | 输出 `PlayerContributionEvaluation`，可被程序拒绝 |
| 生成 Goal/Plan/Action Proposal | 是 | 只能生成严格 draft，不能写权威 lifecycle |
| 选择公开候选 | 是 | 只能从投影 action space 选择 |
| 修改 World State | 否 | 只有 Tool Executor + CaseEngine + Store 路径能提交 |
| 直接调用 Engine | 否 | Runtime 才能把通过边界的 Action 交给 service |
| 判断最终权限 | 否 | `NPCAuthorityPolicy` 确定性裁定 |
| 绕过 Policy/Contract | 否 | 校验在 Python 中执行，Prompt 指令不能关闭 |
| 写数据库/JSON | 否 | Store/repository 仅由应用服务调用 |
| 直接写 Memory | 否 | 普通 Memory 来自 committed event；Reflection 只是候选且需校验/策略 |
| 宣布 Goal/Step 完成 | 否 | Runtime/Evaluator 改状态；Step 当前按执行结果粗粒度推进 |
| 授予自己治疗权限 | 否 | confirmation 绑定玩家批准、decision/action 和 revision |

### 面试追问：“LLM 到底有没有控制权？”

LLM 有**策略提议权**：解释输入、提出 Goal/Plan 变化、选择一个 Action。它没有**副作用执行权、最终权限裁定权、世界事实裁定权或持久化写权**。即使 Proposal 最终执行，也不是 LLM 单独决定，而是模型选择与确定性约束共同作用的结果。

---

## 五、为什么不能让 LLM 直接执行 Tool

### 5.1 参数可靠性

`ToolCallRequest.arguments` 是开放 JSON 值容器；只有 Action Contract 才强制调查只含 `investigation_id`、治疗只含 `treatment_id`，诊断只允许 `diagnosis_id/evidence_clue_ids`，并检查类型。Schema 只能保证它是 dict，不能保证字段适配当前 Tool。

### 5.2 业务合法性

结构正确的 `submit_diagnosis` 仍可能在诊断未开放时执行，或引用未发现线索；结构正确的 investigation ID 也可能已过期。Contract 用最新 Observation 判断业务合法性，Engine 还会再次验证领域前置条件。

### 5.3 权限问题

调查属于可逆信息行动，可自主；诊断是协商提案；治疗不可逆，需要确认。模型看到 Authority view 只是为了决策，不能替代 Python Authority 裁定。

### 5.4 状态一致性

模型请求是某个 Observation revision 的快照。执行前必须验证 pending revision、当前公开 action 和 Session ownership；执行后必须重读世界，不能让模型猜测工具结果。

### 5.5 可审计性

分层后可以分别记录 operation、prepared decision、Authority mode、selected Tool/target、event sequence、error code、Agent State revision 和 Memory/Reflection trace。

### 5.6 可测试性

Policy、Contract、Authority、Engine、Store 和故障窗口均可用 fake Agent 与 fault injection 独立验证。直接让模型执行会把概率决策与副作用耦合，难以证明拒绝路径“零 Tool、零 world event”。

---

## 六、Proposal 层设计

### 6.1 Proposal 的意义

Proposal 是 LLM 表达意图的不可执行数据。它允许模型保持灵活性，同时给程序一个可解析、可拒绝、可修复、可审计的边界。

### 6.2 真实 Schema

`GameNPCTurnProposal` 包含：

```text
goal_update: GoalUpdateProposal
plan_update: PlanUpdateProposal
decision: GameNPCDecisionProposal
  ├─ contribution_evaluation
  ├─ capability
  ├─ action: AgentAction
  │    ├─ action_id
  │    ├─ action_type: respond | use_tool
  │    ├─ dialogue
  │    ├─ tool_call?: {name, arguments}
  │    └─ confidence
  └─ explanation
memory_usage?: MemoryUsageProposal
```

Proposal 本身：

- 没有执行权；
- 不直接改 World/Memory/Store；
- 可被 Schema、Contract、Policy、Alignment 或 Authority 拒绝；
- Goal/Plan draft 只有经 Runtime `_apply_proposal()` 才成为 Agent intent state；
- 即使 Agent intent 已应用，最终 Action 仍可能被拒绝，且不会修改世界。

---

## 七、Schema Validation

项目使用 Pydantic v2 模型和 provider response schema：`extra="forbid"`、严格类型、枚举、长度/范围、model validators。`GameNPCTurnProposal.model_validate_json()` 先完成 JSON parse 和领域 shape 校验。

Schema 能保证：

- JSON 可解析；
- 必填/多余字段、类型和枚举受控；
- `RESPOND` 不带 ToolCall，`USE_TOOL` 必须带；
- Goal/Plan draft 形状、2～4 步、update/draft 组合合法；
- 基础 ID、文本、confidence 范围等不变量。

Schema 不能保证：

- target 当前公开或仍可用；
- Tool 与调查类型匹配；
- 诊断证据已经发现；
- Plan 与当前 Goal、Authority、Decision 对齐；
- 用户真的批准；
- Engine 执行成功；
- 模型推理结论正确。

所以 Schema 通过后 Action 仍可能在 Contract、Policy、Alignment、Authority 或 Engine 失败。

---

## 八、Action Contract

`PublicActionContractValidator` 解决“这个结构化 Action 是否属于**当前公开业务接口**”：

- investigation 必须只有 `investigation_id`，且 ID 在最新可用调查中，Tool 与 action type 匹配；
- diagnosis 只允许 `diagnosis_id/evidence_clue_ids`，候选公开、阶段 ready、证据是 discovered subset；
- treatment 必须只有 `treatment_id` 且当前公开；
- 非支持 Tool 拒绝；
- `RESPOND` 无 Tool 副作用，直接通过 Contract。

| | Schema | Action Contract |
|---|---|---|
| 解决问题 | 数据能否解析、形状是否封闭 | Action 对当前公开业务状态是否有效 |
| 时间点 | raw LLM response parse | parser-side 及 Runtime 执行前重检 |
| 判断内容 | 类型、枚举、字段组合 | Tool/参数/target/阶段/公开证据 |
| 例子 | `USE_TOOL` 必须有 `tool_call` | `diagnosis_id` 必须在当前候选且诊断已开放 |
| 失败 | 一次 format repair/fallback | 有界 repair 或 safe fallback |

Contract 不判断最终权限，也不证明领域执行一定成功。

---

## 九、Policy 机制

项目中“Policy”不是单一总类，而是多组确定性规则：

| Policy | 检查内容 | 失败结果 |
|---|---|---|
| `GoalPlanPolicy` | Goal 阶段、公开引用、Plan update、Step Tool/target/capability、Authority view、Plan/Decision 对齐、active executable commitment | Proposal 拒绝、安全回复、零 Tool |
| Runtime Plan alignment | final Action 与 resulting/current active Step 的 Tool/target | Action rejected，写 feedback/evaluation |
| `NPCAuthorityPolicy` | Agent 是否可自主执行、需协商/确认或禁止 | pending/forbidden，不执行 |
| Memory projection/retrieval policy | committed source、player/session scope、status/tombstone、conflict、预算 | 不写或不进入 Context |
| Reflection proposal/write policy | evidence refs、scope、强度、重复、冲突 | no-write/rejected，不污染 Memory |

`GoalPlanPolicy` 判断的是 Proposal 在当前公开状态下是否合规；`NPCAuthorityPolicy` 判断最终 Action 是否有资格执行。Policy 是 Python 规则，不是 Prompt、Schema 或模型自评。

---

## 十、Authority 机制

Authority 回答“即使 Action 合法，NPC 是否有资格现在执行”。

| Action | Authority mode | 是否立即执行 | 原因 |
|---|---|---:|---|
| `RESPOND` | `AUTONOMOUS` | 是，无世界 Tool | 社交/解释行为 |
| 五类公开调查 Tool | `AUTONOMOUS` | 是 | 可逆信息行动 |
| `submit_diagnosis` | `PROPOSAL_ONLY` | 否 | 需要玩家协商批准 |
| `execute_treatment` | `CONFIRMATION_REQUIRED` | 否 | 高风险/不可逆处置 |
| 缺 ToolCall 或不在权限表 | `FORBIDDEN` | 否 | 越权或非法 |

当前不是通用 RBAC/ABAC、组织账号权限系统，也没有动态角色层级。它是针对单个 NPC 和有限 Tool 集的确定性风险分级 Authority。

---

## 十一、Confirmation 机制

```text
validated matching Action
          ↓
Authority = proposal_only / confirmation_required
          ↓
PendingActionConfirmation（完整 Action + decision + owner + revision）
          ↓ 无世界副作用
PlayerContributionType.APPROVAL
          ↓ scope、responds_to_decision_id、case revision 校验
下一轮模型必须再次输出相同 ToolCall
          ↓
Authority 才放行
```

确认对象绑定：`confirmation_id`、`decision_id`、player/case/session、完整 Action、Authority mode 和 `case_revision`。确认前不会调用 Tool。确认后若模型换了 ToolCall，或 world revision 改变，不会获得旧授权。

局限：pending 存在 Clinic 进程内字典，不是 durable authority source；重启后失效。协作 History 中的旧 pending 公开信息只用于上下文，不会恢复授权。

---

## 十二、状态保护

### 12.1 谁能修改 World State

```text
User text             ✗
LLM Proposal           ✗
Agent object           ✗
Runtime direct write   ✗（只编排）
CaseToolExecutor       生成 Engine command/result
CaseEngine             裁定新不可变 Session/events
MultiCase service      ✓ 通过 JsonStateStore 提交 world snapshot
```

Engine 本身返回新状态，不直接写磁盘；最终持久化写权在应用服务/Store。唯一受控主路径便于统一执行领域校验、Session 锁、receipt 和错误分类。

### 12.2 Agent State 与 Memory

- Goal/Plan ID、status、revision 由 Runtime/Evaluator 修改，LLM 只提供 draft。
- Agent State 保存检查 session ownership 和 expected revision。
- 普通 Memory 只能从已提交事件确定性投影；Reflection Memory 需 evidence validator + write policy + repository。
- Memory 写入不能反向改变 world。

---

## 十三、事实来源优先级

不能简单把所有对象排成一个总序，因为 World、Agent intent 和 Memory 是不同权威域。面试时可这样表达：

```text
当前案件事实：Committed CaseSession / CaseEngine result
                     ↓ public projection
               fresh CaseObservation

当前执行约束：Action Contract / GoalPlanPolicy / Authority / Engine rules

当前 Agent 意图：persisted Goal / Plan / evaluation

历史参考：selected Memory / completed conversation history

不可信建议：current user contribution / LLM Proposal
```

若 Memory 与当前 Observation 冲突，以当前 World/Observation 为准；若用户说“我已经批准”但没有匹配 pending contract，以 Authority 状态为准；若 LLM 声称 Tool 已执行但没有 committed receipt，以 world 为准。

---

## 十四、错误分类体系

| 错误 | 发现位置 | 处理方式 |
|---|---|---|
| API/输入 shape | Pydantic Clinic input | 请求拒绝，不进入 Agent |
| scope/owner 错误 | Clinic/Store | 稳定 ownership error |
| Context 必选内容过大 | Context/token budget | fail-closed，不发送或不执行 |
| LLM 超时/限流/认证/截断 | DeepSeek adapter | typed error；安全 fallback 或 abort episode |
| JSON/Schema 错误 | `BoundedStructuredOutput` + Pydantic | 最多一次 format repair，后 fallback |
| Proposal 语义错误 | parser checks/GoalPlanPolicy | repair 或 Runtime 安全拒绝 |
| Action Contract 错误 | `PublicActionContractValidator` | 有界 action repair/fallback |
| Plan alignment 错误 | Runtime | `ACTION_REJECTED`，无 Tool，保存 feedback |
| Authority 拒绝 | `NPCAuthorityPolicy` | pending 或 forbidden；无 Tool |
| Tool/业务规则错误 | Executor/Engine | typed error，Plan needs revision |
| world commit unknown | MultiCase receipt | 标记 unknown，operation recovery_required，阻止 replay |
| Memory/index 失败 | coordinator/index | world 保持 committed，projection/index pending |
| post-commit Observation/Evaluator 失败 | Runtime/Clinic journal | committed follow-up incomplete，阻止同 operation 重放 |
| Agent State 写失败 | Runtime | 返回 `agent_state_projection_pending`，无自动对账 |
| Reflection 失败 | Reflection lifecycle | failed-safe，记录 status/error，不影响 world |
| History complete 写失败 | Clinic/journal | recovery_required，不自动 replay |

---

## 十五、失败恢复机制

| 机制 | 何时使用 | 谁触发 | 是否改变世界 |
|---|---|---|---:|
| Repair | LLM 结构或受控契约错误 | `BoundedStructuredOutput` / Agent | 否 |
| Safe fallback | repair/adapter 失败 | `GameNPCAgent` | 否，通常 RESPOND 或放弃可执行计划 |
| Replan | Tool 失败、Plan 失效 | Evaluator 标记；下一轮 LLM revise | 当轮否 |
| Completed replay | 同 operation、同 payload 已完成 | durable cooperative journal | 不重执行，返回旧结果 |
| Conservative stop | started/prepared/unknown/committed-follow-up gap | Clinic journal | 不重放 Tool |
| Reconciliation | committed world 后 Memory/index 缺失 | startup/service reconciliation | 只补派生投影 |
| Rollback | SQLite 单事务内部失败 | repository | 仅本地 SQLite transaction |
| World rollback | 未实现 | 无 | 已提交 world 不回滚 |
| Ask/confirm user | 高风险 Action | Authority/Clinic | 确认前无副作用 |

格式错误可以修复，因为还没有副作用；权限拒绝、Tool 业务失败和提交未知不能简单再问一次 LLM，因为重复 Action 可能扩大权限或产生双重副作用。

---

## 十六、重试策略

代码中的重试是**有界修复**，不是通用自动 retry：

- 初次 structured output 解析/确定性 validation 失败：最多一次 format repair。
- Action Contract 在 Runtime 失败：若之前只调用一次模型，可再做一次 action-contract repair；若已经 format repair，则直接 fallback，模型总尝试不超过 2。
- DeepSeek HTTP adapter 明确 `no implicit retry`；超时、限流和 transport error 不在 adapter 内自动重发。
- Authority rejection、Engine rule violation、world commit unknown、post-commit failure不自动 retry。
- Memory projection/index 可以通过确定性 reconciliation 重建，不需要让 LLM 重写。

这是“按错误类别选择恢复”，而不是所有失败都重新调用模型。

---

## 十七、幂等性与重复执行保护

### 17.1 协作入口（recording 启用）

`SQLiteCooperativeHistoryRepository` 以 `(player_id, case_id, session_id, operation_id)` 为主键，保存稳定请求 fingerprint 和 lifecycle：

- 同 operation + 同 payload + completed：返回已存结果；
- 同 operation + 不同 payload：`operation_payload_conflict`；
- 同 operation 正在执行：进程内 live claim 返回 `operation_in_progress`；
- 重启发现 started/prepared/recovery_required：阻止自动重放；
- world 已知提交但后续失败：返回 committed-follow-up-incomplete，不重放 Tool。

它优先保证 **at-most-once safety**，不承诺自动恢复为成功，也不宣称 world exactly-once。

### 17.2 Tool service 与普通入口

`MultiCaseEpisodeService` 有进程内 `_ACTION_RECEIPTS`；普通 Clinic action 也有进程内 `_ORDINARY_OPERATION_RECEIPTS` 和 payload conflict。重启后这些缓存消失，因此普通非协作入口没有同等 durable replay 保证。Engine 对已完成调查等会依据状态再次拒绝，但这不是所有 Tool 的通用 exactly-once 证明。

### 17.3 Memory

Memory 使用稳定 `source_event_id`、projection version/ordinal、SQLite unique 约束和 source receipt；重复投影可幂等返回。生命周期 operation 也有 operation ID 和事务。

---

## 十八、事务与一致性

### 18.1 已实现的局部原子性

- 单个 JSON snapshot：临时文件写入、flush/fsync、`os.replace` 原子替换。
- SQLite cooperative history/memory：单次 repository 操作使用 SQLite transaction/WAL。
- Engine：在内存中产生不可变新 Session；规则失败不会保存。

### 18.2 没有全局事务

一个协作 Action 可能依次写：world JSON → Memory SQLite/index → Agent State JSON → Reflection SQLite/index → History SQLite。这些不在同一个 ACID 事务中，不能保证“全部成功或全部失败”。

项目采用 world-first 与显式 failure state：

- world 是权威，提交后不因下游失败回滚；
- Memory 失败可 pending/reconcile；
- post-commit Runtime/History 失败进入 recovery_required，阻止危险 replay；
- Agent State projection pending 当前没有通用重建器；
- 没有补偿事务或 durable outbox 覆盖所有投影。

---

## 十九、并发安全

当前是单 NPC、单 Session 回合模型，不是多 Agent 共同写同一世界。

已实现：

- `JsonStateStore.session_write_lock()` 使用按 root/session 的进程内 `RLock`；Clinic、Runtime 和 MultiCase 路径复用，序列化同进程同 Session 写者。
- cooperative live operation claim 阻止同进程相同 operation 并发。
- SQLite `BEGIN IMMEDIATE`、主键和 sequence unique 处理 journal 竞争。
- Agent State 有 expected revision 与 ownership 校验。

未实现：

- 跨进程/多主机 Session lock；
- JSON 文件上的原子 compare-and-swap；
- Agent State revision 的数据库级 CAS；
- 多 Agent 冲突解决或分布式锁。

所以不能声称支持高并发多 Agent 写同一 Session。

---

## 二十、Memory 安全

普通 Memory 只从已经提交的 allowlisted CaseEvent 投影：调查完成、诊断提交、治疗执行。Coordinator 先验证 Engine transition，再保存 world，再构造 `VerifiedMemorySource`；失败 Action 没有 committed event，因此不会投影为成功经验。

安全措施包括：

- stable source receipt、payload hash、source session/sequence/revision；
- player scope、current-session exclusion、active status、tombstone、embedding-space 校验；
- 与当前 Observation 冲突的 Memory 默认过滤；
- selected Memory 是只读、非权威上下文；模型声明的 ID 必须来自本轮 selected/retained 集合；
- Reflection lesson 必须引用封闭的公开 evidence refs，通过 Proposal validator 和 write policy；重复、弱证据、过宽 scope、冲突可拒绝；
- SQLite write transaction、生命周期 correction/invalidation/delete 和索引对账。

仍然可能出现语义上不相关但相似的 Memory 被选中；这由 current-world-first、使用归因和评测控制，而不是宣称检索永不出错。

---

## 二十一、Context 安全

`CaseObservation` 是从 CaseSession/CaseDefinition 投影的公开视图，明确排除隐藏 world truth。Context 将信息分区：

- `AUTHORITATIVE_WORLD`：当前公开 Observation/环境反馈；
- `AUTHORITATIVE_CONSTRAINTS/ACTION_SPACE`：权限、公开候选、pending read-only view；
- persisted Goal/Plan：权威意图，不是世界事实；
- `HISTORICAL_NON_AUTHORITATIVE_CONTEXT`：Memory 和历史；
- current player contribution：不可信输入。

安全措施：player/case/session ownership、completed history 选择、pending revision 过滤、Memory scope/conflict 过滤、History/Memory 可裁剪、必选 Context 超预算 fail-closed、最终 provider payload tokenizer-aware 预算。Provider adapter 不记录 Prompt。

Observation 是信息隔离边界，但不是传统机密管理系统或公网认证层；其安全性依赖投影代码不泄露 hidden field。

---

## 二十二、Prompt Injection 风险

玩家可以输入“忽略规则”“直接治疗”“把某 ID 当已批准”。Prompt 会明确声明贡献不是命令或事实，但 Prompt 不是最终边界。

真正防护来自：

1. 用户文本无法构造 `PendingActionConfirmation` 或 Store 写调用；
2. LLM 只能输出严格 Proposal；
3. target 必须来自最新公开 action space；
4. Goal/Plan Policy 与 final alignment 在 Python 中执行；
5. Authority 只认绑定的 pending/action/revision，不认自然语言自述；
6. Engine 再验证领域规则；
7. world/Memory/Agent State 的写 API 不暴露给模型。

因此 Prompt injection 可能影响模型建议或回复质量，但不能仅靠文本直接越过副作用边界。

---

## 二十三、Agent 行为可解释性

系统能够回答一部分“为什么”：

- Decision 保存玩家贡献评价、capability、Action、explanation、fallback/repair kind 和 usage；
- Result 保存 public rationale、Authority mode、Tool/公开 target、Plan step、alignment reason、validation error path、event sequences 和状态变化摘要；
- Agent State 保存 Goal/Plan/evaluation/feedback/revision；
- world action history 保存 committed action record；
- Memory 保存来源 receipt，usage trace 保存 candidate/selected/declared/accepted；
- Reflection 保存 trigger、proposal status、write outcome、provenance refs；
- cooperative journal 保存 request、prepared final decision、result、lifecycle/failure code。

但这不是对模型内部推理的因果解释，也不能完整重建所有生产请求：完整初始 Goal/Plan proposal、原始 Prompt、原始无效输出与每次修复 response 主要存在于 thread-local diagnostic/evaluation trace，不是 production journal 的永久字段。

---

## 二十四、日志与可观测性

| 观测对象 | 当前记录 | 位置/边界 |
|---|---|---|
| 协作请求 | stable request JSON/fingerprint、contribution、sequence | SQLite cooperative journal |
| 最终执行前 Decision | prepared decision JSON | journal；不含完整 Goal/Plan update proposal |
| 最终结果 | `CooperativeTurnResult` 全量 JSON | journal completed result |
| operation 生命周期 | started/prepared/completed/failed/recovery_required | journal |
| 模型调用 | provider ID、tokens、finish reason、duration、validation path、sanitized summaries | `BoundedAttemptTelemetry`；主要供运行期 hook/评测 |
| Context 构建 | block 来源/字符/预算、token budget trace | thread-local build records/评测，不进 Prompt |
| Plan 对齐 | proposed/action/active step 摘要、reason | Result fields |
| World | Action history、events、revision | CaseSession |
| Memory | source receipt、lifecycle、usage trace | SQLite/Result |
| Reflection | lifecycle receipt、candidate/write/index 状态 | SQLite/Result |

当前没有 OpenTelemetry、跨服务 span、集中日志平台、告警/SLO 或完整 production raw request archive。DeepSeek adapter 明确不记录 Prompt，这是隐私/密钥边界，但也限制事后完整复现。评测系统有更丰富 request ledger 与 artifact，不应等同于生产 observability。

---

## 二十五、测试体系

本次针对可靠性链运行 13 个测试文件，共 **156 tests passed**；当前工作区可收集 **674 tests**。前者是本次已完成的定向执行，后者只是收集数量，不在此冒充全量通过结果。

| 测试类型 | 是否存在 | 代表验证 |
|---|---:|---|
| Agent 决策/repair/fallback | 是 | `test_m1_cooperative_runtime.py`、Planning/repair tests |
| Schema/Contract | 是 | `test_p4_treatment_action_contract.py`、planning contract tests |
| Policy/Alignment | 是 | GoalPlan、P2/P5 tests |
| Authority/Confirmation | 是 | `test_m1_npc_authority.py`、web/runtime tests |
| Tool/Engine | 是 | `test_case_engine.py`、case tool/MCP tests |
| State/Revision | 是 | `test_m2_cooperative_state_store.py` |
| 幂等/故障窗口 | 是 | `test_commit_consistency_faults.py`、CE-2A replay tests |
| Memory 安全 | 是 | projection、coordination、repository、retrieval tests |
| Reflection 污染防护 | 是 | proposal、memory、lifecycle tests |
| Context/Prompt isolation | 是 | CE-1.1、CE-2A、token budget tests |
| 集成/Web/MCP | 是 | cooperative web、production wiring、`test_mcp_p0.py` |
| 真实模型行为评测 | 有限 | 冻结 harness/pilot；不能证明全局可靠性 |

“不是 Demo 能跑”的证据是：拒绝链、零副作用、重复请求、payload conflict、world commit unknown、post-commit failure、原子替换失败、重启 replay 阻断和 Memory/Reflection 写入错误都有确定性或故障注入测试。它仍不等于生产高并发/SLO 证明。

---

## 二十六、安全边界总结图

```text
                Untrusted User / Memory / LLM
                            │
                      [Public Context]
                            │
                     [LLM Proposal]
                            │
              [Schema + deterministic parse]
                            │
                  [Public Action Contract]
                            │
                 [Goal/Plan Policy + Align]
                            │
                    [Authority / HITL]
                            │
                    [Tool Executor]
                            │
                      [CaseEngine]
                            │
                 [Committed World State]
                            │
       [Observation → Plan/Memory/Reflection projections]
                            │
                  [Journal / feedback / next turn]
```

- Schema 防畸形数据；
- Contract 防过期或不属于当前公开接口的 Action；
- Policy 防 Goal/Plan/Decision 逻辑不一致；
- Authority 防合法但越权的副作用；
- Engine 防领域前置条件错误；
- Store/journal 防静默覆盖和危险重放；
- post-commit provenance/filter 防 Memory/Reflection 污染。

---

## 二十七、可靠性设计 Trade-off

| 方案 | 优点 | 缺点 | 本项目选择 |
|---|---|---|---|
| 全规则 Workflow | 可预测、易验证 | 难理解开放自然语言，策略僵硬 | 规则负责边界和事实，不包办策略 |
| 纯 LLM Tool Agent | 灵活、实现快 | 格式、权限、状态和副作用不可控 | 不采用 |
| 混合 Proposal + deterministic control | 灵活与可控兼顾，可分层测试 | 代码层次多、重复校验、状态推理复杂 | 当前方案 |
| 全局分布式事务 | 强跨存储一致性 | 对本地 JSON/SQLite 项目成本过高 | 未采用；world-first + pending/reconcile |
| 自动 retry 所有失败 | 提高表面成功率 | 可能双重执行、放大成本/越权 | 仅无副作用阶段有界 repair |
| 保存全部 Prompt/Response | 最强复盘 | 隐私、存储、安全风险 | 生产不完整保存，评测单独留证 |

核心取舍是：让 LLM 处理开放语义，让确定性代码掌握副作用和事实；在提交不确定时优先停止而不是追求自动可用性。

---

## 二十八、设计文档 vs 真实代码

| 能力 | 文档描述 | 实际代码 | 是否一致 |
|---|---|---|---|
| Validation 顺序 | Planning 图为 Schema → Policy/Align → Contract | `_parse_turn()` 实际先 Schema → ActionContract → Memory usage → GoalPlanPolicy；Runtime 又重复 Policy/Contract/Align | **高层图过度简化** |
| Contract | 当前公开 Tool/参数/target 校验 | 已实现；duplicate 多通过 available Observation 间接排除，并非独立 duplicate rule | 基本一致，表述需精确 |
| Policy | Goal/Plan、权限视图、一致性 | 已实现；最终 Authority 是另一层 | 一致 |
| Authority | 调查自主、诊断 proposal、治疗确认 | 已实现，绑定 pending action/revision | 一致 |
| Retry | 有限 repair，无隐式 provider retry | 代码确实最多两次模型尝试，adapter 无隐式 retry | 一致 |
| Replan | Runtime 图写 `PlanEvaluator / Replan` | Evaluator 只标 needs_revision；下一轮 LLM revise | **图容易误导** |
| Evaluator | 使用 Observation、当前步骤和 Tool 结果 | 丢弃 executed action/message/events/pending，且不读 Step completion signal | **文档语义偏强** |
| Transaction | 文档明确无跨存储事务 | 代码只有 JSON 原子替换和 SQLite 局部事务 | 一致 |
| Idempotency | cooperative journal replay/阻断，不承诺 exactly-once | recording 启用时 durable；ordinary receipts 仍进程内 | 一致，但必须说明开关边界 |
| Logging | 可审计状态/错误 | 有 journal/result/telemetry；无完整 raw Proposal/Prompt 永久生产 trace | **“可审计”不能扩大为全链路复现** |
| Testing | 确定性与 fault injection 证明边界 | 大量测试存在；真实模型/并发/SLO 证据有限 | 一致 |

另一个文档措辞问题是“Agent 可以创建、保持、修订、阻塞或放弃 Goal/Plan”：代码中 Goal 可以 `BLOCK`，Plan 没有 block operation，只有 `NEEDS_REVISION` 或 `ABANDONED`，两者不应合并表述。

---

## 二十九、当前可靠性最大风险

### 29.1 最大风险：跨存储部分提交后的恢复不完整

World、Memory、Agent State、Reflection 和 History 不在同一事务中。当前最安全的策略是 world-first、记录 commit 三态并阻止危险 replay，但这解决的是“不要重复副作用”，没有完全解决“怎样自动恢复到一致状态”。特别是 world 已提交而 Agent State 保存失败时只返回 `agent_state_projection_pending`，缺少从 committed world/operation journal 确定性重建 Goal/Plan 投影的通用 reconciler。

### 29.2 其他真实风险

1. cooperative durable operation journal 依赖 recording 开关；程序化组合默认可关闭，旧路径没有同等跨重启保证。
2. pending confirmation 不持久，重启牺牲可用性；虽然不会从历史错误恢复授权。
3. JSON Session lock 和 Agent revision 只在单进程可靠，没有跨进程原子 CAS。
4. 普通 action receipts 主要进程内，跨重启不提供统一 operation replay。
5. Runtime 在最终 Action Contract/Authority 前已应用 Goal/Plan intent；Action 后续被拒绝时 world 安全，但 Agent intent 状态推理更复杂。
6. Step completion 仍按 success flag 粗粒度推进，未使用 `completion_signal`。
7. production journal 不保存完整初始/修复 GoalPlan proposal 与 raw context，根因复盘存在盲区。
8. Policy 是有限病例域的 allowlist，不是通用 sandbox、网络隔离或多租户认证系统。
9. 当前测试证明控制流，不证明真实模型长期语义正确、攻击覆盖率或生产 SLO。

优先改进：为 Agent State 增加 committed-operation correlation 和 deterministic reconciler；再统一 durable operation contract、持久 pending/consume、跨进程 CAS；同时补 Step completion predicate 与安全可脱敏的 production trace。

---

## 三十、最终面试回答版

### 30.1 30 秒：“你的 Agent 如何保证可靠？”

> 我没有让 LLM 直接控制系统。它只输出结构化 Proposal，先经过 Pydantic Schema、当前公开 Action Contract、Goal/Plan Policy、最终 Plan 对齐和 Authority；只有 Executor/CaseEngine 能产生世界变化。执行后以 committed World 和重读 Observation 为准，再投影 Agent State、Memory 和 Reflection。模型错误只有一次有界修复，提交不确定时不自动重放；协作 operation journal 会做 replay、payload conflict 和 recovery blocking。

### 30.2 2 分钟回答

> 可靠性首先来自权限分层。用户输入、Memory 和 LLM 都不是事实源；模型只能提出 `goal_update + plan_update + one Action`。Pydantic 解决格式，Action Contract 解决当前 Tool 参数和公开 target，GoalPlanPolicy 解决目标、计划、能力和 Action 一致性，Authority 决定调查能否自主、诊断是否只可提案、治疗是否必须确认。最后 CaseEngine 再验证领域前置条件。
>
> 状态方面，世界只通过 ToolExecutor、Engine 和应用服务提交；Agent State 使用 session ownership、revision 和原子文件替换。同进程同 Session 有 RLock。协作入口把 operation_id、request fingerprint、prepared decision 和 result 存到 SQLite journal：完成请求可 replay，不同 payload 冲突，started/prepared 或 world commit unknown 会进入 recovery_required，同 operation 不会自动重放 Tool。
>
> 失败恢复按类型处理：无副作用的格式问题最多修复一次；契约失败 fallback 为安全回复；权限失败等待确认或拒绝；Tool 失败触发下一轮 replan；world 已提交后的 Memory 可以对账，Reflection failed-safe。当前不夸大：跨多个 Store 没有全局事务，跨进程没有 JSON CAS，Agent State projection pending 也没有通用自动重建器，这是最大的剩余可靠性风险。

### 30.3 “为什么不能让 LLM 直接调用工具？”

> 因为 JSON 合法不等于参数属于当前公开 action，不等于业务阶段允许，不等于 NPC 有权限，也不等于 world 仍是模型看到的 revision。直接执行还无法安全处理重复请求和提交不确定。我的实现把模型 ToolCall 当 Proposal，程序逐层校验并由 Engine 裁定结果。

### 30.4 “你的安全边界在哪里？”

> 真正边界不在 Prompt，而在 Python 控制面：公开 Observation/Action projection、Schema、Contract、GoalPlanPolicy、Plan alignment、Authority、CaseEngine 和 Store/journal。任何一层拒绝都不应执行 Tool 或产生 world event。

### 30.5 “如果 LLM 输出错误怎么办？”

> JSON/Schema/受控 validation 错误最多做一次 format repair；Action Contract 可在总调用上限内做一次专门 repair；仍失败就安全 RESPOND/fallback，不执行 Tool。业务或权限失败不靠反复调用模型绕过，而是返回稳定反馈、等待确认或下一轮 replan。

### 30.6 “如何保证 Agent 不会修改错误状态？”

> LLM 没有 Store 引用。World 只接受 Contract、Policy、Authority 都通过的结构化 Action，Engine 还会检查领域规则。提交后重读 Observation，再更新 Plan；Agent State 有 ownership/revision；Memory 只从 committed events 或经过 evidence validator 的 Reflection 写入。

### 30.7 白板版

```text
[Untrusted User / Memory]
          ↓
[LLM Proposal]
          ↓
[Schema + Contract]
          ↓
[GoalPlan Policy + Alignment]
          ↓
[Authority / Human Confirmation]
          ↓
[Executor + CaseEngine]
          ↓
[Committed World + Receipt]
          ↓
[Observation / State / Memory / Journal feedback]
```

---

## 三十一、高频面试追问（32 题）

### Q1. 你的可靠性是靠 Prompt 吗？

- 考察点：软约束与硬边界。
- 推荐回答：Prompt 只帮助模型遵循；真正边界是 Schema、Contract、Policy、Authority、Engine 和 Store。
- 代码依据：`action_contract.py`、`goal_plan_policy.py`、`npc_authority.py`。

### Q2. LLM 有工具执行权吗？

- 考察点：模型权限。
- 推荐回答：没有，只能产生 Action Proposal；Runtime 才能提交给 service。
- 代码依据：`GameNPCTurnProposal` 与 `CooperativeRuntime.handle()`。

### Q3. Schema 和 Contract 为什么要分开？

- 考察点：结构合法与业务合法。
- 推荐回答：Schema 验证数据形状；Contract 用最新 Observation 验证 Tool/参数/target/阶段。
- 代码依据：`AgentAction` Pydantic model、`PublicActionContractValidator`。

### Q4. Contract 和 Policy 有什么区别？

- 考察点：职责分层。
- 推荐回答：Contract 判断 Action 是否属于当前公开接口；GoalPlanPolicy 判断 Goal/Plan/Decision 整体是否一致。
- 代码依据：两个 validator 的真实规则。

### Q5. Policy 和 Authority 有什么区别？

- 考察点：合法与有权。
- 推荐回答：Policy 判断意图是否合规；Authority 判断当前 NPC 是否能自主执行，还是需确认/禁止。
- 代码依据：`GoalPlanPolicy.validate()`、`NPCAuthorityPolicy.evaluate()`。

### Q6. 为什么 Engine 还要再校验？

- 考察点：纵深防御。
- 推荐回答：上层是公开接口约束，Engine 是最终领域不变量；状态可能变化，也不能依赖单一上层 validator。
- 代码依据：`CaseToolExecutor`/`CaseEngine` RuleViolation。

### Q7. LLM 输出非法 JSON 怎么办？

- 考察点：repair 边界。
- 推荐回答：Pydantic parse 失败后最多一次 format repair；仍失败 fallback，不执行 Tool。
- 代码依据：`BoundedStructuredOutput.run()`。

### Q8. 所有错误都会重试模型吗？

- 考察点：错误分类。
- 推荐回答：不会。只有无副作用的格式/契约问题有界 repair；权限、业务失败、提交未知不自动重试。
- 代码依据：bounded output、Runtime error branches。

### Q9. Provider 网络失败会自动重试吗？

- 考察点：隐藏 retry。
- 推荐回答：DeepSeek adapter 明确无隐式 retry；返回 typed error，按 abort/fallback 处理。
- 代码依据：`DeepSeekChatAdapter` docstring。

### Q10. 如何防止 Prompt Injection 直接治疗？

- 考察点：硬边界。
- 推荐回答：文本不能生成有效 pending；治疗必须公开 candidate、Plan 对齐、Contract 通过，并匹配玩家批准的完整 Action/revision。
- 代码依据：Authority 与 `_validated_pending()`。

### Q11. 用户说“我批准了”够吗？

- 考察点：授权真实性。
- 推荐回答：不够；贡献类型、decision ID、owner、case revision、pending ToolCall 都必须匹配。
- 代码依据：`PendingActionConfirmation`、`_validated_pending()`。

### Q12. 确认后模型换参数怎么办？

- 考察点：TOCTOU。
- 推荐回答：pending.action.tool_call 必须等于最终 action.tool_call，否则不把 confirmed ID 交给 Authority。
- 代码依据：Runtime pending match。

### Q13. 谁能修改世界？

- 考察点：mutation authority。
- 推荐回答：Engine 产生新 Session，应用服务通过 Store 提交；LLM/User/Memory 都不能写。
- 代码依据：`MultiCaseEpisodeService.submit_action_with_receipt()`。

### Q14. 如何防止重复协作请求？

- 考察点：幂等。
- 推荐回答：recording 模式用 durable operation journal + fingerprint；completed replay，payload conflict，未决 operation 阻止重放。
- 代码依据：`SQLiteCooperativeHistoryRepository.begin()`、Clinic lifecycle。

### Q15. 这是不是 exactly-once？

- 考察点：不夸大。
- 推荐回答：不是。它主要提供 at-most-once safety 和 completed replay；提交未知时停止，不能自动证明成功。
- 代码依据：`recovery_required`、`world_commit_status="unknown"`。

### Q16. 普通非协作 Action 也能跨重启幂等吗？

- 考察点：能力边界。
- 推荐回答：不能保证；其 receipt 主要是进程内缓存。durable journal 是协作 recording 路径能力。
- 代码依据：`_ORDINARY_OPERATION_RECEIPTS`、`_ACTION_RECEIPTS`。

### Q17. World commit 不确定时为什么不重试？

- 考察点：重复副作用。
- 推荐回答：第一次可能已经成功；重试治疗/诊断可能重复提交，所以记录 recovery_required 并阻断。
- 代码依据：commit consistency fault tests。

### Q18. 有 rollback 吗？

- 考察点：事务语义。
- 推荐回答：SQLite 单事务失败有 rollback，JSON 单文件原子替换；已提交 world 没有跨存储 rollback。
- 代码依据：`sqlite_memory._write_transaction()`、`JsonStateStore._write()`。

### Q19. 有全局事务吗？

- 考察点：跨存储一致性。
- 推荐回答：没有。采用 world-first、pending/recovery/reconciliation。
- 代码依据：world→Memory→AgentState→Reflection→History 顺序。

### Q20. Memory 写失败会回滚案件吗？

- 考察点：权威优先级。
- 推荐回答：不会；world 保持 committed，Memory 标 projection_pending，可从 committed Session 对账。
- 代码依据：`V1MemoryCoordinator.commit_engine_result()`。

### Q21. 如何避免失败 Action 写成成功 Memory？

- 考察点：Memory provenance。
- 推荐回答：普通 Memory 只投影 committed CaseEvent；Engine rejection 没有 event/commit。
- 代码依据：`DeterministicMemoryProjector` 与 coordinator。

### Q22. Reflection 幻觉怎么办？

- 考察点：二次 LLM 风险。
- 推荐回答：Reflection 只是 proposal，必须引用 evidence bundle，通过 lesson/evidence/scope validator 和 write policy。
- 代码依据：`ReflectionProposalValidator`、`ReflectionMemoryWritePolicy`。

### Q23. Memory 与 World 冲突相信谁？

- 考察点：事实源。
- 推荐回答：当前 World/Observation 优先；冲突 Memory 默认过滤且 Prompt 明确非权威。
- 代码依据：`GameNPCMemoryProjectionPolicy`。

### Q24. 如何防隐藏信息泄漏？

- 考察点：Context boundary。
- 推荐回答：LLM 接收 `PlayerView/CaseObservation` 公开投影和公开 action projections，不直接接收 CaseDefinition hidden truth。
- 代码依据：`views.py`、`context.py`。

### Q25. 同一 Session 并发写怎么办？

- 考察点：并发。
- 推荐回答：单进程通过 per-session RLock 串行化；跨进程仍没有数据库 CAS，不能夸大。
- 代码依据：`JsonStateStore.session_write_lock()`。

### Q26. Agent State revision 能解决跨进程竞争吗？

- 考察点：CAS 语义。
- 推荐回答：不能完全解决；它是读后 revision 检查再文件替换，不是原子 compare-and-swap。
- 代码依据：`save_cooperative_agent_state()`。

### Q27. 为什么先保存 world 再写 Memory？

- 考察点：事实不能由派生层领先。
- 推荐回答：避免 Memory 记录未提交事实；派生失败可从 world 重建，反向则无法安全证明。
- 代码依据：`memory_coordination.py` 的明确顺序。

### Q28. 系统能完整解释模型为什么这么做吗？

- 考察点：可解释性边界。
- 推荐回答：能解释公开输入、Proposal 结果、规则路径和副作用，但不能证明模型内部因果；生产也不永久保存全部 raw Prompt/attempt。
- 代码依据：Result/journal/telemetry 字段。

### Q29. 有生产级分布式 Trace 吗？

- 考察点：Observability 诚实度。
- 推荐回答：没有。现有是本地 journal、状态/event、telemetry 和评测 artifact，不是 OpenTelemetry 全链路。
- 代码依据：SQLite journal 与 optional diagnostic hook。

### Q30. 如何证明拒绝没有副作用？

- 考察点：测试策略。
- 推荐回答：用 fake Agent、Engine state/event count 和 fault injection 验证 schema/policy/alignment/authority 拒绝分支零 Tool、零 world event。
- 代码依据：Runtime、Authority、commit consistency tests。

### Q31. 当前最大可靠性风险是什么？

- 考察点：系统性思考。
- 推荐回答：跨 Store 部分提交后的自动恢复不完整，尤其 world 已提交而 Agent State/History follow-up 失败；系统会安全阻止 replay，但可能需要恢复工具。
- 代码依据：`agent_state_projection_pending`、`recovery_required`。

### Q32. 下一步如何提升？

- 考察点：演进优先级。
- 推荐回答：先给所有 world mutation 建 durable correlation 和 AgentState reconciler，再按需要引入跨进程 CAS/durable pending；不应直接用自动 retry 掩盖不确定性。
- 代码依据：Commit consistency 当前限制。

---

## 三十二、理解检查：20 个问题

如果下面问题答不上来，就说明没有真正理解本项目可靠性设计：

1. 为什么 Prompt 不能作为最终安全边界？
2. LLM 的策略提议权和副作用执行权如何区分？
3. Schema、Action Contract、GoalPlanPolicy 各自拦截什么错误？
4. Authority 为什么不能并入 Action Contract？
5. 为什么 Schema 合法的诊断仍可能被拒绝？
6. 为什么 Action Contract 通过后 Engine 还要验证？
7. 格式 repair 和业务失败后的 replan 有什么区别？
8. 一次模型请求最多允许几次尝试，为什么？
9. 为什么 provider transport failure 不自动 retry？
10. pending confirmation 绑定哪些字段？
11. 为什么历史中的批准文字不能恢复 Authority？
12. cooperative operation journal 怎样处理同 ID 同 payload 和不同 payload？
13. `world_commit_status=unknown` 为什么必须阻止重放？
14. JSON 原子替换、SQLite transaction 和全局事务有什么区别？
15. 当前 Session lock 能否覆盖多进程？
16. world、Observation、Agent State、Memory 的权威边界分别是什么？
17. 如何保证失败 Tool 不会生成成功 Memory？
18. production journal 能否完整还原原始 Prompt 和所有 Proposal？
19. world 已提交但 Agent State 保存失败时如何处理，当前还缺什么？
20. 156 个专项测试能证明什么，又不能证明什么？

---

## 三十三、最终概念收口

### Constraint

限制系统允许的输入、输出、行动与状态迁移范围；可来自 Schema、白名单、状态机或预算。

### Validation

对具体数据或 Proposal 执行检查，失败则拒绝、修复或降级，不产生未授权副作用。

### Policy

确定性业务规则：当前 Goal/Plan/Action 是否在公开状态和能力范围内合理。

### Contract

组件间可执行接口约定；本项目 Action Contract 规定当前 Tool 的精确参数与公开 target。

### Authority

合法 Action 是否由这个 NPC 在此刻自主执行，还是需要玩家确认或必须禁止。

### Executor

把已批准结构化 Action 转成领域 Command 并调用 Engine 的确定性适配层。

### Safety Boundary

不可信模型输出与真实副作用之间不可由 Prompt 绕过的程序边界。

### Reliability

面对模型、环境、存储和并发失败时，仍保持事实、权限、重复执行和错误语义可控。

### Failure Recovery

根据失败阶段选择 repair、fallback、replan、replay、reconcile、等待确认或保守停止；不是统一重试。

### Observability

用 operation lifecycle、Decision、receipt、event、revision、error code、Memory/Reflection provenance 和 telemetry 解释系统发生了什么，同时承认未记录的部分。

### 最终闭环

```text
LLM / User / Memory 的不确定性
                 ↓
Public Context + bounded Proposal
                 ↓
Schema / Contract / Policy / Alignment / Authority
                 ↓
Executor + Engine
                 ↓
Committed World / explicit commit status
                 ↓
Observation + State/Memory/Reflection projections
                 ↓
Journal / feedback / repair or next-turn replan
```

最终面试定性：**本项目的可靠性不是让 LLM 更“听话”，而是让任何不听话、错误或不确定的输出都必须经过确定性控制面，且只有有证据的执行结果才能进入权威状态；剩余短板主要在跨存储提交后的自动恢复与跨进程一致性，而不在是否有一条更强的 Prompt。**
