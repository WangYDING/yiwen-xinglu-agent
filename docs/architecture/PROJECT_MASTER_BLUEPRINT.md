# 《异闻行录》项目总纲

> 状态：当前产品身份冻结（2026-08-21）
>
> 作用：本文件是当前产品身份与核心体验的最高层权威来源。它不改写历史提交、实验结果、M/R 里程碑或退出审计；旧材料中的“玄医问道”“问道医途”按形成时的历史产品身份理解。

## 一句话主题

**《异闻行录》是一套 Human-Agent Cooperative Game NPC System：玩家与一名具备独立判断、Planning、Memory 和 Tool-use 能力的自主 NPC 结伴调查古风志怪异案。**

所有病例、人物、术法、异常现象和处置方式均为架空游戏叙事，不提供现实医疗诊断、处方、剂量或健康建议。

## 当前产品身份

1. **玩家**：调查合作者。玩家提供线索、假设、质疑和建议，影响调查方向，与 NPC 协商诊断，并对重大、高风险或不可逆处置提供明确确认。
2. **当前主 Agent**：`GameNPCAgent`。它读取权限过滤后的公开 Observation，维护 Goal/Plan，评价 `PlayerContribution`，在 Public Action Space 中选择候选行动，在权限内自主推进普通调查，并根据结果 Replan。
3. **确定性系统**：`PublicActionContract`、`GoalPlanPolicy`、Authority Policy 与 `CaseEngine` 验证行动、计划和权限，执行合法 Tool，并独占实际世界状态的变更权。
4. **长期记忆与反思**：Memory 是有范围和来源约束的历史经验；Reflection 必须以真实执行结果为证据，经确定性验证和保守写入后才能成为未来经验。
5. **保留分支**：`MentorAgent` 是 retained teaching / presentation branch，服务课程、成长、考试、权限和传承表达，不代表当前 Cooperative Game NPC 的主 Agent 身份。
6. **历史基线**：`DoctorAgent` 是 V0 baseline / historical benchmark Agent，用于回归、演示与历史工程评测，不代表当前玩家体验。
7. **系统形态**：普通案件角色不是 Agent；当前每次合作回合只有一个 `GameNPCAgent` 参与决策。**This is not a Multi-Agent system.**

## 核心权责

### Agent

- 形成调查意图；
- 维护 Goal 与 Plan；
- 评价玩家贡献，可接受、部分接受、拒绝、请求更多证据或提出替代方案；
- 在公开 Action Space 中选择候选行动；
- 自主执行权限范围内的普通调查；
- 根据新 Observation 与 Tool 结果 Replan；
- 使用经过范围、来源和使用归因约束的历史 Memory。

### Player

- 提供线索、假设、质疑和建议；
- 影响调查方向，但不能直接构造或执行 Agent ToolCall；
- 与 NPC 协商诊断；
- 对重大、高风险和不可逆处置提供确认。

### Deterministic System

- 验证 Action、Goal、Plan 与 Authority；
- 执行合法 Tool；
- 由 `CaseEngine` 决定实际结果、事件和世界状态；
- 拒绝越权、非法参数和与当前公开状态不一致的行动，并保证拒绝不污染状态。

核心原则：

> Agent 决定准备推进什么；玩家参与判断和高风险授权；确定性系统裁定什么真正能够发生。

## 当前核心体验

```text
PlayerContribution
→ public Observation
→ Goal / Plan
→ scoped Memory Retrieval
→ GameNPCAgent proposal
→ cooperative Decision
→ deterministic validation
→ bounded Tool
→ CaseEngine
→ Plan Evaluation / Replanning
→ evidence-grounded Reflection
→ conservative Experience Consolidation
```

玩家应感受到：

- NPC 不是等待固定触发词的脚本角色，而会依据当前证据、目标和历史自主判断下一步；
- 玩家能够真正影响 NPC，但不能遥控 NPC 或绕过权限；
- 新证据、拒绝和执行结果可以产生可观察的计划调整；
- 历史经验可以改变合法 Plan 顺序或 Tool priority，但不能覆盖当前 Observation；
- 高风险处置需要明确确认，模型不能直接修改世界状态；
- 每个决定、拒绝、执行结果和经验来源都可追踪、恢复和审计。

