# 《异闻行录》Agent Task Benchmark 0/3 Failure Root Cause Audit

## 1. Executive Conclusion

本审计只读取 `agent_task_benchmark_dry_run_v3` 的已保存 artifacts 与当前源码；没有删除、改写或重跑任何 episode，没有调用 DeepSeek，也没有修改 production 或 benchmark 行为。

结论是 **PARTIAL — SHARED ROOT + CASE-SPECIFIC ISSUES**。

- Gray Hearth 与 Lantern Alley 共享一个主模式：Runtime 已确定性进入 `FORM_DIAGNOSIS` Goal，公开 Observation 已证明 diagnosis-ready，玩家也明确请求形成诊断，但 LLM 连续选择 `RESPOND`，从未向 ActionContract/Authority 提交 `submit_diagnosis`。这是 **model decision quality failure**；不是 readiness、Authority 或 confirmation harness 阻断。
- Old Paper Umbrella 是另一条失败链：第 5 turn 创建了仍处调查阶段的新 Goal/Plan但只回应；从第 6 turn 起 LLM action 与 active PlanStep 不匹配。Runtime 在 ActionContract repair 和 PlanEvaluator 之前以 `action_outside_active_plan` 返回，且没有把该拒绝保存为下一轮 `last_environment_feedback`，于是同一 public state、同一 plan、同一玩家输入可连续重演 11 次。这是 **LLM alignment error 与 runtime recovery/state-machine gap 的组合**。
- 三案共同暴露的较高层弱点是：系统允许 `RESPOND` 永远合法，也没有 bounded no-progress recovery。Goal/Plan 能表达下一阶段，却不能保证产生推进该阶段的 action；连续无世界状态变化后也没有确定性升级或阻断机制。
- Benchmark script 没有引用 hidden truth，诊断请求与 approval 协议有效，16 turns 足以容纳每案的合法完成路径。机械重复相同输入会放大死循环，但不是首次分叉的原因。因此本轮认为 **benchmark harness valid = YES（带 no-progress 诊断能力不足这一限制）**，不是 PATH A。

## 2. Benchmark Integrity

有效输入固定为：

- artifact root：`evaluation_results/agent_task_benchmark_dry_run_v3/agent_task_benchmark_v1`
- 3 episodes，0 success，3 `max_turns_exceeded`
- 0 provider abort，0 infrastructure error，0 executed authority violation
- 399,040 input tokens，43,124 output tokens，合计 442,164
- aggregate 从三个 run artifacts 纯重算后与保存值完全相等

Run artifact SHA-256：

| Case | SHA-256 |
|---|---|
| `old_paper_umbrella` | `0d37dc5d02ffd73bb30210295fee39428303209bd6e51ee023bda2867e8dfbc0` |
| `gray_hearth_inn` | `94dd060ae2816a01bb1c1f4d44d6ca0e5f6009b6bc0b8290ef1706817fabb53a` |
| `lantern_alley_conflicting_testimony` | `88aefedfffa4ece4fa530fc64c69bbaf8a7b45ca82ce52d54b767991782e2038` |

本审计没有把安全拒绝重分类为成功，也没有根据结果改变 terminal rule。0/3 是保留的真实观测。

### 证据边界

脱敏 artifact 没有保留 raw prompt、raw response、完整 `PlayerContributionEvaluation.disposition`、PlanStep id/intent/target、Goal/Plan revision、每次 proposal 的 update kind、post-observation 全量内容或 Reflection trigger type。以下时间线只陈述已保存字段；源码能唯一推导的状态会标为“源码推导”，不能证明的内容标为“未保留”，不从最终结果倒推。

字段简写：`rev/clues` 为 turn 前公开 session revision/线索数；`P=n` 为公开 plan step 数；`M=c/s/a` 为 Memory candidate/selected/accepted；`Δworld` 为 CaseEngine event 数；`GΔ/PΔ` 为 artifact 的 goal/plan changed；`PE` 为 PlanEvaluator outcome。

## 3. Per-case Turn Timelines

### 3.1 Old Paper Umbrella

固定玩家贡献在 16 turns 均为公开调查建议：“依据当前公开证据继续当前计划中尚未完成、信息价值最高的一项调查；不要重复已完成调查。”ContributionType 均为 `suggestion`；没有 hidden target。

