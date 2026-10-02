# 《异闻行录》面试训练统一事实底稿

> 用途：后续面试训练、项目追问和表述校准的共同事实来源。
>
> 本文件不是宣传稿、简历文案、模拟答案或 STAR 故事。它只整理当前工作区中能够由源码、测试、架构文档和评测产物支持的事实。若本文件与历史聊天或旧文档冲突，应继续核对其引用的当前代码和结果文件。
>
> 当前核对基线：工作区 657 项 pytest 通过（2026-09-26 当前工作区实测）；V2.1 已发生真实模型执行，但没有完整、无混杂的 54 项统一结果。

## 1. 项目一句话定位

《异闻行录》是一个本地运行的古风志怪调查游戏，也是一套由单一 `GameNPCAgent` 驱动、以确定性规则控制权限和权威世界写入、并配有可审计评测体系的 Human-Agent Cooperative Game NPC System。

边界：它不是通用 Agent 平台，不是多 Agent 系统，不提供现实医疗能力，也不以 LLM 文本作为权威世界事实。

证据：[项目总纲](../architecture/PROJECT_MASTER_BLUEPRINT.md)、[README](../../README.md)、[主 Agent](../../src/xuanyi_npc/agents/game_npc.py)。

## 2. 30 秒项目介绍所需事实

这里列出可用于组织介绍的事实，不提供逐字背诵稿：

- 产品有六个正式古风志怪案件，玩家与一个自主 NPC 通过自然语言共同调查、诊断和处置异常；
- 玩家输入被建模为贡献而不是工具命令，NPC 可以接受、部分接受、拒绝、请求更多证据或提出替代方案；
- LLM 负责提出 Goal/Plan 和当前行动，确定性系统负责公开视图、契约、权限、工具执行和权威世界提交；
- 普通调查可由 NPC 自主执行，诊断需要协商确认，不可逆处置需要绑定具体决策和状态版本的确认；
- 系统包含玩家隔离的长期 Memory 和证据约束的 Reflection，但当前只证明机制、检索和有限曝光，没有证明稳定行为收益；
- 项目不只包含产品，还包含冻结任务、真实模型运行、独立 grader、请求账本、费用和失败审计；
- 当前关键证据包括 E6 历史冻结基线 8/9、诊断修复小批次 9/9、V2.1 G 17/18，以及存在接口混杂的部分 C 和完整 M recovery 结果；这些数字不能合并成一个项目成功率。

## 3. 产品 / Agent / Evaluation 三层结构

| 层 | 解决的问题 | 主要入口 | 当前边界 |
|---|---|---|---|
| Product | 玩家如何实际进入游戏、创建档案、调查六案并恢复本地状态 | [Clinic server](../../src/xuanyi_npc/clinic/server.py)、[Clinic service](../../src/xuanyi_npc/application/clinic.py)、[六案资源](../../src/xuanyi_npc/resources/cases/) | 本地回环服务，不是公网产品 |
| Agent | 如何将玩家贡献、公开世界、计划、记忆和权限组合为一个受约束回合 | [CooperativeRuntime](../../src/xuanyi_npc/application/cooperative_runtime.py)、[GameNPCAgent](../../src/xuanyi_npc/agents/game_npc.py) | 单一主 Agent；通常每个玩家回合只执行一个公开行动 |
| Evaluation | 如何冻结任务、运行真实模型、记录请求、评分并区分模型/实现/协议失败 | [evaluation package](../../src/xuanyi_npc/evaluation/)、[评测总览](../evaluation/README.md)、[V2.1 设计](../evaluation/v2_design/revision_20260920/README.md) | 不把测试数量、离线 substitute 或小样本结果包装成线上能力 |

三层共享领域契约和生产执行链，但评测专用病例位于 `src/xuanyi_npc/evaluation/fixtures/v21`，不属于六个正式产品案件。

## 4. 从 PlayerContribution 到世界提交的 Runtime 链路

正常工具行动的完整链路如下：

```text
PlayerContribution
  → CooperativeRuntime.handle
  → resume public episode / load player, session and AgentState
  → validate pending confirmation against owner, decision and world revision
  → derive public CaseObservation
  → initialize or advance deterministic Goal stage
  → retrieve scoped Memory and build AgentMemoryContext
  → build GameNPCAgentInput
  → A1 propose_turn (Goal update + Plan update + Decision)
     or A0 decide (Decision only)
  → GoalPlanPolicy validation (A1)
  → associate Decision with current Goal/Plan
  → active PlanStep–Decision alignment check (A1)
  → PublicActionContractValidator
  → NPCAuthorityPolicy
  → autonomous execute / create pending / reject
  → CaseToolExecutor
  → domain CaseCommand
  → CaseEngine.execute
  → save authoritative world state and domain events
  → DeterministicPlanEvaluator
  → save AgentState revision
  → project authoritative Memory / reconcile derived index
  → optional evidence-grounded Reflection lifecycle
  → CooperativeTurnResult
```

