# 玄医 NPC 当前路线图

## 文档优先级

本文件是项目唯一有效的里程碑状态来源。发生冲突时，按以下顺序解释：

1. 用户当前明确要求；
2. `docs/ROADMAP.md`；
3. `docs/DECISIONS.md` 中最新且状态为“已接受”的 ADR；
4. `README.md` 与 `docs/VERIFICATION.md`；
5. 其他历史材料。

Word 设计总结、`xuanyi-npc-handoff` 和 `docs/algorithm-experiment-plan-v0.1.md` 仅作为历史基线，不再表示当前执行状态。实验执行使用 v0.2 或更高版本。

## 当前状态

| 里程碑 | 状态 | 已验证范围 |
|---|---|---|
| M0：仓库与领域模型 | 已完成 | Pydantic 模型、病例 JSON、状态保存与读取 |
| M1：确定性病例引擎 | 已完成 | 调查、证据、诊断、处置、评分、明确错误、无 LLM Demo |
| M1.5：Agent 前安全门槛 | 已完成 | 安全视图、AgentAction、EpisodeResult、事件重放、Gold 快照、版本边界 |
| M2a：Fake LLM Agent Harness 与安全闭环 | 已完成 | 可替换协议、Fake LLM、结构化行动、一次格式修复、确定性降级、规则工具、公开候选、完整 Episode |
| M2b-P0：供应商无关预检 | 已完成 | 3 条严格 dev 场景、参考/错误轨迹、确定性评测器、安全上下文审计、事件重放 |
| M2b-P1a：DeepSeek Adapter 离线预检 | 已完成 | 供应商无关用量、人民币价格快照、直接 HTTP Adapter、模型发现、错误分类、预算门禁、MockTransport 测试 |
| M2b-P1b：真实 LLM Pilot | 待单独授权，下一阶段 | 查询 Key 可用模型、3 场景小型 Pilot、真实超时/Token/延迟/CNY 成本 |
| M3：最小 MCP 工具层 | 未开始 | M2b-P1b 完成前禁止开始 |
| M4 及以后 | 未开始 | 长期记忆、自适应教学、Reflection、界面、多 Agent 均未开始 |

## M2a 完成边界

M2a 证明以下工程性质：

- Agent 只接收 `PlayerView`、`CaseObservation`、最近有限消息和固定课程；
- 公开诊断词表、调查说明和处置说明提供可提交语义，但不携带正确性、结果、评分或隐藏门槛；
- `AgentAction` 必须通过 Pydantic 校验；首次格式错误只修复一次，再失败安全降级；
- 工具层只把建议翻译为领域命令，关键状态只能由规则引擎和领域事件修改；
- 已知错误诊断可正常提交并计为错误，未知诊断被拒绝且不改变状态；
- Fake LLM Episode 有最大步骤、连续事件、统一记录和可重放终态。

M2a 不证明真实模型能够完成病例，也不产生真实成功率、延迟、Token 或成本数据。

## M2b-P0 已完成边界

M2b-P0 不依赖真实供应商，已建立：

1. `dev_case_correct_001`、`dev_case_wrong_hypothesis_001` 和 `dev_recovery_001` 三条人工定义场景；
2. 每条场景各一条参考轨迹和至少一条明确错误轨迹；
3. 严格、禁止未知字段的场景 Schema，真值和成功/失败条件由数据定义；
4. 只以统一 `EpisodeResult` 为输入的确定性评测器；
5. 正确闭环、语义错误分类、一次格式修复、最大步骤、连续事件和终态重放测试；
6. 对 Agent 请求的安全字段审计，以及 `measurement_status = not_measured` 的 Fake LLM 输出；
7. 本地命令 `xuanyi-dev-eval`，一次运行全部三条场景及其对照轨迹。

P0 是真实 Pilot 前的强制门槛，不代表真实模型行为已经验证。

## M2b-P1a 已完成边界

供应商已确定为 DeepSeek 官方 API，首轮模型固定为 `deepseek-v4-flash`。P1a 已在不读取真实 Key、不发起真实网络请求的条件下完成：

1. `ModelUsage` 使用供应商无关 Token、缓存、推理、延迟、估算成本、币种和供应商元数据；
2. 2026-08-04 DeepSeek Flash 人民币价格作为带来源的数据快照保存；
3. `DeepSeekChatAdapter` 使用 `/chat/completions`、JSON Output、显式关闭思考、非流式和 512 Token 默认上限；
4. 模型发现只检查 `/models` 中是否存在 Flash，不自动切换 Pro 或旧别名；
5. 认证、限流、超时、5xx、非法响应、空内容、缺字段和截断具有明确错误；Adapter 无隐式重试；
6. Pilot 只允许冻结的 3 条 P0 场景各 1 次、每 Episode 8 步、每步一次格式修复；
7. 返回 Token 的人民币成本达到 1.00 元后停止启动新 Episode，并保留已完成结果；
8. 所有供应商与预算测试只使用 MockTransport 或进程内测试桩。

P1a 不证明 Key 可用、模型当前可见或真实模型能够完成病例，不产生真实指标。

## M2b-P1b 强制门槛

P1b 只有在用户再次明确授权付费 Pilot 后才能开始：

1. 先调用只读 `/models`，确认当前 Key 实际可见 `deepseek-v4-flash`；不存在时报告列表并停止；
2. 使用 P0 已冻结的 3 条场景各运行 1 次，不改变 P1a 的预算和步骤限制；
3. 保存原始结构化轨迹、精确返回模型名、请求 ID、指纹、Prompt 版本和配置；
4. 只报告供应商实际返回的格式结果、任务结果、超时、Token、延迟和 CNY 成本；
5. 验证关键状态非法写入为 0、会话串扰为 0、事件可重放、测试与日志完整；
6. 全部 M0–M2b-P1a 测试继续通过。

未满足以上条件时，M2 保持“进行中”，不得开始 M3。

## M3 及以后

M3 只计划把现有应用服务包装为最小 MCP 工具，不复制领域规则。M3 尚未开始，M2b-P1b 完成前不创建 MCP 文件或依赖。

V1 仅规划基础向量 Top-K 长期记忆与固定课程；V2 才规划多因素记忆排序、自适应教学和 Reflection。三个产品版本始终启用 `AgentContextFilter`，模型始终不能直接写永久记忆或关键状态。
