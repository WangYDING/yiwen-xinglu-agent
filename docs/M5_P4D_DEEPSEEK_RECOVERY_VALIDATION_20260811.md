# M5-P4d DeepSeek V0 最终真实恢复验证

## 结论

P4d 在冻结提交 `60f54a5d20f684f5e922c617c7c795a1d622613d` 上完成唯一一次授权运行，没有重跑、调参或修改产品代码。

1. **通用接口被真实触发**：两个新病例的 16 个决策步骤中，首次输出 16/16 均通过 `AgentAction` JSON Schema；其中 5 个不符合当前公开行动契约，触发 `action_contract_repair`。
2. **修复真实有效**：5/5 修复输出都成为合法公开行动并被规则层接受；修复失败、格式修复和确定性降级均为 0，同一步最多 2 次 Chat。
3. **本次行为闭环完成**：灰灶和月井均完成 6 次调查、诊断、处置，事件连续 1–8，终态均为 `completed / resolved / 100`。
4. **完整连续体验得到单次验证**：免费旧纸伞前史进入灰灶；灰灶完成后形成 `handoff_sequence_check`，并真实进入月井开场。CampaignEvent 连续 1–3，可重放。

这是修复前/后各一次的工程案例，不具备统计因果性，不是正式成功率、稳定性或玩家收益结论。P4b 的负结果没有被覆盖。

## 冻结身份与边界

- 执行提交：`60f54a5d20f684f5e922c617c7c795a1d622613d`
- 模型：`deepseek-v4-flash`
- Prompt：V0 `v0.2.1`
- semantic shadow：`off`
- 授权预算：`0.05 CNY`
- 单次 Chat 超时上限：180 秒
- `/models`：1 次
- 旧纸伞 Chat：0
- 灰灶 Chat：12
- 月井 Chat：9
- Chat 总计：21
- 实际确认费用：`0.02345744 CNY`
- 运行结束时最大已承诺费用：`0.02345744 CNY`
- BGE、Embedding API、其他模型和供应商请求：0

运行前 HEAD、工作树、空白状态目录、新结果路径、模型、预算、Prompt 和 shadow 配置均通过冻结预检。`.env` 只检查 Key 是否存在，没有输出或提交密钥。

## 免费前史与跨案上下文

旧纸伞由确定性 Fake 路径免费完成：事件 1–8、`resolved / 100`、处置 `return_token_and_fulfill_vow`，CampaignEvent 1 解锁 `contract_provenance_check`。病例与 Campaign 重放均一致。

灰灶开场只收到 P3 确定性公开前史：曾在旧纸伞案核对契物来源，并公开推荐 `inspect_hearth_contract`。灰灶完成后 CampaignEvent 2 解锁 `handoff_sequence_check`。月井开场随后公开提及灰灶中的归属与通路核验经历，并推荐 `question_lantern_witness`。这些信息来自确定性 Campaign，不是语义记忆。

## 灰灶逐步结果

| 步骤 | 最终模型行动 | Chat | 首次行动契约结果 | 最终执行 |
|---:|---|---:|---|---|
| 1 | `inspect_object(inspect_fuel_and_hearth)` | 1 | 合法 | 接受，事件 1 |
| 2 | `inspect_object(inspect_hearth_contract)` | 2 | `invalid_tool_arguments` | 修复成功，事件 2 |
| 3 | `observe_qi(observe_flue_qi)` | 2 | `unknown_investigation` | 修复成功，事件 3 |
| 4 | `investigate_location(investigate_smoke_passage)` | 1 | 合法 | 接受，事件 4 |
| 5 | `question_patient(question_innkeeper)` | 2 | `diagnosis_not_ready` | 修复成功，事件 5 |
| 6 | `observe_patient(observe_cook)` | 2 | `diagnosis_not_ready` | 修复成功，事件 6 |
| 7 | `submit_diagnosis(displaced_hearth_contract)` | 1 | 合法 | 接受，事件 7 |
| 8 | `execute_treatment(restore_token_and_clear_flue)` | 1 | 合法 | 接受，事件 8 |

灰灶共触发 4 次行动契约修复，4/4 成功。两次过早诊断提案在状态服务前被识别并改为公开调查，没有形成规则拒绝或状态变化。最终诊断和处置均由确定性规则接受，结局 `resolved`，得分 100，CampaignEvent 2 正常产生。

## 月井逐步结果

| 步骤 | 最终模型行动 | Chat | 首次行动契约结果 | 最终执行 |
|---:|---|---:|---|---|
| 1 | `inspect_object(inspect_wooden_slip)` | 1 | 合法 | 接受，事件 1 |
| 2 | `question_patient(question_route)` | 1 | 合法 | 接受，事件 2 |
| 3 | `inspect_object(inspect_binding_cord)` | 1 | 合法 | 接受，事件 3 |
| 4 | `question_patient(question_lantern_witness)` | 2 | `invalid_tool_arguments` | 修复成功，事件 4 |
| 5 | `observe_patient(observe_courier)` | 1 | 合法 | 接受，事件 5 |
| 6 | `observe_qi(observe_well_echo_qi)` | 1 | 合法 | 接受，事件 6 |
| 7 | `submit_diagnosis(misbound_message_handoff)` | 1 | 合法 | 接受，事件 7 |
| 8 | `execute_treatment(verify_recipient_and_deliver)` | 1 | 合法 | 接受，事件 8 |

