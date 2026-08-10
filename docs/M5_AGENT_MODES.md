# M5-P4a Agent 运行模式与 semantic shadow 边界

## 结论

M5-P4a 只完成离线装配与隔离验证。正式玩法使用两个正交开关：

- `GameplayMode`：`manual`、`fake`、`deepseek_v0`；
- `SemanticShadowMode`：`off`、`record_only`。

默认是 `manual/off`。semantic shadow 不是第四种 Agent；它没有行动权，也不是 Agent 输入源。

## 正式执行路径

manual 继续使用 P1～P3 的交互式菜单。Fake 和 DeepSeek V0 由 `ModeAwareEpisodeRunner` 编排，但每个工具行动都经过同一条路径：安全 `PlayerView`/`CaseObservation` → 严格 `AgentAction` → `MultiCaseEpisodeService` → `V0ToolExecutor`/规则引擎 → 原子保存 → completed 后 Campaign 协调。Runner 只消费应用服务返回的领域事件回执，不复制病例规则、评分或 Campaign 投影。

Fake 的三条参考脚本只用于测试和录屏演示，不进入病例 JSON、公开菜单或 DeepSeek Prompt。每案仍是 6 次调查、1 次诊断和 1 次处置，产生连续事件 1–8、`resolved / 100`。格式修复、规则拒绝、最大步骤和确定性降级继续有界；拒绝不会污染病例或 Campaign。

DeepSeek V0 保持 Prompt `v0.2.1`、`AgentAction` Schema、一次格式修复、无隐式重试、Flash-only 和现有成本/错误契约。真实启动前必须同时存在 API Key、显式付费确认、正预算、最长 180 秒超时、安全结果目录和一次模型发现。P4a 只使用 `MockTransport`，没有真实 `/models` 或 Chat 请求。

## record-only shadow

shadow 仅在成功领域事件已经保存后运行。它只接收刷新后的公开观察，过滤其他玩家和当前 Episode 候选，把脱敏 JSONL 写入 Git 忽略目录，然后丢弃检索结果。记录包含玩家 SHA-256 引用、Session、Memory ID、相似度、检索状态、表示空间、当前 Episode 排除、固定安全错误及三个固定 `false` 标记：`injected_into_prompt`、`affected_action`、`affected_state`。

记录不包含 API Key、完整 Prompt、原始聊天、隐藏真值、未发现线索或真实玩家敏感内容。shadow 失败只记录 `shadow_unavailable`；正式玩法继续。检测到跨玩家候选时记录安全错误并丢弃，不把候选发送给 Agent。`off` 不构造 Repository、Embedding、Torch、BGE 或结果文件。

## 隔离证据与限制

捕获型 Fake/Mock 已验证 shadow off/on 的 Agent 请求字节、`AgentAction`、工具、固定课程、行动序列、病例事件、终态和 Campaign 一致；唯一允许差异是 Git 忽略目录中的 shadow 记录。DeepSeek Mock 请求不含 `retrieved_memories`、相似度、Memory ID 或 CampaignFact 全文。

该结论只证明程序化装配隔离，不证明真实 DeepSeek 的三病例完成率，也不证明真实 BGE shadow 的语义质量。M4.5 的 Dense 负结果保持不变，语义记忆仍不得进入正式 Prompt。真实 P4b 必须另行限定模型、病例次数、预算和停止条件；P5 尚未开始。