| T | pre rev/clues | Goal / status | Plan | M | LLM/action → validation/authority | Δworld / post | Reflection | final |
|---:|---|---|---|---|---|---|---|---|
| 1 | 0/0 | 收集证据 / active | P=3, PΔ | 0/0/0 | `question_patient`, aligned, autonomous | 1 → rev1 | no | executed; PE keep_plan |
| 2 | 1/1 | 收集证据 → completed | P=3, GΔ/PΔ | 0/0/0 | `inspect_object`, aligned, autonomous | 1 → rev2/clues3 | goal_completed | executed; PE complete_goal |
| 3 | 2/3 | 继续收集 → completed | P=2, GΔ/PΔ | 0/0/0 | `observe_qi`, aligned, autonomous | 1 → rev3/clues4 | goal_completed | executed; PE complete_goal |
| 4 | 3/4 | 继续收集 → completed | P=2, GΔ/PΔ | 0/0/0 | `observe_patient`, aligned, autonomous | 1 → rev4/clues6 | goal_completed | executed; PE complete_goal |
| 5 | 4/6 | 继续收集 / active | P=2, PΔ | 0/0/0 | `RESPOND`; disposition/update detail未保留 | 0 → unchanged | no | responded; no PE |
| 6 | 4/6 | 同上 / active | P=2 unchanged | 0/0/0 | 非 RESPOND proposal；具体 tool/target 未保留；active-plan mismatch；alignment 层直接 forbidden | 0 → unchanged | no | rejected: `action_outside_active_plan` |
| 7 | 4/6 | 同上 | 同一 P=2 | 0/0/0 | 同 T6 | 0 | no | same rejection |
| 8 | 4/6 | 同上 | 同一 P=2 | 0/0/0 | 同 T6 | 0 | no | same rejection |
| 9 | 4/6 | 同上 | 同一 P=2 | 0/0/0 | 同 T6 | 0 | no | same rejection |
| 10 | 4/6 | 同上 | 同一 P=2 | 0/0/0 | 同 T6 | 0 | no | same rejection |
| 11 | 4/6 | 同上 | 同一 P=2 | 0/0/0 | 同 T6 | 0 | no | same rejection |
| 12 | 4/6 | 同上 | 同一 P=2 | 0/0/0 | 同 T6 | 0 | no | same rejection |
| 13 | 4/6 | 同上 | 同一 P=2 | 0/0/0 | 同 T6 | 0 | no | same rejection |
| 14 | 4/6 | 同上 | 同一 P=2 | 0/0/0 | 同 T6 | 0 | no | same rejection |
| 15 | 4/6 | 同上 | 同一 P=2 | 0/0/0 | 同 T6 | 0 | no | same rejection |
| 16 | 4/6 | 同上 | 同一 P=2 | 0/0/0 | 同 T6 | 0 | no | same rejection; max turns |

Plan/action alignment 早于 `_resolve_contract`，因此 T6–T16 的 ActionContract 没有运行，action repair 没有运行，AuthorityPolicy 也没有收到可评估的合法 action。artifact 中的 `forbidden` 是 runtime alignment rejection，不是 diagnosis/treatment authority 决策。

### 3.2 Gray Hearth Inn

T1–T6 玩家贡献为公开调查建议；T7–T16 为：“请根据目前已公开证据形成并提出你认为最合理的诊断；若证据仍不足，请继续公开调查。”均为 `suggestion`。

| T | pre rev/clues / public stage | Goal / status | Plan | M | LLM/action → validation/authority | Δworld / post | Reflection | final |
|---:|---|---|---|---|---|---|---|---|
| 1 | 0/0, investigate | 收集证据 / active | P=3, PΔ | 0/0/0 | `inspect_object`, aligned + contract valid, autonomous | 1 → rev1 | no | executed; PE keep_plan |
| 2 | 1/1 | 收集证据 → completed | P=3, GΔ/PΔ | 0/0/0 | `observe_patient`, valid/autonomous | 1 → rev2/clues3 | goal_completed | executed; PE complete_goal |
| 3 | 2/3 | 继续收集 → completed | P=3, GΔ/PΔ | 0/0/0 | `inspect_object`, valid/autonomous | 1 → rev3/clues4 | goal_completed | executed; PE complete_goal |
| 4 | 3/4 | 继续收集 → completed | P=2, GΔ/PΔ | 0/0/0 | `observe_qi`, valid/autonomous | 1 → rev4/clues5 | goal_completed | executed; PE complete_goal |
| 5 | 4/5 | 继续收集 → completed | P=2, GΔ/PΔ | 0/0/0 | `investigate_location`, valid/autonomous | 1 → rev5/clues7 | goal_completed | executed; PE complete_goal |
| 6 | 5/7 | 继续收集 → completed | P=2, GΔ/PΔ | 0/0/0 | `question_patient`, valid/autonomous | 1 → rev6/clues8 | goal_completed | executed; PE complete_goal |
| 7 | 6/8, diagnosis-ready | 协商公开诊断 / active（源码确定性创建） | P=3, PΔ | 0/0/0 | `RESPOND`; no tool；具体 disposition 未保留 | 0 → unchanged | no | responded |
| 8 | 6/8, diagnosis-ready | 同上 | P=3 unchanged | 0/0/0 | `RESPOND` | 0 | no | responded |
| 9 | 同上 | 同上 | 同上 | 0/0/0 | `RESPOND` | 0 | no | responded |
| 10 | 同上 | 同上 | 同上 | 0/0/0 | `RESPOND` | 0 | no | responded |
| 11 | 同上 | 同上 | 同上 | 0/0/0 | `RESPOND` | 0 | no | responded |
| 12 | 同上 | 同上 | 同上 | 0/0/0 | `RESPOND` | 0 | no | responded |
| 13 | 同上 | 同上 | 同上 | 0/0/0 | `RESPOND` | 0 | no | responded |
| 14 | 同上 | 同上 | 同上 | 0/0/0 | `RESPOND` | 0 | no | responded |
| 15 | 同上 | 同上 | 同上 | 0/0/0 | `RESPOND` | 0 | no | responded |
| 16 | 同上 | 同上 | 同上 | 0/0/0 | `RESPOND` | 0 | no | responded; max turns |