月井触发 1 次行动契约修复并成功。最终诊断和处置由规则接受，结局 `resolved`，得分 100，CampaignEvent 3 正常产生。

## 修复码的离线核对方法

冻结 Runner 不保存原始错误提案或完整 Prompt，只保存每次请求的 SHA-256、最终行动和修复类型。为了在不泄漏 Prompt 的情况下核对修复前稳定错误码，离线使用同一提交、公开状态和最终行动重建了 16 个基础请求：16/16 SHA 与原始审计完全相同。随后为每个触发步骤枚举现有安全错误码并重建修复请求；5 个修复请求均得到唯一 SHA 匹配：

- 灰灶步骤 2：`invalid_tool_arguments`；
- 灰灶步骤 3：`unknown_investigation`；
- 灰灶步骤 5、6：`diagnosis_not_ready`；
- 月井步骤 4：`invalid_tool_arguments`。

该过程没有读取或恢复供应商请求 ID、完整 Prompt 或原始错误输出，也没有再次调用模型。

## 协议、行为与安全统计

- 首次结构化成功：16/16；所有 Chat 结构化成功：21/21。
- `action_contract_repair`：5 次触发，5 次成功。
- 格式修复：0；修复失败：0；确定性降级：0。
- 实际进入应用服务的付费病例行动：16；均被接受并各产生一个事件。
- 首次无效提案进入应用服务：0；规则层拒绝：0。
- 空耗 `respond`：0；重复调查：0；最终过早诊断：0；错误处置：0。
- 原始过早诊断提案：2，均在契约层修复为合法调查。
- 灰灶、月井事件均严格为 1–8，修订均为 8；磁盘终态与事件重放一致。
- Campaign revision 为 3，事件严格为 1–3；磁盘终态与 Campaign 重放一致。
- 请求审计中的语义记忆标记命中：0；semantic shadow 关闭。
- 跨玩家污染、非法状态写入、拒绝后事件、隐藏信息注入：均为 0。

## Token、延迟与费用

| 范围 | Chat | 输入 Token | 缓存命中 | 缓存未命中 | 输出 Token | 推理 Token | 总延迟 | 费用 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 灰灶 | 12 | 23,674 | 14,336 | 9,338 | 1,245 | 0 | 26,453.029 ms | 0.01211472 CNY |
| 月井 | 9 | 17,194 | 7,936 | 9,258 | 963 | 0 | 17,804.496 ms | 0.01134272 CNY |
| 合计 | 21 | 40,868 | 22,272 | 18,596 | 2,208 | 0 | 44,257.525 ms | 0.02345744 CNY |

全部供应商用量完整且可核对；没有超时、用量缺失或预算冻结。

## P4b / P4d 单次案例对比

以下只比较灰灶，不作统计因果推断：

| 指标 | P4b 修复前案例 | P4d 修复后案例 |
|---|---:|---:|
| 合法调查 | 2 | 6 |
| 参数错误进入工具/规则路径 | 2 | 0 |
| 行动契约修复触发/成功 | 0/0 | 4/4 |
| 规则拒绝 | 6 | 0 |
| 空耗 `respond` | 1 | 0 |
| 诊断 | 未提交 | `displaced_hearth_contract` |
| 处置 | 未执行 | `restore_token_and_clear_flue` |
| 结局/得分 | active / 无 | resolved / 100 |
| 灰灶闭环 | 否 | 是 |
| `handoff_sequence_check` | 未形成 | 已形成 |
| Chat | 8 | 12 |
| 输入/输出 Token | 14,377 / 834 | 23,674 / 1,245 |
| 延迟 | 15,000.352 ms | 26,453.029 ms |
| 费用 | 0.01278356 CNY | 0.01211472 CNY |

P4d 的额外 Chat 来自 4 次同一步行动契约修复。费用没有随请求数线性增长，主要受本次缓存命中差异影响，不能据此推断未来成本。

## 四层退出判断

1. **接口触发**：通过。通用行动契约在真实请求中触发 5 次。
2. **纠正效果**：通过。5/5 修复为合法公开行动，错误提案均未触达状态服务。
3. **模型策略**：本次单次运行未再出现 `respond`、重复调查、最终过早诊断或错误处置，并完成两个病例；但单次案例不能证明模型策略稳定可靠。
4. **产品连续体验**：本次验证覆盖免费旧纸伞 → 真实灰灶 → 真实月井的完整三病例 Campaign，两个公开前史反应和两项知识均出现；它不是普通玩家试玩或产品收益证据。

M5-P4 按“工程与安全通过、P4d 单次行为闭环成功、P4b 历史负结果保留”的实际证据关闭。此后不得继续 P4 真实重跑或 Prompt 调优；M5-P5 尚未开始，等待单独授权。

## 原始结果身份

- Git 忽略路径：`results/m5_p4d_recovery_20260811.json`
- 文件大小：83,606 bytes
- SHA-256：`24B4105E1607F84FA0E1D15810BAF9051FBAADCEF3D90470411EB7A0543BADD8`

P4b 原始结果未修改，SHA-256 仍为 `EFDC6B37692CAA117B352DD199B52AAFF20D765945E5C8FB585994453B712C2B`。仓库不提交原始结果、供应商请求 ID、完整 Prompt、`.env` 或 API Key。

运行后全量测试 `476 passed`，`pip check`、`git diff --check`、敏感信息和运行文件跟踪检查均通过；结果提交只包含脱敏报告和当前状态文档。