关键分支：

- `RESPOND` 不进入 `CaseEngine`；非工具 PlanStep 可以由确定性 PlanEvaluator 根据公开回应推进；
- A1 规划策略或计划—动作对齐失败时，本轮停止，不调用工具、不改变 world；
- ActionContract 失败最多触发一次有界 contract repair，仍失败则安全 fallback；
- 权限要求确认时先产生 pending，不立即提交 world；
- 只有授权通过且 `CaseEngine` 成功执行后才有权威 world commit。

证据：[CooperativeRuntime](../../src/xuanyi_npc/application/cooperative_runtime.py)、[CaseToolExecutor](../../src/xuanyi_npc/application/case_tools.py)、[CaseEngine](../../src/xuanyi_npc/engine/case_engine.py)。

## 5. 组件职责边界

| 组件 | 负责 | 不负责 |
|---|---|---|
| Runtime | 装配公开输入，编排 Agent、Policy、Contract、Authority、Executor、状态保存、Memory 和 Reflection | 不替模型选择具体诊断或处置 |
| Agent | 评价玩家贡献，提出 Goal/Plan 更新和当前 Decision，生成解释 | 不直接写 world、权限、Memory 或案件真相 |
| GoalPlanPolicy | 校验 Goal/Plan 更新、步骤、公开 target 及 Decision 对齐 | 不执行工具，不判断工具产生的真实结果 |
| PublicActionContract | 检查当前公开行动是否存在、参数形状是否准确、证据是否已公开 | 不授予高风险权限，不判断隐藏正确答案 |
| Authority | 根据工具风险、pending 和确认身份决定 autonomous / proposal-only / confirmation-required / forbidden | 不修复参数，不执行领域规则 |
| Executor | 把合法公开 ToolCall 映射为领域 Command，并交给服务或 CaseEngine | 不相信模型的成功声明 |
| CaseEngine | 检查调查前置、诊断、处置、评分，生成事件并决定权威 world 变化 | 不接受自由文本，不进行 LLM 推理 |
| PlanEvaluator | 根据执行前后 Observation、动作和工具结果推进 Plan/Goal | 不扩大权限，不替代 CaseEngine 结果 |

源码：[GoalPlanPolicy](../../src/xuanyi_npc/application/goal_plan_policy.py)、[ActionContract](../../src/xuanyi_npc/application/action_contract.py)、[Authority](../../src/xuanyi_npc/application/npc_authority.py)、[PlanEvaluator](../../src/xuanyi_npc/application/plan_evaluator.py)。

## 6. World State、Agent State、Observation、Context 的区别

| 概念 | 内容 | 权威性与生命周期 |
|---|---|---|
| World State | `CaseSessionState`、玩家状态、Campaign、已发现线索、诊断、处置、revision、领域事件 | 由确定性领域服务和 `CaseEngine` 改变，是案件结果的权威来源；见 [cases.py](../../src/xuanyi_npc/domain/cases.py) |
| Agent State | 当前 Goal、Plan、上次 PlanEvaluation、Agent revision 和更新来源 | 持久化的 Agent 意图状态，不等于 world，也不能覆盖 world；见 [cooperative_planning.py](../../src/xuanyi_npc/domain/cooperative_planning.py) |
| Observation | 从 world 和权限边界投影出的模型可见案件视图，如已发现线索、公开候选、可用调查和 session revision | 是经过过滤的当前事实，不含隐藏真相；见 [views.py](../../src/xuanyi_npc/application/views.py) |
| Context | 每次模型请求装配的输入，包括 player view、Observation、贡献、Authority view、Goal/Plan、上次反馈、Memory 和 pending ID | 是一次请求的模型输入集合；其中 Memory 是非权威历史参考，玩家文本也是不可信输入；见 `GameNPCAgentInput` in [game_npc.py](../../src/xuanyi_npc/agents/game_npc.py) |

面试口径中不能把这四者统称为“Agent 状态”。区分它们才能解释隐藏信息隔离、重规划和跨存储一致性问题。

## 7. Human-Agent Cooperation 的真实实现

`PlayerContribution` 至少包含 contribution ID、player/session/case 身份、贡献类型和原始文本。类型包括 suggestion、hypothesis、challenge、evidence interpretation、question、approval、rejection 和 general message 等受控类别。

Agent 返回 `PlayerContributionEvaluation`，其中 disposition 可以表达接受、部分接受、拒绝、请求更多证据或替代方案。玩家输入不会直接拼成 `ToolCallRequest`；Agent 仍需依据公开 Observation 独立选择行动。

合作关系有三个可观察结果：

1. 玩家贡献进入模型输入并获得明确评价；
2. 合法贡献可以影响 Goal、Plan 或当前行动；
3. 玩家对受控动作的确认或拒绝改变 pending 生命周期，但不直接伪造执行结果。