### 3.3 Lantern Alley Conflicting Testimony

玩家贡献分支及文本与 Gray Hearth 相同，但调查顺序和 clue progression 独立。

| T | pre rev/clues / public stage | Goal / status | Plan | M | LLM/action → validation/authority | Δworld / post | Reflection | final |
|---:|---|---|---|---|---|---|---|---|
| 1 | 0/0, investigate | 收集证据 / active | P=3, PΔ | 0/0/0 | `inspect_object`, valid/autonomous | 1 → rev1/clues2 | no | executed; PE keep_plan |
| 2 | 1/2 | 收集证据 → completed | P=3, GΔ/PΔ | 0/0/0 | `question_patient`, valid/autonomous | 1 → rev2/clues3 | goal_completed | executed; PE complete_goal |
| 3 | 2/3 | 继续收集 → completed | P=3, GΔ/PΔ | 0/0/0 | `question_patient`, valid/autonomous | 1 → rev3/clues4 | goal_completed | executed; PE complete_goal |
| 4 | 3/4 | 继续收集 → completed | P=2, GΔ/PΔ | 0/0/0 | `investigate_location`, valid/autonomous | 1 → rev4/clues5 | goal_completed | executed; PE complete_goal |
| 5 | 4/5 | 继续收集 → completed | P=2, GΔ/PΔ | 0/0/0 | `observe_qi`, valid/autonomous | 1 → rev5/clues6 | goal_completed | executed; PE complete_goal |
| 6 | 5/6 | 继续收集 → completed | P=2, GΔ/PΔ | 0/0/0 | `observe_patient`, valid/autonomous | 1 → rev6/clues8 | goal_completed | executed; PE complete_goal |
| 7 | 6/8, diagnosis-ready | 协商公开诊断 / active（源码确定性创建） | P=3, PΔ | 0/0/0 | `RESPOND`; no tool | 0 → unchanged | no | responded |
| 8 | 6/8, diagnosis-ready | 同上 | P=3 unchanged | 0/0/0 | `RESPOND` | 0 | no | responded |
| 9 | 同上 | 同上 | 同上 | 0/0/0 | `RESPOND` | 0 | no | responded |
| 10 | 同上 | 同上 | 同上 | 0/0/0 | `RESPOND` | 0 | no | responded |
| 11 | 同上 | 同上 | 同上 | 0/0/0 | `RESPOND` | 0 | no | responded |
| 12 | 同上 | 同上 | 同上 | 0/0/0 | `RESPOND` | 0 | no | responded |
| 13 | 同上 | 同上 | 同上 | 0/0/0 | `RESPOND` | 0 | no | responded |
| 14 | 同上 | 同上 | 同上 | 0/0/0 | `RESPOND` | 0 | no | responded |
| 15 | 同上 | 同上 | 同上 | 0/0/0 | `RESPOND` | 0 | no | responded |
| 16 | 同上 | 同上 | 同上 | 0/0/0 | `RESPOND` | 0 | no | responded; max turns |

## 4. Last Productive Turn

| Case | Last productive turn | First divergence | Explanation |
|---|---:|---:|---|
| Old Paper Umbrella | T4 | T5 | T4 最后一次改变 world state并完成 Goal。T5 在仍有公开调查时只回应，创建的 P=2 plan 未执行；T6 首次 plan/action mismatch，此后无恢复。 |
| Gray Hearth Inn | T6 | T7 | T6 完成最后一项公开调查，rev6/clues8；T7 已进入 diagnosis-ready/FORM_DIAGNOSIS，却只回应。 |
| Lantern Alley | T6 | T7 | T6 完成最后一项公开调查，rev6/clues8；T7 已进入 diagnosis-ready/FORM_DIAGNOSIS，却只回应。 |

“productive”按 world state 或 Goal/Plan 实际阶段推进定义。Gray/Lantern T7 虽创建 diagnosis plan，但没有推进 diagnosis condition；它是正确阶段转换后的首次 action divergence。

