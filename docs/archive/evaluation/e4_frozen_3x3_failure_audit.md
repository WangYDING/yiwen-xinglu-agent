# E4 — Frozen 3×3 Failure Differential Audit

## E4 verdict

Lantern repeat 2 provides `SUPPORTED BUT NOT PROVEN` evidence for the proposed crash chain, because the crashing turn was not serialized. Independently, source wiring proves a deterministic production contract incompatibility: structured-output exhaustion can return fallback `KEEP + RESPOND`, and P5 necessarily rejects that fallback when the current active step is executable and unblocked.

Old Paper repeats 1/2 versus repeat 3 differ at model-authored treatment Plan creation, not at public phase, script, repair, fallback, alignment, or Authority. The failures are case-conditioned model Plan/Decision variance operating through a permitted non-tool discussion path. That path is a robustness weakness, but it is not proven to violate the current explicit P5 design boundary.

## Part A — Lantern repeat 2

### Last serialized turns

- T7: `FORM_DIAGNOSIS`; initial schema error, repair policy error, then safe fallback `RESPOND`; a non-tool analysis Plan was persisted.
- T8: valid `submit_diagnosis` proposal; active tool/target matched; Authority=`proposal_only`.
- T9: player approval; diagnosis executed correctly; Goal transitioned after world mutation.
- T10: `SELECT_TREATMENT`; a new active step was persisted with intent=`discuss_treatment`, tool=`execute_treatment`, target=`reconstruct_timeline_and_return_token`; Decision=`RESPOND`; this first discussion turn was legal because the Plan was created in the same proposal.
- The run then terminated as `failure_reason=runtime_error`, `infrastructure_error_code=GoalPlanPolicyError`, terminal status=`active`.
- No T11 sanitized summary exists. Its initial proposal error, repair error, repaired structure, and fallback flag are therefore `NOT PROVEN BY CURRENT ARTIFACTS`.

### Proposed hypothesis

```text
executable active step
→ invalid proposal
→ structured repair exhausted
→ fallback KEEP + RESPOND
→ P5 rejects KEEP + RESPOND
→ GoalPlanPolicyError escapes runtime
```

Artifact-level status: `SUPPORTED BUT NOT PROVEN`.

Support is strong but incomplete: T10 proves the next turn started from an executable active step; the terminal infrastructure class is exactly `GoalPlanPolicyError`; no next-turn telemetry survived. The artifact does not prove that both LLM attempts failed or that fallback was selected.

### Code-level contract compatibility

- `GameNPCAgent.propose_turn()` returns `_fallback_turn_proposal()` whenever structured output has no valid output.
- With any existing Plan, `_fallback_turn_proposal()` deterministically emits Goal `KEEP`, Plan `KEEP`, and plain `RESPOND`.
- P5 `_validate_executable_step_commitment()` deterministically raises `GoalPlanPolicyError` for active tool+target plus no pending plus `KEEP/KEEP + RESPOND`.
- The fallback is returned without passing through `_parse_turn()` validation again.
- `CooperativeRuntime.handle()` then validates the returned proposal with the same GoalPlanPolicy; the exception is not converted into a safe turn result at that boundary.

Therefore the fallback can generate a proposal that is guaranteed to be rejected by the immediately downstream policy. This contradiction is code-proven without a model replay and is a production correctness defect. What remains unproven is only whether Lantern r2 reached fallback by exactly that route.

## Part B — Old Paper repeats 1/2/3

### Equivalent treatment-entry state

All three repeats had:

- The same initial public fingerprint.
- Correct diagnosis `rain_vow_breach`, confirmed and executed at T8.
- Pre-treatment session revision 7 and eight discovered clues.
- Goal description corresponding to `SELECT_TREATMENT`.
- Player contribution type=`suggestion`; branch=`request_public_treatment`.
- Memory candidates/selected/declared/accepted all zero at T9; Reflection not triggered.
- No T9 repair, fallback, alignment rejection, or Authority difference.

The exact serialized public treatment candidate list is absent from run artifacts: `NOT PROVEN BY CURRENT ARTIFACTS`. Production projection is deterministic from `available_treatments`; repeat 3 proves `return_token_and_fulfill_vow` was public in its observation. The artifacts do not retain full T9 observation/recent-message text for byte-level equality.

### Divergence

| Repeat | T9 Plan intent | Tool | Target | T9 Decision | Later result |
|---|---|---|---|---|---|
| 1 | `discuss_treatment` | null | null | RESPOND | RESPOND through T16; max turns |
| 2 | `discuss_treatment` | null | null | RESPOND | RESPOND through T16; max turns |
| 3 | `discuss_treatment` | `execute_treatment` | `return_token_and_fulfill_vow` | RESPOND | matching tool T10; confirmed/executed T11 |

Repeats 1/2 kept the same non-tool Plan step from T9–T16. They had no repair/fallback during the stall, no world revision change, no alignment rejection, and no treatment proposal. Repeat 3 used the same structural phase and script but authored an executable binding; P5 then committed the next decision to the matching tool.

### Classification

- Schema/validator difference: NO evidence; all three T9 proposals were accepted by the same schema and policy.
- Public action surface difference: NOT PROVEN; no artifact field records the full list, and no evidence shows a difference.
- Runtime state difference: NO material recorded difference at treatment entry.
- Repair/fallback difference: NO at T9 or during the failed stalls.
- Model-visible context difference: full text is not retained; case is identical, but generated dialogue/history may differ.
- Direct cause: case-conditioned stochastic model Plan selection, followed by legal RESPOND decisions on the chosen non-tool step.

The production contract explicitly allows `SELECT_TREATMENT → non-tool discussion → RESPOND`; P5 intentionally applies only after a step has tool+target. It also provides no bounded commitment for a non-tool discussion step. This is a systemic robustness weakness exposed twice, but not a proven correctness bug: the stated design preserves discussion steps and did not require them to become executable within a fixed number of turns.

## Fix threshold and freeze

- Lantern meets the narrow correctness-fix threshold because the fallback/downstream-policy contradiction is code-proven and case-independent.
- Any fix should be limited to making structured fallback policy-valid for an executable current step, without choosing a tool/target, relaxing P5, or optimizing a frozen case.
- Old Paper does not meet the behavior-fix threshold. Its 1/3 result should remain recorded variance; do not add a treatment-only or no-progress rule.
- Maintain the capability freeze against score-driven changes. A narrowly scoped correctness repair for the Lantern contradiction is an allowed freeze exception, followed by targeted/full regression before any paid evaluation decision.

LANTERN RUNTIME ERROR ROOT CAUSE: proposed exact episode chain SUPPORTED BUT NOT PROVEN; code-proven fallback KEEP+RESPOND versus P5 executable-step policy contradiction

LANTERN CORRECTNESS BUG PROVEN: YES

OLD PAPER FAILURE ROOT CAUSE: case-conditioned stochastic non-tool treatment Plan selection followed by legal RESPOND persistence

OLD PAPER SYSTEMIC CONTRACT BUG PROVEN: NO

OLD PAPER MODEL VARIANCE: YES

CAPABILITY FREEZE SHOULD REMAIN: YES

BEHAVIOR FIX JUSTIFIED: YES

MINIMUM NEXT STEP: narrowly repair the code-proven fallback/policy incompatibility only; do not address Old Paper variance or rerun cases in this audit

MEMORY/REFLECTION ABLATION STILL DEFERRED: YES