证据：[cooperation.py](../../src/xuanyi_npc/domain/cooperation.py)、[CooperativeRuntime](../../src/xuanyi_npc/application/cooperative_runtime.py)、[项目总纲](../architecture/PROJECT_MASTER_BLUEPRINT.md)。

## 8. Goal / Plan / Decision / Action / PlanEvaluator 的关系

- **Goal**：当前要实现的受约束目标，有类型、状态和确定性 completion condition；模型可以 KEEP、REPLACE、BLOCK 或 ABANDON，不能自行把 Goal 标为完成。
- **Plan**：实现 Goal 的有序步骤及当前索引。步骤描述 intent、capability、公开 summary、完成信号，并可绑定公开 tool/target；Plan 本身不授权执行。
- **Decision**：本轮模型提交的结构化决定，包含玩家贡献评价、能力、一个 `AgentAction` 和解释，并与当前 Goal/Plan 关联。
- **Action**：本回合唯一的公开行为，或者 `RESPOND`，或者一个 `ToolCallRequest`。
- **PlanEvaluator**：在行动执行后比较前后 Observation 和领域结果，确定步骤完成、计划修订、Goal 完成或继续。

因果顺序是：Goal 约束 Plan，active PlanStep 约束 Decision/Action；Action 经过 Contract 和 Authority 后才可能执行；真实环境结果再由 PlanEvaluator 反向更新 Plan/Goal。

重要边界：模型提出一个“完成”叙述不会完成 Goal。完成权来自确定性 completion condition 和真实环境结果。

证据：[cooperative_planning.py](../../src/xuanyi_npc/domain/cooperative_planning.py)、[planning_contract.py](../../src/xuanyi_npc/domain/planning_contract.py)、[actions.py](../../src/xuanyi_npc/domain/actions.py)。

## 9. Structured Output、schema repair、contract repair 和 safe fallback

项目使用 provider 的 JSON 对象响应配合请求内完整 JSON Schema，由本地 Pydantic 解析。主链路不是供应商原生 `tools/tool_choice` Function Calling。

四个阶段需要分开：

1. **Structured output**：模型首次返回目标 schema；解析、字段、枚举或额外字段错误都属于 schema failure。
2. **Schema repair**：`BoundedStructuredOutput` 最多进行一次结构化修复，并保存 attempt telemetry、usage、耗时和 repair kind。
3. **Contract repair**：JSON 合法但不符合当前公开行动契约时，Runtime 向模型提供只含公开安全信息的反馈，最多再进行一次动作契约修复。
4. **Safe fallback**：修复仍失败、规划策略拒绝或输出不可用时，产生不执行工具的安全回应；fallback 是安全停止机制，不代表任务成功。

schema 只能证明表达契约，不能证明事实正确、权限允许或业务可执行，所以后面仍需要 GoalPlanPolicy、ActionContract、Authority 和 CaseEngine。

证据：[bounded_output.py](../../src/xuanyi_npc/agents/bounded_output.py)、[DeepSeek adapter](../../src/xuanyi_npc/agents/deepseek.py)、[GameNPCAgent](../../src/xuanyi_npc/agents/game_npc.py)。

## 10. 权限、confirmation 与 pending invalidation

当前权限分层：

- 读取公开视图和普通调查属于 autonomous；
- `submit_diagnosis` 属于 proposal-only，匹配确认后才可提交；
- `execute_treatment` 属于 confirmation-required；
- 不在公开工具集合或缺少 ToolCall 的动作属于 forbidden。

pending confirmation 保存并校验具体 decision、action digest、owner 和 world revision。确认只有在身份、决策、摘要和版本仍匹配时有效。玩家拒绝、状态变化、确认 ID 不匹配或动作变化会使旧 pending 失效；重新提出相同业务动作也必须生成新的确认身份。

V2 诊断验证中的 T16 真正走过：创建旧 pending → 玩家拒绝 → 旧 pending invalidated → 新 Decision 和 confirmation ID → 新确认 → 单次诊断提交 → 治疗确认。该证据属于指定小批次，见 [诊断验证报告](../../evaluation_results/v2/v2_diagnosis_validation_20260920_05/RESULTS_REPORT.md)。

当前缺口：pending 主要保存在内存，重启后不能完整恢复原确认流程。

## 11. Long-term Memory

### 存储与来源

- 权威记忆只从已提交的公开领域事实和通过证据验证的 Reflection 产生；
- SQLite 保存 source、authoritative memory、embedding、生命周期记录、tombstone、投影回执和 Reflection 索引回执；
- world/Agent JSON 与 SQLite Memory 是不同提交边界。

### 检索

- 先按 player、Episode 排除、类型、来源和生命周期过滤；
- 再使用 BGE-M3 1024 维 dense embedding 做精确余弦排序；
- 检索异常、索引不完整或结果二次校验失败时 fail closed，不把部分越界历史发给模型。