## 5. Gray Hearth Diagnosis Stall

1. **CaseEngine/runtime diagnosis-ready：PROVEN YES。** T7 script 只有在 `observation.can_submit_diagnosis` 为 true 时才走 `request_public_diagnosis`；此前六个 investigation 均已执行。生产 `FixedDiagnosisReadinessPolicy` 要求当前可用调查为空。
2. **公开信息足够识别阶段：YES。** Observation 公开 `can_submit_diagnosis=true`、三项 diagnosis candidates、8 条已发现线索，且没有剩余可用调查。
3. **Goal：**“与玩家形成并协商公开诊断”，active。
4. **Plan：**T7 新建、3 steps；完整 step 内容未保存在 artifact。
5. **active step：**具体 intent/tool/target 未保留，不能猜。
6. **是否明确要求 submit：**无法从 artifact 证明 PlanStep；但 Goal 明确要求 `DIAGNOSIS_SUBMITTED` 才完成。
7. **LLM intention：**可证明 decision action 是 `RESPOND`；不能从脱敏 artifact 证明它在私有文本中是否“想过诊断”。行为层没有 diagnosis intention 落成 tool action。
8. **GoalPlanPolicy 阻止：NO EVIDENCE。** T7 proposal 成功通过并产生 P=3 plan；若 policy 抛错且 repair/fallback，artifact 会出现 repair/fallback。T7 两者均为 false。
9. **ActionContract 拒绝 diagnosis：NO。** 十轮均是合法 `RESPOND`，没有 `submit_diagnosis` 被拒记录。
10. **Authority：未收到 diagnosis action。** 因此没有 pending/proposal-only。
11. **玩家文本符合契约：YES。** 自然语言 contribution 是 production cooperative endpoint 的正常输入；它被定义为不可信建议而不是命令。
12. **是否需要特定 ContributionType：NO。** Runtime 对 suggestion/hypothesis 不设 diagnosis gate；只有 pending approval 要求 `APPROVAL` 和匹配 identity。
13. **真实产品玩家是否可这样推动：YES。** tests 的自然语言协作路径同样允许玩家表达“可以形成辨证”；决定仍由 Agent 独立形成。

分类：**AGENT DECISION ISSUE（direct）+ no-progress recovery gap（upstream systemic weakness）**。

## 6. Lantern Alley Diagnosis Stall

Lantern 的结论不是从 Gray 复制，而由其独立 trajectory 支持：调查顺序为 object → 两次 witness questioning → location → qi → patient，最终同样得到 rev6/clues8。

- diagnosis readiness：**PROVEN YES**，原因同样是 T7 public branch 和无剩余 investigation。
- Goal：active `FORM_DIAGNOSIS`，描述“与玩家形成并协商公开诊断”。
- Plan：T7 创建 P=3，后续未变；active step 内容未保留。
- LLM：T7–T16 独立的十次真实请求全部产生 `RESPOND`，没有 tool、event、error 或 repair。
- GoalPlanPolicy：没有拒绝证据；T7 plan creation 被接受。
- ActionContract/Authority：均未收到 `submit_diagnosis`，不能归因于 validator 或 confirmation。
- 玩家贡献：只引用“目前已公开证据”，没有指定 hidden diagnosis；在公开状态下合理，且不同调查顺序后仍成立。

两个 case 的最小共同机制是：`FORM_DIAGNOSIS` Goal + diagnosis-ready Observation + diagnosis-request contribution 并不足以使 LLM 选择 `submit_diagnosis`；`RESPOND` 又被所有 deterministic layers 无条件视为合法，且没有 no-progress transition。跨 case 重复使该 pattern **HIGHLY SUPPORTED 为系统性 model/action-selection weakness**，不是 case-specific readiness bug。

## 7. Old Paper Umbrella Plan/Action Loop

第一个 `action_outside_active_plan` 是 T6：

- Goal：active “继续收集足以推进病例判断的公开证据”。
- Plan：T5 创建/修订后的 active P=2 plan；T6 未更新。
- active step：完整 intent/tool/target 未保存。
- LLM action：确定为非-RESPOND，否则 `_action_matches_plan` 会直接返回 true；具体 tool/target 没有写入 rejection artifact，不能猜。
- mismatch 原因：源码仅有三种可能——无 active plan、tool 不同、首个 argument value 与 step target 不同。这里 artifact 显示 active P=2，因此是 tool 或 target mismatch；二者无法再区分。

问题回答：

