# M5-P2 正式病例设计记录

状态：M5-P2 已实现并完成离线验证；M5-P3 尚未开始。

本文记录两个正式病例的玩法目标、公开/隐藏边界、冻结参考轨迹和失败对照。它是内容审计资料，不进入 Agent 上下文，也不改变 `CaseDefinition`、`CaseEngine`、事件、评分或重放语义。

## 公共边界

| 允许进入玩家视图 | 只留在可信病例与评测层 |
|---|---|
| 病例标题、简介、人物公开资料 | `root_cause`、`causal_chain` |
| 当前可用调查的说明 | `valid_diagnosis_ids` 与正确性标记 |
| 已经发现的线索说明 | 尚未发现的线索及调查隐藏依赖 |
| 三个诊断候选的公开解释 | 正确处置标记、内部评分判定 |
| 当前规则允许显示的处置说明 | 人物隐藏信息与 P3 未来跨案条件 |
| 完成后的公开结局和总分 | 领域事件中的内部正确性收据 |

公开候选只描述可供玩家检验的假设，不使用“正确答案”等标签。CLI 继续只读取 `CaseObservation` 和公开结果；病例 JSON 的隐藏字段不会交给 CLI、Prompt 或普通用户输入。

## 灰灶客栈与无火炊烟

- `case_id`：`gray_hearth_inn`
- 玩法目标：把调查从患者扩展到燃料、灶台、契物和烟道；区分异常表象、普通故障与契物/通路错位，避免看到逆风灰痕就直接归因于恶意侵害。
- 内容规模：6 个调查、8 条线索（6 关键、2 误导）、3 个诊断候选、3 个处置、3 级提示。
- 初始调查：观察掌勺人、询问店主、检查燃料和旧灶，可任意选择。
- 后续结构：检查旧灶后，契槽核对与观炁可以交换顺序；二者完成后才开放烟道调查。整张依赖图无环且没有单一路径。

冻结正确轨迹：

1. `observe_cook → question_innkeeper → inspect_fuel_and_hearth → inspect_hearth_contract → observe_flue_qi → investigate_smoke_passage`
2. `inspect_fuel_and_hearth → observe_flue_qi → inspect_hearth_contract → investigate_smoke_passage → question_innkeeper → observe_cook`

两条轨迹随后提交 `displaced_hearth_contract`，执行 `restore_token_and_clear_flue`，均产生连续事件 1–8，终态为 `completed / resolved / 100`。

冻结失败对照：

- 正确诊断 + `seal_hearth_mouth`：`suppressed / 70`；
- 正确诊断 + `expel_ash_keeper`：`worsened / 50`；
- 合法错误诊断 `ash_wraith_intrusion` + 根因处置：诊断分为 0，最终 70；
- 缺少公开前置时执行根因处置：规则拒绝，状态不变；
- 重复调查、未知调查/诊断/处置：规则拒绝，事件与修订不增加，持久化文件逐字节不变。

P3 可评估但本阶段未实现的公开钩子：玩家是否选择归还契物、是否保留客栈烟道记录。这些只能由未来已提交事件投影为结构化公开事实，不得改变本案隐藏真相或写进当前运行逻辑。

## 月井回声与错投木简

- `case_id`：`moon_well_echo`
- 玩法目标：交叉核对送信人陈述、木简/系绳物证、月井现象和见证人顺序；区分恶意实体、紧张错觉与消息交接错绑，避免仅凭提前回声就封井。
- 内容规模：6 个调查、8 条线索（6 关键、2 误导）、3 个诊断候选、3 个处置、3 级提示。
- 初始调查：观察送信人、询问行程、检查木简，可任意选择。
- 后续结构：检查木简后，系绳核对与月井观炁可以交换顺序；询问行程后可独立访问见证人。完整证据至少存在两种明显不同的合法顺序。

冻结正确轨迹：

1. `observe_courier → question_route → inspect_wooden_slip → inspect_binding_cord → observe_well_echo_qi → question_lantern_witness`
2. `inspect_wooden_slip → observe_well_echo_qi → inspect_binding_cord → question_route → question_lantern_witness → observe_courier`

两条轨迹随后提交 `misbound_message_handoff`，执行 `verify_recipient_and_deliver`，均产生连续事件 1–8，终态为 `completed / resolved / 100`。

冻结失败对照：

- 正确诊断 + `seal_moon_well`：`suppressed / 70`；
- 正确诊断 + `destroy_wooden_slip`：`worsened / 50`；
- 合法错误诊断 `malicious_echo_entity` + 根因处置：诊断分为 0，最终 70；
- 缺少公开前置时执行根因处置：规则拒绝，状态不变；
- 重复调查、未知调查/诊断/处置：规则拒绝，事件与修订不增加，持久化文件逐字节不变。

P3 可评估但本阶段未实现的公开钩子：玩家是否保存交接证据、是否完成核对后的递送。这些只作为未来确定性跨案事实的设计候选，不进入当前病例真值、玩家状态或 CLI 分支。

## 共同工程约束

- 两案只使用新建玩家已有的 `observe_form`、`ask_cause`、`inspect_object`、`observe_qi` 四项能力，基础完成路径不依赖其他病例、关系、成长或长期记忆。
- 调查顺序和答案没有硬编码到 `CaseCatalog`、`MultiCaseEpisodeService` 或 CLI；目录仅通过加载可信 JSON 自动发现病例。
- 两案内容均为架空契物、炁息与消息回响，不提供现实医疗诊断、处方、药材剂量或健康建议。
- M5-P2 不创建 `CampaignEvent`、`CampaignFact`，不修改 `handled_case_ids`、关系、技能或任何 SQLite 记忆。