当前没有 BM25、RRF、ANN/HNSW 或独立 Reranker，不能将其描述为混合召回系统。

### 生命周期

Memory 支持创建、纠正、失效和硬删除；派生 embedding 需要与权威记录和 embedding space 匹配。投影写入和索引写入有回执/对账，但不构成 world 与 SQLite 的单一事务。

### 使用归因

系统区分：

- `selected`：检索器选入候选；
- `declared`：模型在 proposal 中声明使用；
- `accepted`：最终合法 Goal/Plan/Decision 确实接受该使用。

因此“召回到了”不等于“模型使用了”，使用了也不等于“任务因此成功”。

证据：[SQLiteMemoryRepository](../../src/xuanyi_npc/storage/sqlite_memory.py)、[memory_retrieval.py](../../src/xuanyi_npc/application/memory_retrieval.py)、[Memory 评测](../evaluation/memory_evaluation.md)。

## 12. Reflection 的真实生命周期和证据边界

真实生命周期是：

```text
Episode / Goal / Plan / Tool outcome
  → deterministic trigger
  → claim trigger receipt（去重）
  → build public evidence bundle
  → model generates ReflectionProposal
  → schema repair（有限）
  → deterministic evidence / scope validation
  → build memory candidates
  → conservative write policy
  → SQLite authoritative record
  → embedding write or pending index receipt
  → reconciliation
  → completed / rejected / no_write / failed lifecycle result
```

Reflection 可以在执行后形成候选经验，不要求立即重新规划。合法 `no_write` 表示证据不足或没有值得写入的经验，不是失败，也不是已经学习到经验。

现有证据支持：固定候选机制链可写入和检索；真实模型触发和生成曾发生；校验器可以拒绝越界候选；修复后的真实运行曾得到合法 `no_write`。

现有证据不支持：真实模型稳定产生高质量经验、错误记忆率已经可接受、后续任务表现得到提升、模型参数发生训练或系统持续自我进化。

证据：[Reflection 实现报告](../archive/reflection/PHASE_C_REFLECTION_IMPLEMENTATION_REPORT.md)、[E11](../archive/reflection/e11_reflection_ofat_harness_implementation.md)、[E12](../archive/reflection/e12_real_agent_reflection_ofat_pilot.md)、[E13](../archive/reflection/e13_reflection_no_write_root_cause_audit.md)。

## 13. A0 / A1 两套架构的真实差异

| 维度 | A0 `SimpleActionGameNPCAgent` | A1 `GameNPCAgent` |
|---|---|---|
| 模型输出 | 当前 `GameNPCDecisionProposal` | Goal update + Plan update +当前 Decision |
| 持久 Goal/Plan | 不由模型维护显式跨回合 Plan | 持久化 Goal/Plan 和上次 PlanEvaluation |
| 规划校验 | 不经过 A1 GoalPlan proposal 分支 | 经过 GoalPlanPolicy 和 PlanStep–Decision 对齐 |
| 安全执行链 | 共享 ActionContract、Authority、confirmation、Executor 和 CaseEngine | 同左 |
| 架构 ID | `A0` | `A1` |

A0 不是确定性脚本，它仍由模型选择每个当前动作。A1 也不是自由自治循环，它仍是一回合一个候选行动，并受确定性校验。

V2.1 C recovery 中已执行 8 个配对：A0 0/8、A1 8/8。但 closure audit 发现接口不对称：A0 没看到与 A1 等价的精确 `arguments` action-space 投影，254/256 个 A0 响应加入了不允许的 `target_id`；A1 的 108 个 provider responses 没有该问题。另有 4 个配对未启动。

因此当前只能说“architecture-as-implemented 的已执行配对结果不同”，不能说 A1 已被证明优于 A0，更不能把差异单独归因于 Planning。

证据：[A0 代码](../../src/xuanyi_npc/agents/simple_action.py)、[A1 代码](../../src/xuanyi_npc/agents/game_npc.py)、[C/M closure audit](../../evaluation_results/v21/v2_1_slim_cm_recovery_20260920_04/RESULTS_REPORT.md)。

## 14. V2 失败到 P0–P5 修复链

### 起点：真实失败暴露

早期 V2 任务运行出现大面积停滞：Agent 能调查，却在 diagnosis-ready 后持续 `RESPOND`；另一些轨迹在 active PlanStep 和实际 Action 不一致后被 Runtime 反复拒绝。初始 V2 全量产物还暴露了 runner、artifact contract 和可观测性缺陷。

历史证据：[V2 failure audit](../archive/evaluation/agent_task_benchmark_failure_audit.md)、[V2 结果目录](../../evaluation_results/v2/)。

### 修复链

