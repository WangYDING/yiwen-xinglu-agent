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

该结论只证明程序化装配隔离，不证明真实 DeepSeek 的三病例完成率，也不证明真实 BGE shadow 的语义质量。M4.5 的 Dense 负结果保持不变，语义记忆仍不得进入正式 Prompt。

## P4b 一次真实验证

2026-08-11 的冻结 P4b 窗口使用免费 Fake 路径建立旧纸伞前史，再以 `deepseek-v4-flash`、shadow off 和 `0.05 CNY` 上限运行灰灶。模型发现 1 次，灰灶 Chat 8 次，实际费用 `0.01278356 CNY`；8/8 首次结构化成功，格式修复、降级、超时和语义记忆字段命中均为 0。灰灶只接受 2 个调查事件，随后出现 2 次参数错误、1 次解释性 `respond` 和 3 次 `diagnosis_not_ready`，未形成诊断、处置或 Campaign 解锁。月井因此按门禁保持 0 次调用。工程与规则安全通过，完整行为目标未达到。详见 `docs/M5_P4B_DEEPSEEK_CAMPAIGN_PILOT_20260811.md`；P5 尚未开始。

## P4c 通用行动契约与恢复

P4c 不改 Prompt `v0.2.1`、病例、规则、Campaign 或 8 步上限。它把“结构合法的 `AgentAction`”与“当前公开上下文中可执行的行动”分成两层：

1. DoctorAgent 先产生并通过外层 JSON Schema；
2. `PublicActionContractValidator` 根据刷新后的 `CaseObservation` 校验准确工具名、唯一参数字段、公开 ID、诊断就绪状态和已发现证据；
3. 第一次不符合时，使用既有一次修复额度发送严格结构化的公开反馈，并记录 `action_contract_repair`；
4. 修复后的行动只有再次通过契约才会提交 `MultiCaseEpisodeService`；
5. 规则引擎仍作最终裁决；第二次仍不合法时确定性降级，不进行第三次模型调用。

修复反馈只含稳定错误码、安全说明、公开诊断就绪状态、刷新后的准确调查工具/ID、公开诊断候选和当前处置候选，并固定提醒“口头描述不等于提交诊断”。反馈不含隐藏真值、评分、未发现线索、语义记忆、原始异常或完整 Prompt。正常合法动作不增加模型调用。

三病例 Fake 使用同一实现继续得到事件 1–8 和 `resolved / 100`；manual、MCP、Campaign、事件重放与 shadow off/on 隔离保持不变。冻结 P0/Pilot 历史轨迹仍按原历史语义重评，避免新修复步骤篡改既有结果。完整根因、证据与推断边界见 `docs/M5_P4C_AGENT_CONTRACT_AUDIT.md`。

该 P4c 检查点只有离线 Fake/Mock 证据，当时不能证明 DeepSeek 会在拒绝后选择高效动作，也没有解决解释性 `respond` 或一般策略选择问题。P4b 仍是灰灶未完成、月井未运行的历史负结果；后续 P4d 结果不得改写它。

## P4d 最终真实恢复验证

P4d 在精确提交 `60f54a5d20f684f5e922c617c7c795a1d622613d` 上使用 `deepseek-v4-flash`、Prompt `v0.2.1`、shadow off 和 `0.05 CNY` 上限执行一次，不修改代码、病例、Prompt、规则或步骤上限。旧纸伞仍由免费 Fake 路径建史；灰灶和月井各运行一次。

两个新病例的 16 个首次输出全部通过 JSON Schema，其中 5 个不符合当前公开行动契约，分别触发 `invalid_tool_arguments` 2 次、`unknown_investigation` 1 次和 `diagnosis_not_ready` 2 次。5/5 `action_contract_repair` 成功，格式修复、降级、规则拒绝、`respond`、重复调查和错误处置均为 0。灰灶与月井都以 8 个连续事件得到 `resolved / 100`；CampaignEvent 连续 1–3，两项知识和两段公开历史反应完整出现且可重放。

本次 `/models` 1 次、Chat 21 次，费用 `0.02345744 CNY`；语义记忆标记命中 0，BGE 和 Embedding 请求 0。它证明 P4c 接口在一次真实运行中被触发并成功纠正行动，也验证了一次完整三病例产品链路；但修复前后各只有一个案例，不能声明统计因果、正式成功率或稳定玩家收益。详细证据见 `docs/M5_P4D_DEEPSEEK_RECOVERY_VALIDATION_20260811.md`。

M5-P4 已按真实正负结果关闭，不再授权新的 P4 重跑或 Prompt 调优。M5-P5 尚未开始。
