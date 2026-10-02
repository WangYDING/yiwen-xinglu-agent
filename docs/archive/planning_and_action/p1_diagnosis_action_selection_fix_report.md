# P1 Diagnosis Action Selection Fix Report

## Implementation

P1 只修改了两个既有职责点：

- `src/xuanyi_npc/application/action_contract.py`
  - 新增 validator-derived `PublicDiagnosisAction`。
  - 仅在 public `can_submit_diagnosis=true` 时，为每个公开 diagnosis candidate投影一个 `submit_diagnosis` call。
  - arguments 使用现有 validator接受的 `diagnosis_id` 与已发现 `evidence_clue_ids`。
  - 所有候选被同等投影，不读取 `valid_diagnosis_ids`、root cause或隐藏 truth。
- `src/xuanyi_npc/agents/game_npc.py`
  - 将 diagnosis calls 与既有 investigation calls 放入同一 model-visible public action space。
  - 增加 diagnosis action-selection contract：当 active diagnosis step要求该tool时，应选择公开call推进，或合法 revise/block；普通解释/交流步骤仍允许 `RESPOND`。

没有修改 Runtime自动决策、Authority、proposal-only、confirmation、ActionContract validator、CaseEngine、case、benchmark、Memory、Reflection、turn limit或模型。

## Test result

- Targeted regression：28 passed
- Full `python -m pytest -q`：100% passed

新增/验证的约束：

- `submit_diagnosis` 出现在model-visible action surface；
- 每个投影call可被原 PublicActionContractValidator直接接受；
- 未ready时不投影 diagnosis action；
- `FORM_DIAGNOSIS` request包含明确phase/action contract；
- 所有公开候选等价呈现，不包含正确答案标签或hidden root cause；
- 普通 `RESPOND` 仍合法；
- 原 diagnosis proposal → proposal-only → approval → CaseEngine测试继续通过。

## Frozen post-P1 benchmark

- Output：`evaluation_results/agent_task_benchmark_post_p1/agent_task_benchmark_v1`
- 配置：原 frozen 3 cases × 1 repeat，max turns 16，fixed script，原success rule
- DeepSeek + semantic Memory + Reflection
- Budget cap：¥1.00
- Result：0/3 success，3 `max_turns_exceeded`
- Provider abort：0
- Executed authority violation：0
- Total tokens：472,993
- Estimated cost：¥0.21215392
- Stored aggregate 与纯重算完全一致
- Manifest hash：`e39176d72ec151ebf371a8f34fc931ee37e2bbddf255a4ba7161814ffb359f22`
- Configuration hash：`319453f6e0ea9d44b4d6cb4caa17033ea104605a22d2df7c6299074fd233eba6`

Pre-P1/post-P0 artifacts 未覆盖：`evaluation_results/agent_task_benchmark_post_p0/agent_task_benchmark_v1`。

## Gray pre/post

| Metric | Pre-P1 | Post-P1 |
|---|---:|---:|
| FORM_DIAGNOSIS entry | T7 | T7 |
| diagnosis-request turns | 10 | 10 |
| RESPOND | 10 | 9 |
| non-RESPOND rejected by plan alignment | 0 | 1（T8） |
| legal `submit_diagnosis` observed | 0 | 0 |
| proposal pending / approval | 0 | 0 |
| diagnosis executed | no | no |
| treatment stage | no | no |
| terminal success | no | no |

Post-P1 T7仍为 `RESPOND`；T8产生非-RESPOND proposal，但被 `action_outside_active_plan` 拒绝；T9–T16回到 `RESPOND`。被拒proposal的具体tool/target未保存在artifact：`NOT PROVEN BY CURRENT ARTIFACTS`。因此不能把T8计为恢复的 diagnosis action。

## Lantern pre/post

| Metric | Pre-P1 | Post-P1 |
|---|---:|---:|
| FORM_DIAGNOSIS entry | T7 | T7 |
| diagnosis-request turns | 10 | 10 |
| RESPOND | 10 | 0 |
| non-RESPOND rejected by plan alignment | 0 | 10（T7–T16） |
| legal `submit_diagnosis` observed | 0 | 0 |
| proposal pending / approval | 0 | 0 |
| diagnosis executed | no | no |
| treatment stage | no | no |
| terminal success | no | no |

Lantern 的原 `RESPOND ×10` pattern确实消失，但被 `action_outside_active_plan ×10` 取代。具体proposal tool未保存：`NOT PROVEN BY CURRENT ARTIFACTS`。没有任何 action到达 ActionContract/Authority，因此不满足“至少实际产生合法 `submit_diagnosis`”的P1成功判据。

## Old Paper observation only

Old Paper仍为16 turns、active、0 success、10次 `action_outside_active_plan`。本轮未针对它实施或建议额外修复。

## Diagnosis action surface verdict

静态和测试层面，surface修复有效：模型现在能看到与原validator一致的每候选 exact diagnosis call，且没有泄露正确性信息或绕过authority。

真实行为层面，surface明显改变了 action selection，尤其Lantern从十次RESPOND变为十次非-RESPOND proposal；但这些proposal没有与 active PlanStep对齐。由于当前benchmark rejection telemetry不保存proposed tool/target，不能证明模型选择的是 diagnosis，也不能证明具体 mismatch端。

因此必须区分：

- `DIAGNOSIS ACTION SURFACE FIX: PASS`
- legal diagnosis action recovery：FAIL
- overall P1 success：FAIL

## Safety

- plan/action alignment没有放宽；所有不匹配action继续拒绝。
- 无world event由被拒action产生。
- 无proposal绕过proposal-only/confirmation。
- executed authority violations为0。
- 原后置pipeline测试继续通过。

`SAFETY REGRESSION: NO`。

## New blocker

新的exact blocker是：

> 在model-visible diagnosis calls存在、玩家请求诊断、Goal为FORM_DIAGNOSIS时，模型开始产生非-RESPOND action；但action与其active PlanStep不一致，因而在进入ActionContract和Authority之前被安全拒绝。

Gray只出现一次后退回RESPOND；Lantern连续出现十次。现有artifact不能证明被拒action名称，也不能证明active PlanStep内容。继续修复需要进入下一阶段的 Plan/Decision co-generation alignment 或先增强旁路telemetry；这超出本轮边界。

没有进入treatment阶段，因此 `NEXT GATE` 不是P2。也不能继续顺手调整prompt或Runtime。

```text
P1 IMPLEMENTATION: FAIL
P1 TEST: PASS
DIAGNOSIS ACTION SURFACE FIX: PASS
GRAY DIAGNOSIS STALL RESOLVED: NO
LANTERN DIAGNOSIS STALL RESOLVED: NO
SAFETY REGRESSION: NO
POST-P1 TASK SUCCESS: 0/3
NEXT GATE: STOP
```
