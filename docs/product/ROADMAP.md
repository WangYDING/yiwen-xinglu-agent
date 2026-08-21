# 《异闻行录》当前路线图

> 状态：A2 Authoritative Product Identity Unification（2026-08-21）
>
> 本文件是当前里程碑状态来源。产品身份以 [`../architecture/PROJECT_MASTER_BLUEPRINT.md`](../architecture/PROJECT_MASTER_BLUEPRINT.md) 为准，系统边界以 [`../architecture/PRODUCT_SYSTEM_ARCHITECTURE.md`](../architecture/PRODUCT_SYSTEM_ARCHITECTURE.md) 为准。

## 文档优先级

1. 用户当前明确要求；
2. `docs/architecture/PROJECT_MASTER_BLUEPRINT.md`；
3. `docs/architecture/PRODUCT_SYSTEM_ARCHITECTURE.md`；
4. `docs/product/ROADMAP.md`；
5. `README.md`；
6. 追加式 ADR、产品分支文档与验证记录；
7. 历史归档与早期设计材料。

旧 Word 总结、`xuanyi-npc-handoff`、历史提交和 `docs/archive/` 继续按形成时身份解释，不代表当前产品定义。

## Current Product State

当前正式产品是 **《异闻行录》Human-Agent Cooperative Game NPC System**。玩家与 `GameNPCAgent` 组成调查搭档，共同处理古风志怪异案。Agent 维护 Goal/Plan、评价 `PlayerContribution`、使用受限 Memory 并在权限内自主调查；玩家参与线索、质疑、诊断协商和高风险授权；确定性系统验证行动并由 `CaseEngine` 独占世界状态变化。

M1–M5 是当前 Cooperative Agent 核心工程与验证主线，均已完成并封版：

| 当前主线 | 状态 | 已验证范围 |
|---|---|---|
| M1：Human-Agent Cooperation | 已完成并封版 | `PlayerContribution`、合作决策、Public Action Space、Authority 与每回合单 Tool 边界 |
| M2：Goal / Planning / Replanning | 已完成并封版 | 持久化 Goal、短期 Plan、`GoalPlanPolicy`、`PlanEvaluator` 与可观察 Replanning |
| M3：Long-term Memory | 已完成并封版 | 来源与作用域过滤、MemoryView、玩家隔离、持久化，以及 selected → declared → accepted 使用归因 |
| M4：Reflection / Experience Learning | 已完成并封版 | outcome-grounded Reflection、弱证据拒绝、MemoryCandidate 验证与保守 consolidation |
| M5：Benchmark / Real LLM Validation | 已完成并封版 | deterministic paired ablation、真实模型小样本验证、stage-level telemetry、失败分析与 post-fix 复核 |
| A2：Narrative Repositioning / Presentation Alignment | 进行中 | 当前权威产品身份、架构、路线图、首页和作品集口径统一；不修改 Agent 行为 |

### 当前产品证据

- 本地六病例 Clinic 是正式玩家入口；`xuanyi-play` 是保留的 CLI / 工程入口；MCP 是本地集成入口。
- M5 冻结的 5 个 deterministic paired experiments 中：3 个 `IMPROVED`、2 个 `EXPECTED_NOOP`、0 个 `REGRESSED`。
- `deepseek-v4-flash` post-fix small pilot 共 9 runs：9/9 complete、9/9 schema valid、9/9 contract pass、9/9 plan policy pass、9/9 direct proposal success，repair/fallback/truncation 均为 0/9。
- Prompt Injection 条件中模型 3/3 拒绝越权建议，确定性系统 3/3 无危险执行。
- 上述结果是单一模型、每条件 3 repeats、有限场景下的描述性工程证据，不是统计成功率、生产能力或玩家收益。

### 当前限制

- 真实模型证据范围有限；没有跨模型统计结论。
- 语义向量记忆的 Dense-only 实验未通过完整质量门禁，继续默认关闭，不进入正式 Agent 决策链。
- 没有生产并发、公网认证、长期运维或远程发布证据。
- 没有真人对照实验、教学效果、留存或玩家收益结论。
- 所有医疗相关内容均为架空游戏设定。

## Retained Product Branch

R-series 是 retained / historical teaching、growth、exam、permission 与 inheritance product evolution。其实现、测试、内容和离线验收继续保留，也可以作为 Clinic 的教学、成长与表达能力，但不再代表整个产品的最终身份，不替代 `GameNPCAgent` 的 Cooperative Investigation 主链。

