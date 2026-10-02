# P5 — Old Paper Treatment Decision Stall Differential Audit

## Verdict

Old Paper's direct episode cause is `CASE_CONTEXT_MODEL_DECISION_QUALITY`: given a valid executable treatment step, the model chose a structurally legal `RESPOND` eight times. A systemic `ACTION_SELECTION_CONTRACT_WEAKNESS` enabled the stall: `RESPOND` bypasses both treatment co-generation validation and runtime Plan alignment without requiring execution, replan, or block.

## Positive-control comparison

| Evidence | Gray | Lantern | Old Paper |
|---|---|---|---|
| Goal | `SELECT_TREATMENT`, active | `SELECT_TREATMENT`, active | `SELECT_TREATMENT`, active |
| Public description | 与玩家协商安全处置。 | same | same |
| Active intent | `discuss_treatment` | `discuss_treatment` | `discuss_treatment` |
| Active capability | `PROPOSE_TREATMENT`* | `PROPOSE_TREATMENT`* | `PROPOSE_TREATMENT`* |
| Suggested tool | `execute_treatment` | `execute_treatment` | `execute_treatment` |
| Public target | `restore_token_and_clear_flue` | `reconstruct_timeline_and_return_token` | `return_token_and_fulfill_vow` |
| Player contribution / branch | `suggestion` / `request_public_treatment` | same | same |
| First treatment decision | RESPOND, then tool | RESPOND, then tool | RESPOND ×8 |

\* Capability is not serialized in turn telemetry, but is proven by validation: any persisted `execute_treatment` step must have `PROPOSE_TREATMENT` capability (`goal_plan_policy.py:200-202`).

Gray and Lantern each used one discussion turn, then emitted a matching `execute_treatment`; Authority produced confirmation-required, player approval executed treatment, and the goal completed. Old Paper preserved the same step id/tool/target from turns 9–16, with no pending confirmation, rejection, fallback, or alignment error.

## Model-visible context

`_planning_request()` serializes `current_goal`, full `current_plan`, public observation, player contribution, Authority view, feedback, and `AVAILABLE_PUBLIC_ACTION_SPACE`. `project_public_treatment_actions()` exposes every currently public treatment as `execute_treatment(treatment_id=...)`. Thus Old Paper's Goal, active step, tool, public target, and treatment action were model-visible by the production wiring.

The exact candidate counts/descriptions are not retained in these artifacts: `NOT PROVEN BY CURRENT ARTIFACTS`. The validated Old Paper Plan target proves at least `return_token_and_fulfill_vow` was a currently public treatment. Structural player input is identical; case observation, target semantics, and recent dialogue necessarily differ, but their complete text is not artifacted.

## Why RESPOND remains legal

The treatment prompt requires a tool only when PlanStep intent/capability is `propose_treatment`; the visible active intent is `discuss_treatment`, so the wording does not explicitly require advancing its nevertheless executable tool binding. More decisively, `_validate_tool_decision_alignment()` returns immediately for every `RESPOND`, and `_action_matches_plan()` treats every `RESPOND` as matching. No boundedness or “execute vs revise/block” obligation exists.

Therefore Gray/Lantern did not avoid a different state or contract: their model decisions happened to advance after one response. Old Paper exposed the shared loophole through case-conditioned model behavior. This supports a general contract rule: when the active step has executable tool + public target and no pending/blocker, Decision must either issue the matching tool proposal or explicitly revise/block the Plan; explanatory RESPOND must not indefinitely substitute for progress. Runtime must not choose or execute the treatment itself.

OLD PAPER DIRECT ROOT CAUSE: CASE_CONTEXT_MODEL_DECISION_QUALITY; repeated legal RESPOND choices under an executable treatment step

GRAY/LANTERN POSITIVE CONTROL DIFFERENCE: same structural Goal/Plan/player branch; different case/public-target semantics and successful model choice after one RESPOND

ACTIVE TOOL STEP VISIBLE: YES

RESPOND UNBOUNDED UNDER EXECUTABLE STEP: YES

DECISION CONTRACT WEAKNESS: YES

MODEL QUALITY DIRECT CAUSE: YES

EVIDENCE SUFFICIENT FOR FIX: YES

MINIMUM FIX: strengthen the Decision contract so an unblocked executable active step requires matching tool use or explicit Plan revise/block; retain Agent-selected treatment and existing Authority/confirmation

READY FOR P5 IMPLEMENTATION: YES