| 阶段 | 关键失败或根因 | 修复/结论 | 证据 |
|---|---|---|---|
| P0 | `action_outside_active_plan` 的拒绝反馈没有进入下一轮模型上下文，Agent 可重复同类错误 | 当时先持久化 PlanEvaluation recovery feedback；当前实现又新增独立 `last_decision_feedback`，覆盖主要拒绝分支并一次性注入。历史真实 3×1 仍为 0/3，说明反馈可见不等于模型会恢复 | [P0](../archive/planning_and_action/p0_plan_action_recovery_fix_report.md) |
| P1 | diagnosis-ready 后模型反复回应，不选择 `submit_diagnosis`；规则没有阻止，问题在行动选择 | 加强诊断行动选择契约与公开候选表达；继续用真实运行验证，不把 prompt 修改当成功 | [P1 audit](../archive/planning_and_action/p1_diagnosis_action_selection_audit.md)、[P1 fix](../archive/planning_and_action/p1_diagnosis_action_selection_fix_report.md) |
| P2 | 模型可同时提出 Plan 和不匹配的 Decision，尤其 CREATE/REVISE 首步与当前行动不一致 | 加强 Plan/Decision 对齐校验，并记录对齐遥测 | [P2 audit](../archive/planning_and_action/p2_plan_decision_alignment_audit.md)、[P2 fix](../archive/planning_and_action/p2_plan_decision_alignment_fix_report.md)、[P2a](../archive/planning_and_action/p2a_alignment_telemetry_report.md) |
| P3 | 校验器知道契约，但模型在输入中看不到足够精确的诊断契约；结构修复也可能继续失败 | 把可执行公开诊断形状和本轮首步对齐要求放进模型可见上下文，记录每次 repair attempt | [P3](../archive/planning_and_action/p3_model_visible_diagnosis_contract_fix_report.md)、[P3a](../archive/planning_and_action/p3a_repair_attempt_telemetry_report.md) |
| P4 | 诊断推进后仍可能在 treatment 阶段停滞，PlanStep 与 `execute_treatment` 缺少明确绑定 | 明确治疗动作契约、tool 和 public target 绑定 | [P4](../archive/planning_and_action/p4_treatment_action_contract_fix_report.md) |
| P5 | active step 已形成可执行承诺，但 Decision 仍可能只解释或选择另一动作 | 强制 KEEP 可执行 active step 时 Decision 与已绑定 tool/target 一致；CREATE/REVISE 的首步也要承诺本轮行动 | [P5](../archive/planning_and_action/p5_executable_step_decision_commitment_fix_report.md) |

这条链说明了三点：

- 安全拒绝本身不保证任务会继续；
- 确定性校验必须与模型可见的接口说明一致；
- 修复必须通过同一生产 Runtime 的真实轨迹验证，不能只看单元测试或 prompt 是否“更清楚”。

## 15. 当前主要评测结果与适用范围

不同协议的结果不能合并。

| 结果 | 数字 | 支持的结论 | 不支持的结论 | 来源 |
|---|---:|---|---|---|
| 当前代码回归 | 657 passed | 当前工作区确定性回归通过 | 真实模型可靠性、真人体验、线上安全 | 2026-09-26 当前工作区实际 `pytest`；测试目录 [tests](../../tests/) |
| E6 历史冻结基线 | Task Success 8/9；Diagnosis 9/9；Treatment 8/9 | 3 个冻结案件 × 3 次、指定模型/脚本/规则下的历史表现 | 线上成功率、新任务泛化、因果提升 | [E6 报告](../archive/evaluation/e6_post_e5_frozen_3x3_reliability_report.md) |
| 诊断修复小批次 | T 6/6；M01 的 M0/M1/M2 3/3，共 9/9 | 指定已暴露任务的关键路径、确认、Trace 和预算链恢复 | 正式可靠性、Memory/Reflection 收益、未见任务泛化 | [20260920_05 报告](../../evaluation_results/v2/v2_diagnosis_validation_20260920_05/RESULTS_REPORT.md) |
| V2.1 G | 17/18 strict success | 六个已暴露回归任务 × 3 次的 A1 结果；T16 3/3 覆盖拒绝后新确认链 | C 新任务泛化、A0/A1 差异、Memory 收益 | [精简首轮报告](../../evaluation_results/v21/v2_1_slim_first_round_20260920_02/RESULTS_REPORT.md) |
| 原 V2.1 C/M | C 全部实现失败；M 首项 artifact failure、其余未启动 | 暴露 campaign rule、artifact contract、停止门控和可观测性缺陷 | 任何模型或架构能力结论 | 同上 |
| V2.1 C recovery | 计划 24、启动 16；8 配对中 A0 0/8、A1 8/8；4 配对未启动 | architecture-as-implemented 的部分观察 | A1 的 Planning 因果收益；完整 C 结果 | [Closure-audited report](../../evaluation_results/v21/v2_1_slim_cm_recovery_20260920_04/RESULTS_REPORT.md) |
| V2.1 M recovery | 12/12 strict success；M0 6/6、M1 6/6 | 六个有效配对中两条件均能完成；隔离、配对和结果链可运行 | Memory 提高成功率；广泛行为收益 | 同上 |

