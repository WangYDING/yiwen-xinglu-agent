# P2 — Plan/Decision Co-generation Alignment Behavior Fix Report

## Verdict

P2 的结构 contract 已实现并通过全部测试，但真实 frozen benchmark 未达到 P2 production success gate。

新 contract 成功消除了 Gray/Lantern 的 diagnosis `TOOL_MISMATCH ×9`，
且没有放宽 alignment gate 或产生 safety regression。

但是 DeepSeek 在 diagnosis phase 的 structured repair 未能返回合规的
Plan+Decision，bounded repair 耗尽后安全 fallback 为 `RESPOND`，
所以 diagnosis 没有到达 Authority/pending/confirmation/CaseEngine。

因此：结构校验机制有效，P2 整体 production implementation 判定 FAIL。

## Modified files

- `src/xuanyi_npc/application/goal_plan_policy.py`
- `tests/test_p2_plan_decision_alignment.py`
- `docs/p2_plan_decision_alignment_fix_report.md`

P2a telemetry 文件保持使用，但本轮没有修改 matcher、benchmark fixture、
Memory、Reflection、Authority、ActionContract 或 CaseEngine semantics。

## Actual fix mechanism

`GoalPlanPolicy.validate()` 新增两个结构 invariant：

1. 任何 `propose_diagnosis` intent/capability PlanStep 必须显式包含：
   - `suggested_tool=submit_diagnosis`
   - public diagnosis target
2. FORM_DIAGNOSIS 中的非-RESPOND Decision 必须与本轮 resulting active step 一致：
   - Decision tool 必须为 `submit_diagnosis`
   - PlanStep tool 必须为 `submit_diagnosis`
   - PlanStep target 必须等于 Decision `diagnosis_id`

CREATE/REVISE 使用 proposal draft 的 first step；KEEP 使用 persisted active step。

不一致 proposal 在 `GameNPCAgent._parse_turn()` 内进入已有 bounded structured repair，
早于 Runtime `_apply_proposal`、`_action_matches_plan` 和执行层。

Runtime 不补写 Plan、不选择 diagnosis、不选择 evidence。

普通 RESPOND 仍合法，但不能同时创建结构残缺的 `propose_diagnosis` step。

## Targeted tests

新增 6 个 P2 tests，覆盖：

- matching diagnosis Plan/Decision 通过 policy 与原 matcher；
- 空 tool/target diagnosis step 在 runtime alignment 前触发 structured repair；
- wrong diagnosis target 拒绝；
- wrong tool 拒绝；
- 合法 RESPOND 不被全局禁止；
- RESPOND 不能持久化结构残缺的 diagnosis step；
- aligned diagnosis 仍由原 Authority 分类为 `proposal_only`。

完整 targeted command 覆盖 P2、P2a、Goal/Plan runtime、public action surface、benchmark harness：

```text
python -m pytest -q \
  tests/test_p2_plan_decision_alignment.py \
  tests/test_p2a_alignment_telemetry.py \
  tests/test_m2_planning_contract.py \
  tests/test_m2_cooperative_runtime_planning.py \
  tests/test_m5_public_action_space.py \
  tests/test_agent_task_benchmark.py
59 passed
```

## Full pytest

```text
python -m pytest -q
504 passed
```

Full suite 在最终 contract revision 后 100% PASS。

## Frozen validation runs

### First post-P2 validation

- Output：`evaluation_results/agent_task_benchmark_post_p2/agent_task_benchmark_v1/`
- Frozen 3×1、max turns 16、same script/success rule
- DeepSeek + semantic Memory + Reflection
- Hard budget：¥1.00
- Success：0/3
- Safety violations：0
- Tokens：528,639
- Cost：¥0.18491924

首次验证证明只约束非-RESPOND Decision 不足：
之前由 RESPOND 创建的空 diagnosis PlanStep 会继续持久化。

因此补充 PlanStep 自身结构 invariant；首次 artifact 未覆盖。

### Final post-P2 retry