| 分支阶段 | 状态 | 保留能力与边界 |
|---|---|---|
| R1：Apprenticeship Growth | 已完成 | 跨 Episode 能力、三维关系、来源证据、长期事件、存储、回放与恢复；确定性状态，不改变 Agent 权限 |
| R2：Mentor Teaching Loop | 已完成 | 固定课程、HintCard、反思、师评与成长解释；Mentor 无病例 Tool 和权威写权限 |
| R3：Adaptive Curriculum / Structured Memory | 已完成 | 三病例课程、补课、确定性选课、教学计划和结构化历史；不以 LLM 自由决定权威课程状态 |
| R4：Exam / Permission / Inheritance | 已完成 | 阶段、规则考试、补课重考、权限聚合与“溯契还因”传承链；结果由确定性规则决定 |
| R5：Six-case Clinic Progression | 已完成 | 六病例、课程选择、成长/关系/师评/考试/传承页面与 loopback Clinic 组合入口 |
| R6：Retained Branch Acceptance | 离线工程范围已完成；真人/发布未完成 | 离线产品验收、受控 Mentor Pilot 与展示边界；不代表真人效果、生产稳定性或正式发布 |

详细范围见：

- [`PRODUCT_COMPLETION_PLAN_V1.md`](PRODUCT_COMPLETION_PLAN_V1.md)
- [`R1_APPRENTICESHIP_GROWTH.md`](R1_APPRENTICESHIP_GROWTH.md)
- [`R2_MENTOR_TEACHING_LOOP.md`](R2_MENTOR_TEACHING_LOOP.md)
- [`R3_ADAPTIVE_THREE_CASE_TEACHING.md`](R3_ADAPTIVE_THREE_CASE_TEACHING.md)
- [`R4_EXAM_PERMISSION_INHERITANCE.md`](R4_EXAM_PERMISSION_INHERITANCE.md)
- [`R5_SIX_CASE_CLINIC_PRODUCT.md`](R5_SIX_CASE_CLINIC_PRODUCT.md)

`MentorAgent` 的当前定位是 retained teaching / presentation branch：它可以表达确定性规则已经形成的公开课程、评价、考试、权限和传承事实，但不能替玩家或 `GameNPCAgent` 操作病例，也不能写权威状态。

## Historical / Baseline

以下内容继续保留为可复现的历史工程证据：

- `DoctorAgent`：V0 baseline / historical benchmark Agent；
- V0/V1 Doctor 输入、Fake 自动演示与旧真实模型 Pilot；
- M4.5 BGE-M3、语义 Gold、holdout、负结果与终止审计；
- M5 三病例纵向切片、Campaign 连续性、CLI 恢复和早期 Agent 模式；
- M6 分发、作品集和发布准备记录；
- R-series 各阶段报告及 Mentor Pilot。

这些记录不因当前身份统一而回写。旧文件中的“玄医问道”“问道医途”、三病例范围或 Mentor 主产品定义按形成时历史上下文阅读；它们不覆盖当前 Blueprint。

## 技术与兼容性标识

以下名称保持不变：

- repository/package identifier：`xuanyi-npc`；
- Python package：`xuanyi_npc`；
- console commands：`xuanyi-*`；
- Git tags、历史 commit 名、M/R milestone 名；
- 既有 API、schema、resource 与 benchmark identifier。

这些是 historical / compatibility engineering identifiers，不是当前对外品牌。当前正式产品名统一为“异闻行录”。

## Presentation Follow-up

本阶段只统一权威文档与展示元数据，不改功能。以下留待 UI 最终定稿后处理：

- `xuanyi-play` 中“玄医问道 · 病例修习”等历史 CLI public strings：`FOLLOW_UP_PRESENTATION_CANDIDATE`；
- Python docstrings、MCP 的 `Xuanyi` / `M3-P1` 描述：`TECHNICAL_IDENTITY_CLEANUP_CANDIDATE`；
- 仍显示“玄医问道”、旧三病例目录或旧定位的 SVG、transcript、screenshot：`REGENERATE_AFTER_UI_FINALIZED`；
- Clinic 中 retained teaching 页面沿用的“导师”“弟子”“考试”“传承”称谓：需要在不改变 R-series 功能的前提下完成角色与导航层级说明。

## 后续门禁

任何新的产品文案必须检查：

1. 是否承诺不存在的 Observation 权限；
2. 是否改变 Agent、Player 与 deterministic system 的现有权责；
3. 是否把工程限制写成世界物理规律；
4. 是否把 `MentorAgent` 重新描述成 Cooperative 主 Agent；
5. 是否把 R-series 描述成当前唯一产品主线；
6. 是否改写了历史 benchmark、Pilot 或负结果。

任一答案为“是”，停止合入并回到 Blueprint 与 System Architecture 核对。
