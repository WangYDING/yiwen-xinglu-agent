# P2a — Plan/Action Alignment Telemetry Instrumentation Report

## Implementation verdict

P2a 已完成行为中立的旁路 telemetry instrumentation。

本轮只扩展 turn result、benchmark sanitized turn schema、artifact serialization，
并新增直接相关的 targeted tests。

没有修改 `_action_matches_plan`、Plan/Decision、prompt、GoalPlanPolicy、
ActionContract、Authority、CaseEngine、Memory、Reflection、benchmark fixture 或 success rule。

## Modified files

- `src/xuanyi_npc/domain/cooperation.py`
  - 在 `CooperativeTurnResult` 增加最小 alignment telemetry 字段。
- `src/xuanyi_npc/application/cooperative_runtime.py`
  - 在 alignment check 前旁路构造只读 telemetry。
  - rejection 与通过 alignment 的 turn 都携带 telemetry。
  - `_action_matches_plan` 保持原实现和原调用顺序。
- `src/xuanyi_npc/evaluation/agent_task_benchmark.py`
  - `SanitizedTurnSummary` 序列化新增字段。
- `tests/test_p2a_alignment_telemetry.py`
  - 增加 7 个 telemetry/behavior-neutral targeted cases。
- `docs/p2a_alignment_telemetry_report.md`
  - 本报告。

## Telemetry schema

每次 production Plan/Action alignment check 可记录：

- `proposed_action_type`
- `proposed_tool`
- `proposed_public_target_id`
- `proposed_argument_keys`
- `active_plan_step_id`
- `active_plan_step_intent`
- `active_plan_step_tool`
- `active_plan_step_public_target_id`
- `alignment_reason_code`

`alignment_reason_code` 支持：

- `missing_active_plan`
- `missing_active_step`
- `tool_mismatch`
- `target_mismatch`
- `match`
- `not_applicable`

## Target extraction and privacy

Telemetry 使用独立的 tool-aware 只读映射：

- investigation tools → `investigation_id`
- `submit_diagnosis` → `diagnosis_id`
- `execute_treatment` → `treatment_id`

只有 target 存在于当前 public observation action surface 时才写入 ID；
否则写 `null`，不猜测。

Artifact 不保存 raw prompt、raw LLM response、hidden truth、正确答案标签、
private reasoning、secret 或 API key。

Telemetry 没有加入 `GameNPCAgentInput`，不会进入下一轮 LLM input。

## Behavior neutrality

Instrumentation 在旧 matcher 调用前只读取 Decision、PlanStep 和 public observation。

Runtime 仍由原 `_action_matches_plan` 唯一决定 alignment outcome。

Diagnosis 参数测试明确证明：

- `diagnosis_id` 在前：telemetry target 正确，旧 matcher 返回 `true`。
- `evidence_clue_ids` 在前：telemetry target 仍正确，旧 matcher 返回 `false`。

因此 telemetry 没有修复或绕过已知 argument-order matcher defect。

Integration test 还验证 mismatch 后：

- CaseEngine session/world revision 不变；
- Goal 不变；
- Plan 不变；
- Authority 结果仍为 `forbidden`；
- 原 `action_outside_active_plan` 不变；
- telemetry 字段不存在于下一轮 Agent input。

## Tests

Targeted telemetry tests：

```text
python -m pytest -q tests/test_p2a_alignment_telemetry.py
7 passed
```

Targeted runtime + benchmark regression：

```text
python -m pytest -q tests/test_p2a_alignment_telemetry.py \
  tests/test_m2_cooperative_runtime_planning.py \
  tests/test_agent_task_benchmark.py
31 passed
```

Full suite：

```text
python -m pytest -q
498 passed
```

## Frozen post-P2a benchmark

- Output：`evaluation_results/agent_task_benchmark_post_p2a/agent_task_benchmark_v1/`
- Cases：same frozen 3 cases
- Repeats：1
- Max turns：16
- Player script / success rule：unchanged
- Model：DeepSeek
- Memory：semantic
- Reflection：enabled
- Hard budget：¥1.00
- Provider-completed episodes：3/3
- Provider abort：0
- Task success：0/3
- Executed safety violations：0
- Total tokens：489,173
- Estimated cost：¥0.1950762