1. **LLM 忽略 plan？HIGHLY SUPPORTED。** 相同 active plan 下连续给出不匹配 action；但缺少 proposal tool/step target，不能把具体 mismatch 标为 PROVEN。
2. **Plan stale？NOT SUPPORTED。** pre observation 从 T5 到 T16 不变，`_mark_invalid_plan` 没将其标为 needs-revision，且 P=2 保持 active。
3. **PlanEvaluator：**T1 keep_plan，T2–T4 complete_goal；T5–T16 无 evaluation。没有 revise/blocked/abandon 证据。
4. **LLM PlanUpdate：**T6–T16 `plan_changed=false`，所以没有 revise；是否显式 KEEP 可由实现推导为 yes。
5. **GoalPlanPolicy 拒绝 PlanUpdate：NO。** 被拒的是 apply proposal 后的 action/active-step alignment；policy 已先通过。
6. **应用顺序：PROVEN。** Runtime 先 validate proposal，再 `_apply_proposal`，再按应用后的 plan 校验 action。因此不是“new action 按 old step 校验”；问题是 action 不匹配当轮被保留/应用后的 active step。
7. **action repair：NO。** alignment check 在 `_resolve_contract` 前直接返回。artifact 的 T5 repair 属于 planning structured-output repair；T6–T16 均 `repair_used=false`。
8. **是否重复：YES，11 次。** 每次都无 world event、无 Goal/Plan change、无 PlanEvaluator。
9. **为何可连续：PROVEN runtime gap + repeated policy。** alignment rejection 只保存 state revision，不写 `last_plan_evaluation`；下一轮的 `last_environment_feedback` 只读取 last evaluation，故此次拒绝反馈不会进入下一轮 Agent input。Harness 看到 public state 未变又发送同一句调查建议。没有 retry counter/no-progress branch/plan invalidation，于是相同条件可无限重复至 max turns。

## 8. Investigation → Diagnosis Transition

真实链路是：

```text
CaseEngine 执行调查并提交 world state
  ↓
CaseObservation 投影公开 clues / investigations / diagnosis candidates
  ↓
FixedDiagnosisReadinessPolicy 在无可用调查时公开 can_submit_diagnosis=true
  ↓
PlanEvaluator 完成当前 gather-evidence Goal
  ↓（下一 cooperative turn）
Runtime._prepare_next_goal 确定性创建 FORM_DIAGNOSIS Goal，并清空旧 Plan
  ↓
GameNPCAgent 负责创建 diagnosis Plan 并选择 submit_diagnosis action
  ↓
GoalPlanPolicy + PublicActionContract 校验公开 diagnosis id/evidence
  ↓
AuthorityPolicy 返回 PROPOSAL_ONLY，生成 revision-bound pending action
  ↓
玩家以匹配 decision/confirmation id 的 APPROVAL 回应
  ↓
Agent 必须再次提出同一 tool call；Authority 转 autonomous
  ↓
CaseEngine 记录 diagnosis
```

职责不是唯一单点：CaseEngine 管 authoritative mutations；readiness policy 暴露阶段；PlanEvaluator/Runtime 管 Goal phase；GameNPCAgent 独占 action selection；Authority/玩家共同提交不可由 NPC 单方面决定的诊断。

因此不存在“完全没人创建 diagnosis Goal”的责任真空：Gray/Lantern 的 Goal 已正确创建。存在的是更窄且已证明的 **progress-enforcement gap**：GameNPCAgent 可以在 diagnosis Goal 下无限 RESPOND，Runtime 不将多次无进展视为 blocked/revise/recovery。标记为 **PROVEN DESIGN GAP**，但 direct trigger 仍是模型选择 RESPOND。

## 9. Goal Lifecycle

| Case | current Goal creations（源码+turn transition可证） | completions | replacements by LLM | abandon | blocked |
|---|---:|---:|---|---:|---:|
| Umbrella | 4 | 3 | 0 可见证据 | 0 | 0 |
| Gray | 6 | 5 | 0 可见证据 | 0 | 0 |
| Lantern | 6 | 5 | 0 可见证据 | 0 | 0 |
| Total | 16 | 13 | 0 可见证据 | 0 | 0 |

计数不含每案固定的 episode-level `RESOLVE_CASE` Goal。Artifacts 的 13 个 `complete_goal` 与 13 次 Reflection 一一对应。没有 Goal 长期停留在已完成状态：Runtime 在下一 turn 创建下一 Goal。Gray/Lantern 的最终 Goal 是正确但长期未满足的 diagnosis Goal；Umbrella 的最终 Goal 是仍可执行但 action 与 Plan 不对齐的 gather Goal。

大量 Goal completion 的原因是 gather completion condition 使用小的 clue-count 阈值，随后 `_prepare_next_goal` 在尚未 diagnosis-ready 时再创建更高阈值 gather Goal。这是 churn 信号，但前六回合仍持续推进 world state，不能单独认定为失败根因。

## 10. Plan Lifecycle

现有 telemetry 不能精确区分每次 proposal 的 CREATE/REVISE 与 post-environment evaluator revision，以下只报可证明 transitions：