- Output：`evaluation_results/agent_task_benchmark_post_p2_retry/agent_task_benchmark_v1/`
- 配置与 post-P2a 完全相同
- Success：0/3
- Provider abort：0
- Safety violations：0
- Tokens：622,720
- Cost：¥0.2051214
- Failure：3 × `max_turns_exceeded`

两个验证目录均独立保存；没有覆盖旧 artifact。

## Gray pre/post

| Metric | post-P2a | final post-P2 retry |
|---|---:|---:|
| diagnosis Goal first turn | 7 | 7 |
| diagnosis `action_outside_active_plan` | 9 | 0 |
| diagnosis tool mismatch | 9 | 0 |
| diagnosis structured repairs | not applicable | 10 |
| diagnosis pending | 0 | 0 |
| diagnosis confirmed | 0 | 0 |
| diagnosis executed | 0 | 0 |
| terminal success | no | no |

Final retry T7–T16：

```text
active step intent = analyze_evidence
active step tool/target = null/null
proposed action = RESPOND
alignment = not_applicable
repair_used = true
```

原 `propose_diagnosis(null/null) + submit_diagnosis -> tool_mismatch` 不再出现。

但每轮 bounded repair 均安全 fallback，没有合法 diagnosis proposal 到达 Authority。

## Lantern pre/post

| Metric | post-P2a | final post-P2 retry |
|---|---:|---:|
| diagnosis Goal first turn | 7 | 7 |
| diagnosis `action_outside_active_plan` | 9 | 0 |
| diagnosis tool mismatch | 9 | 0 |
| diagnosis structured repairs | not applicable | 10 |
| diagnosis pending | 0 | 0 |
| diagnosis confirmed | 0 | 0 |
| diagnosis executed | 0 | 0 |
| terminal success | no | no |

Final retry 与 Gray 相同：T7–T16 均为 bounded repair 后的
`RESPOND + analyze_evidence` fallback；没有 diagnosis Authority event。

## Alignment, Authority and execution

Targeted tests 证明合法一致 proposal 的原 production sequence仍为：

```text
GoalPlanPolicy validation
→ Runtime apply proposal
→ unchanged _action_matches_plan
→ ActionContract
→ Authority proposal_only
→ pending / confirmation
→ CaseEngine
```

真实 retry 中没有模型生成的合法 diagnosis proposal完成第一步，
所以不能把 targeted path 证据冒充为 production diagnosis execution。

- Diagnosis reached ActionContract：NO
- Diagnosis reached Authority：NO
- Pending diagnosis：NO
- Player confirmation：NO
- Diagnosis executed：NO
- Treatment phase reached：NO

## Safety

- `_action_matches_plan` 未修改、未放宽、未绕过。
- outside-plan action 没有执行。
- Runtime 没有选择或补写 diagnosis/target/evidence。
- Authority、pending、confirmation、CaseEngine semantics 未修改。
- 两次真实验证 executed safety violations 均为 0。

`SAFETY REGRESSION: NO`。

## New blocker

`STRUCTURED_REPAIR_EXHAUSTED_TO_SAFE_RESPOND_FALLBACK`。

模型在 diagnosis Goal 下未能在 bounded repair 内返回符合新增 structural contract 的
Plan+Decision，Agent fallback 创建 `analyze_evidence` 非工具计划并 RESPOND。

这是新的真实 blocker；继续改变 repair contract、prompt、fallback 或 replan 行为
超出本轮已授权的最小 structural alignment fix。

Old Paper retry 的调查期 alignment stall：`OUT OF P2 SCOPE`。

## Final gate

```text
P2 IMPLEMENTATION: FAIL
P2 TEST: PASS
PLAN_DECISION STRUCTURAL ALIGNMENT FIX: PASS
GRAY TOOL_MISMATCH RESOLVED: YES
LANTERN TOOL_MISMATCH RESOLVED: YES
DIAGNOSIS REACHED AUTHORITY: NO
DIAGNOSIS EXECUTED: NO
SAFETY REGRESSION: NO
POST-P2 TASK SUCCESS: 0/3
NEW BLOCKER: STRUCTURED_REPAIR_EXHAUSTED_TO_SAFE_RESPOND_FALLBACK
NEXT GATE: STOP
```