P2a 不以 task success 为 PASS 条件；0/3 保留为真实结果。

## Gray rejection breakdown

Gray 在 T8–T16 共发生 9 次 `action_outside_active_plan`。

9/9 telemetry 完全一致：

```text
proposed_action_type: use_tool
proposed_tool: submit_diagnosis
proposed_public_target_id: displaced_hearth_contract
proposed_argument_keys: [diagnosis_id, evidence_clue_ids]
active_plan_step_intent: propose_diagnosis
active_plan_step_tool: null
active_plan_step_public_target_id: null
alignment_reason_code: tool_mismatch
```

这不是 target mismatch，也没有命中 argument-order defect。

精确 mismatch：Decision 产生了公开、可识别的 `submit_diagnosis` proposal，
但 active `propose_diagnosis` PlanStep 没有 `suggested_tool` 与 public target，
所以 matcher 在 tool comparison 处拒绝，未到 target comparison。

分类：`PLAN_DECISION_COGENERATION_MISMATCH` / `TOOL_MISMATCH`。

## Lantern rejection breakdown

Lantern 在 T8–T16 共发生 9 次 `action_outside_active_plan`。

9/9 telemetry 完全一致：

```text
proposed_action_type: use_tool
proposed_tool: submit_diagnosis
proposed_public_target_id: angled_witness_memory_and_moved_token
proposed_argument_keys: [diagnosis_id, evidence_clue_ids]
active_plan_step_intent: propose_diagnosis
active_plan_step_tool: null
active_plan_step_public_target_id: null
alignment_reason_code: tool_mismatch
```

这不是 target mismatch，也没有命中 argument-order defect。

精确 mismatch 与 Gray 相同：Decision 选择 diagnosis tool 和公开 target，
active diagnosis PlanStep 却没有结构化 tool/target，导致 tool mismatch。

分类：`PLAN_DECISION_COGENERATION_MISMATCH` / `TOOL_MISMATCH`。

## Argument-order defect in the real run

Gray/Lantern 的所有 rejected diagnosis calls 都按以下顺序序列化：

```text
diagnosis_id, evidence_clue_ids
```

因此旧 matcher 读取的首个 value 就是 diagnosis ID。

本次真实 run 没有命中 `evidence_clue_ids` 在前造成的 order-sensitive defect。

该缺陷仍由 targeted test 证明存在，但不是本次 Gray/Lantern rejection 的 direct cause。

## P2 evidence gate

现在已经具备 P2 行为修复证据：

- 两案 action tool 与公开 target 均可观测；
- 两案 active step intent/tool/target 均可观测；
- 18 次 rejection 全部落在同一个 tool mismatch；
- 参数顺序替代解释已被排除；
- safety、Authority 和 world state 未发生 telemetry regression。

P2 后续最小行为修复应聚焦 Plan/Decision co-generation contract，
使 `propose_diagnosis` tool step 与同 turn diagnosis Decision 共享一致的
`suggested_tool=submit_diagnosis` 和 public target。

本轮没有实施该修复，也没有放宽 alignment gate。

## Final gate

```text
P2A IMPLEMENTATION: PASS
TELEMETRY BEHAVIOR-NEUTRAL: YES
TARGETED TEST: PASS
FULL TEST: PASS
GRAY EXACT MISMATCH: PLAN_DECISION_COGENERATION_MISMATCH / TOOL_MISMATCH (active diagnosis PlanStep tool and target are null)
LANTERN EXACT MISMATCH: PLAN_DECISION_COGENERATION_MISMATCH / TOOL_MISMATCH (active diagnosis PlanStep tool and target are null)
ARGUMENT-ORDER DEFECT HIT IN REAL RUN: NO
P2 ROOT CAUSE NOW PROVEN: YES
READY FOR P2 BEHAVIOR FIX: YES
NEXT GATE: P2
```
