# M5-P3 确定性跨 Episode 连续性

## 结论

M5-P3 已完成。三个病例保持始终可玩；推荐顺序是“旧纸伞→灰灶客栈→月井回声”，只影响目录提示，不形成锁关。正式玩法的历史反应只读取已经保存的公开病例结果，不依赖 BGE、LLM、评测 Gold、诊断正确性或隐藏评分条件。

## 权威状态与投影

`campaigns/{player_id}.json` 是完成摘要、公开 CampaignFact 和知识成长的独立权威状态。每个 `CampaignEvent` 持有来源病例、Session、连续 ActionRecord 序号、公开诊断/处置、已发现线索、公开结局与分数，并使用 `campaign_projection_v1`。事件从 1 连续，Campaign revision 等于事件数，可由空 `CampaignState` 重放为相同终态。

提交顺序固定为：病例 Session 原子保存成功 → 校验 completed 公开收据 → 运行 `cross_episode_rules_v1` → 原子保存 Campaign。病例保存失败时 Campaign 写入为 0；Campaign 保存失败时病例保持成功，并返回 `campaign_projection_pending`。`reconcile_campaign` 只扫描已提交 completed Session，重复运行幂等；来源 Session 缺失、损坏或与收据不一致时明确停止，既有 Campaign 文件不变。

## 两项知识与公开效果

| 知识 | 公开解锁条件 | 后续效果 |
|---|---|---|
| `contract_provenance_check` | 旧纸伞 `resolved` 且处置为 `return_token_and_fulfill_vow` | 玩家历程显示知识；灰灶显示旧案反应并建议现有 `inspect_hearth_contract` 调查 |
| `handoff_sequence_check` | 灰灶 `resolved` 且处置为 `restore_token_and_clear_flue` | 玩家历程显示知识；月井显示灰灶反应并建议现有 `question_lantern_witness` 调查 |

规则不读取诊断正确性或 `score=100`。因此错误诊断配合相同公开解决处置仍会解锁；`suppressed` 和 `worsened` 不解锁。建议不会执行调查、发现线索、改变可用性、答案、处置、评分、技能或关系。

## 安全边界

- Campaign、规则和 CLI 不读取或公开 root cause、causal chain、合法诊断真值、正确性、未发现线索或隐藏门槛。
- 玩家 ID 在 Session、Campaign、事件、事实和知识各层校验；跨玩家 resume 拒绝且零写入。
- 拒绝动作、只读操作和 quit 不生成 CampaignEvent；不存在的 Campaign 文件是合法空历程，损坏文件明确失败。
- `CaseEngine`、三个病例 JSON、AgentAction、MCP 工具、V0 Prompt、SQLite 语义记忆和 M4.5 结果均未改变。
- JSON 存储仍不提供并发多进程事务；本阶段验证的是依次启动的独立进程恢复，不是并发写入。

## 验证摘要

Campaign A 按推荐顺序完成三案：每案 8 个连续病例事件、`resolved / 100`；Campaign 事件 1–3 连续；两项知识和两处历史反应可见；病例与 Campaign 均可重放。Campaign B 无前史直接完成月井：使用中性反应、无前两案知识，仍为 `resolved / 100`。

专项还覆盖错误诊断解锁语义、非 resolved 不解锁、重复 finish/reconcile 幂等、病例/Campaign 两个故障窗口、来源删除和篡改、损坏 Campaign、玩家隔离、拒绝零写入、公开视图隐藏字段哨兵和三个独立进程的连续恢复。
