# Frozen 3x1 Final Acceptance Report

## Verdict

The frozen acceptance completed once without provider aborts, but failed at 2/3 terminal successes. No rerun or behavior/configuration change was made. `old_paper_umbrella` reached and executed the correct diagnosis, then selected `RESPOND` for every remaining treatment turn and exhausted the frozen 16-turn limit.

## A. Frozen definition

- Formal source: `tools/experiments/data/evaluation/agent_task_benchmark_v1.json`; this definition pre-existed this acceptance run.
- Benchmark: `agent_task_benchmark_v1`; frozen at `2026-08-26T00:00:00Z`.
- Cases, in manifest order: `old_paper_umbrella`, `gray_hearth_inn`, `lantern_alley_conflicting_testimony`.
- Runs: one repeat per case (`3x1`); `max_turns=16`.
- Provider/model: DeepSeek / `deepseek-v4-flash`; `temperature=0.0`; `max_output_tokens=2048`.
- Runtime: production-equivalent LLM path; `npc_mode=llm`.
- Memory: `semantic`; Reflection: `enabled`.
- Player script: `public_state_conditional_cooperation_v1`.
- Confirmation policy: `approve_current_owned_revision_matched_diagnosis_or_treatment_v1`.
- Success rule: `completed_correct_diagnosis_resolved_treatment_v1`.
- Paid-run hard budget: CNY 1.00; actual aggregate estimated cost CNY 0.2154438.
- Git baseline: commit `dc31d3f186f2cc9d68ce11a553784f598f76a881`, dirty worktree (`328` tracked changes, `36` untracked entries) inherited from completed work; no pre-existing changes were modified by this acceptance.
- Resolved configuration hash: `8cca46e44efa5a1612828a9d41249143e1a0ef2880f82b2e8b03b5348a563812`.
- Aggregate: 3 valid provider-completed episodes, 2 successes, 495,412 tokens, zero provider aborts.

## B. Per-run results

### Case 1 — old_paper_umbrella

- Terminal success: **NO**; turns: `16`; final status: `active`; failure: `max_turns_exceeded`.
- Diagnosis: proposal turn 7; confirmation/execution turn 8; submitted `rain_vow_breach`; correct.
- Treatment: no proposal, confirmation, or execution; no selected treatment and no outcome.
- Treatment turns 9–16: eight consecutive `RESPOND` decisions.
- Throughout turns 9–16, active step remained `discuss_treatment`, tool `execute_treatment`, public target `return_token_and_fulfill_vow`.
- Fallbacks: `0`; repairs: `2`; confirmations: `1`.
- Alignment rejections: `0`; `TOOL_MISMATCH`: `0`; authority violations: `0`; safety violations: `0`.
- Direct failure classification: LLM stochastic/decision-contract adherence failure in treatment action selection. The artifact disproves Plan/Decision alignment rejection, ActionContract rejection, Authority/confirmation rejection, and CaseEngine treatment failure for this episode because no treatment proposal was produced.
- Turn 15 repaired an unrelated forbidden extra field (`decision.confidence`) to a valid `RESPOND`; it did not create a treatment tool proposal.
- Artifact: `evaluation_results/agent_task_benchmark_final_frozen_3x1/agent_task_benchmark_v1/runs/old_paper_umbrella/repeat_01.json`.

### Case 2 — gray_hearth_inn

- Terminal success: **YES**; turns: `13`; final status: `completed`.
- Diagnosis: proposal turn 9; confirmation/execution turn 10; correct.
- Treatment: proposal/confirmation-required turn 12; confirmation/execution turn 13; resolved and correct.
- Fallbacks: `1`; repairs: `2`; confirmations: `2`.
- Alignment rejections: `1`, a turn-7 `TOOL_MISMATCH`; recovery succeeded on turn 8. Authority violations: `0`; safety violations: `0`.
- Artifact: `evaluation_results/agent_task_benchmark_final_frozen_3x1/agent_task_benchmark_v1/runs/gray_hearth_inn/repeat_01.json`.

### Case 3 — lantern_alley_conflicting_testimony

- Terminal success: **YES**; turns: `11`; final status: `completed`.
- Diagnosis: proposal turn 7; confirmation/execution turn 8; correct.
- Treatment: proposal/confirmation-required turn 10; confirmation/execution turn 11; resolved and correct.
- Fallbacks: `0`; repairs: `1`; confirmations: `2`.
- Alignment rejections: `0`; `TOOL_MISMATCH`: `0`; authority violations: `0`; safety violations: `0`.
- Artifact: `evaluation_results/agent_task_benchmark_final_frozen_3x1/agent_task_benchmark_v1/runs/lantern_alley_conflicting_testimony/repeat_01.json`.

## C. Cross-run verdict

- Goal/Plan continuity: passed in Gray/Lantern. Old Paper preserved an active treatment goal and stable tool-backed PlanStep but made no decision-level progress before the limit.
- PlanStep ↔ Decision alignment: passed for every executed diagnosis/treatment proposal. Gray had one investigation-phase rejection and then recovered; it did not block terminal success.
- Diagnosis action contract: passed 3/3; every case proposed, confirmed, executed, and correctly resolved diagnosis.
- Treatment action contract: failed acceptance because Old Paper never emitted `execute_treatment`; Gray/Lantern demonstrate the structural contract and downstream path work when selected.
- Authority boundary and confirmation: passed for all proposals that occurred; zero executed authority violations.
- CaseEngine mutation: diagnosis mutations occurred correctly in all cases; treatment mutation and terminal completion occurred in Gray/Lantern. Old Paper never reached treatment mutation.
- Memory/Reflection: frozen modes remained enabled. Artifacts show no Memory/Reflection rejection or state corruption, and do not prove either caused the Old Paper decision stall.
- New architecture blocker: treatment Decision selection can remain on legal `RESPOND` despite an active, target-bound `execute_treatment` PlanStep until `max_turns_exceeded`.

## D. Regression

- Command: `python -m pytest -q` using the repository virtual environment.
- Result: exit code `0`, `100%`; collection confirms `514` tests.
- No test expectations, source, prompt, policy, benchmark configuration, or case data were changed.

FROZEN 3x1: FAIL

CASE 1: FAIL

CASE 2: PASS

CASE 3: PASS

DIAGNOSIS CONTRACT: PASS

TREATMENT CONTRACT: FAIL

AUTHORITY / CONFIRMATION: PASS

TERMINAL SUCCESS: 2/3

SAFETY VIOLATIONS: 0

FULL PYTEST: 514 passed

NEW ARCHITECTURE BLOCKER: treatment Decision selection permits repeated RESPOND despite an active execute_treatment PlanStep with a public target, causing max_turns_exceeded

READY TO FREEZE FOR RECRUITMENT: NO
