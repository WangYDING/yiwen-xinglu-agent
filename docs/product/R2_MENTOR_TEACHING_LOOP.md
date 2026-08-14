# R2：最小导师教学闭环

> 状态：已实现（2026-08-11）
> 课程版本：`evidence_before_diagnosis_v1`
> 教学状态：`teaching_session_v1`

## 导师与角色边界

版本化可信人物资源定义“玄医先生”（`xuanyi_mentor`，v1，隐居玄医导师）。他冷静、克制、重视证据、诚实、谨慎、承诺与当事人保护；不因异类或异象自动判断恶意，不羞辱弟子，也不提供现实医疗建议。

玩家仍通过正式病例服务选择调查、提交诊断和执行处置。导师只负责课程说明、一次反思、最多两张可信提示卡、病例后师评解释与固定下一步建议。导师没有病例工具，不写病例、R1 能力、关系、阶段、知识、权限或记忆。原 DoctorAgent 自动解题路径原样保留为 Fake/工程评测模式。

## 固定课程与 HintCard

R2 只有课程“证据齐备再定证”，且只绑定“旧纸伞与失约书生”。五项目标是覆盖必要公开调查、区分事实/推断/诱饵、引用已发现证据、让处置与判断一致、不草率认定异类恶意。

反思检查点在至少三类有效调查后最多触发一次。提示额度为两次并持久化：`hint_1` 提醒检查未覆盖的公开调查类别，`hint_2` 提醒对照已发现证据与可用调查方向。模型只能选择允许的 `hint_id`；展示正文始终由可信 HintCard 覆盖。提示不包含正确诊断、正确处置、隐藏线索、固定顺序或“选择某 ID”的答案。

固定下一步只有“下一步练习交叉核对契物来源”。R2 不做弱点驱动选课。

## MentorAgent 输入与动作

`MentorAgentInput` 按阶段提供最小公开输入：可信导师公开资料、课程公开视图、`ApprenticeshipView`、三维关系公开值、当前公开病例视图或最终公开结果、当前允许 HintCard、结构化师评、允许动作和可选玩家消息。它不含根因、正确性标记、未发现线索、隐藏门槛、传承条件、原始数据库、语义记忆或 DoctorAgent 计划。

`MentorAction` 只允许 `speak`、`ask_reflection`、`give_hint`、`review_performance`、`recommend_fixed_next_step`。Schema 拒绝额外字段；上下文契约再校验阶段、提示 ID、已发现证据 ID、能力 ID 和本次关系变化维度。任何状态写入前完成校验；失败最多进行一次 `mentor_action_contract_repair`，再次失败采用不泄漏、不写状态、不耗提示的确定性降级。

## TeachingSession 与重放

独立状态保存在 `teaching_sessions/{teaching_session_id}.json`，绑定一个玩家、课程、导师和病例 Session。阶段依次为 `assigned`、`active`、`case_completed`、`reviewed`、`completed`。

事件包括 `LessonAssigned`、`MentorBriefingIssued`、`ReflectionRequested`、`PlayerReflectionSubmitted`、`HintDelivered`、`CaseCompletionObserved`、`AssessmentAttached`、`MentorReviewIssued`、`TeachingSessionCompleted`。序号从 1 连续，修订等于事件数；读写均完整重放并比对快照。显示文本不可执行。反思只保存为教学显示记录，不进入病例事实、R1 或长期记忆。一个病例 Session 只会得到一个教学会话；重复创建、完成和师评均幂等。

## AssessmentReport

结构化师评先于导师语言，来源仅为已提交病例动作、公开结局/评分、提示、诊断证据引用和 R1 对该 Session 已提交的公开成长事件。报告包含完成/未完成目标、展示/待改进能力、提示、能力变化、关系变化、公开证据引用、固定下一步和来源修订。

同一来源产生稳定 `assessment_id` 和相同报告。错误诊断会保留“辨证仍需改进”，即使后续处置碰巧解决也不误表扬辨证；`suppressed` 与 `worsened` 均把施治和守则列为待改进，导师不会称为圆满解决。报告不复制根因、正确答案标记或未发现线索。MentorAgent 只能解释，不能修改报告。

## 提交顺序与故障窗口

```text
病例原子完成 → Campaign 投影 → R1 投影
→ CaseCompletionObserved → AssessmentAttached
→ MentorReviewIssued → TeachingSessionCompleted
```

- 病例未完成：`case_not_completed`，无最终师评。
- R1 待协调：`apprenticeship_projection_pending`，不声称成长完成。
- 师评保存失败：`teaching_assessment_pending`；病例、Campaign、R1 保持已提交，可显式重试。
- 导师失败：保留 Assessment，使用安全文本，不回滚权威事实。
- 教学保存失败：`teaching_state_pending`，不影响病例、Campaign 或 R1。
- 跨玩家访问在读取公开内容前拒绝，拒绝零写入。

## CLI

默认 `xuanyi-play --state-dir <目录>` 的 `mentor-mode=off` 行为不变，也不初始化 MentorAgent。离线教学入口：

```powershell
xuanyi-play --state-dir <目录> --mode manual --mentor-mode fake
```

教学模式只列出旧纸伞，展示课程、目标、提示额度、反思、结构化师评、R1 能力/关系变化和固定下一步。真实 DeepSeek Mentor 未开放。

## 当前限制与 R3 预留

R2 不含自适应选课、多课程、自动补课、新病例、晋级、考试、权限、传承、正式语义记忆、多 Agent、网页或真实导师模型。R3 可在不改变 R2 权威边界的前提下增加多病例课程标签、确定性弱点识别和结构化可信教学历史；R3 尚未开始。

## 验证摘要

R2 专项 15 项、R1+R2 联合专项 31 项、全量 523 项均离线通过。专项覆盖正确/错误诊断、0/2 次提示、第三次提示零写入、`resolved`/`suppressed`/`worsened`、非法动作一次修复与降级、反思不写 R1、跨玩家隔离、服务重建和两个独立 Python 进程恢复。既有 M5 32-worker 验收、MCP 22 项、V0/Fake/重放 34 项与无 LLM Demo 均通过。没有调用 DeepSeek、BGE、Embedding API 或网络，费用为 0 CNY。
