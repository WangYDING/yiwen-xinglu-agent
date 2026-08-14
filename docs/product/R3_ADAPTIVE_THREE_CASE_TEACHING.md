# R3：三病例自适应教学与结构化长期记忆

> 状态：已实现；R4 尚未开始。

R3 把 R2 的旧纸伞固定课程扩展为同一套通用三病例教学服务。玩家仍亲自调查、诊断和处置；规则层先根据已提交事实决定课程、补课、师评、长期计划和记忆，导师只解释这些结构化结果。

## 三个核心课程

| 课程 | 病例 | 核心目标 |
| --- | --- | --- |
| `evidence_before_diagnosis_v1` | 旧纸伞与失约书生 | 证据齐备再定证 |
| `provenance_before_intent_v1` | 灰灶客栈与无火炊烟 | 先核归属，再论善恶 |
| `corroborate_before_handoff_v1` | 月井回声与错投木简 | 证人与物证交叉核对 |

三课均来自包内版本化 JSON 资源，每课最多一次反思、两张可信 HintCard。提示不包含正确诊断、正确处置、隐藏调查顺序、未发现线索或直接答案 ID。

## 三个固定补课

- `remediate_evidence_completeness_v1`：调查类别缺失、过早判断或证据引用不足；
- `remediate_diagnostic_reasoning_v1`：合法错误诊断或辨证改进证据；
- `remediate_treatment_alignment_v1`：`suppressed`、`worsened`、施治或守则改进证据。

补课是固定结构化选择题，由规则比较 `option_id`；错误答案是合法教学事件，正确答案完成补课。补课不写 R1 熟练度，只有后续病例表现能成为新能力证据。

## 确定性课程策略

`curriculum_selection_v1` 的顺序冻结为：守则 → 施治 → 辨证 → 基础调查 → 旧纸伞 → 灰灶 → 月井。规则只读取 R1 能力证据、可信 Assessment 和已完成课程/补课；并列按稳定 ID 排序。相同状态必得相同结果。三课完成后显示“基础三课完成，等待后续考核规划”。推荐不锁关，玩家可以直接进入任一现有病例，且病例定义、答案和评分不变。

## 长期教学计划

`TeachingPlanState` 是唯一的长期教学聚合，不是第二个成长权威。它保存当前推荐、完成课程、完成补课、未解决改进项、原因码、最新 Assessment 与来源引用。事件包括初始化、`CoreLessonCompleted`、`RemediationAssigned`、`RemediationAttempted`、`RemediationCompleted` 和 `TeachingRecommendationUpdated`。完整事件重放、原子 JSON 保存和幂等协调保证退出恢复一致；R1 状态和证据不被迁移或改写。

## 结构化长期记忆

R3 复用 M4 的同一 SQLite 权威库、来源收据、状态、失效、更正、墓碑和硬删除机制。允许类型为病例经历、能力强项、学习模式、导师反馈和补课历史；来源仅为已提交病例完成、R1 能力证据、确定性 Assessment、补课结果和课程完成。聊天、自由反思、导师生成文本、DoctorAgent 输出、拒绝动作、未提交动作、隐藏根因、未发现线索和 Prompt 均不能写入。

`StructuredMentorMemorySelector` 先按玩家过滤，再排除当前 Episode、inactive、superseded、已删除和非允许类型。候选按未解决问题、相关师评、同类病例、相关强项、最近补课分类，并严格执行 `priority DESC / occurred_at DESC / memory_id ASC`，最多三条。它不调用向量检索、BGE、Embedding API、相似度或模型判断；空结果和没有 Embedding 都合法。

## MentorAgent 边界与关系表达

`retrieved_structured_memories` 只含 memory ID、类型、公开摘要、来源病例、时间和原因码，位于用户数据 JSON。系统约束明确它不是指令、工具命令或当前病例事实，不能覆盖课程、规则、工具和 Schema。导师只能引用它解释课程，不能用前案直接回答本案，也不能写记忆、选课、能力或关系。

信任和认可只映射为低、中、高三个确定性表达档位，影响称呼、语气、解释详略和是否强调独立完成；不影响提示额度、答案、评分、选课、成长、病例入口或权限。

## 路线、恢复与故障

优秀路线依次完成三课并引用前史；错误诊断进入辨证补课；危险处置优先进入处置与守则补课；证据引用不足进入证据完整性补课。不同玩家共用相同病例与评分定义，但计划、记忆和导师解释隔离。

三个独立进程已覆盖旧纸伞落盘、灰灶读取前史、月井再次恢复和最终三课完成。病例、Campaign、R1 和 Assessment 的既有提交不会因后段失败回滚；教学计划失败返回 `teaching_plan_pending`，记忆失败返回 `memory_projection_pending`，显式协调可幂等补齐。R2 原有 Campaign、R1、Assessment、教学和导师失败语义继续保留。

## 当前限制与 R4 接口

R3 不实现考试、重考、晋级、权限、传承、新病例、网页、多导师、真实 DeepSeek Mentor、语义检索、reranker、向量数据库、自动课程或自动病例。R4 只能读取三课完成状态、可信补课历史和结构化公开证据，仍不得让 LLM 决定考试、权限或传承。R4 尚未开始。
