# Tool 与 Action 执行机制设计

> 分析口径：以 2026-09-27 当前工作区代码为准。主分析对象是 Web 协作路径中的 `GameNPCAgent → CooperativeRuntime → MultiCaseEpisodeService → CaseToolExecutor → CaseEngine`。普通页面操作与独立 MCP stdio 接口会单独说明，不能把某一入口的保证推广到所有入口。
>
> 核心原则：**LLM 只提出意图；校验通过不等于执行成功；Engine 计算出的新状态也只有成功提交后才成为权威事实。**

## 一、先定义本项目里的 Tool 与 Action

### 1. Action 是什么

**它是什么：** `AgentAction` 是一次模型决策中“本轮准备做什么”的结构化业务对象，定义在 [`domain/actions.py`](../../src/xuanyi_npc/domain/actions.py#L33)。它只有两种顶层类型：

- `RESPOND`：只输出对话，不调用工具；
- `USE_TOOL`：必须携带一个 `ToolCallRequest(name, arguments)`。

字段还包括 `action_id`、公开 `dialogue` 和 `confidence`。Pydantic validator 保证 `RESPOND` 不能夹带 tool call，`USE_TOOL` 不能缺少 tool call。

**为什么需要：** 自然语言“我想检查纸伞”不能直接成为执行指令。`AgentAction` 把自由文本判断收敛为程序可以验证、记录、比对、授权的对象。

**在本项目里怎么实现：** LLM 先返回包含 Goal/Plan/Decision 的 `GameNPCTurnProposal`，其中 `decision.action` 已经是 `AgentAction`。因此严格说，Runtime 不是再把 Proposal 转换成另一种 Action；Action 本来就是 Proposal 的嵌套字段，Runtime 做的是抽取、修复、重关联并逐层验证。

### 2. Tool 是什么

**它是什么：** `ToolName` 是 Agent 能力名的静态枚举，定义在 [`domain/actions.py`](../../src/xuanyi_npc/domain/actions.py#L16)。`ToolCallRequest` 通过一个枚举名和 JSON arguments 表达“希望调用哪项能力”。

**为什么需要：** Tool 把“观察病人”“提交诊断”“执行处置”等能力从 LLM 文本中分离出来，形成有限、可审计的执行面。

**在本项目里怎么实现：** 代码共有 9 个 `ToolName`；`CaseToolExecutor.execute()` 支持这 9 个名字。主协作 Agent 的 `PublicActionContractValidator` 只接受其中 7 个会推进案件的公开行动；两个 GET 类只读 Tool 由应用/MCP 路径使用，主 Agent 通常通过 Runtime 直接获得 Observation，而不是自己调用 GET Tool。

### 3. Executor 是什么

**它是什么：** [`CaseToolExecutor`](../../src/xuanyi_npc/application/case_tools.py#L100) 是独立的应用层适配器。入口是 `execute(action, case, player, session, occurred_at)`。

**为什么需要：** LLM 的 JSON 参数与领域引擎接受的强类型 Command 不是同一层对象。Executor 负责校验参数、将 Tool 名映射为领域动作、补齐可信时间和 target，并把 Engine 结果统一包装为 `ToolExecutionResult`。

**在本项目里怎么实现：** 它用 Pydantic 参数模型解析 arguments，用字典与 `if` 分发构造 `InvestigationCommand`、`SubmitDiagnosisCommand` 或 `ExecuteTreatmentCommand`，然后调用 `CaseEngine.execute()`。它不直接持久化状态，也不负责协作 Agent 的 Authority。

### 4. Engine 是什么

**它是什么：** [`CaseEngine`](../../src/xuanyi_npc/engine/case_engine.py#L43) 是确定性的领域规则执行器。

**为什么需要：** 即使 Tool 名和参数合法，也仍需依据完整可信状态检查 session 是否关闭、调查是否重复、技能是否满足、前置线索是否存在、诊断证据是否真实发现、处置是否满足条件。

**在本项目里怎么实现：** `execute()` 以 Command 类型分派到 `_investigate()`、`_submit_diagnosis()`、`_execute_treatment()`。它**不原地修改输入，也不写文件**，而是返回新的不可变 `CaseSessionState`、领域事件、消息和可选评分。

### 5. Execution Result 是什么

项目没有一个覆盖所有层的万能 Result，而是逐层收敛：

- `EngineResult`：Engine 的新 session、至少一个 event、message、可选 score breakdown；
- `ToolExecutionResult`：Executor 的统一返回，读 Tool 可以零 event；
- `MultiCaseServiceResult`：应用层公开结果，含 `ok/error_code`、Observation、revision、事件序号等；
- `MultiCaseActionReceipt`：内部提交回执，额外记录 world commit 三态与 Memory 投影状态；
- `CooperativeTurnResult`：Runtime 最终回合结果，含 Authority、pending、计划、Memory、Reflection 等信息。

### 6. 真实关系

```text
LLM JSON
  ↓ Pydantic parse / limited repair
GameNPCTurnProposal
  └─ decision.action: AgentAction
       ↓ GoalPlanPolicy / Plan alignment / PublicActionContract / Authority
Approved AgentAction
       ↓ MultiCaseEpisodeService.submit_action_with_receipt()
CaseToolExecutor.execute()
       ↓ arguments → typed domain Command
CaseEngine.execute()
       ↓ EngineResult(new session + events)
MultiCaseEpisodeService + JsonStateStore
       ↓ world commit / memory projection
MultiCaseActionReceipt
       ↓ reload Observation / PlanEvaluator / AgentState / Reflection
CooperativeTurnResult
```

### 面试时的一句话版本

> 我的模型只在结构化 Proposal 里提出 `AgentAction`；Runtime 依次做规划、计划对齐、公开行动契约和权限校验，批准后由 `CaseToolExecutor` 把 ToolCall 转成强类型领域 Command，`CaseEngine` 依据权威状态计算新 Session 和事件，再由应用服务与 Store 提交。LLM 和 Agent 都没有直接写 World State 的路径。

## 二、盘点项目中的所有 Tool / Action

### 1. 数量口径

| 口径 | 数量 | 说明 |
|---|---:|---|
| `AgentActionType` | 2 | `respond`、`use_tool` |
| `ToolName` / Executor 支持能力 | 9 | 2 个只读 + 5 个调查 + 诊断 + 处置 |
| 主协作 Agent 当前公开可执行 Tool | 7 | 5 个调查 + 诊断 + 处置；GET 类被 Action Contract 拒绝 |
| `CaseActionType` 领域行动 | 7 | 与 7 个案件变更能力对应 |
| Engine Command 类型 | 3 | 调查统一为一个 Command，另有诊断、处置 |
| MCP structured tools | 9 | 与完整 `ToolName` 集合一致，但走独立入口 |

### 2. 真实 Tool 清单

| Action / Tool | 文件与入口 | 输入参数 | 作用 | 是否修改 State |
|---|---|---|---|---:|
| `get_player_view` | `case_tools.py` / `CaseToolExecutor.execute` | `{}` | 生成权限过滤后的玩家只读视图摘要 | 否 |
| `get_case_observation` | 同上 | `{}` | 生成当前病例公开 Observation 摘要 | 否 |
| `observe_patient` | 同上 → `InvestigationCommand` | `investigation_id` | 执行公开望形调查 | 是 |
| `question_patient` | 同上 → `InvestigationCommand` | `investigation_id` | 执行公开问询调查 | 是 |
| `inspect_object` | 同上 → `InvestigationCommand` | `investigation_id` | 执行公开验物调查 | 是 |
| `observe_qi` | 同上 → `InvestigationCommand` | `investigation_id` | 执行公开察炁调查 | 是 |
| `investigate_location` | 同上 → `InvestigationCommand` | `investigation_id` | 执行公开地点调查 | 是 |
| `submit_diagnosis` | 同上 → `SubmitDiagnosisCommand` | `diagnosis_id`、可选 `evidence_clue_ids` | 记录诊断及引用证据 | 是 |
| `execute_treatment` | 同上 → `ExecuteTreatmentCommand` | `treatment_id` | 结算处置、案件状态与评分 | 是 |

这里的“修改 State”指会产生新 `CaseSessionState` 和领域事件；真正落盘还需应用服务提交。两个 GET Tool 返回原 session 且 events 为空。

### 3. 不应混入 Tool 数量的其他操作

`create_player`、`list_cases`、`start_episode`、`resume_episode`、`finish_episode`、`quit` 是 `MultiCaseEpisodeService` 的应用用例，不是 `ToolName`；`PlayerContribution` 是用户输入；Goal/Plan update 是模型 Proposal 的规划操作，也不是 Tool。把它们都称为 Agent Tool 会模糊执行授权边界。

## 三、Action、Tool、Function 到底有什么区别

| 概念 | 本项目中的含义 | 示例 |
|---|---|---|
| Proposal | 模型一次完整结构化提议，包含 Goal/Plan 更新与 Decision | `GameNPCTurnProposal` |
| Action | Decision 中本回合要做的业务动作；可能只是回复，也可能要求 Tool | `AgentAction(action_type=USE_TOOL, ...)` |
| Tool | 有限能力接口名及其参数请求 | `ToolCallRequest(name=INSPECT_OBJECT, arguments=...)` |
| Executor | Tool 到领域 Command 的适配和参数防线 | `CaseToolExecutor.execute()` |
| Engine | 依据完整权威状态执行领域规则、计算新状态 | `CaseEngine.execute()` |
| Function | 代码层真实被调用的方法，不是架构授权概念 | `_investigate()`、`save_case_session()` |

本项目中 7 个变更型 Tool 与 `CaseActionType` 高度重合，但并非完全同义：五类调查 Tool 最终都转为同一个 `InvestigationCommand`；而 `RESPOND` 是 Action，却不是 Tool。Function 更不能等同 Tool，因为一次 Tool 会经过多个函数。

## 四、找到真正的执行入口

| 层级 | 文件 | Class / Function | 作用 |
|---|---|---|---|
| Proposal 接收 | `application/cooperative_runtime.py` | `CooperativeRuntime.handle()` | 调 `agent.propose_turn()` 接收完整 Proposal |
| Parse / schema | `agents/game_npc.py` | `GameNPCAgent._parse_turn()` | 将 LLM JSON 解析成 Pydantic Proposal，并做内部校验/有限修复 |
| Action 抽取 | `cooperative_runtime.py` | `handle()` 中 `decision.proposal.action` | Action 已在 Proposal 内，不存在另一次自由文本转换 |
| 最终 Contract | `cooperative_runtime.py` | `_resolve_contract()` | 校验当前公开 action space，允许一次定向 repair |
| Authority | `application/npc_authority.py` | `NPCAuthorityPolicy.evaluate()` | 判断自主、提议、需确认或禁止 |
| 应用执行入口 | `application/multicase.py` | `submit_action_with_receipt()` | 锁定 Session、去重、加载上下文、执行、提交 |
| Executor 入口 | `application/case_tools.py` | `CaseToolExecutor.execute()` | 参数解析、Tool dispatch、Command 构造 |
| Engine 入口 | `engine/case_engine.py` | `CaseEngine.execute()` | 领域 Command dispatch 和规则裁定 |
| 状态转换 | `case_engine.py` | `_investigate/_submit_diagnosis/_execute_treatment` | 生成新 session、ActionRecord、事件 |
| 物理写入 | `storage/json_store.py` | `save_case_session()` / `_write()` | temp + fsync + `os.replace` 原子替换单文件 |
| 回执 | `application/multicase.py` | `MultiCaseActionReceipt` | 区分 `not_committed/committed/unknown` |
| Runtime 写回 | `cooperative_runtime.py` | `handle()` 后半段 | 重读 Observation、评估 Plan、保存 AgentState、触发 Reflection |

函数级主链：

```text
ClinicService.submit_player_contribution()
→ CooperativeRuntime.handle()
→ GameNPCAgent.propose_turn()
→ GoalPlanPolicy.validate()
→ CooperativeRuntime._action_matches_plan()
→ CooperativeRuntime._resolve_contract()
→ NPCAuthorityPolicy.evaluate()
→ MultiCaseEpisodeService.submit_action_with_receipt()
→ CaseToolExecutor.execute()
→ CaseEngine.execute()
→ CaseEngine._investigate() / _submit_diagnosis() / _execute_treatment()
→ JsonStateStore.save_case_session()
→ CooperativeRuntime._resume()
→ DeterministicPlanEvaluator.evaluate()
→ JsonStateStore.save_cooperative_agent_state()
```

## 五、还原一次真实调查 Action 执行

以 `inspect_object` 为例。假设当前 Observation 暴露调查 `inspect_umbrella_paper`。

| 阶段 | 输入 → 输出 | 负责人 | 改 World？ | 失败行为 |
|---|---|---|---:|---|
| 1. LLM Proposal | JSON → `GameNPCTurnProposal` | `GameNPCAgent` | 否 | 格式/规划合同失败可有限 repair，最后 safe `RESPOND` |
| 2. Schema | `action_type=use_tool`、Tool 枚举、arguments dict | Pydantic | 否 | 非法枚举或缺字段不能形成 Action |
| 3. Planning | Goal/Plan/Decision → policy result | `GoalPlanPolicy` | 否 | 拒绝或 fallback，不执行 Tool |
| 4. Alignment | Action 与 active PlanStep 对比 | Runtime | 否 | 一次 Action Contract repair 后仍不对齐则拒绝 |
| 5. Public Contract | `inspect_object + investigation_id` 与当前 Observation 对比 | `PublicActionContractValidator` | 否 | 未公开、参数多余、Tool 类型不匹配则 repair/fallback |
| 6. Authority | Action → `AUTONOMOUS` | `NPCAuthorityPolicy` | 否 | 调查属于可逆信息行动；未知 Tool 则 forbidden |
| 7. Submit | `SubmitActionInput` | `MultiCaseEpisodeService` | 否 | session 关闭或 action 非 mutating Tool 则返回 rejected receipt |
| 8. Executor | arguments → `InvestigationToolArguments` → `InvestigationCommand` | `CaseToolExecutor` | 否 | Pydantic 参数错、调查不存在、类型不匹配则拒绝 |
| 9. Engine | 旧 Session + Command → `EngineResult` | `CaseEngine` | 计算新对象 | 重复调查、技能、前置线索等不满足则 `RuleViolation`，旧对象不变 |
| 10. Commit | 新 Session → JSON snapshot | Service + Store | **是，成为权威** | 保存异常时结果为 `unknown`，禁止盲目重放 |
| 11. Projection | committed events → Memory / index | Memory coordinator | 不改 World | 失败标记 pending，不回滚 World |
| 12. Observe | 重载 Session → post Observation | Runtime | 否 | 已提交后重读失败进入 post-commit recovery 状态 |
| 13. Evaluate | pre/post Observation + Action → Plan transition | PlanEvaluator | 改 AgentState | 失败不回滚 World，协作 operation 标记需恢复 |

示例参数的真实转换：

```text
{"name":"inspect_object","arguments":{"investigation_id":"inspect_umbrella_paper"}}
→ InvestigationToolArguments(investigation_id="inspect_umbrella_paper")
→ 从 CaseDefinition 查到 target_id 与 CaseActionType.INSPECT_OBJECT
→ InvestigationCommand(investigation_id, action_type, target_id, occurred_at)
→ EngineResult(session revision + 1, InvestigationCompletedEvent, message)
```

## 六、Executor 到底解决什么问题

### 当前实现的职责

- 独立 Class：`CaseToolExecutor`；
- 接收：已形成的 `AgentAction`、可信 `CaseDefinition/PlayerState/CaseSessionState` 与应用层时间；
- 返回：`ToolExecutionResult`；
- 做：强类型参数解析、Tool 分发、公开视图刷新、Tool→Command 转换、Engine 结果统一包装；
- 不做：LLM 推理、Goal/Plan 决策、协作 Authority、持久化、跨存储事务。

### 为什么 Runtime 不直接调用 Engine

Runtime 处理的是 Agent 生命周期和协作状态；Engine 处理的是领域 Command。若 Runtime 自己解析每种 Tool 参数、查 target、构造 Command，会把 orchestration 与领域适配耦合在一个巨型函数中，也会让 Web、MCP、普通页面难以复用同一执行逻辑。

### 为什么 Agent 不能直接调用 Tool

Agent 持有的是公开 Observation，不应接触隐藏 `CaseDefinition`、Repository 或 Store；其输出还可能幻觉、越权或引用过期 target。直接调用会绕过 Action Contract、Authority、可信时间和 Engine 规则。

### 真实收益与未实现项

Executor 确实提供解耦、参数规范化、统一 Tool result、可复用测试边界。它没有独立日志/Tracing sink、动态 health check、超时、取消或 retry manager；错误到公共结果的统一映射主要在 `MultiCaseEpisodeService` 与 `MCPApplicationService`，不能把所有工程能力都归到 Executor。

## 七、Action 如何映射到 Tool

本项目不是一种单一 dispatch 技术，而是三层组合：

1. `PublicActionContractValidator` 用 `if` 和 `INVESTIGATION_TOOL_BY_ACTION` 字典检查公开合法性；
2. `CaseToolExecutor` 用 `if` 分派 GET、诊断、处置，用 `INVESTIGATION_TOOL_ACTIONS` 字典将五个调查 Tool 映射为 `CaseActionType`；
3. `CaseEngine.execute()` 用 `isinstance(command, ...)` 实现 Command pattern 分派。

因此拿到 `submit_diagnosis` 后，程序会走 Executor 的显式分支，使用 `DiagnosisToolArguments` 解析参数，构造 `SubmitDiagnosisCommand`；Engine 再按 Command 类型调用 `_submit_diagnosis()`。没有通过字符串反射任意调用函数。

## 八、Tool 注册机制

### 当前没有通用 Tool Registry

主 Agent 执行链采用静态枚举 + 显式映射 + `if` 分派。不存在把 name、description、schema、handler、permission、metadata 放在一个统一 registry 的机制。

独立 MCP 入口有类似注册表的静态结构：

- `FROZEN_MCP_TOOL_NAMES`：9 个对外名字；
- `_TOOL_INPUTS`：ToolName → Pydantic input model；
- `_TOOL_DESCRIPTIONS`：ToolName → 描述；
- `_make_structured_tool()`：生成 MCP `Tool` 与 JSON Schema。

但这只是 MCP server 的静态装配，不是主 Agent Runtime 的动态 Registry。

### 新增 Tool 要修改哪些地方

至少要检查：`ToolName`、可能的 `CaseActionType`、参数模型、公开 Action 投影/Validator、Goal/Plan 能力约束、Authority、Executor dispatch、Command/Engine、Observation/Memory/Campaign 投影、MCP 映射与测试。第 31 节给出完整流程。

## 九、Tool Schema / 参数定义

### 四层参数契约

| 层 | 结构 | 特点 |
|---|---|---|
| LLM 输出 | `ToolCallRequest.arguments: dict[str, JsonValue]` | 灵活承接 JSON，但只有 ToolName 枚举约束 |
| 当前公开 Contract | `PublicActionContractValidator` | 检查精确 key、当前可见 target、证据子集、readiness |
| Executor arguments | `Empty/Investigation/Diagnosis/TreatmentToolArguments` | Pydantic、`extra="forbid"`、frozen |
| Engine Command | 3 个不可变 Pydantic Command | 补入可信 `occurred_at`、action type、target id |

真实诊断转换：

```text
Proposal.arguments
  {diagnosis_id: str, evidence_clue_ids?: list[str]}
→ PublicActionContractValidator
  候选必须公开、diagnosis 已开放、证据必须已发现
→ DiagnosisToolArguments
  evidence list 转为 frozenset，拒绝额外字段
→ SubmitDiagnosisCommand
  加入可信 timezone-aware occurred_at
→ CaseEngine._submit_diagnosis()
```

MCP 入口另有 `MCPToolInput` 系列，在业务参数外要求 `player_id/session_id`；server 用其 JSON Schema 生成 structured tool，然后移除作用域字段，将剩余 arguments 交给同一个 Executor。

## 十、参数校验：Schema 合法不等于 Action 可执行

| 校验类型 | 项目示例 | 负责层 |
|---|---|---|
| 类型 | `confidence` 为严格 float 且 0～1；ID 是非空合法 Identifier | Pydantic domain model |
| 枚举 | `ToolName`、`AgentActionType`、`CaseActionType` | Pydantic + Enum |
| 必填/互斥 | `USE_TOOL` 必须有 tool_call；调查必须且只能有 `investigation_id` | Action model + Contract |
| 当前公开范围 | target 必须出现在最新 Observation 的 available 集合 | Action Contract |
| 业务规则 | 调查不能重复、技能和线索前置必须满足 | Engine |
| 状态前置 | Session 必须 active；处置前必须已有诊断 | Service + Engine |
| 权限 | 诊断需协商，处置需确认 | Authority |

Pydantic 只能证明“形状像一个合法命令”，不能证明它适用于当前世界。例如 `{treatment_id: "treatment_a"}` 类型完全合法，但若尚未提交诊断，Engine 会抛 `diagnosis_required`；若该处置不在最新公开列表，Action Contract 会更早拒绝。

## 十一、Tool 的前置条件

| Tool | 主要前置条件 | 谁检查 |
|---|---|---|
| 两个 GET | 空参数、player/session/case 作用域有效 | Executor / ContextFilter |
| 五类调查 | 当前公开；Tool 与 action type 匹配；未完成/同需求未满足；技能解锁且等级足够；所需线索已发现；session active | Contract + Executor + Engine |
| `submit_diagnosis` | 当前公开候选；readiness 开放；证据均已发现；确认匹配；session active | Contract + readiness policy + Authority + Engine |
| `execute_treatment` | 当前公开处置；具体确认匹配；已有诊断；所需线索已发现；session active | Contract + Authority + Engine |

PlanStep 允许某 Tool 只是计划对齐条件，不是领域前置或权限凭证。即使 Policy/Contract 检查时合法，执行前状态也可能改变；因此 Engine 根据刚加载的权威 Session 再验证。

## 十二、Tool 与 Action Contract 的关系

Action Contract 在本项目中定义的是“本轮公开视图允许形成什么 Action”，包括：

- Tool name；
- 精确 arguments key；
- 公开 investigation / diagnosis / treatment target；
- `can_submit_diagnosis`；
- 诊断证据必须是 discovered clue 的子集；
- investigation action type 与 Tool binding。

它不负责执行、不决定用户权限、不检查所有隐藏领域规则，也不提交状态。

> Action Contract 回答“这个模型输出能否成为当前公开范围内的合法 Action”；Executor 回答“如何把已批准 ToolCall 翻译成领域 Command”；Engine 回答“在权威状态上该 Command 实际是否成立”。

## 十三、Tool 与 Policy 的关系

项目中的“Policy”不是单一总开关：

- `GoalPlanPolicy` 检查 Goal/Plan 更新、能力与 Decision 的结构关系；
- Runtime 的 `_action_matches_plan()` 检查最终 Action 是否对应 active PlanStep；
- `PublicActionContractValidator` 检查当前公开行动；
- `NPCAuthorityPolicy` 检查风险权限。

Tool/Engine 仍做防御性检查。上层通过后若状态已改变，Executor 可能找不到 investigation，Engine 可能返回 `investigation_already_completed`、`session_closed` 或前置条件错误。应用服务将稳定 `RuleViolation.code` 映射为 `ok=False`；不保存新 world，Runtime 记录一次公开失败反馈并让 PlanEvaluator 看到 `tool_succeeded=False`。

## 十四、Tool 与 Authority 的关系

```text
Proposal
  ↓ Planning / Alignment / Public Action Contract
Candidate ToolCall
  ↓ NPCAuthorityPolicy
AUTONOMOUS | PROPOSAL_ONLY | CONFIRMATION_REQUIRED | FORBIDDEN
  ↓ only AUTONOMOUS
Executor
```

当前分级：

- `RESPOND`：自主；
- 两个 GET 与五类调查：自主；
- `submit_diagnosis`：`PROPOSAL_ONLY`，匹配确认后转为自主；
- `execute_treatment`：`CONFIRMATION_REQUIRED`，匹配确认后转为自主；
- 其他：禁止。

Tool 存在只代表系统具备能力，不代表当前 Agent、当前状态、当前用户确认已经授予执行权。Authority 是对“谁可以在何种风险下触发能力”的独立约束。

## 十五、用户确认与 Tool 调用

真实流程不是“保存 Action 后确认直接执行”，而是：

```text
Agent 提出诊断/处置 ToolCall
→ Authority 返回 proposal_only / confirmation_required
→ Runtime 创建 PendingActionConfirmation，不执行 Tool
→ ClinicService 存入进程内 cooperative_pending
→ 玩家携 confirmation_id + responds_to_decision_id 发 APPROVAL
→ 校验 player/case/session/revision/decision 关联
→ 再调用一次 LLM 生成本轮 Proposal
→ 只有新 Proposal.tool_call 与 pending.action.tool_call 完全相等
   才把 pending.decision_id 交给 Authority，获得 AUTONOMOUS
→ Executor 执行
```

具体回答：

- **pending 保存在哪里：** `ClinicService.cooperative_pending` 进程内字典；`PendingActionConfirmation` 含 confirmation/decision/player/case/session/action/authority/revision。
- **如何关联：** 请求提供 `pending_confirmation_id` 和 `responds_to_decision_id`；Clinic 与 Runtime 都校验作用域、decision 和当前 Case revision。
- **是否重新调用 LLM：** 是。批准是新的协作 turn，Agent 会重新生成 Proposal。
- **参数是否重新生成：** 是，模型会重新输出 Action；但要获得旧确认授权，新 `tool_call` 必须与 pending 中保存的 `tool_call` 精确相等。
- **如何避免确认 A 执行 B：** 通过 scope + decision + revision + exact `ToolCallRequest` equality。代码没有名为 `action_digest` 的字段。
- **当前边界：** pending 不是 durable 状态，进程重启后不会恢复；这是 fail-closed——确认失效而不是误执行，但用户需重新协商。也没有 TTL/后台清理机制。

## 十六、Tool 执行过程中谁修改 World State

需要区分三种“修改权”：

| 层 | 实际职责 | 是否直接写持久状态 |
|---|---|---:|
| Executor | 参数/Tool 适配，构造 Command | 否 |
| CaseEngine | 拥有领域转换权；从旧 Session 计算合法新 Session + events | 否 |
| MultiCaseEpisodeService / MemoryCoordinator | 编排 world-first 提交及后续投影 | 是，调用 Store |
| JsonStateStore | 将完整 Session 快照原子替换到 JSON 文件 | 是，物理写入 |

`CaseEngine._updated_session()` 使用旧对象的 dump 加 changes 再验证成新对象，不修改传入对象。只有 `save_case_session(execution.session)` 成功返回后，新 Session 才成为持久化 source of truth。

> 在我的项目里，`CaseEngine` 拥有权威领域状态转换权，应用服务和 `JsonStateStore` 拥有提交与物理写入权；LLM、Agent、Runtime 和 Executor 都没有直接写 World State 的路径。

## 十七、为什么不能让 LLM 直接修改 World State

- **幻觉：** 模型可能编造不存在的线索、诊断或 Tool。
- **参数错误：** JSON 类型正确也可能引用过期或隐藏 target。
- **越权：** 模型不能把“我认为应该处置”变成用户确认。
- **状态一致性：** 事件序号、revision、action history、线索集合必须一起变化。
- **不可逆副作用：** 处置会完成案件并决定 outcome/score。
- **审计：** 领域事件与稳定 error code 能解释发生了什么。
- **测试：** Engine 可脱离 LLM 做确定性单元测试。
- **并发：** Session 锁和提交边界属于程序控制面。
- **错误恢复：** world commit unknown 时必须保守阻断，不能让模型猜测并重试。

可以把职责概括为：LLM 说 “I want to do X”；Contract/Authority 说 “X 是否允许进入执行层”；Engine 说 “在当前事实下 X 实际改变什么”；Store 的成功提交才说 “变化已经成为事实”。

## 十八、Execution Result 设计

### 1. `ToolExecutionResult`

| 字段 | 含义 | 谁生成 | 谁消费 |
|---|---|---|---|
| `session` | 候选的新 Session；读 Tool 时可等于旧 Session | Executor / Engine | MultiCase 或 MCP application service |
| `events` | 本次领域事件；读 Tool 可为空 | Engine，经 Executor 包装 | 提交、Memory、公开 event sequence |
| `message` | 安全环境消息 | Engine / read Tool branch | 应用结果、Runtime、PlanEvaluator、UI |
| `score_breakdown` | 处置评分明细，可空 | Engine | receipt / completed projection |

### 2. 提交层补充

`MultiCaseActionReceipt` 还包含 `result`、`world_commit_status`、`events`、`score_breakdown`、`memory_commit_status`、`memory_error_code`、`memory_ids`。`MultiCaseServiceResult` 包含 `ok/error_code/message`、player/case/session ID 与 revision、Observation、action options、episode result、event sequences、Campaign 投影等真实字段。

### 3. 为什么不能只返回字符串

字符串无法可靠区分“Engine 拒绝”“world 已提交但 Memory 失败”“提交结果未知”，也无法驱动 PlanEvaluator、Observation revision、Memory projection、事件审计和精确测试。结构化结果让 Runtime 不必从自然语言猜测成功与否。

## 十九、执行成功以后发生什么

成功的 mutating Tool 并不意味着 Runtime 立即结束：

```text
EngineResult
→ 保存 CaseSessionState（world commit）
→ 投影 ordinary Memory
→ 尝试更新 Memory index
→ 若案件完成，投影 Campaign
→ 返回 MultiCaseActionReceipt(committed)
→ Runtime 重新加载 post Observation
→ DeterministicPlanEvaluator 推进/修订/完成 Plan
→ 保存 CooperativeAgentState
→ 构造 CooperativeTurnResult
→ 触发 post-commit Reflection
→ cooperative History 写 completed result
```

顺序边界：

- World 先于 AgentState，是权威事实；
- Memory/index/Campaign/AgentState/Reflection/History 不在同一事务；
- AgentState 保存失败时结果仍是 `ACTION_EXECUTED`，但附 `agent_state_projection_pending`；
- Reflection 失败不会回滚 World；
- `CooperativeRuntime.handle()` 一次请求执行至多一个 Tool，然后结束本 turn；下一次行动由下一请求触发。

## 二十、Tool 执行失败以后发生什么

| 失败 | 谁发现 | 返回/抛出 | World 是否变化 | 重试/LLM 行为 |
|---|---|---|---:|---|
| Tool 名不在 Enum | Proposal Pydantic parse | structured validation failure | 否 | 最多一次格式修复，最后 safe fallback |
| GET Tool 被主 Agent 提出 | Public Action Contract | `unsupported_action` | 否 | 一次 action repair，仍失败则 `RESPOND` fallback |
| 参数类型/多余字段错误 | Contract 或 Executor Pydantic | `invalid_tool_arguments` | 否 | Contract 可一次定向 repair；执行层不自动重试 |
| 当前公开 State 不满足 | Contract | `unknown_*` / readiness 等 | 否 | repair 或拒绝 |
| Plan 不匹配 | Runtime alignment | `plan_decision_mismatch` 类拒绝 | 否 | 不执行；下一轮收到固定公开反馈 |
| 权限不足 | Authority | pending 或 forbidden reason | 否 | pending 等用户；forbidden 不自动重试 |
| Engine 业务规则失败 | Engine | `RuleViolation.code` | 否 | MultiCase 返回 `ok=False`；本 turn 不重调 LLM |
| Executor/Engine 意外异常 | MultiCase | `internal_error` | 在保存前确定未提交 | 不自动重试；公开消息不泄漏内部异常 |
| World 保存异常 | Service/Store | `world_commit_uncertain` + receipt `unknown` | **无法断言** | 协作 operation 进入 recovery 阻断，禁止盲目重放 |
| Memory 投影失败 | Memory coordinator | `projection_pending` | World 已提交 | 不重放 Tool；后续 reconcile |
| Index 失败 | MultiCase | `index_pending` | World 已提交 | 可重建索引，不重放 Tool |
| Campaign 失败 | completed projection | `campaign_projection_pending` | World 已提交 | `reconcile_campaign`，不重放 Tool |
| post Observation / PlanEvaluator 失败 | Runtime | `CooperativePostCommitError` | World 已提交 | History 标记 recovery，禁止同 operation 重放 |
| AgentState 保存失败 | Runtime | `ACTION_EXECUTED` + `agent_state_projection_pending` | World 已提交 | 不重放 Tool；当前没有完整自动恢复闭环 |
| 外部 Tool 超时 | 不适用 | 主执行 Tool 全部为本地同步代码 | 不适用 | 当前没有外部 Tool timeout/retry manager |

注意 `MultiCaseEpisodeService` 在调用 Engine 前后的异常语义不同：Engine/参数拒绝发生在保存前，可确定未提交；`save_case_session()` 抛错可能发生在 `os.replace` 前或后，所以只能标为 unknown，不能对用户声称“状态未改变”。

## 二十一、可重试错误 vs 不可重试错误

项目没有一个统一 `RetryableError` 分类器，但代码已形成明确边界：

| 错误 | 当前是否自动重试 | 原因 |
|---|---:|---|
| LLM JSON/结构错误 | 有限：最多一次 repair | 尚未进入副作用层，且 repair 有明确上限 |
| Action Contract 错误 | 有限：最多一次定向 repair | 只修公开 shape，不执行旧 Action |
| 参数错误 | 否 | 执行层不应让模型无界猜参数；下一用户 turn 可基于反馈重决策 |
| Policy / Alignment 拒绝 | 否 | 代表语义/计划冲突，不是瞬时基础设施错误 |
| Authority 拒绝 | 否 | 重试不能创造权限；需真实确认或换行动 |
| Engine 业务失败 | 否 | 代表权威状态/规则不满足 |
| Tool 超时 | 不适用 | 当前没有外部 Tool，也没有超时机制 |
| Provider 429/timeout | 否 | DeepSeek adapter 明确无隐式网络重试，避免重复计费与不透明延迟 |
| World commit unknown | **禁止自动重试** | Tool 可能已经产生持久副作用 |
| Memory/index/Campaign 投影失败 | 不重试 Tool；可对账/重建派生层 | World 已提交，重做业务动作会重复副作用 |

Tool 失败不能一律“让 LLM 再试一次”：权限失败需要外部授权，业务失败需要新事实或新计划，unknown 可能已经提交。只有确定处于 pre-commit 且错误可安全修正，才适合新的 operation 重新决策。

## 二十二、幂等性

### 1. 同一个 Action 执行两次会怎样

- 调查：Engine 检查 action history，重复同一 investigation 返回 `investigation_already_completed`；同一 requirement 已由其他调查满足也会拒绝。
- 诊断：Engine 当前没有禁止重复提交诊断；只要 session 仍 active，直接入口重复调用可以追加新的诊断记录并增加 revision。
- 处置：第一次会把 session 设为 completed；第二次被 `session_closed` 拒绝。
- GET：只读，可重复。

### 2. 不同入口的 operation 幂等保证

| 入口 | 当前实现 |
|---|---|
| 协作入口，recording 开启 | SQLite cooperative History 按 player/case/session/operation + fingerprint；completed 返回原结果，payload 冲突拒绝，started/prepared/recovery 阻断重放 |
| 协作入口，recording 关闭 | 只剩本进程锁与下层精确请求 cache，无跨重启保证 |
| 普通页面行动 | `operation_id` + payload 进程内 receipt；同 ID 不同 payload 冲突；重启丢失 |
| 直接 MultiCase | cache key 包含 root/session/action_id/完整 fingerprint；完全相同请求复用 receipt，但同 action ID 不同 payload 可形成另一个 key |
| MCP | 没有调用级 operation ID；内部 `action_id=mcp_<tool>` 不构成幂等账本 |

所以不能笼统说“所有 Tool 都幂等”。准确说法是：协作产品入口在默认 recording 下有持久 operation replay/阻断；Engine 对部分领域动作有重复防御；MCP 与直接入口没有统一跨重启 exactly-once。

## 二十三、原子性与事务

### 已有保证

- Engine 对一个 `CaseSessionState` 聚合一次性构造完整新对象；Pydantic 验证失败就没有结果；
- World 单文件保存使用临时文件、flush、`fsync`、`os.replace`，不会逐字段半写；
- SQLite Memory/history 各自使用局部数据库事务和唯一约束；
- Session 锁覆盖受控入口的读—计算—写。

### 没有的保证

不存在覆盖 World JSON、Memory SQLite、Campaign JSON、AgentState JSON、Reflection 与 History 的全局事务。真实顺序是 world-first；World 成功后 Memory 或 AgentState 失败，会出现部分提交，但系统保留 `pending/error/recovery_required`，不伪装成整体回滚。

因此“一个 Tool 同时改多个 World 字段”在**单个 Session JSON 聚合内**是完整快照替换；“一个 Tool 影响多个存储域”则不是全部成功或全部失败。

## 二十四、并发执行

项目 Web 使用线程服务器，确实存在并发请求。当前受控写入口共享 [`JsonStateStore.session_write_lock()`](../../src/xuanyi_npc/storage/json_store.py#L51)：键是 `(resolved state root, session_id)`，值为进程内 `RLock`。

这把锁覆盖：

- Cooperative Runtime 整个 turn；
- MultiCase 的 load → Engine → commit → projection；
- Clinic 普通 action；
- MCP 的 load → execute → save。

因此同一 Python 进程、同一 root、同一 Session、经受控入口的两个请求会串行，不会在普通线程场景同时基于同一旧 snapshot 覆盖。不同 Session 可以并行。

边界：

- 锁不跨进程；
- `save_case_session()` 没有 expected revision/CAS；
- 直接调用 Store 可以绕过锁；
- AgentState 有 expected revision 检查，但读取—检查—替换也不是跨进程原子 CAS；
- 没有数据库级 World 事务。

面试中应说“单进程核心写路径按 Session 串行化”，不能说“并发问题已经彻底解决”。

## 二十五、Tool 调用是否同步

主 Agent Tool 链全部是本地同步调用：Runtime、MultiCase、Executor、Engine、JSON save 都不是 `async/await`，也没有 background job 或事件队列。MCP server 的 `dispatch` 是 `async def` 以符合协议框架，但内部直接同步调用 `MCPApplicationService.execute_tool()`，并没有异步领域执行。

选择理由与项目规模相符：每 turn 至多一个 Tool、Tool 全在本进程、状态转换很快，同步顺序更容易证明 Authority、commit 和 post-commit 语义。代价是 LLM、embedding 或文件 I/O 会占用请求线程；当前没有并行 Tool、取消或长任务调度。

## 二十六、Tool 是否有副作用

### Read-only Tool

- `get_player_view`
- `get_case_observation`

它们返回原 session、零 events，不落盘；主 Agent Runtime 通常直接构造 Observation，独立 MCP 会真实暴露这两个 Tool。

### Mutating Tool

- 五类调查；
- `submit_diagnosis`；
- `execute_treatment`。

它们产生新 session 与领域事件，随后可能触发 Memory、Campaign、Agent Plan 与 Reflection 等派生副作用。诊断和处置风险更高，Authority 要求协商/确认；处置会结束 session，必须按具体 pending Action 授权。

## 二十七、Tool 和 Environment 的关系

本项目的 Environment 不是单一外部 API，而是：

- `CaseDefinition`：完整可信案件规则与隐藏真相；
- `PlayerState`：玩家能力；
- `CaseSessionState`：当前权威世界状态；
- `CaseEngine`：环境转移函数；
- JSON/SQLite 存储：持久事实与派生状态；
- `CaseObservation`：环境对 Agent 的权限过滤投影。

```text
GameNPCAgent
→ AgentAction / ToolCallRequest
→ Contract + Authority
→ CaseToolExecutor
→ CaseEngine(case, player, session, command)
→ new CaseSessionState + events
→ Store commit
→ CaseObservation
→ next Agent turn
```

Tool 是 Agent 与 Environment 的受控交互接口，但完整边界还包括验证、授权和提交；单独一个函数名不能代表全部安全边界。

## 二十八、Function Calling 在本项目中的位置

主 Agent 当前**没有使用模型厂商原生 Function Calling**。DeepSeek adapter 请求使用 `response_format={"type":"json_object"}`，完整 Pydantic JSON Schema 被注入 prompt/provider payload；模型返回普通 JSON，再由 `GameNPCAgent` 解析。没有向 provider 发送 `tools`、`tool_choice`，也不消费 provider `tool_calls`。

项目中的 `ToolCallRequest` 是自定义领域对象，不是 OpenAI/DeepSeek 原生 tool-call 消息。

> 当前项目没有把模型原生 Function Calling 作为最终执行授权机制；事实上主 Agent 连原生 Function Calling 都没有使用。即使未来采用，它也只替代“模型如何表达调用意图”，不能替代当前状态校验、Authority、Executor、Engine 与 commit receipt。

Function Calling 能保证输出更像函数参数，却不能知道用户是否确认、Observation 是否过期、证据是否已发现、写入是否成功，更不能提供跨存储事务。

## 二十九、MCP 和本项目 Tool 机制的关系

MCP 解决的是模型/Agent 如何通过标准协议发现和调用外部能力。它不是 Tool 的业务语义本身，也不是 Executor、Policy 或 Authority。

项目确实有独立 `xuanyi-mcp-stdio`：

```text
MCP client
→ MCP structured tool（9 个）
→ Pydantic MCPToolInput
→ MCPApplicationService.execute_tool()
→ CaseToolExecutor
→ CaseEngine
→ JsonStateStore
```

它与主协作 Agent 共享 `ToolName`、`CaseToolExecutor`、`CaseEngine` 和 Store，但主 Agent Runtime **不通过 MCP client 调 Tool**。MCP path 不调用 LLM、Goal/Plan、PublicActionContract 或 `NPCAuthorityPolicy`；它被设计为另一个直接应用接口，由严格 schema、公开视图与 Engine 保护，而不是继承协作 NPC 的确认语义。

这意味着两点：

1. 不能说“主 Agent 使用 MCP 调工具”；
2. 若未来把 MCP 暴露给不受信任的远程 Agent，就必须在 MCP 边界另加身份认证、调用级 Authority/confirmation、durable operation ID 和 sandbox；当前本地 stdio 不具备这些生产级保证。

## 三十、为什么没有直接使用 LangChain / LangGraph Tool

当前自研执行层与问题形态匹配：

- Tool 集合固定且只有 9 个；
- 当前公开 action space 每 turn 随 Observation 变化；
- 诊断/处置需要与 decision、scope、revision 和 exact ToolCall 绑定的确认；
- Engine 是已有的强领域状态机，不应由通用 Tool wrapper 取代；
- 需要显式区分 `not_committed/committed/unknown` 与 post-commit projection；
- 每 turn 最多一个 Tool，不需要通用并行 Tool DAG。

这不是说 LangGraph/LangChain 做不到，而是引入后仍需保留 Action Contract、Authority、Engine、Store 和 recovery 语义；框架主要替换 orchestration/Tool adapter，不能自动提供本项目的领域保证。当前显式 Python 调用链更容易审计。若未来出现大量异构远程 Tool、长任务、分支并发和 durable workflow，LangGraph 或工作流引擎才更有价值。

## 三十一、增加一个新 Tool 的完整流程

假设新增一个当前不存在的变更型能力 `collect_sample`，用于采样调查。若它只是现有调查的一种新类型，标准流程是：

1. 在 `ToolName` 增加 `COLLECT_SAMPLE`；若要进入领域 action history，也在 `CaseActionType` 和 `INVESTIGATION_ACTIONS` 增加对应类型。
2. 在案件资源的 `InvestigationDefinition` 中声明可公开调查、target、线索、技能和前置。
3. 在 `INVESTIGATION_TOOL_BY_ACTION` 增加 CaseActionType → ToolName，使公开投影和 Contract 接受它。
4. 在 `INVESTIGATION_TOOL_ACTIONS` 增加 ToolName → CaseActionType，使 Executor 能构造 `InvestigationCommand`。
5. 在规划允许 Tool 集合/Goal capability 中加入它，否则 A1 PlanStep 可能无法表达或校验。
6. 在 `AUTONOMOUS_TOOLS` 或 Authority policy 中明确风险等级；不要因枚举存在就默认授权。
7. 若沿用通用 InvestigationCommand，Engine 的调查分支可复用；若采样有新状态字段或副作用，应新增独立 Command、Engine 分支与事件，而不是把逻辑塞进 Executor。
8. 检查 Observation、Memory projection、Campaign/评测统计是否需要认识新事件或 action type。
9. 若对 MCP 暴露，更新 `FROZEN_MCP_TOOL_NAMES`、`_TOOL_INPUTS`、description 和 input contract。
10. 增加 domain、Contract、Authority、Executor/Engine、service integration、MCP、重复执行、并发与故障测试。
11. 更新 prompt/action projection 与架构文档，并运行全量回归。

若新增的是纯只读 Tool，则不应伪造 Engine event；可以像 GET Tool 一样返回原 session 与零 events，但仍需明确数据可见性和调用权限。

## 三十二、Tool 测试体系

| 测试层 | 代表文件 | 主要证明 |
|---|---|---|
| Engine 单元 | `tests/test_case_engine.py` | 调查/诊断/处置规则、新 Session、事件、评分、各种 RuleViolation |
| Public Contract | `tests/test_m5_public_action_space.py` | 当前公开 target、参数 key、隐藏真相不暴露、非法 Action 拒绝 |
| Authority | `tests/test_m1_npc_authority.py` | autonomous/proposal/confirmation/forbidden 分类 |
| Runtime 集成 | `tests/test_m1_cooperative_runtime.py` | Proposal→Authority→Tool→结果主链 |
| Planning/Alignment | `test_m2_cooperative_runtime_planning.py`、`test_p2_plan_decision_alignment.py`、`test_p4_treatment_action_contract.py`、`test_p5_executable_step_commitment.py` | Action 必须与 Plan/诊断/处置契约一致 |
| Service integration | `tests/test_multicase_episode_service.py` | 执行、持久化、公开结果、错误映射 |
| MCP | `tests/test_mcp_p0.py`、`test_mcp_stdio.py` | 9 个 structured tools、schema、读写、错误与 stdio |
| Commit / concurrency / idempotency | `tests/test_commit_consistency_faults.py`、`test_context_engineering_ce2a.py` | Session 串行、重复 operation、commit unknown、post-commit failure、重启阻断 |

覆盖不仅有正常路径，还包括非法参数、权限拒绝、状态不满足、重复调查、world 保存异常、Memory/Campaign/AgentState 后提交失败、并发写和 replay。证明方式是断言 Session revision、action history、领域 event、error code、receipt 生命周期与持久文件，而不是只看 UI 文案或手工试玩。

## 三十三、从输入到状态变化的完整时序图

```mermaid
sequenceDiagram
    actor User
    participant Clinic as ClinicService
    participant Runtime as CooperativeRuntime
    participant Agent as GameNPCAgent
    participant LLM
    participant Contract as Policy/Contract/Authority
    participant Service as MultiCaseEpisodeService
    participant Executor as CaseToolExecutor
    participant Engine as CaseEngine
    participant Store as JsonStateStore

    User->>Clinic: PlayerContribution
    Clinic->>Runtime: handle(contribution, pending?)
    Runtime->>Service: resume_episode()
    Service-->>Runtime: public Observation
    Runtime->>Agent: propose_turn(context)
    Agent->>LLM: JSON request + schema
    LLM-->>Agent: structured Proposal
    Agent-->>Runtime: GameNPCTurnProposal / Decision
    Runtime->>Contract: GoalPlanPolicy + alignment + ActionContract
    Contract-->>Runtime: accepted / repair / reject
    Runtime->>Contract: NPCAuthorityPolicy.evaluate(action)
    alt requires confirmation
        Contract-->>Runtime: pending
        Runtime-->>Clinic: PendingActionConfirmation
        Clinic-->>User: ask confirmation; no Tool executed
    else autonomous
        Runtime->>Service: submit_action_with_receipt(action)
        Service->>Executor: execute(action, case, player, session)
        Executor->>Engine: execute(typed Command)
        Engine-->>Executor: EngineResult(new session, events)
        Executor-->>Service: ToolExecutionResult
        Service->>Store: save_case_session(new session)
        Store-->>Service: committed or exception
        Service-->>Runtime: MultiCaseActionReceipt
        Runtime->>Service: resume_episode()
        Service-->>Runtime: refreshed Observation
        Runtime->>Runtime: PlanEvaluator + save AgentState + Reflection
        Runtime-->>Clinic: CooperativeTurnResult
        Clinic-->>User: dialogue + environment result
    end
```

## 三十四、真实代码级调用链：`inspect_object`

| 顺序 | 文件 / Function | 关键输入 | 输出 |
|---:|---|---|---|
| 1 | `application/clinic.py` `submit_player_contribution()` | `ClinicContributionInput` | 进入 Session 锁和 operation ledger |
| 2 | `application/cooperative_runtime.py` `handle()` | `CooperativeTurnInput` | 本轮 orchestration |
| 3 | `agents/game_npc.py` `propose_turn()` / `_parse_turn()` | Context + LLM JSON | `GameNPCTurnProposal` / `GameNPCDecision` |
| 4 | `application/goal_plan_policy.py` `validate()` | Proposal + current state + Observation | 接受或拒绝 |
| 5 | `cooperative_runtime.py` `_action_matches_plan()` | Decision + AgentState | bool |
| 6 | `application/action_contract.py` `validate()` | `AgentAction` + Observation | 通过或 `PublicActionContractError` |
| 7 | `application/npc_authority.py` `evaluate()` | Action + confirmation IDs | `AuthorityDecision` |
| 8 | `application/multicase.py` `submit_action_with_receipt()` | `SubmitActionInput` | 锁、缓存、调用一次提交 |
| 9 | `application/case_tools.py` `execute()` | Action + trusted context | `InvestigationToolArguments` → `InvestigationCommand` |
| 10 | `engine/case_engine.py` `execute()` / `_investigate()` | Command + old Session | `EngineResult(new session, event)` |
| 11 | `application/memory_coordination.py` `commit_engine_result()` | previous session + result | 先 world、后 Memory receipt |
| 12 | `storage/json_store.py` `save_case_session()` | new Session | 原子替换 JSON snapshot |
| 13 | `cooperative_runtime.py` `_resume()` | scope IDs | post Observation |
| 14 | `application/plan_evaluator.py` `evaluate()` | pre/post Observation + Action | Goal/Plan transition |
| 15 | `json_store.py` `save_cooperative_agent_state()` | AgentState + expected revision | Agent 投影持久化 |

在 IDE 现场建议按 2 → 6 → 7 → 8 → 9 → 10 → 12 → 13 的顺序打开，先讲控制链，再补 Agent parse 和 post-commit 投影。

## 三十五、Tool 执行的安全边界

| 边界 | 能做什么 | 不能做什么 |
|---|---|---|
| LLM | 基于公开 Context 提出 Proposal | 不能写 Store、不能授予权限、不能宣布状态已改变 |
| Validation | 检查 schema、规划、对齐、当前公开 Action | 不能代替最新权威领域规则 |
| Authority | 判定自主/待确认/禁止 | 不执行 Tool、不改变 Plan 或 World |
| Executor | 解析参数、映射 Command、统一结果 | 不持久化、不决定协作授权 |
| Engine | 依据完整可信状态裁定领域转移 | 不调用 LLM、不写文件 |
| State/Commit | Store 成功后形成权威事实 | 不接受 LLM 文本作为事实 |

System Prompt 写“不要执行危险操作”只能影响概率性输出，不能防止 prompt injection、模型 bug、过期 Context 或错误参数。确定性校验链的价值在于：即使模型不听话，也只能得到拒绝或 pending，不能越过程序的写入路径。

## 三十六、Tool 执行机制的最大风险

按当前代码证据排序：

1. **跨存储 post-commit 恢复未闭环。** World、Memory、Campaign、AgentState、Reflection、History 不在全局事务中；已有 pending/reconcile/recovery 阻断，但不能自动恢复所有玩家意图与公开回复。
2. **幂等保证因入口而异。** 默认协作入口最强；MCP 没有 operation ID，直接 MultiCase receipt 仅内存。不能对外统一承诺 exactly-once。
3. **MCP 不继承协作 Authority。** 本地 stdio 直接暴露 9 个 Tool；若未来让不受信任远程 Agent 使用，诊断/处置确认、身份认证和 durable receipt 必须在 MCP 边界补齐。
4. **静态映射分散。** 新 Tool 要同步修改枚举、正反映射、Planning、Authority、MCP、投影和测试，存在漏改导致接口漂移的风险；当前数量小所以可接受。
5. **重复诊断不是 Engine 级幂等。** 非协作直接入口可能重复追加 diagnosis ActionRecord。
6. **跨进程并发保护不足。** Session `RLock` 只在单进程有效；World 没有数据库 CAS。
7. **顶层异常诊断性有限。** MultiCase/MCP 会将未知异常收敛为安全 `internal_error`，防泄漏但缺少正式日志/Tracing 后端，排障证据可能不足。
8. **pending confirmation 不持久。** 重启后安全失效，但用户体验与恢复不完整。
9. **同步执行缺少 timeout/cancel。** 当前 Tool 都是本地快速操作所以影响有限；扩展远程 Tool 前必须增加。

## 三十七、设计文档 vs 真实代码

| 能力 | 文档描述 | 真实代码 | 是否一致 |
|---|---|---|---|
| Tool 定义 | `ToolName` 冻结能力集 | 9 个枚举，Executor 与 MCP 均支持 | 一致 |
| 主 Agent 公开 Tool | 从 Observation 投影调查/诊断/处置 | Contract 只接受 7 个；GET 两个不接受 | 基本一致，但容易把 9 个都说成主 Agent Tool |
| Action | 模型输出结构化 Action | Proposal 内嵌 `AgentAction`，不是 Runtime 再转换 | 一致，表述需精确 |
| Executor | Tool→Command 适配 | 参数解析、dispatch、Engine wrapper；不负责持久化/Authority | 一致 |
| Contract 顺序 | 架构图简化为 Schema→Policy→Align→Contract | Agent 内先做 schema/identity/contract/memory/policy；Runtime 又做 policy→apply intent→align→contract/repair→final align | **图是职责简化，不是精确调用顺序** |
| Authority | 调查自主、诊断协商、处置确认 | `NPCAuthorityPolicy` 如此实现 | 一致 |
| 确认绑定 | README 写 decision、action digest、world revision | 对象保存完整 Action；代码用 decision/scope/revision + exact `tool_call` equality，没有显式 `action_digest` 字段 | **语义接近，术语不完全一致** |
| Engine | “独占权威案件状态写入” | Engine 只计算新对象；Service/Store 才落盘 | **概念可理解，但代码级应区分转换权与物理写权** |
| State mutation | 只有 Engine 接受的转换成为事实 | Engine result 还必须成功保存 | 一致，需补 commit 条件 |
| Execution Result | 结构化结果与失败安全 | Engine/Tool/Service/Receipt/Turn 多层 result | 一致 |
| Retry | 有限修复、安全 fallback | 只对模型/Action Contract 有限修复；Tool/网络/unknown 不自动重试 | 一致 |
| Transaction | 单文件原子，跨存储非事务 | temp+fsync+replace；world-first 投影 | 一致 |
| MCP | 独立 stdio，主 Agent 不经过 MCP | MCP 共用 Executor/Engine，但跳过协作 Goal/Plan/Contract/Authority | 一致；面试必须补后半句 |

另外，[`PLANNING_AND_ACTION_DESIGN.md`](../architecture/PLANNING_AND_ACTION_DESIGN.md) 的流程图把职责画成单线顺序，适合架构概览，但不能当作函数级 trace。当前 README 的“CaseEngine 独占写入”也应在面试时解释成“独占合法领域转换”，而不是说 Engine 直接写数据库。

## 三十八、最终面试回答版

### 1. 30 秒回答：“你的 Agent 工具调用机制是怎么设计的？”

> 我的 Agent 不允许 LLM 直接执行函数。模型在结构化 Proposal 里生成一个 `AgentAction`，Runtime 先做 Goal/Plan、计划对齐、当前公开 Action Contract 和 Authority 校验。通过后，`CaseToolExecutor` 把 Tool 名和 JSON 参数解析成强类型领域 Command，`CaseEngine` 根据权威案件状态确定性地生成新 Session 和事件，应用服务再提交到 Store。提交结果会区分未提交、已提交和未知，成功后重读 Observation、推进 Plan 和 AgentState。这样把“模型想做什么”和“系统真实做成了什么”彻底分开。

### 2. 2 分钟回答

> 整条链从 `GameNPCTurnProposal` 开始。LLM 每次不只返回对话，还返回嵌套的 `AgentAction`：要么 `RESPOND`，要么 `USE_TOOL`。第一层 Pydantic 只保证 JSON 结构和枚举合法；之后 `GoalPlanPolicy` 检查 Goal/Plan 更新，Runtime 检查 Action 是否与当前 active PlanStep 对齐，`PublicActionContractValidator` 再确认 Tool、参数和 target 真在当前 Observation 的公开 action space 里。结构合法不代表有权限，所以接下来 `NPCAuthorityPolicy` 把调查设为自主、诊断设为协商、处置设为必须确认。
>
> 只有最终获得自主权限的 Action 才进入 `MultiCaseEpisodeService.submit_action_with_receipt()`。它在 Session 锁中加载最新状态，再调用 `CaseToolExecutor.execute()`。Executor 不是业务状态机，它负责把通用 JSON arguments 解析成 `InvestigationToolArguments` 等强类型模型，并构造 `InvestigationCommand`、`SubmitDiagnosisCommand` 或 `ExecuteTreatmentCommand`。真正的领域规则在 `CaseEngine`：它检查 session、重复操作、技能、证据和处置前置，然后返回新的不可变 Session 和领域事件。
>
> 这里还不能马上说执行成功，因为 Engine 不写存储。应用服务必须先把新 Session 通过 `JsonStateStore` 原子替换保存，才得到 `committed` receipt；如果保存抛错，就标记 `unknown`，禁止盲目重放。成功后 Runtime 重读 Observation，用 PlanEvaluator 推进计划，再保存 AgentState、处理 Memory 和 Reflection。所以这条链是 Proposal → Validation → Approved Action → Executor → Engine → Commit → Execution Result → Observation，而不是 LLM 输出一个函数名就算完成。

### 3. “Action 和 Tool 有什么区别？”

> Action 是本轮业务意图，顶层既可以是“回复”，也可以是“使用工具”；Tool 是 `USE_TOOL` Action 里选中的具体能力和参数。例如 `RESPOND` 是 Action 但不是 Tool，`inspect_object` 是 Tool。Tool 最终还要由 Executor 转为 Engine Command，因此 Tool 也不等于实际函数执行。

### 4. “为什么还需要 Executor？”

> 因为 LLM 输出的是通用 ToolName + JSON arguments，Engine 接受的是带可信时间、action type 和 target 的强类型领域 Command。Executor 隔离了这两个模型，统一参数解析、Tool dispatch 和结果包装，让 Runtime 不需要知道每个领域参数，也让 Web、MCP 和普通页面复用同一适配层。它不负责 Authority 或持久化，这两个边界仍然分开。

### 5. “为什么不能让 LLM 直接调用 Tool？”

> 因为模型只看到权限过滤后的 Observation，而且输出可能幻觉、过期或被注入；它不知道完整领域前置，也不能创造用户授权。直接调用会绕过当前 action space、确认、Session 锁、提交状态和恢复规则。我的设计让 LLM 只能提出 Proposal，程序才拥有批准与执行权。

### 6. “真正修改 World State 的是谁？”

> 精确答案分三层：`CaseEngine` 拥有领域转换权，从旧 Session 计算合法的新 Session 和事件；`MultiCaseEpisodeService` 拥有提交编排权；`JsonStateStore` 执行物理落盘。Engine 不直接写文件，Executor 更不写。只有 Engine 接受且 Store 成功提交的新 Session 才是权威 World State。

### 7. “Tool 失败怎么办？”

> 先按阶段区分。Schema/Contract 错误在副作用前最多做一次有限修复；Authority 不通过就 pending 或拒绝；Engine 业务失败返回稳定 error code 且不保存世界。World 保存失败则不能假设未提交，回执标记 `unknown` 并阻断自动重放。若 World 已提交、Memory 或 AgentState 后处理失败，则保留 World，通过 pending/recovery 处理派生层，绝不重放 Tool 来伪装事务回滚。

### 8. “Function Calling 和你这个 Tool 系统有什么区别？”

> 当前主 Agent 没用厂商原生 Function Calling，而是 `json_object + Pydantic Schema`。但即使换成 Function Calling，也只改变模型表达 Tool 意图的方式；它不能替代当前 Observation Contract、Authority、Executor、Engine、事务边界和 commit receipt。Function Calling 是模型协议能力，Tool 系统是应用执行与安全控制体系。

### 9. 白板版：6～8 个框怎么画

现场画 8 个框即可：

```text
[1 User / Observation]
          ↓
[2 LLM Proposal + AgentAction]
          ↓
[3 Policy + Plan Alignment + Action Contract]
          ↓
[4 Authority / Confirmation]
          ↓
[5 CaseToolExecutor: ToolCall → Command]
          ↓
[6 CaseEngine: rules → new Session + Events]
          ↓
[7 Service + Store: commit / receipt]
          ↓
[8 New Observation + Plan/AgentState update]
```

在第 4 框旁画一条 `pending → user approval → exact action match` 回路；在第 7 框写 `not committed / committed / unknown`。讲解时强调第 6 框只是计算新状态，第 7 框成功才形成事实。

## 三十九、高频面试追问

### 1. Proposal 和 Action 有什么区别？

- **考察点：** 是否把整次模型输出与单次可执行动作混为一谈。
- **推荐回答：** Proposal 是 Goal/Plan update、贡献评价、Decision、Memory usage 等完整结构；Action 只是 `decision.action`。Runtime 接收的是 Proposal，真正送入 Authority/Executor 的是其中最终修复后的 Action。
- **代码依据：** `domain/planning_contract.py` 的 `GameNPCTurnProposal`；`domain/cooperation.py` 的 `GameNPCDecisionProposal`；`domain/actions.py` 的 `AgentAction`。

### 2. Action 和 Tool 有什么区别？

- **考察点：** 抽象层次。
- **推荐回答：** Action 是“本轮做什么”，包括纯回复和用工具；Tool 是 `USE_TOOL` 内的具体能力。`RESPOND` 没有 Tool，`USE_TOOL` 必须有 `ToolCallRequest`。
- **代码依据：** `AgentAction.validate_action_shape()`。

### 3. 项目到底有多少 Tool？

- **考察点：** 是否真正盘点代码并理解口径。
- **推荐回答：** `ToolName` 和 Executor/MCP 支持 9 个；主协作 Agent 的 Public Action Contract 只允许 7 个变更型 Tool；另有 2 个 GET 只读 Tool。Action 顶层类型是 2 个。
- **代码依据：** `domain/actions.py`、`action_contract.py:179-197`、`mcp_server/server.py:FROZEN_MCP_TOOL_NAMES`。

### 4. 为什么 GET Tool 不在主 Agent action space？

- **考察点：** Observation 与 Tool 的关系。
- **推荐回答：** Runtime 在调用 Agent 前已经通过应用层构造了最新 `CaseObservation` 和 player view，无需模型再花一个 turn 刷新。Executor/MCP 保留 GET 能力供独立客户端使用；主 Contract 对它返回 `unsupported_action`。
- **代码依据：** `CaseToolExecutor.case_observation()`、`PublicActionContractValidator.validate()`。

### 5. Executor 为什么不直接保存 State？

- **考察点：** 单一职责与提交边界。
- **推荐回答：** Executor 只做 Tool→Command 适配；保存需要处理锁、memory projection、campaign、commit unknown 和 receipt，这属于应用服务。否则 MCP/Web 的提交语义会散落在 Tool handler 中。
- **代码依据：** `case_tools.py:134-255` 无 Store；`multicase.py:624-815` 负责提交。

### 6. 项目有没有 Tool Registry？

- **考察点：** 不要把枚举/字典包装成动态注册中心。
- **推荐回答：** 主链没有通用 Registry，使用静态 `ToolName`、两个方向映射和 `if` dispatch。MCP 有静态名字、schema、description 映射，但也不是动态插件 registry。
- **代码依据：** `INVESTIGATION_TOOL_BY_ACTION`、`INVESTIGATION_TOOL_ACTIONS`、`_TOOL_INPUTS`。

### 7. 为什么静态分派而不是 Registry？

- **考察点：** Trade-off。
- **推荐回答：** 当前只有 9 个固定领域 Tool，且权限、Observation、Command 都强耦合业务规则；显式映射透明且易审计。代价是新增 Tool 要多处同步，规模增大后可引入声明式 descriptor 并做一致性测试。
- **代码依据：** `CaseToolExecutor.execute()` 的分支和两个映射表。

### 8. Tool Schema 的 owner 是谁？

- **考察点：** 是否存在多层契约。
- **推荐回答：** 不是单一 owner。模型层由 Proposal Pydantic Schema 约束通用 ToolCall，当前公开合法性由 Action Contract 决定，Executor 参数模型是执行前 shape owner，Engine Command 是领域输入 owner；MCP 另有 transport input schema。
- **代码依据：** `actions.py`、`action_contract.py`、`case_tools.py`、`commands.py`、`mcp_server/contracts.py`。

### 9. Pydantic 验证通过为什么还可能失败？

- **考察点：** 类型正确与业务可执行的区别。
- **推荐回答：** Pydantic 只证明字段类型/枚举/结构；Action 可能不在最新 Observation、没有权限、session 已关闭、调查已完成、技能或证据不足。
- **代码依据：** `CaseEngine._investigate()`、`_submit_diagnosis()`、`_execute_treatment()`。

### 10. Action Contract 和 Engine 校验是不是重复？

- **考察点：** 分层防御。
- **推荐回答：** 有意重叠但数据权限和目的不同。Contract 只基于公开 Observation，防止模型引用未公开能力；Engine 基于完整可信状态保护领域不变量，并处理校验后状态变化。前者改善安全反馈，后者是最终业务防线。
- **代码依据：** `PublicActionContractValidator` 对 available 集合；`CaseEngine` 对完整 Case/Session。

### 11. Policy、Contract、Authority 怎么区分？

- **考察点：** 是否把所有 validation 统称为 policy。
- **推荐回答：** Planning Policy 管 Goal/Plan 语义；Action Contract 管当前公开 Action 的 shape 与 target；Authority 管谁能在什么风险下执行。三者通过也仍可能被 Engine 业务规则拒绝。
- **代码依据：** `goal_plan_policy.py`、`action_contract.py`、`npc_authority.py`。

### 12. 为什么 Tool 存在不代表 Agent 有权限？

- **考察点：** Capability 与 authorization 分离。
- **推荐回答：** `execute_treatment` 是系统能力，但 NPC 只能在匹配玩家确认后触发；能力目录描述“能做什么”，Authority 描述“当前谁可做”。
- **代码依据：** `NPCAuthorityPolicy.evaluate()`。

### 13. 用户确认如何避免 TOCTOU 或确认错 Action？

- **考察点：** 授权绑定。
- **推荐回答：** pending 绑定 player/case/session、decision、完整 Action 和 case revision；批准 turn 还要求新 `tool_call` 与 pending `tool_call` 精确相等。revision 变化会使确认失效。同进程 Session 锁进一步串行读改写。
- **代码依据：** `PendingActionConfirmation`、Clinic `current_pending()`、Runtime `_validated_pending()` 与 460 行 equality。

### 14. 确认后是否直接执行旧 Action？

- **考察点：** 对真实链路的掌握。
- **推荐回答：** 不是。批准是新 turn，会再次调用 LLM；只有新 Proposal 重申完全相同的 ToolCall，旧 pending 才能授权。这样允许模型在新 Context 下改变判断，改变后则不能沿用旧确认。
- **代码依据：** Runtime 先 `propose_turn()`，后比较 `pending.action.tool_call == action.tool_call`。

### 15. Pending confirmation 持久化了吗？

- **考察点：** 恢复边界。
- **推荐回答：** 没有，主要在 Clinic 进程内 dict；重启后失效，属于 fail-closed。Cooperative History 能重放 completed result/阻断不确定 operation，但不会恢复可继续授权的 live pending。
- **代码依据：** `ClinicService.cooperative_pending`、`test_context_engineering_ce2a.py` restart tests。

### 16. 谁真正修改 World State？

- **考察点：** 领域计算权与物理写权。
- **推荐回答：** Engine 计算并裁定新 Session；Service 编排提交；Store 写文件。不能只说 Engine 写数据库，也不能说 Store 决定业务合法性。
- **代码依据：** `CaseEngine._updated_session()`、`MultiCaseEpisodeService._submit_action_with_receipt_once()`、`JsonStateStore._write()`。

### 17. Execution Result 为什么分这么多层？

- **考察点：** 结果语义。
- **推荐回答：** Engine 只关心领域结果，Executor 统一 Tool 返回，Service 需要公开视图和 error code，receipt 需要 commit/memory 状态，Runtime 还要表达 Authority、Plan、Memory/Reflection。若强塞成一个模型会泄漏内部信息并耦合层次。
- **代码依据：** `EngineResult`、`ToolExecutionResult`、`MultiCaseServiceResult`、`MultiCaseActionReceipt`、`CooperativeTurnResult`。

### 18. Tool 业务失败会重新调用 LLM 吗？

- **考察点：** Agent loop 是否无界自修复。
- **推荐回答：** 当前同一 turn 不会。Runtime 将 `tool_succeeded=False` 交给 PlanEvaluator，保存固定公开 `last_decision_feedback`，本 turn 返回 `ACTION_REJECTED`；下一用户请求才可能产生新决策。
- **代码依据：** `cooperative_runtime.py:531-568`。

### 19. 哪些失败可以 repair？

- **考察点：** repair 与 retry。
- **推荐回答：** 模型结构/规划输出最多一次有限 repair，Public Action Contract 可一次定向 repair；Authority、Engine、Store 失败不通过重新问模型自动 repair。
- **代码依据：** `GameNPCAgent._parse_turn()`、Runtime `_resolve_contract()`。

### 20. 为什么 commit unknown 不能重试？

- **考察点：** 副作用与 exactly-once。
- **推荐回答：** `save_case_session()` 可能在 `os.replace` 后抛错，调用方无法确定新状态是否已成为事实；重试可能重复诊断或其他副作用。协作 ledger 因此进入 recovery 阻断，而不是让 LLM 猜。
- **代码依据：** `world_commit_status="unknown"`、`CooperativeCommitUncertainError`、commit fault tests。

### 21. Tool 是否幂等？

- **考察点：** 不要一概而论。
- **推荐回答：** GET 幂等；调查在 Engine 层拒绝重复；处置完成后拒绝；诊断本身可重复追加。默认协作入口按 operation 提供持久 replay/阻断，但 MCP 没有 operation ID。因此不是系统级统一幂等。
- **代码依据：** Engine 各分支、SQLite cooperative history、MCP facade。

### 22. 有事务吗？

- **考察点：** 原子文件不等于全局事务。
- **推荐回答：** 单个 World JSON 是 temp+fsync+replace 的原子快照，SQLite 各有局部事务；World、Memory、Campaign、AgentState、History 之间没有全局事务，采用 world-first + pending/reconcile/recovery。
- **代码依据：** `JsonStateStore._write()`、`V1MemoryCoordinator.commit_engine_result()`、commit design doc。

### 23. 同一 Session 两个 Tool 并发会怎样？

- **考察点：** 并发边界。
- **推荐回答：** 规范入口共享 per-root/per-session 的进程内 `RLock`，会串行化完整读改写链；不同 Session 可并行。跨进程、直接 Store 写和数据库 CAS 仍未解决。
- **代码依据：** `JsonStateStore.session_write_lock()`、`test_same_session_different_operations_are_serialized_without_lost_update`。

### 24. Tool 是异步的吗？

- **考察点：** 不为复杂而复杂。
- **推荐回答：** 主链全同步本地调用，每 turn 至多一个 Tool。MCP handler 语法上 async，但内部同步执行。没有队列、后台 job、并行 Tool 或取消。
- **代码依据：** Runtime/Executor/Engine 均为普通 `def`；MCP `_make_structured_tool()`。

### 25. Function Calling 是否等于执行授权？

- **考察点：** 模型协议与应用控制面。
- **推荐回答：** 不等于。Function Calling 只让模型输出 name/arguments；参数仍可能越权或过期，程序仍需 Contract、Authority、Engine 和 commit。当前项目甚至未使用原生 Function Calling。
- **代码依据：** `DeepSeekChatAdapter` 发送 `response_format=json_object`，没有 tools/tool_calls。

### 26. MCP 与主 Agent Tool path 是什么关系？

- **考察点：** 标准协议与内部执行层。
- **推荐回答：** MCP 是独立 stdio 入口，暴露 9 个 structured tools，共用 Executor/Engine；主 Agent 不通过 MCP。MCP 也不继承协作 Goal/Plan、Action Contract 和 Authority。
- **代码依据：** `mcp_server/server.py`、`application/mcp_facade.py`、`docs/INDEX.md`。

### 27. MCP path 为什么是当前安全风险？

- **考察点：** 边界扩展意识。
- **推荐回答：** 当前只绑定本地 stdio，风险可控；但它允许直接调用诊断/处置且无协作确认、身份认证、operation ID。若远程开放，必须把这些控制移到协议边界，而不能只依赖 Engine。
- **代码依据：** `MCPApplicationService.execute_tool()` 直接构造 Action 后调用 Executor。

### 28. 怎么证明 Tool 执行不是手工试玩？

- **考察点：** 测试证据。
- **推荐回答：** Engine 单测验证状态与事件；Contract/Authority 测试验证零 Tool 拒绝；service/runtime 集成测试验证持久化；fault tests 注入保存后抛错、投影失败和同 Session 并发；MCP tests 验证 9 个 schema 和 stdio。
- **代码依据：** 第 32 节列出的测试文件。

### 29. 新增 Tool 最容易漏掉什么？

- **考察点：** 横切关注点。
- **推荐回答：** 最容易只加 Executor 分支，却漏掉 Public Action projection、Planning 允许集、Authority、Observation/Memory/Campaign 投影、MCP schema 和重复/恢复测试。当前静态映射分散，必须用 checklist 和一致性测试。
- **代码依据：** Tool 名在 `actions.py`、`action_contract.py`、`case_tools.py`、`cooperative_planning.py`、`npc_authority.py`、`mcp_server` 多处出现。

### 30. 如果 Tool 数量增长到上百个，当前设计怎么演进？

- **考察点：** 扩展性思考。
- **推荐回答：** 保留 Engine 与 Authority 的确定性边界，把散落元数据收敛成 typed ToolDescriptor：name、public schema、Command factory、risk/authority class、result projector；启动时做完整性校验。远程 Tool 再引入超时、取消、隔离、durable operation receipt 与可观察性。不能仅换成框架 decorator 就认为安全问题解决。
- **代码依据：** 当前多处静态表与 `if` 分派正是演进触发点。

## 四十、理解检查

### 如果下面 15 个问题答不上来，就说明我没有真正理解 Tool 执行机制

1. LLM 返回的 `GameNPCTurnProposal` 与最终送进 Executor 的 `AgentAction` 之间，经历了哪些可能改变或拒绝 Action 的步骤？为什么 parse 成功仍远远不够？
2. 为什么说本项目有 9 个 Tool，却又说主协作 Agent 的公开 action space 只有 7 个？另外两个 Tool 在哪里使用？
3. `RESPOND`、`USE_TOOL`、`ToolCallRequest`、`CaseCommand` 四者是什么关系？哪些属于业务 Action，哪些属于执行协议？
4. 系统收到字符串 `inspect_object` 后，如何确定参数模型、`CaseActionType`、target 和最终 Engine 分支？请按代码顺序讲，不要只说“通过 Registry”。
5. 为什么 `PublicActionContractValidator` 已经验证当前 Observation 后，`CaseEngine` 仍必须检查 investigation、技能、重复和前置线索？
6. `CaseToolExecutor` 解决了哪些真实问题，又明确没有负责哪些问题？如果删掉它，哪些逻辑会污染 Runtime 或 Engine？
7. “CaseEngine 修改 World”与“CaseEngine 不写文件”为什么可以同时成立？领域转换权、提交编排权、物理写入权分别属于谁？
8. Engine 已返回 `EngineResult`，为什么仍不能立即对用户说 Tool 成功？`world_commit_status=unknown` 代表什么？
9. 诊断或处置进入 pending 后，用户批准时是否直接执行旧 Action？新的模型输出怎样与旧授权匹配？revision 变化会怎样？
10. Tool 执行成功、World 已保存，但 AgentState 保存失败时，下一轮应该相信 World 还是 AgentState？为什么不能回滚或重放 Tool？
11. 同一个 investigation、diagnosis、treatment 分别执行两次，会出现什么不同结果？这说明“Tool 幂等”为什么不能作为统一结论？
12. 同一 Session 两个线程同时提交 Action 时，当前锁覆盖哪里？如果换成两个 Python 进程，为什么同样结论不再成立？
13. 原生 Function Calling 即使能 100% 生成合法 JSON，为什么仍不能替代 Public Action Contract、Authority 和 Engine？
14. 主 Agent Tool path 与 MCP path 共享什么、不共享什么？为什么将本地 MCP 直接开放给远程不受信任 Agent 会改变安全假设？
15. 新增一个会改变案件状态的 Tool 时，除了增加 ToolName 和 Executor 分支，为什么还必须检查 Planning、Authority、Observation、事件投影、幂等、commit failure 与测试？

## 四十一、最终概念收口

### Proposal

LLM 对本轮 Goal/Plan/Decision 的完整结构化提议；是候选，不是事实。

### Action

Proposal 中当前 turn 要做的业务动作；本项目只有 `RESPOND` 或 `USE_TOOL` 两类。

### Tool

`USE_TOOL` Action 选择的有限能力名及 JSON 参数；能力存在不等于有权限执行。

### Tool Schema

规定参数结构与类型的契约；本项目由 Proposal schema、Action Contract、Executor Pydantic model、Engine Command 和 MCP input model 分层承担。

### Action Contract

把当前 Observation 投影成最小公开可执行面，验证 Tool、参数和 target 是否属于当前公开选择。

### Policy

对 Goal/Plan、能力、计划步骤和行动语义做确定性约束；不产生执行权限。

### Authority

决定当前 Actor 对 Action 是自主、只可提议、必须确认还是禁止；Plan 不能扩大 Authority。

### Executor

将批准的 ToolCall 解析为强类型领域 Command，并统一包装 Engine 结果的应用层适配器。

### Engine

依据完整可信状态和领域规则计算新 Session、事件与评分的确定性状态转换器；不直接持久化。

### World State

当前持久化 `CaseSessionState` 所代表的权威案件事实，包括线索、action history、诊断、处置、结果和 revision。

### Execution Result

程序记录“实际发生了什么”的结构化结果；从 EngineResult 到 commit receipt 再到 Runtime result，明确区分业务结果、提交状态和后处理状态。

### Observation

从 World State 与可信定义投影出的权限过滤视图，是 LLM 下一轮能看到的环境反馈，不等于完整 World。

### 一条链路串起来

```text
LLM
→ Proposal
→ AgentAction
→ Goal/Plan Policy
→ Plan Alignment
→ Public Action Contract
→ Authority / Confirmation
→ Approved ToolCall
→ CaseToolExecutor
→ typed Domain Command
→ CaseEngine
→ EngineResult(new Session + Events)
→ Service / Store Commit
→ authoritative World State
→ Execution Receipt
→ filtered Observation
→ Plan / AgentState / Memory feedback
→ next LLM turn
```

最后只记住一句：

> **模型负责提出，程序负责批准，Executor 负责翻译，Engine 负责裁定，Service/Store 负责提交，Observation 负责把真实结果反馈给下一轮。**