补充边界：C/M recovery 的 `20/36` 只表示计划项目中有 20 项具备 strict-success 证据，不是模型成功率，因为 8 个计划 C 项没有模型结果。完整 162-episode V2.1 设计、独立 R、真实 S、正式并发与重启 E 轨道没有执行；这不否定当前已经补充的 Session 线程竞争和若干 post-commit/restart 定向测试。

## 16. 当前明确未完成能力

- 跨进程同一 session 的数据库级原子 CAS 或单写者边界；正常单进程入口的 Session 串行化已经实现并有并发测试；
- pending confirmation 的完整持久化和重启恢复；
- world、AgentState、SQLite Memory 各提交边界的完整 crash recovery；
- 多进程及所有提交边界的系统性并发/崩溃/恢复矩阵；当前已有单进程 Session 竞争、保存后抛错和若干 post-commit/restart 定向测试；
- 稳定的原始 structured-output schema 遵循，以及 schema 失败后完整 usage 保留；
- 公平、完整、接口等价的 A0/A1 真实模型比较；
- Memory 对任务成功、效率或错误率的稳定收益证据；
- Reflection 候选质量、错误记忆率和下游行为收益证据；
- 完整 V2.1 162-episode 设计；
- 独立 Reflection 质量轨道和真实攻击轨道；
- 充分的 prompt injection 组合覆盖；
- 公网身份认证、生产多租户隔离、TLS、限流、告警与密钥运维；
- OS/container sandbox；
- 大规模性能、P95 延迟、高并发或生产 SLA；
- 真人用户研究和稳定的新任务泛化证据。

来源：[ROADMAP](../product/ROADMAP.md)、[V2.1 设计](../evaluation/v2_design/revision_20260920/README.md)、[Closure audit](../../evaluation_results/v21/v2_1_slim_cm_recovery_20260920_04/RESULTS_REPORT.md)。

## 17. 重要设计取舍及原因

| 取舍 | 当前选择 | 原因 | 代价 |
|---|---|---|---|
| 模型与权威世界 | 模型 proposal，规则提交 | 保留语言推理灵活性，同时让状态、权限和结果可审计 | 需要多层契约；合法表达和业务执行之间可能产生摩擦 |
| 单步回合与后台循环 | 每个玩家贡献通常只推进一个行为 | 容易审计、确认和中断，避免无界自主循环 | 需要更多交互回合，模型可能在中间阶段停滞 |
| 显式 Goal/Plan | A1 持久化受约束 Goal/Plan | 可观察意图、支持重规划和确定性完成判断 | schema 更复杂，模型遵循和 Plan/Decision 对齐成本更高 |
| 静态领域工具 | 小型固定 action space | 领域边界清楚、参数和权限可精确验证 | 不能直接扩展为任意工具平台 |
| Risk-based confirmation | 普通调查自主，诊断/处置受确认约束 | 玩家保留高风险决定权，同时不阻塞每个低风险步骤 | pending 生命周期、失效和恢复更复杂 |
| 权威/派生 Memory 分离 | 领域事实为权威记录，embedding 为派生索引 | 可纠正、失效、重建并安全 fail closed | 跨存储一致性和对账复杂 |
| Dense exact retrieval | BGE-M3 + 精确余弦排序 | 数据规模可控，易审核并复用已有 Gold/Holdout | 没有混合检索、ANN 和独立 reranking 能力 |
| Reflection 保守写入 | evidence bundle + validator + consolidation + `no_write` | 减少把模型自由文本固化为事实 | 可能少写；真实行为收益尚未证明 |
| 冻结评测 | task、顺序、预算、哈希和不可变 artifact | 防止选择性补跑、运行中改规则和结果污染 | 冻结实现缺陷会导致整批结果失效，修复需要新实验 |
| 失败分类 | 区分模型、实现、协议、基础设施和未启动 | 避免把 runner 缺陷算成模型失败或把未启动算入分母 | 报告更复杂，不能用一个总分概括 |

## 18. 当前能由代码和证据支撑的个人工作内容

仓库 Git 历史的近期提交作者统一显示为 `WangYDING`，`pyproject.toml` 的项目作者也为 `WangYDING`。如果候选人本人确认这就是自己的身份，可以用 Git 记录证明自己对仓库存在持续提交，包括产品身份统一、生产 Agent Runtime、评测套件、Memory 实验归档和本次入口文档事实收口。

在本人进一步确认职责边界前，代码和结果能够支撑的是“项目中完成了以下工程工作”，不能自动升级为“全部由我独立完成”：