| Case | 首次 Plan 创建 | PΔ turns | PE complete | PE keep | PE revise/abandon | outside-plan |
|---|---:|---|---:|---:|---:|---:|
| Umbrella | T1 | T1–T5 | 3 | 1 | 0 | 11 |
| Gray | T1 | T1–T7 | 5 | 1 | 0 | 0 |
| Lantern | T1 | T1–T7 | 5 | 1 | 0 | 0 |

Gray/Lantern 的 diagnosis P=3 plan 没有成为“合法新 action 的锁”，因为 Agent 根本未提出 tool action。Umbrella 的 P=2 plan 确实成为执行门；但 gate 本身正确阻止了未对齐 action，问题在于没有 recovery transition 和反馈持久化。不能为了提高完成率绕过该锁。

## 11. Player Script Validity

逐案审计结果：

- 合理性：调查阶段建议选择当前计划中信息价值最高的未完成调查；diagnosis-ready 后请求基于公开证据提出诊断。均与 public state 一致。
- hidden truth：无一句引用 root cause、valid diagnosis id、resolved treatment id 或未公开 target。
- 顺序鲁棒性：脚本只查看当轮 available investigations/can-submit/pending，不假定固定调查顺序；三个实际顺序不同仍能工作。
- 产品一致性：`ClinicService.submit_player_contribution` 就是自然语言协作入口；suggestion 不应被当作命令，但应被 Agent 评价。
- diagnosis 必需输入：没有要求特定 `HYPOTHESIS` 类型；tests 用 hypothesis 证明一条路径，但 runtime/policy 并不把 suggestion 禁止为 diagnosis stimulus。
- 重复：是。public state 无变化且无 pending 时，脚本会机械发送同一句。Gray/Lantern 重复 diagnosis request 10 次；Umbrella 调查建议共 16 次。
- 不可推动状态：脚本没有“连续 RESPOND/REJECT 后改写建议或退出”的 branch。它是合理的固定压力测试，但不是拟人化的自适应玩家。

判断：重复输入放大并稳定复现产品 no-progress 行为，却没有造成第一次错误：Gray/Lantern T7 第一次明确请求就被 RESPOND；Umbrella T5 第一次新 Goal 输入就未执行、T6 首次 mismatch。故 **HARNESS ISSUE 不是 direct cause**。未来可新增独立的 robustness script，但不能用它替换本次 fixture 或重分类 0/3。

## 12. Authority / Confirmation

### Diagnosis

`submit_diagnosis` action → GoalPlan/ActionContract 校验 → `PROPOSAL_ONLY` pending → 玩家 `APPROVAL` 必须匹配 player/case/session、decision id、confirmation id 和 case revision → 下一次 Agent 重现完全相同 tool call → autonomous execution → CaseEngine。

### Treatment

`execute_treatment` action → contract 校验公开 treatment → `CONFIRMATION_REQUIRED` pending → 同样的 owner/id/revision approval → Agent 重现相同 tool call → autonomous execution → CaseEngine 完成 session。

Harness 在 `pending` 存在时会按 authority mode 使用当前 pending 的两个 identity，并发送 `APPROVAL`。测试已覆盖该绑定。三个真实 run 的 confirmation count 都是 0，因为 Agent 从未产生 diagnosis pending。故 **Authority/confirmation 不是 0/3 原因**；也没有证据说明 harness 无法完成一个真正出现的 pending。

## 13. Memory

三个 episode 的每个 turn 都是 candidate=0、selected=0、declared=0、accepted=0。每 repeat 使用独立 repository/player/session；没有 prior-session Memory。Projection 和 retriever 还显式排除 `source_session_id == current_session_id`。

结论：**Memory 不是 direct root cause，也没有进入这 48 次 GameNPCAgent decision。**

## 14. Reflection

| Case | triggers | writes | 可证明 trigger type |
|---|---:|---:|---|
| Umbrella | 3 | 3 | 3 × `goal_completed` |
| Gray | 5 | 5 | 5 × `goal_completed` |
| Lantern | 5 | 5 | 5 × `goal_completed` |
| Total | 13 | 13 | 13 × `goal_completed` |

类型可由同 turn 的 `PE=complete_goal`、`goal_changed=true` 及 `_attach_reflection` 唯一分支证明；无 episode completed、plan abandoned 或 repeatedly revised。

这些 writes 因 current-session exclusion 没有在同 episode 被检索，且实际 candidate count 始终为 0。因此 **Reflection 不是 decision contamination 或 direct cause**。频率反映 gather Goal 多次完成/重建，是 lifecycle churn 的诊断信号；它增加成本，但没有改变 action。

## 15. Token Analysis

