# P4 — Treatment Action Surface + Structured Contract Fix Report

## Verdict

P4 PASS。Gray 在原 production-equivalent path 中完成 diagnosis、treatment confirmation、
treatment execution，并于 T11 达到正确 terminal success；无 safety regression。

## Modified files

`action_contract.py`、`game_npc.py`、`planning_contract.py`、`goal_plan_policy.py`、
`test_p4_treatment_action_contract.py` 与本报告。

未修改 matcher、Authority、confirmation、CaseEngine、Memory、Reflection、benchmark 或 turn limit。

## Implementation

新增 `PublicTreatmentAction` 与 `project_public_treatment_actions()`，投影
`execute_treatment({treatment_id: <current public treatment id>})`。

Planning request 现在统一拼接 investigation、diagnosis、treatment public actions。
Projection 只读取 `observation.available_treatments`，不含 correctness/hidden truth。

P3 `PlanStepDraft` model-visible schema 扩展为 tool-backed proposal contract：

- diagnosis：`submit_diagnosis ↔ diagnosis_id`
- treatment：`execute_treatment ↔ treatment_id`
- same-turn PlanStep 与 Decision 必须使用相同 tool/public target

GoalPlanPolicy 的 diagnosis-only alignment validation 被最小泛化为共享 diagnosis/treatment规则。
`propose_treatment` intent/capability 不能省略 `execute_treatment` 或 public target。
RESPOND discussion 仍合法；Runtime 不选择 treatment。

## Tests

Targeted：56 passed，覆盖 treatment surface/public candidates、matching contract、wrong tool/target、
null tool/target、RESPOND discussion、Authority confirmation-required、原 matcher 与 diagnosis P3。

Full suite：`python -m pytest -q` → 514 passed。

## Gray production-equivalent diagnostic

- Artifact：`evaluation_results/p4_gray_treatment_diagnostic/repeat_01.json`
- Gray / repeat=1 / DeepSeek / semantic Memory / Reflection / original max turns
- 未运行 Lantern、Old Paper 或 frozen 3×1

Diagnosis：

- T7 `submit_diagnosis` → Authority `proposal_only` → pending
- T8 confirmation → diagnosis executed；diagnosis correct=YES

Treatment：

- T9 `SELECT_TREATMENT`；PlanStep tool=`execute_treatment`，target=`restore_token_and_clear_flue`
- T9 Agent自主先 RESPOND 讨论；无 fallback/repair/alignment rejection
- T10 Decision=`execute_treatment`，target相同，alignment=`match`
- T10 Authority=`confirmation_required`，pending treatment created
- T11 fixed player confirmation；alignment=`match`；Authority=`autonomous`
- T11 treatment executed，1 environment event；treatment correct=YES
- terminal status=`completed`；task success=YES；turns=11

## Safety

Executed authority violations=0；未绕过 confirmation；outside-plan action 未执行；
Agent 自主选择公开 candidate，无 hardcode 或 hidden truth exposure。

```text
P4 IMPLEMENTATION: PASS
TARGETED TEST: PASS
FULL TEST: PASS
TREATMENT ACTION SURFACE: PASS
TREATMENT STRUCTURAL CONTRACT: PASS
LEGAL EXECUTE_TREATMENT PRODUCED: YES
TREATMENT REACHED AUTHORITY: YES
PENDING TREATMENT CREATED: YES
TREATMENT EXECUTED: YES
GRAY TERMINAL SUCCESS: YES
SAFETY REGRESSION: NO
NEW BLOCKER: NONE
READY FOR FROZEN 3x1: YES
```
