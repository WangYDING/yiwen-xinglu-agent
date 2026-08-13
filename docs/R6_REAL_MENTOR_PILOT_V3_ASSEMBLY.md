# R6 真实导师 Pilot v3 执行装配

状态：离线装配完成，真实 v3 Pilot 尚未授权、尚未运行。

## 为什么预冻结后仍不能运行

预冻结提交只固定了五个输入、CommunicationPlan、Prompt、`MentorActionV2` Schema、评测器和停止策略；当时 CLI 仍静默加载 v2 manifest、历史 `MentorAction`、v2 request builder 与 v2 停止策略。启动门禁因此在网络前拒绝，`/models` 和 Chat 均为 0。

## v2 / v3 入口边界

当前入口必须显式指定 `--pilot-version v3`；未知或缺失版本由参数层在任何传输创建前拒绝。v3 runner 只读取 v3 manifest、v3 输入快照与 v3 期望快照，不读取 v2 manifest。v2 runner 保留为历史代码和结果重放证据，不作为当前准入入口。

## 完整执行链

`v3 CLI → v3 manifest/blob及七类哈希 → 五个v3输入 → MentorCommunicationPlanner → 冻结Prompt → MentorActionV2 Schema → 专用DeepSeek传输 → JSON/Schema/point覆盖/正文/安全评测 → 一次公开修复 → 场景结果与运行停止分离 → fallback → 脱敏结果与原始结果SHA`。

真实启动前还要求 Git 工作树干净、模型/价格/thinking/预算/请求数匹配。任何身份错误发生在传输实例创建前。

## 修复、fallback 与停止

首次输出遗漏或正文不支撑 point 时，修复消息只列缺失或不被支撑的公开 point ID，沿用同一 CommunicationPlan，并由传输层重新进行预算预留。第二次仍安全但不完整时，场景记录 `teaching_failed`，交付确定性 fallback，`run_stop_reason=null`，继续下一个独立场景；fallback 不计为模型通过。

非 JSON、错误 Schema 或未知 point ID 在一次修复后仍失败时为 `contract_stop`。泄漏、越权、替玩家行动、`AgentAction` 或病例工具越界为 `safety_stop`，不使用 fallback 掩盖，并将后续请求记为 `not_observed`。协议、预算、超时和供应商身份失败同样立即停止。

## dry-run

离线命令：

```powershell
xuanyi-real-mentor-pilot --pilot-version v3 --dry-run
```

只输出模型、thinking、预算、价格快照、五个 request/plan ID、每计划 point 数、Prompt/Schema/评测器哈希、停止策略和最大请求数；不输出完整 Prompt、密钥、隐藏状态、答案或门槛，传输调用数固定为 0。

Mock 已覆盖五场景首次通过、一次修复成功、质量失败 fallback 后继续到授予、安全失败停止、协议/契约/模型/usage/超时失败、预算与请求纯度。本轮未访问任何网络，费用为 `0 CNY`。