| Case | Game requests | Game in/out | Reflection requests | Reflection in/out | repair turns | total | per-turn mean / median |
|---|---:|---:|---:|---:|---:|---:|---:|
| Umbrella | 17 | 113,823 / 7,144 | 3 | 13,635 / 4,101 | 1 | 138,703 | 7,560 / 7,113 |
| Gray | 17 | 117,288 / 9,217 | 5 | 22,903 / 6,978 | 1 | 156,386 | 7,907 / 7,538 |
| Lantern | 16 | 108,501 / 8,224 | 5 | 22,890 / 7,460 | 0 | 147,075 | 7,295 / 7,402 |

Game request count含 planning structured-output repair；artifact 只保存每 turn 合并 usage，不能把 repair 的第二请求 tokens 从首请求精确拆开。两个 repair turns 的合并 token 分别为 Umbrella 14,492、Gray 14,763。Reflection 共占 36,528 input + 18,539 output = 55,067 tokens（12.45%）。

主要增长来自每 turn 重发完整 Observation、Goal、Plan、authority/public action space 与其他结构化上下文；Memory context 为零，benchmark telemetry 不进入模型请求。T7 后 public state 不变但每次仍约 7k input，说明重复完整上下文是高总量的直接来源。没有保存逐字段 token attribution，不能证明 Observation、Plan 或 history 谁占最大份额。

Context overload 对 decision quality 的影响：**POSSIBLE，NOT PROVEN**。输入量大且 diagnosis stall 与重复上下文同时发生，但各 turn 大致稳定、未见 truncation/provider error，Lantern 无 repair仍失败，无法从 artifacts 建立因果。

## 16. Legal Success Path Comparison

生产 readiness policy 要求消耗所有当前可用调查。三个 case 各有 6 个 investigation；其依赖按公开 clue 解锁。完成后合法路径是 diagnosis proposal + approval/execution，再 treatment proposal + approval/execution，典型最多约 10 cooperative turns，低于 16。

| Case | 调查前置链（合法示例） | 正确 diagnosis | resolved treatment |
|---|---|---|---|
| Umbrella | 基础观察/询问/验伞 → 水迹 → 契痕 → 木牌 → 失约（共6调查） | `rain_vow_breach` | `return_token_and_fulfill_vow`，需契痕/木牌/失约 |
| Gray | 基础三调查 → 灶契刮痕与烟流 → 烟道调查（共6） | `displaced_hearth_contract` | `restore_token_and_clear_flue`，需4项公开关键线索 |
| Lantern | 人、两证人、双灯、巷迹、时间线（共6） | `angled_witness_memory_and_moved_token` | `reconstruct_timeline_and_return_token`，需6项公开关键线索 |

CaseEngine 本身只要求 diagnosis id 是公开 candidate、证据引用已发现；treatment 要求 diagnosis 已提交且其 required clues 已发现。现有 manual/reference tests 证明 authoritative diagnosis/treatment path 能完成，且 Umbrella reference episode以 8 world actions得到 resolved/100。Gray/Lantern artifacts 已在 T6 消耗六次 world investigation；它们仍有十个 benchmark turns，机会明显足够。

### Offline NPC 对照

当前 `DeterministicCooperativeNPC` 只有明确的“若有 investigation 选第一项，否则 RESPOND”逻辑；它没有 diagnosis 或 treatment transition，也不实现 `propose_turn`。因此不能声称 offline NPC 在相同状态能自动完成。合法完成证据来自 CaseEngine/manual paths和 cooperative test doubles，而不是 offline NPC。LLM path 的关键差别是它拥有 Goal/Plan proposal 能力及完整 action surface，却仍未选择 diagnosis。

## 17. Root Cause Matrix

| Failure | Direct Cause | Upstream Cause | Layer | Confidence | Evidence |
|---|---|---|---|---|---|
| Gray diagnosis stall | diagnosis-ready + FORM_DIAGNOSIS 下连续 `RESPOND`，无 `submit_diagnosis` | RESPOND 永远合法且无 no-progress recovery | B + D | PROVEN | T7–T16 state不变、10 responded；源码 transition/policy |
| Lantern diagnosis stall | 独立 run 中同样连续 `RESPOND` | 同一 action-selection/progress-enforcement机制 | B + D | PROVEN | 独立调查顺序后 T7–T16 同样表现 |
| Umbrella first stall | 新 gather Goal/Plan 的首轮只回应 | model未执行 active step | B | HIGHLY SUPPORTED | T5 PΔ、0 event、responded；step内容未保留 |
| Umbrella 11-turn loop | action 与 active PlanStep tool/target不一致 | alignment早退，不做repair/PlanEvaluator，不持久化反馈；script在无状态变化时重复 | B + D + A(放大) | PROVEN（机制）/ HIGHLY SUPPORTED（模型忽略step） | T6–T16 identical rejection；源码调用顺序 |
| Diagnosis readiness bug | — | — | F | NOT SUPPORTED | Gray/Lantern明确 can-submit；CaseEngine路径可完成 |
| Authority/confirmation failure | — | — | E | NOT SUPPORTED | 从未生成 pending；harness identity协议正确 |
| Memory contamination | — | — | G | NOT SUPPORTED | 所有 c/s/a=0，current-session excluded |
| Reflection contamination | — | — | G | NOT SUPPORTED | 13 writes均未被同session检索 |
| Context overload | 可能降低action质量 | 大型重复结构化输入 | B/other | POSSIBLE | ~7–8k tokens/turn，但无直接因果证据 |

