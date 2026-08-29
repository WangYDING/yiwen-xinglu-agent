# 《异闻行录》产品系统架构

> 状态：当前 Cooperative Agent 架构冻结（2026-08-21）
>
> 本文描述当前产品的权威系统边界与数据流。产品身份以 [`PROJECT_MASTER_BLUEPRINT.md`](PROJECT_MASTER_BLUEPRINT.md) 为准；里程碑状态以 [`../product/ROADMAP.md`](../product/ROADMAP.md) 为准。

## 当前主链

```text
Player
→ PlayerContribution
→ CooperativeRuntime
→ public Observation + Goal / Plan + scoped Memory
→ GameNPCAgent proposal
→ cooperative Decision
→ PublicActionContract
→ GoalPlanPolicy
→ Authority Policy
→ bounded Tool
→ CaseEngine
→ committed event / public result
→ PlanEvaluator / Replanning
→ evidence-grounded Reflection
→ conservative Experience Consolidation
```

`GameNPCAgent` 形成候选决策，玩家影响判断并提供高风险授权，确定性系统验证并执行。LLM 没有直接修改世界状态、绕过 Tool 契约或扩大自身权限的能力。

## 总体原则

- 当前唯一产品 Agent 是 `GameNPCAgent`。
- 普通病例角色不是 Agent；当前系统不是 Multi-Agent system。
- 玩家文本被建模为 `PlayerContribution`，不能直接转换为 `ToolCall`。
- Agent 只能读取权限过滤后的公开 Observation、Goal/Plan 与受限历史；隐藏真值和未发现线索不能进入决策上下文。
- 每个 cooperative turn 最多执行一个 Tool；调查可在权限内自主推进，诊断通过协商形成，高风险处置需要明确确认。
- LLM proposes；deterministic system validates。所有真实状态变化必须经过领域命令、规则验证和事件记录。
- 当前 Observation 优先于历史 Memory；Reflection 不能未经验证直接写入长期记忆。

## 核心模块与权威边界

### PlayerContribution 与合作决策

玩家可以提交线索、假设、建议、质疑、风险意见或确认。`GameNPCAgent` 独立评价并选择 `ACCEPT`、`PARTIAL_ACCEPT`、`REJECT`、`REQUEST_MORE_EVIDENCE` 或 `PROPOSE_ALTERNATIVE`；玩家文本本身不是执行命令，不能绕过计划、权限或病例规则。

### GameNPCAgent

`GameNPCAgent` 读取 public Observation、Goal/Plan、PlayerContribution、作用域受限的 Memory 和当前 Public Action Space，输出结构化 proposal。它可以形成调查意图、维护计划、评价玩家贡献并选择候选 Tool，但没有世界状态写权限。

### Goal / Plan / Replanning

Goal 与 Plan 保存在 `CooperativeAgentState`。`GoalPlanPolicy` 检查目标、步骤与当前公开合法 target 的一致性；`PlanEvaluator` 根据新 Observation 和已发生的执行结果决定保持、修订、完成或结束计划。Plan 表示意图与顺序，不授予执行权限。

### Memory

长期历史先经过玩家、案件、类型、来源和当前 Episode 过滤，再以最小只读 MemoryView 进入 Agent 上下文。`selected → declared → accepted` 是实际使用归因路径；retrieved/selected 不自动等于 used。当前 Observation 始终优先，Memory 不能替代世界真相、注入指令或扩大权限。

### Reflection 与经验形成

Reflection 只能基于已提交 Episode 结果及其 evidence 形成候选总结。弱证据、越界推断和无来源内容由 validator 拒绝；通过验证的 `MemoryCandidate` 仍需保守 consolidation 才能进入未来检索。模型总结本身不是权威事实。

### Public Action Space 与验证链

`PublicActionContract` 拒绝未知 Tool、非法 target、错误 arguments 和上下文不一致动作；`GoalPlanPolicy` 检查计划一致性；Authority Policy 控制执行权限。拒绝不会执行 Tool 或污染状态，每个 cooperative turn 最多提交一个合法 Tool。

| 行动类别 | 当前权责 |
|---|---|
| 普通调查 | Agent 可在公开权限范围内自主执行 |
| 诊断 | Agent 与玩家协商形成，玩家文本不能直接强制提交 |
| 高风险处置 | 必须获得玩家明确确认后才能进入执行验证 |
| 世界状态写入 | 仅由确定性服务与 `CaseEngine` 完成 |

### CaseEngine 与事件

`CaseEngine` 接收已通过上层验证的领域命令，独占病例真相、证据发现、诊断、处置、结局、评分和世界状态变化。成功执行产生连续 `CaseEvent`；LLM 不能指定隐藏结果、跳过前置条件或直接修改 `CaseSessionState`。

### 持久化、恢复与回放

Case、Player、Campaign、Cooperative Agent state 与 Memory 各自具有明确的 JSON/SQLite 权威边界。系统保证玩家隔离、修订检查、幂等、拒绝零写入、显式故障窗口和事件回放；LLM 没有文件或数据库写权限。

## 交互入口

| 入口 | 定位 |
|---|---|
| `yiwen-xinglu` | 当前正式本地 Web 入口，承载六异案 Cooperative Investigation |
| `xuanyi-clinic` | deprecated compatibility alias，与 `yiwen-xinglu` 共用组合根 |
| `xuanyi-mcp-stdio` | 本地 MCP 集成入口；不是规则捷径 |

所有入口必须调用相同应用服务和确定性规则，不能让自然语言、浏览器、CLI 或 MCP 绕过权限与状态边界。

## Memory 工程依据

M4.5 语义检索实验继续作为当前 Memory 实现的回归、benchmark 与失败分析证据。

普通案件角色不是 Agent；每个合作回合只有一个 `GameNPCAgent` 参与决策。**This is not a Multi-Agent system.**

## 评测与可观测性

- deterministic paired ablation 验证受控机制是否改变可观察行为；
- real-model pilot 验证有限模型、有限场景下的结构化输出和安全链路；
- stage-level telemetry 定位 parser、contract、plan 与 authority 的首个失败阶段；
- benchmark 真值和成功条件由冻结契约定义，不读取模型自评；
- Fake、Fixture、测试数量和小样本 Pilot 不得描述为生产成功率或玩家收益。

## 状态更新顺序

1. 加载并校验玩家、案件、Cooperative Agent 与相关历史状态。
2. 服务端构造权限过滤后的公开 Observation 和 Public Action Space。
3. 接收 `PlayerContribution`，由 `GameNPCAgent` 形成结构化 proposal。
4. 依次验证 Schema、Action Contract、Goal/Plan 与 Authority。
5. 拒绝时不执行 Tool，不产生世界状态写入。
6. 合法时每回合最多执行一个 Tool，由 `CaseEngine` 产生结果和连续事件。
7. 保存权威状态，再从已提交结果构建公开反馈。
8. `PlanEvaluator` 根据结果保持、修订、完成或结束计划。
9. Episode 结束后，Reflection 只能基于 evidence 形成候选经验并经验证写入。
10. 重放从初始状态与事件序列重建，并与持久化终态核对。

## 架构声明门禁

任何新增文案或功能说明都必须满足：

- 不承诺 Agent 未获授权的 Observation；
- 不改变 Agent、Player 与 deterministic system 的既有权责；
- 不把工程策略或评测限制写成世界物理规律；
- 不把普通案件角色包装成 Multi-Agent 协作。