- 将 LLM proposal 与 `CaseEngine` 权威写入分离；
- 建立 PlayerContribution、Goal/Plan、公开 ActionContract 和 Authority 的协作 Runtime；
- 实现结构化输出修复、契约修复、fallback 和请求遥测；
- 实现玩家隔离 Memory、BGE-M3 检索、生命周期与投影对账；
- 实现 Reflection evidence、validation、consolidation 和 receipt；
- 建立真实模型 benchmark、grader、预算守卫、冻结哈希、请求账本和失败审计；
- 根据失败轨迹完成 P0–P5 多轮修复；
- 实现 A0/A1 两套入口并执行 V2.1，但也识别出接口不对称导致的归因问题。

仍需候选人本人补充或确认，仓库无法单独证明：

- 每个模块是否由本人独立设计、主导或仅参与；
- AI 辅助、他人协作、代码生成和人工审阅的比例；
- 项目起止时间、投入时长和团队规模；
- 是否有真实玩家、商业使用、线上流量或外部客户；
- 哪些失败由本人首先发现，哪些方案是本人独立决策；
- 个人最熟悉、能在白板上完整重建的模块。

证据：[Git history](../../.git/)、[pyproject.toml](../../pyproject.toml)、[评测与实现导航](../INDEX.md)。

## 19. 高频 Agent 术语与项目对应关系

| 术语 | 本项目中的具体对应 | 必须保留的边界 |
|---|---|---|
| Agent | 单一 `GameNPCAgent` / `SimpleActionGameNPCAgent` | 不是多 Agent orchestration |
| Agent Runtime | `CooperativeRuntime.handle()` 的单回合编排 | 不是通用后台自主循环 |
| ReAct | 模型根据 Observation 选择行动，再根据环境反馈继续下一回合 | 没有使用“ReAct”库；运行形式受 Goal/Plan 和确定性契约约束 |
| Planning | A1 的持久 Goal、Plan、PlanStep 和 proposal | Plan 不等于 Permission，完成由规则判断 |
| Replanning | 根据 PlanEvaluation、环境变化或拒绝修改未完成计划 | 不是任意 DAG 调度器 |
| Tool use | `AgentAction.tool_call` → ActionContract → Authority → Executor | 主链路不是供应商原生 Function Calling，也不经 MCP client |
| Function Calling | 本项目更准确地说是 JSON structured proposal + 本地解析 | 不应把它说成 `tools/tool_choice` 原生接口 |
| MCP | 独立 `xuanyi-mcp-stdio` 固定工具入口 | MCP 解决接入协议，不替代业务授权；主 Agent 不通过 MCP 执行 |
| Guardrail | Pydantic schema、GoalPlanPolicy、ActionContract、Authority、CaseEngine | 任何单层都不能保证绝对正确或安全 |
| Human in the Loop | diagnosis negotiation、treatment confirmation、rejection/invalidation | 不是所有工具都需确认；确认绑定具体动作和版本 |
| State | world、AgentState、Observation、Context 分层 | 不能用一个“state”掩盖权威性差异 |
| Persistence | JSON world/Agent/Campaign + SQLite Memory | 不等于任意中断点完整恢复 |
| Event sourcing | 领域事件和 replay 支持审计/重放 | 当前主要持久形态仍包含快照，不能笼统称为完整事件溯源平台 |
| RAG | 为 Agent 检索历史 Memory context | 不是通用知识库问答；Memory 不是当前世界事实 |
| Embedding | BGE-M3 dense 1024-dimensional vector | 没有 BM25/RRF/ANN/独立 Reranker |
| Long-term Memory | 权威领域事实和验证 Reflection 的跨 session 投影 | 已证明机制/曝光，未证明稳定收益 |
| Reflection | evidence-grounded candidate experience lifecycle | 不是模型训练或持续自我进化 |
| Idempotency | operation ID、source receipt、trigger claim 和对账机制 | 不能据此承诺未知提交下的 exactly-once |
| Observability | Trace、attempt telemetry、request ledger、provider ID、usage/cost | 仍出现过 schema 失败 usage 丢失，需要审计修正 |
| Evaluation | 冻结任务、grader、重复、预算、不可变 artifact 和失败分类 | 测试通过不等于模型能力，重复也不等于独立新任务 |
| Ablation | A0/A1、M0/M1/M2 条件比较 | 当前 A0/A1 受接口混杂；M 未显示成功收益 |
| Prompt injection | 玩家、Memory 和工具反馈都按不可信输入处理并限制权限 | 真实攻击轨道和充分覆盖尚未完成 |
| Sandbox | 当前是领域工具/权限边界 | 不是 OS 或 container sandbox |

## 20. Claim Boundary

### SAFE TO CLAIM

