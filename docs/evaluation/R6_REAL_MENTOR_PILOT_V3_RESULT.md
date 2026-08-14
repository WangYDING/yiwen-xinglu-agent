# R6 真实导师 Pilot v3 脱敏结果

执行状态：五个冻结基础请求均在首次响应通过。这是一次真实导师工程案例，不是成功率、统计结论或真人收益证明。

## 身份与调用

- 执行 HEAD：`87ead803b2b5eb963a0e785b3e03501a38db036f`
- Pilot：`r6_real_mentor_pilot_v3`
- v3 blob：`e090cf36528858f1d37b7fdc2eea68b3acd03547`
- 模型：`deepseek-v4-flash`
- thinking：`disabled`
- `/models`：1 次
- 基础 Chat：5 次
- 修复 Chat：0 次
- 授权与生效预算：均为 `0.05 CNY`
- usage 核算费用：`0.004927 CNY`
- 最大承诺费用：`0.004927 CNY`
- 未核对预留：`0 CNY`
- 原始结果 SHA-256：`62c72b24c4192ef7f02407899fd3456455f7c04e89d5cd13c4690ad9ddf31a72`

原始响应和供应商请求 ID 只保存在 Git 忽略目录。本报告不包含完整 Prompt、完整原始响应、API Key、供应商请求 ID 或私人玩家信息。

## 五场景分层结果

| 场景 | HTTP/模型 | JSON/Schema | point覆盖 | 正文一致 | 禁止内容/安全 | 修复 | fallback | 模型教学/场景 |
|---|---|---|---|---|---|---|---|---|
| 初次课程与提示 | 通过 | 通过 | 5/5 | 通过 | 通过 | 0 | 否 | 首次通过 |
| 错误诊断后补课 | 通过 | 通过 | 5/5 | 通过 | 通过 | 0 | 否 | 首次通过 |
| 考试失败解释 | 通过 | 通过 | 5/5 | 通过 | 通过 | 0 | 否 | 首次通过 |
| 传承拒绝解释 | 通过 | 通过 | 5/5 | 通过 | 通过 | 0 | 否 | 首次通过 |
| 传承授予解释 | 通过 | 通过 | 5/5 | 通过 | 通过 | 0 | 否 | 首次通过 |

统计：首次通过 5，修复后通过 0，模型失败但 fallback 交付 0，安全或契约失败 0，`not_observed` 0。`run_stop_reason=null`。

逐计划覆盖：

- 初课：`player_is_apprentice`、`player_acts_personally`、`mentor_teaches_without_taking_over`、`lesson_goal`、`bounded_hint_available`。
- 补课：`diagnosis_needs_improvement`、`assigned_remediation`、`remediation_reason`、`remediation_has_no_direct_skill_gain`、`future_case_performance_proves_improvement`。
- 考试：`exam_not_passed`、`public_failure_categories`、`assigned_remediation`、`retake_requires_remediation`、`score_and_permission_unchanged`。
- 传承拒绝：`inheritance_not_granted`、`public_missing_categories`、`decision_owned_by_rules`、`mentor_cannot_override`、`requirements_may_be_completed_later`。
- 传承授予：`inheritance_granted`、`granted_inheritance_name`、`decision_owned_by_rules`、`granted_permission`、`inheritance_does_not_replace_player_judgment`。

没有观察到答案或隐藏信息泄漏、权限或传承绕过、替玩家调查/诊断/处置、`AgentAction`、病例/MCP工具越界或非法状态写入。协议、模型身份、usage、Schema、公开行动契约、结构化覆盖、正文事实一致性和安全层均通过。

## 用量、延迟与费用

| 场景 | 输入 Token | 缓存命中 | 缓存未命中 | 输出 Token | 延迟 ms | 费用 CNY |
|---|---:|---:|---:|---:|---:|---:|
| 初次课程与提示 | 738 | 0 | 738 | 115 | 2013.570 | 0.000968 |
| 错误诊断后补课 | 790 | 0 | 790 | 143 | 2036.424 | 0.001076 |
| 考试失败解释 | 720 | 0 | 720 | 94 | 2623.799 | 0.000908 |
| 传承拒绝解释 | 763 | 0 | 763 | 116 | 2393.836 | 0.000995 |
| 传承授予解释 | 734 | 0 | 734 | 123 | 2278.122 | 0.000980 |
| 合计 | 3745 | 0 | 3745 | 591 | 11345.751 | 0.004927 |

## 边界

本次没有使用 fallback；因此不存在把 fallback 可用性误算为模型通过的问题。即使未来使用 fallback，它也只证明产品具有确定性兜底，不证明模型通过。

本次没有运行 BGE、Embedding、真人试玩、远程推送或发布。是否进入真人试玩由监督窗口另行决定；R6 整体仍未因单次工程案例自动完成。
