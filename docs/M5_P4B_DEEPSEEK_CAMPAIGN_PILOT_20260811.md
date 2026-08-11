# M5-P4b DeepSeek V0 Campaign 小型验证

## 结论

本次授权窗口已经结束，未重跑、未调 Prompt，也未启动 M5-P5。

- 工程与安全：通过。Flash 模型可见，预算、停止门禁、结构化输出、规则拒绝、事件连续性、磁盘保存和重放均正常；semantic shadow 保持关闭，8 个 Chat 请求均未包含语义记忆字段。
- 灰灶行为：未完成。模型在 8 步内只完成 2 个合法调查，正确候选诊断的 3 次提交均被 `fixed_v0` 的 `diagnosis_not_ready` 拒绝，未执行处置，终态保持 active、无得分。
- 月井行为：未运行。灰灶没有形成 `completed/resolved` 和 `handoff_sequence_check`，运行器按冻结条件停止，月井 Chat 调用为 0。
- 跨 Episode 体验：部分验证。旧纸伞的公开前史、`contract_provenance_check`、灰灶开场反应和调查建议真实进入正式产品路径；由于灰灶没有闭环，第二段灰灶→月井连续性没有获得真实模型验证。

这是一名合成测试玩家、一个 Campaign、两个新病例中实际启动一个病例的一次运行，不是成功率、稳定性或玩家收益结论。

## 冻结身份与请求边界

- 授权基线：`bb06270878c8dd10cbd98cdb72fa42cbcaa0f53d`
- 专用运行器执行提交：`2b3fe6abec82b46021d11f3671697c4acd997a6c`
- 模型：`deepseek-v4-flash`
- Prompt：V0 `v0.2.1`
- semantic shadow：`off`
- 授权预算：`0.05 CNY`
- 最长单次 Chat：180 秒
- 模型发现：1 次
- Chat：8 次，全部属于灰灶；旧纸伞和月井均为 0
- 实际确认费用：`0.01278356 CNY`
- 运行结束时最大已承诺费用：`0.01278356 CNY`
- 剩余未使用预算：`0.03721644 CNY`
- BGE、Embedding API 和其他模型请求：0

原始结果位于 Git 忽略的 `results/m5_p4b_campaign_20260811.json`，SHA-256 为：

`EFDC6B37692CAA117B352DD199B52AAFF20D765945E5C8FB585994453B712C2B`

仓库只保留本脱敏报告；原始供应商请求 ID、完整 Prompt 和 API Key 均未提交。

## 免费前史

旧纸伞通过既有确定性 Fake 路径完成，没有调用 DeepSeek：

- 8 个连续病例事件；
- 正确公开处置 `return_token_and_fulfill_vow`；
- `completed / resolved / 100`；
- CampaignEvent 序号 1；
- 解锁公开知识 `contract_provenance_check`；
- 病例和 Campaign 从空状态重放均与磁盘终态一致。

灰灶启动时收到的公开前史反应为：道医记得玩家曾在旧纸伞案核对契物来源，并建议本案留意灶契归属；公开推荐调查为 `inspect_hearth_contract`。这部分只来自 P3 的确定性 Campaign，不是语义向量记忆。

## 灰灶逐步结果

| 步骤 | 模型行动 | 规则结果 | 事件 |
|---:|---|---|---:|
| 1 | `inspect_object(inspect_fuel_and_hearth)` | 接受 | 1 |
| 2 | `question_patient(target_id=cook_shen)` | 拒绝：`invalid_tool_arguments` | 无 |
| 3 | 再次提交相同形式的问询 | 拒绝：`invalid_tool_arguments` | 无 |
| 4 | `observe_qi(observe_flue_qi)` | 接受 | 2 |
| 5 | 用 `respond` 解释并口头给出 `displaced_hearth_contract` | 拒绝：`unsupported_action`；口头说明不等于提交诊断 | 无 |
| 6 | `submit_diagnosis(displaced_hearth_contract)`，引用两条已发现证据 | 拒绝：`diagnosis_not_ready` | 无 |
| 7 | 重复提交同一诊断 | 拒绝：`diagnosis_not_ready` | 无 |
| 8 | 再次提交同一诊断 | 拒绝：`diagnosis_not_ready` | 无 |

行为汇总：

- 合法调查：2；接受事件严格为 1、2。
- 规则拒绝：6，其中参数错误 2、解释性 `respond` 1、过早诊断 3。
- 已接受的重复调查：0；空耗解释性 `respond`：1。
- 最终已提交诊断：无；处置：无；结局：无；得分：无。
- Session 修订为 2，等于接受事件数；6 个拒绝步骤的事件序号均为空，没有增加病例修订。
- 病例事件从初始状态重放与最终 Session 一致；Campaign 保持修订 1，重放一致，没有灰灶 CampaignEvent 或 `handoff_sequence_check`。

模型识别到正确的公开候选方向，但固定 V0 课程仍有公开调查未完成，因此规则层没有接受诊断。这一结果同时暴露了真实行为限制：模型对统一工具参数的遵循和拒绝后的恢复不足，且 8 步上限下没有空间弥补两次参数错误、一次解释性动作和三次重复过早诊断。

## 协议、用量与安全

- 8/8 Chat 首次返回可通过 `AgentAction` Schema 的结构化 JSON。
- 格式修复 0；确定性降级 0；超时 0。
- 输入 Token `14,377`，其中缓存命中 `3,328`、缓存未命中 `11,049`。
- 输出 Token `834`；推理 Token `0`。
- 灰灶 Chat 总延迟 `15,000.352 ms`。
- 费用 `0.01278356 CNY`，用量完整且可以核对，未触发预算冻结。
- 8 个请求均通过发送前审计；`retrieved_memories`、`memory_context_status`、`MemoryView`、`memory_id`、`source_session_id`、`embedding_space_id` 和相似度字段命中数均为 0。
- shadow 关闭；没有初始化或加载 BGE，没有 Embedding 请求，没有语义记忆进入 Prompt、行动或状态。
- 没有跨玩家污染、非法事件、非连续事件或重放差异。

## 后续边界

本次结果不授权重跑灰灶，不授权绕过门禁补做月井，也不授权修改 Prompt、病例、规则或步骤上限。M5-P4b 的完整“两新病例真实闭环”目标尚未达到；M5-P5 仍未开始，等待监督窗口决定是否接受该负结果、另行设计恢复性验证，或直接进入不依赖新付费运行的纵向切片验收规划。