## Planning、Memory 与 Reflection

### Planning / Replanning

Goal 表示当前目标，Plan 保存有序步骤。`GoalPlanPolicy` 检查目标、步骤和公开 target 是否与当前合法行动一致；`PlanEvaluator` 根据新 Observation 和执行结果决定保持、修订、完成或结束计划。Plan 是可观察状态，不等于执行权限。

### Memory

长期记忆先按玩家、案件、类型和来源过滤，再进入候选选择。系统以 `selected → declared → accepted` 区分“检索到记忆”和“实际使用记忆”。当前 Observation 始终优先，Memory 不能注入新指令、替代世界真相或扩大权限。

### Reflection

真实 Episode 结果先形成 evidence，再生成 Reflection proposal。弱证据、越界推断和无来源总结必须被拒绝；只有验证通过的候选经验才能经保守 consolidation 进入未来检索。这里的“学习”是可审计的经验形成，不是模型参数训练。

## 保留的教学与成长分支

R-series 已实现或验证的 Mentor teaching、curriculum、progression、assessment、exam、permission 与 inheritance 能力继续保留。它们可以作为 Clinic 中的教学、成长和表达能力，也保留其工程与产品研究价值，但不再定义整个产品的最终身份，也不取代 `GameNPCAgent` 的 Cooperative Investigation 主链。

该分支继续遵守相同安全原则：Mentor 的语言或建议不是权威状态；课程、成长、考试、权限与传承结果由确定性规则决定。详细范围见 [`../product/ROADMAP.md`](../product/ROADMAP.md) 和 R-series 文档。

## 工程阶段解释

- **M1–M5**：当前 Cooperative Agent 核心工程与验证主线，覆盖 Human-Agent Cooperation、Planning/Replanning、Long-term Memory、Reflection 和 Agent Benchmark / Real LLM Validation。
- **R-series**：retained / historical teaching、growth、exam、permission 与 inheritance product evolution。
- **DoctorAgent 与旧 Pilot**：historical baseline / benchmark evidence。
- **M4.5 语义检索**：保留真实负结果；未通过的 Dense-only 能力继续默认关闭，不进入正式 Agent 决策链。

## 技术标识与历史身份

`xuanyi-npc`、`xuanyi_npc`、`xuanyi-*` 命令、Git tags、M/R 里程碑和既有 API/schema 标识是保留的历史或兼容性工程标识，不因对外品牌统一而重命名。历史文档按形成时身份保留；当前对外产品名统一为“异闻行录”。

## 明确非目标与证据边界

- 不让 LLM 直接写病例、玩家、权限、记忆或其他关键状态；
- 不把普通案件角色包装成多个 Agent；
- 不把固定 Workflow 冒充自主 Planning；
- 不把检索到 Memory 等同于 Agent 实际使用；
- 不把 Reflection 描述为模型训练；
- 不把单模型、小样本真实 Pilot 描述为生产成功率或玩家收益；
- 不把确定性 Fixture、Fake 结果或测试数量替代真实玩家研究；
- 不承诺公网部署、生产并发、开放世界或真实医学能力。

## 权威文档层级

1. 本文件：产品身份与核心体验；
2. [`PRODUCT_SYSTEM_ARCHITECTURE.md`](PRODUCT_SYSTEM_ARCHITECTURE.md)：当前系统架构；
3. [`../product/ROADMAP.md`](../product/ROADMAP.md)：当前状态、保留分支与历史演化；
4. [`../../README.md`](../../README.md)：对外摘要。

这些文件必须共同描述“异闻行录 + Human-Agent Cooperative Game NPC System”，不得再把 Mentor teaching 或 R-series 写成替代 Cooperative Agent 主线的唯一最终产品定义。
