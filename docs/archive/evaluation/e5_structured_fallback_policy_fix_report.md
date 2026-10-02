# E5 — Structured Fallback / Executable-Step Policy Correctness Fix Report

## Verdict

E5 PASS. Structured-output exhaustion can no longer return a fallback that the immediately downstream P5 policy must reject. The repair is generic, non-acting, and limited to an already-active executable PlanStep with no pending confirmation.

## Modified files

- `src/xuanyi_npc/agents/game_npc.py`
- `tests/test_e5_structured_fallback_policy.py`
- This report

No prompt, GoalPlanPolicy/P5 rule, Authority, alignment matcher, CaseEngine, Memory, Reflection, benchmark, case, success rule, model, or turn limit changed.

## Implementation

`_fallback_turn_proposal()` now classifies the existing current Plan only for fallback construction:

- Active step + non-null `suggested_tool` + non-null `public_target_id` + no pending confirmation: emit Goal `ABANDON`, Plan `ABANDON`, Decision `RESPOND`.
- Existing non-tool Plan: retain prior Goal `KEEP`, Plan `KEEP`, Decision `RESPOND` behavior.
- Pending confirmation: retain the current Goal/Plan and emit only `RESPOND`; the pending state is not replaced.
- Missing Plan: retain the existing safe non-tool fallback Plan creation.

The executable fallback does not call, copy, infer, or select any tool/target. `ABANDON/ABANDON` is an existing domain transition and satisfies the existing rule that an abandoned Goal requires an abandoned Plan. On a later turn, the existing runtime may create a fresh phase-appropriate Goal; fallback itself performs no recovery action.

## Correctness proof

Before E5:

```text
repair exhausted → KEEP Goal + KEEP Plan + RESPOND
→ executable-step commitment rejects → GoalPlanPolicyError
```

After E5:

```text
repair exhausted → ABANDON Goal + ABANDON Plan + RESPOND
→ GoalPlanPolicy accepts → Runtime returns a safe non-tool turn
```

The fallback action remains `RESPOND` with `tool_call=null`; therefore it cannot reach tool execution, create a diagnosis/treatment proposal, or create pending confirmation. Applying it changes only Agent Goal/Plan lifecycle metadata, not CaseEngine world state.

## Targeted tests

- Result: 25 passed.
- Existing executable diagnosis step + two invalid structured attempts: fallback is `ABANDON/ABANDON + RESPOND`, policy-valid.
- Existing executable treatment step + two invalid structured attempts: same policy-valid result.
- Both paths prove no tool call and autonomous non-acting Authority classification.
- Non-tool Plan fallback remains `KEEP/KEEP + RESPOND` and policy-valid.
- Pending executable Plan remains `KEEP/KEEP + RESPOND` and policy-valid under the existing pending exemption.
- The original P5 `KEEP/KEEP + RESPOND` rejection for an unblocked executable step remains unchanged.
- Runtime RESPOND alignment semantics remain unchanged; no Runtime action substitution was introduced.
- Existing structured fallback and P5 regression suites were included.

## Full regression

- Command: `python -m pytest -q`.
- Result: exit code 0, 100%; collection confirms 526 passed.
- No test expectation was weakened.

## Evaluation boundary

No paid model or benchmark run was performed. Acceptance is code-level: the formerly guaranteed fallback/policy contradiction is closed for diagnosis and treatment. Lantern terminal success and benchmark score improvement are explicitly not E5 requirements.

Old Paper's non-tool discussion path is untouched: E5 only branches on a current executable active step. Its E3 1/3 reliability result remains unchanged evidence.

E5 IMPLEMENTATION: PASS
TARGETED TEST: PASS
FULL TEST: PASS
FALLBACK/P5 CONTRADICTION RESOLVED: YES
FALLBACK REMAINS NON-ACTING: YES
SAFETY REGRESSION: NO
OLD PAPER BEHAVIOR MODIFIED: NO
CAPABILITY FREEZE MAINTAINED: YES
PAID REVALIDATION REQUIRED: NO
NEXT GATE: EVALUATION
