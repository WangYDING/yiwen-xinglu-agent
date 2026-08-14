# R1：弟子长期状态与确定性成长

> 状态：已实现（2026-08-11）
>
> 策略版本：`apprenticeship_progression_v1`
>
> 状态 Schema：`apprenticeship_state_v1`

## 权威状态

每个玩家只有一个 `apprenticeships/{player_id}.json`。其中的 `ApprenticeshipState` 是跨 Episode 能力与师徒关系的唯一权威来源，包含教学阶段、六项能力、三维关系、能力证据、已应用来源 Session、连续长期事件、修订和时间戳。

病例 Session 中 `PlayerState` 的技能和关系字段继续保留，供既有病例门禁和执行路径兼容使用，但它们不是长期成长写入源。R1 不把长期成长反向同步进病例快照，因此没有两个可独立修改长期成长的权威聚合。后续 R2/R4 才能通过明确接口决定如何读取长期状态；R1 不改变病例权限。

## 初始值与等级

全部初始值来自包内版本化资源 `resources/progression/apprenticeship_progression_v1.json`：

| 能力 ID | 名称 | 初始熟练度 | 初始等级 |
|---|---|---:|---|
| `observe_form` | 察形 | 20 | `novice` |
| `ask_cause` | 问因 | 20 | `novice` |
| `inspect_evidence` | 验物 | 20 | `novice` |
| `reason_diagnosis` | 辨证 | 20 | `novice` |
| `apply_treatment` | 施治 | 20 | `novice` |
| `ethical_practice` | 守则 | 20 | `novice` |

等级阈值依次为 `novice` 0、`apprentice` 25、`competent` 50、`advanced` 75、`mastered` 90。六项能力在 R1 均已解锁；这只表示长期状态可以记录成长，不改变病例行动权限。

三维关系初始值均由同一配置冻结：亲近 10、信任 10、认可 10。

## 能力证据与成长规则

每条 `AbilityEvidence` 都有稳定 ID、玩家和能力、正向或改进极性、强度、公开原因、来源病例与 Session、来源事件序号、来源修订和发生时间。证据只来自已提交 `CaseSessionState.action_history` 和最终公开结果。

- 人物观察 → 察形；询问 → 问因；物件检查与地点调查 → 验物；观炁 → 辨证。
- 每类至少一个已接受的唯一调查形成强度 1 的正向证据；同项能力在一案内的调查强度最多为 2。
- 正确正式诊断为辨证提供强度 2 的正向证据；合法错误诊断只形成改进证据。
- `resolved` 为施治提供 2、为守则提供 1；`suppressed` 和 `worsened` 对两项只形成改进证据。
- 改进证据不降低熟练度。
- 无论一案产生多少正向证据，每项能力的单 Episode 增长最多为 2，熟练度限制在 0～100。
- 重复、未知、被拒绝、未提交的动作以及模型自然语言均不产生成长证据。

长期证据和事件不保存 `root_cause`、隐藏正确性标记、未发现线索、隐藏门槛、Prompt 或供应商内容。正确诊断只公开为“最终辨证获得正向公开评价”，不会复制隐藏答案。

## 三维关系

亲近、信任和认可是独立维度，全部限制在 0～100：

| 公开结果 | 亲近 | 信任 | 认可 |
|---|---:|---:|---:|
| `resolved` 且 90～100 分 | 0 | +1 | +2 |
| `resolved` 且 70～89 分 | 0 | 0 | +1 |
| `resolved` 且 0～69 分 | 0 | 0 | 0 |
| `suppressed` | 0 | 0 | 0 |
| `worsened` | 0 | -1 | -1 |

R1 没有可信社交行为事件，因此亲近始终不随病例完成变化。只有非零实际变化才生成 `RelationshipChanged`，并保存公开原因和来源 Session；边界截断不会产生虚假变化事件。

## 长期事件与重放

事件流由以下事件组成：

- `ApprenticeshipInitialized`；
- `AbilityEvidenceRecorded`；
- `AbilityProgressed`；
- `RelationshipChanged`；
- `EpisodeGrowthApplied`。

事件序号从 1 连续递增，`revision` 始终等于事件数。能力证据历史由证据事件推导，`completed_source_sessions` 由 `EpisodeGrowthApplied` 推导。存储读取和写入都会完整重放事件并比较快照；字段被独立修改或事件不一致时，存档被视为损坏而拒绝使用。

每个已应用 Session 保存基于公开、必要来源收据计算的稳定指纹。后续完成或协调会重新读取 Session 并验证玩家、病例、最终修订和公开内容；缺失、损坏或篡改会在写入前拒绝。内部指纹不进入公开视图。

## 提交顺序与故障窗口

完成链固定为：

```text
病例 Session 原子保存为 completed
→ Campaign 投影
→ Apprenticeship 投影
→ 从已保存权威状态构建公开结果
```

- 病例保存失败：Campaign 和 Apprenticeship 均不写入，原成长文件逐字节不变。
- Campaign 失败：保留已提交病例，返回原有 `campaign_projection_pending`；成长投影不执行。
- Campaign 成功、成长保存失败：保留病例与 Campaign，返回 `apprenticeship_projection_pending`，明确病例已完成且成长待补齐。
- `reconcile_campaign`/`reconcile_apprenticeship` 按同一顺序显式补齐；重复协调不新增事件。
- 重复 `finish_episode` 不增加能力、关系或事件，也不重写成长文件。

协调只扫描调用者明确指定玩家的可信已完成 Session，不会自动扫描磁盘并静默回填全部玩家。已存在但没有 R1 状态的玩家可先初始化新 Schema，再通过显式协调投影其可信历史；这不是旧长期状态 Schema 迁移。

## 公开视图

`ApprenticeshipView` 只公开：教学阶段、六项能力名称/等级/熟练度/证据数量、三维关系当前值、最近一次公开成长原因、已应用 Episode 数量和当前修订。

完成结果额外公开本次能力变化、关系变化、长期视图、成长投影状态和本次长期事件序号。CLI 在病例完成后显示简洁的“本次成长”。视图不公开隐藏病例真相、评分门槛、未发现线索、关系门禁、未来传承条件、内部指纹或存储路径。

## 当前限制与 R2 接口

R1 完全离线且确定性，不包含 MentorProfile、MentorAgent、MentorAction、课程、提示、自然语言师评、考试、晋级、权限或传承，也不启用 BGE 或正式语义记忆。

R2 只能通过只读 `ApprenticeshipView` 和公开变化读取、解释 R1 状态。导师输出仍不能直接构造长期事件、修改能力或关系；任何后续教学评价要转化为成长事实，仍须经过新的确定性规则和已提交领域事件。