- 项目是本地运行的六案古风志怪调查游戏，核心由单一 GameNPC Agent 驱动。
- 玩家自然语言贡献不会直接转成工具命令；Agent 先评价贡献并选择候选行动。
- LLM 只提交结构化 proposal；确定性系统控制可见信息、契约、权限、执行和权威 world commit。
- `CaseEngine` 独占案件状态变化，模型文本和 Plan 都不能直接改变世界。
- A1 实现了持久 Goal/Plan 和确定性 PlanEvaluator；A0 实现了无显式跨回合计划的当前行动接口。
- A0/A1 共享 ActionContract、Authority、confirmation、Executor 和 CaseEngine 执行链。
- 项目实现了一次有界 schema repair、一次动作契约 repair 和 safe fallback。
- 项目实现了玩家隔离的 SQLite Memory、BGE-M3 dense retrieval、生命周期和使用归因。
- 项目实现了 evidence-grounded Reflection 生命周期，并允许合法 `no_write`。
- 当前工作区 657 项 pytest 通过（2026-09-26 当前工作区实测）。
- E6 历史冻结协议下 Task Success 为 8/9。
- V2.1 G 在六个已暴露回归任务 × 3 次下为 17/18 strict success。
- V2.1 M recovery 中 M0 和 M1 都是 6/6 strict success，没有观察到任务成功差异。
- 支持权威快照、事件回放、Memory 投影对账和部分故障恢复。

### CLAIM WITH QUALIFICATION

- “系统具有自主性”：自主性限于公开 action space 内的单 Agent 单步决策；受 Goal/Plan、Contract、Authority 和玩家确认约束。
- “系统支持恢复”：仅指已持久化状态恢复、事件回放、投影对账和部分故障恢复；pending 和部分跨存储恢复未闭环。
- “系统是可审计的”：关键请求、repair、权限、工具、世界事件和费用有较完整证据；历史上仍发生过 M artifact 丢失和 schema 失败 usage 汇总缺陷。
- “结构化输出提高可靠性”：它使表达可校验并支持 repair/fallback；原始 schema 遵循仍不稳定，也不保证事实或业务正确。
- “Memory 已接入生产 Agent”：机制、隔离、检索和曝光已验证；没有证明成功率收益。
- “Reflection 能形成经验”：固定机制和有限真实生成已验证；真实质量、稳定写入和下游收益未证明。
- “V2.1 有 A0/A1 结果”：只有 8 个已执行配对，另 4 个未启动，而且接口不对称影响归因。
- “V2.1 已运行”：G 和后续 C/M recovery 确实运行过；不能说完整 54 项得到一个有效统一结果，更不能合并不同实验分母。
- “没有执行安全违规”：只能限定到具体冻结批次和 grader 覆盖，不能外推为系统绝对安全。
- “个人完成了这些模块”：只有在候选人确认 Git 身份、职责和 AI/协作边界后，才能把项目产物转成个人所有权陈述。

### DO NOT CLAIM

- “这是一个通用 Agent 平台”或“全自动多 Agent 系统”。
- “普通 NPC 都是 Agent”或“系统有多个 Agent 协同推理”。
- “模型可以直接执行工具、修改世界、完成 Goal 或写入 Memory”。
- “全部工具通过 MCP 执行”或“主链路使用 MCP client”。
- “主链路使用供应商原生 Function Calling”。
- “Plan 就是执行权限”或“模型说完成就代表完成”。
- “实现了 BM25 + Dense、RRF、HNSW/ANN 或独立 Reranker”。
- “V2.1 已全面通过”或“有一个完整 54 项总成功率”。
- “A1 已证明优于 A0”或“显式 Planning 带来了 100 个百分点提升”。
- “Memory 已证明提高任务成功率、减少调查或提升泛化”。
- “Reflection 已证明持续自我进化、自主学习或更新模型参数”。
- “支持任意中断点完整恢复”或“已经完成 complete crash recovery”。
- “所有部署形态下同 session 并发安全已经完成”或“revision + 原子文件替换等于原子 CAS”；准确说法是正常单进程入口已串行化，多进程和直接 Store 写仍未覆盖。
- “world、AgentState 和 Memory 是一个强一致事务”。
- “E6 的 8/9 是线上成功率”或“系统诊断准确率始终为 100%”。
- “零安全漏洞”“绝对不会越权”或“有限样本零违规证明全面安全”。
- “player scope 等于生产多租户安全”或“领域工具白名单等于 OS sandbox”。
- “测试 657 项说明真实模型、线上性能或用户体验已经验证”。
- “所有实现、实验和性能提升均由候选人独立完成”，除非有额外个人证据。

## 使用本底稿时仍需补充的个人事实

任何后续 AI 在生成项目介绍、STAR、简历 bullet 或模拟回答前，必须先向候选人核实：个人职责、独立完成范围、AI/协作方式、时间线、目标岗位以及本人能现场解释的代码深度。没有这些信息时，只能基于本文件陈述“项目实现了什么”，不能替候选人虚构“我做了什么”。