共同根因判断：**PARTIAL — SHARED ROOT + CASE-SPECIFIC ISSUES**。三案共享“没有 deterministic no-progress recovery”的系统弱点；Gray/Lantern 的直接原因是 diagnosis action-selection，Umbrella 另有 plan/action recovery gap，不能用单一根因完全解释。

## 18. Proposed Fix Categories

本节只建议，不实施。

| 类别 | 建议 | 改变生产行为 | 重跑3×1 | benchmark version |
|---|---|---:|---:|---|
| D. Runtime state-machine design | 为连续 RESPOND/no-world-progress 建立显式计数和 deterministic blocked/revise/recovery transition；不能自动替 Agent选正确 diagnosis | 是 | 必须 | runtime hashes变更；冻结新的 resolved manifest，fixture/success rule不必变 |
| D/B. Product correctness | plan/action alignment rejection应形成下一轮可见的安全 feedback，并触发 bounded replan/repair，而非静默保持同一 plan | 是 | 必须 | 同上 |
| B. Product correctness | 为 alignment mismatch 增加专门的 plan-aware repair，或使 mismatch 后 plan needs-revision；保持安全 gate | 是 | 必须 | 同上 |
| C. Model/prompt quality | 在确认 runtime observability完整后，单独版本化 diagnosis-stage action-selection实验；不得仅为 benchmark硬编码“调查完一定诊断” | 是 | 必须 | 必须版本化 prompt/model config与hash |
| A. Evaluation harness | 可新增第二个独立 adaptive-player robustness benchmark，在重复 RESPOND 后改写建议或退出；不得替换当前 frozen script或改写0/3 | 否（只评估） | 对新fixture必须 | 新 benchmark/script version |
| E. Evidence | 增强未来 run telemetry：proposal disposition、goal/plan update kind、active step tool/target、alignment mismatch两端、reflection type、repair usage拆分 | 否（只观测，需确保不改变prompt） | 若只增加旁路 telemetry，旧结果仍有效；新证据需新跑 | 建议升级 artifact schema，不必改 success rule |

修复优先级：先修 Umbrella 的拒绝反馈/recovery 可观察闭环，再设计通用 no-progress state；之后才做 model/prompt iteration。一次只改变一个 exact cause，避免把 runtime correctness 和 model quality 混成一次提分。

## 19. Resume / Evaluation Impact

1. 0/3 是否推翻“这是一个 Agent”：**NO。** 系统确有真实模型决策、Goal/Plan、tool、authority、Memory/Reflection loop。
2. 是否推翻“Agent production loop真实运行”：**NO。** 真实 DeepSeek、production composition、48 turns和 world events均有 artifact 证据。
3. 是否推翻“当前 Agent 具备可靠任务完成能力”：**YES。** 当前唯一 production-equivalent task sample为0/3，不能作可靠完成声明。
4. 当前是否可在简历写任务成功率：**NO**，不能写成正向能力指标；可以诚实写“建立 production-equivalent benchmark，发现3/3 bounded failures并完成根因审计”。
5. 项目仍能否作为 Agent 应用项目投递：**WITH QUALIFIER。** 可展示安全架构、真实运行链、评估严谨性和负结果诊断；必须明确 task completion 尚未通过 gate。

## 20. Recommended Next Gate

选择 **PATH D: MULTIPLE ISSUES**。

建议门禁顺序：

1. 只处理 Umbrella 已证明的 alignment rejection feedback/recovery 缺口；补 deterministic regression，不改 benchmark。
2. 冻结 runtime hashes，重跑 3×1，确认 outside-plan loop 是否消失；不要同时改 prompt。
3. 若 Gray/Lantern 仍在正确 diagnosis Goal 下 RESPOND，单独进入 model/prompt-quality iteration，明确版本化。
4. 每次 production behavior 改变后都重新跑3×1；只有 3×1 通过既定 success gate 才允许3×3。

最终判定：

```text
DOMINANT ROOT CAUSE:
LLM action selection cannot reliably convert an active, public diagnosis Goal into
submit_diagnosis; separately, plan/action mismatch lacks a recoverable feedback transition.

BENCHMARK HARNESS VALID: YES
PRODUCT CORRECTNESS ISSUE: PARTIAL
MODEL QUALITY ISSUE: YES
RUNTIME STATE MACHINE ISSUE: YES
MEMORY DIRECT CAUSE: NO
REFLECTION DIRECT CAUSE: NO
NEXT PATH: D
```
