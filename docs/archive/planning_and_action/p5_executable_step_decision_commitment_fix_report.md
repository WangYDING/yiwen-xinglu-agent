# P5 — Executable Active Step Decision Commitment Fix Report

## Verdict

P5 PASS. A persisted executable active PlanStep can no longer be kept indefinitely by a plain `RESPOND`: the model must emit the matching tool proposal or explicitly revise/abandon the Plan or block/abandon the Goal. Runtime still never selects or substitutes an action.

## Modified files

- `src/xuanyi_npc/application/goal_plan_policy.py`
- `src/xuanyi_npc/agents/game_npc.py`
- `src/xuanyi_npc/application/cooperative_runtime.py`
- `tests/test_p5_executable_step_commitment.py`
- This report

No case, benchmark, success rule, turn limit, Memory, Reflection, Authority, alignment matcher, action surface, or CaseEngine behavior changed.

## Implementation

- `GoalPlanPolicy` rejects only this combination: current active PlanStep has tool + public target, Plan/Goal are kept, no pending confirmation exists, and Decision is plain `RESPOND`.
- Matching tool calls continue through existing Plan alignment, ActionContract, Authority, pending confirmation, and CaseEngine paths.
- Existing Plan `REVISE`/`ABANDON` and Goal `BLOCK`/`ABANDON` remain legal alternatives.
- RESPOND remains legal for newly created discussion plans, non-tool steps, blocked step state, and pending confirmation.
- The production Agent input now carries only the validated pending confirmation id and makes the generic execute-or-revise/block obligation model-visible.
- Structured failure uses the existing repair path; the error explicitly states that an executable active step requires a matching tool decision or explicit revision/block.

## Tests

- Targeted: `20 passed` across P2 alignment, P4 treatment contract, and P5 commitment tests.
- Covered matching treatment/diagnosis, plain RESPOND rejection and repair, wrong tool, wrong target, legal revision, pending confirmation, non-tool discussion, unchanged runtime alignment, unchanged Authority behavior, and no Runtime action selection.
- Full: `python -m pytest -q` → `521 passed`, exit code 0, 100%.

## Old Paper production-equivalent diagnostic

- Artifact: `evaluation_results/p5_old_paper_executable_step_diagnostic/repeat_01.json`.
- Frozen model/runtime, DeepSeek, semantic Memory, Reflection, max turns, player script, and success rule preserved.
- T9 created the public treatment Plan and used one legal discussion RESPOND.
- T10 emitted matching `execute_treatment(return_token_and_fulfill_vow)`; alignment=`match`; Authority=`confirmation_required`; pending treatment created.
- T11 player approval executed the same treatment; outcome=`resolved`; terminal=`completed`.
- Result: 11 turns; diagnosis correct; treatment correct; fallback=0; repair=1; alignment rejection=0; executed authority violation=0.
- The former `RESPOND ×8` stall did not recur.

## Final frozen 3x1

- Artifact root: `evaluation_results/agent_task_benchmark_post_p5_final/agent_task_benchmark_v1/`.
- Unchanged frozen definition: 3 cases × repeat 1, max turns 16, `deepseek-v4-flash`, semantic Memory, Reflection enabled, fixed player/confirmation and success rules.
- `old_paper_umbrella`: PASS, 11 turns, diagnosis/treatment correct, treatment confirmed and executed.
- `gray_hearth_inn`: PASS, 11 turns, diagnosis/treatment correct, treatment confirmed and executed.
- `lantern_alley_conflicting_testimony`: PASS, 11 turns, diagnosis/treatment correct, treatment confirmed and executed.
- Aggregate: 3/3 terminal success; diagnosis accuracy=1.0; treatment accuracy=1.0; provider aborts=0; executed safety violations=0.
- Lantern used existing structured repair/fallback behavior before forming a valid treatment plan; it then reached matching tool, confirmation, execution, and terminal success. No new blocker resulted.

P5 IMPLEMENTATION: PASS

TARGETED TEST: PASS

FULL TEST: PASS

EXECUTABLE STEP COMMITMENT CONTRACT: PASS

OLD PAPER RESPOND STALL RESOLVED: YES

TREATMENT REACHED AUTHORITY: YES

TREATMENT EXECUTED: YES

OLD PAPER TERMINAL SUCCESS: YES

SAFETY REGRESSION: NO

FINAL FROZEN 3x1: 3/3

NEW BLOCKER: NONE

READY TO FREEZE FOR RECRUITMENT: YES
