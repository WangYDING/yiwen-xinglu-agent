# E3 — Frozen 3×3 Statistical Agent Evaluation Report

## 1. Evaluation verdict

The first formal multi-run evaluation completed all 9 scheduled episodes exactly once. Result: 6/9 task success (66.67%), diagnosis accuracy 100%, treatment accuracy 66.67%, zero executed safety violations, zero provider aborts, and one infrastructure-class runtime failure.

This is `INITIAL` descriptive reliability evidence, not strong initial evidence. It proves repeated task completion but also exposes material per-case variance. No episode was rerun, removed, replaced, or selected after the fact, and no Agent behavior was changed.

## 2. Frozen identity

- Artifact root: `evaluation_results/agent_task_benchmark_recruitment_3x3/agent_task_benchmark_v1/`.
- Benchmark: `agent_task_benchmark_v1`; fresh 3 cases × 3 repeats = 9 episodes.
- Historical final 3×1 was retained separately and was not included in this aggregate.
- Cases: `old_paper_umbrella`, `gray_hearth_inn`, `lantern_alley_conflicting_testimony`.
- Max turns: 16.
- Provider/model: DeepSeek / `deepseek-v4-flash`.
- Temperature: 0.0; max output tokens: 2048.
- Memory: semantic; Reflection: enabled.
- Player script: `public_state_conditional_cooperation_v1`.
- Confirmation: `approve_current_owned_revision_matched_diagnosis_or_treatment_v1`.
- Success rule: `completed_correct_diagnosis_resolved_treatment_v1`.
- Hard budget: CNY 1.00; actual estimated cost: CNY 0.4086092.
- Preflight: frozen manifest matched P5/E2; all 8 runtime hashes matched; credential configuration was available; output root did not exist.
- Run manifest hash: `cfb90f40751de197810c2f13cce2fcaf8ef8d66bd541a519538a2e95a4ca85e8`.
- The repeats=3 resolved manifest has its own identity; no incompatible 3×1 artifacts were pooled.

## 3. Nine-episode raw summary

| Case | Repeat | Success | Turns | Diagnosis | Treatment | Repair | Fallback | Failure / terminal |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| Gray | 1 | YES | 11 | correct | correct | 3 | 0 | completed |
| Gray | 2 | YES | 11 | correct | correct | 2 | 0 | completed |
| Gray | 3 | YES | 11 | correct | correct | 1 | 0 | completed |
| Lantern | 1 | YES | 11 | correct | correct | 1 | 0 | completed |
| Lantern | 2 | NO | 10 | correct | not executed | 1 | 1 | `runtime_error`; active |
| Lantern | 3 | YES | 11 | correct | correct | 1 | 0 | completed |
| Old Paper | 1 | NO | 16 | correct | not executed | 1 | 0 | `max_turns_exceeded`; active |
| Old Paper | 2 | NO | 16 | correct | not executed | 1 | 0 | `max_turns_exceeded`; active |
| Old Paper | 3 | YES | 11 | correct | correct | 1 | 0 | completed |

Raw artifacts are under `runs/<case_id>/repeat_01.json` through `repeat_03.json`; all nine remain immutable in the output root.

## 4. Overall capability metrics

- Formal/provider-completed episodes: 9/9.
- Task successes: 6/9; task success rate: 0.6667.
- Macro case success rate: 0.6667.
- Terminal completions: 6/9; terminal completion rate: 0.6667.
- Diagnosis accuracy: 9/9 = 1.0000.
- Treatment accuracy: 6/9 = 0.6667.
- Aggregate goal completion rate: 1.0000 under the existing benchmark denominator; raw goal completions: 60.
- Failure distribution: `max_turns_exceeded=2`, `runtime_error=1`.

## 5. Per-case reliability

### gray_hearth_inn

- Success: 3/3; failed repeats: none; diagnosis/treatment accuracy: 1.0/1.0.
- Turns: mean 11.00, median 11, min/max 11/11, sample std 0.00.
- Tokens: mean 151,266; median 151,720; min/max 141,420/160,659; sample std 9,628.
- Failure reason distribution: none.

### lantern_alley_conflicting_testimony

- Success: 2/3; failed repeat: 2; diagnosis/treatment accuracy: 1.0/0.6667.
- Turns: mean 10.67, median 11, min/max 10/11, sample std 0.58.
- Tokens: mean 135,612; median 140,531; min/max 124,709/141,597; sample std 9,458.
- Failure reason distribution: `runtime_error=1`; infrastructure code `GoalPlanPolicyError`.

### old_paper_umbrella

- Success: 1/3; failed repeats: 1 and 2; diagnosis/treatment accuracy: 1.0/0.3333.
- Turns: mean 14.33, median 16, min/max 11/16, sample std 2.89.
- Tokens: mean 165,321; median 175,760; min/max 137,713/182,491; sample std 24,145.
- Failure reason distribution: `max_turns_exceeded=2`.

## 6. Efficiency

- Turns across all episodes: total 108; mean 12.00; median 11; min/max 10/16; sample std 2.29.
- Input tokens: total 1,199,404; mean 133,267; median 124,506; min/max 109,778/164,132; sample std 17,948.
- Output tokens: total 157,196; mean 17,466; median 17,995; min/max 14,931/19,146; sample std 1,301.
- Total tokens: 1,356,600; mean 150,733; median 141,597; min/max 124,709/182,491; sample std 18,893.
- Estimated cost: total CNY 0.4086092; mean CNY 0.045401/episode; median CNY 0.037942; min/max CNY 0.034475/0.065845; sample std CNY 0.012110.
- Duration: total 968.68 s; mean 107.63 s; median 105.06 s; min/max 89.85/124.44 s; sample std 10.75 s.
- Provider requests: 180 total; mean 20.0/episode.

## 7. Agent behavior

- Tool calls: 84 total.
- Confirmations: 15 total.
- Repairs: 12 total; 12/108 turns = 0.1111 repair frequency.
- Fallbacks: 1 total; 1/108 turns = 0.0093 fallback frequency.
- Rejected actions: 0.
- Plan/action alignment rejections: 0; no recorded tool/target mismatch rejection.
- Goal completions: 60 total.
- Successful episodes all completed diagnosis and treatment confirmation/execution paths.

## 8. Safety and infrastructure

- Executed authority violations: 0.
- Existing executed safety violation rate: 0.0 per tool call.
- Provider aborts: 0; provider failure rate: 0/9 = 0.0.
- Infrastructure failures: 1; infrastructure failure rate: 1/9 = 0.1111.
- No failed episode was rerun or overwritten.

## 9. Failure classification

### Old Paper repeats 1 and 2

Both correctly proposed, confirmed, and executed diagnosis by turn 8. At treatment entry they created `discuss_treatment` steps with `suggested_tool=null` and `public_target_id=null`, then selected plain RESPOND through turn 16. There was no repair/fallback during the stall, no alignment rejection, no Authority violation, and no treatment proposal.

Classification: `stochastic model Plan/Decision failure` with a repeatable case-level treatment-plan weakness (2/3 repeats). This is not a P5 executable-step violation because those failed PlanSteps were not executable. The artifacts do not establish a hidden-domain, Authority, alignment, or provider cause.

### Lantern repeat 2

Diagnosis recovered from one structured fallback and executed correctly. Treatment turn 10 created an executable `execute_treatment` step but responded once. The episode then ended as `runtime_error`, infrastructure code `GoalPlanPolicyError`, before a turn-11 summary was serialized.

Classification: `structured repair/fallback or policy-boundary runtime failure`, exact subcause unknown from current artifact. Code contains a plausible incompatibility: repair exhaustion returns KEEP+RESPOND fallback, while P5 rejects KEEP+RESPOND on an executable step; however the missing failed-turn proposal/repair telemetry means `NOT PROVEN BY CURRENT ARTIFACTS` for this episode's exact chain. It is one observed infrastructure correctness signal, not yet a reproduced bug.

## 10. Claims supported

- Nine frozen episodes completed at the provider/artifact level with 6/9 terminal task success.
- Diagnosis was correct in all 9 episodes.
- Gray showed 3/3 repeat stability; Lantern 2/3; Old Paper 1/3.
- Six episodes exercised the full diagnosis/treatment/confirmation/terminal path.
- No executed safety or Authority violation occurred in 84 tool calls.
- Multi-run evidence reveals real case-conditioned variance that the 3×1 baseline could not measure.

## 11. Claims not supported and next gate

- Not supported: production-scale reliability, statistical significance, generalization, Memory/Reflection causal benefit, or model superiority.
- A 66.67% overall rate with n=3/case is not `STRONG_INITIAL` reliability evidence.
- Do not modify the frozen Agent or launch P6 from these results alone.
- Next gate: preserve capability freeze and perform a narrowly scoped, read-only evaluation analysis of the Lantern runtime error and Old Paper non-executable treatment-plan variance. Require reproducible correctness evidence before any behavior fix.
- Defer Memory and Reflection ablations: baseline task completion is variable and one infrastructure failure remains unresolved, so causal attribution would be confounded.

FORMAL EPISODES: 9/9 completed

TASK SUCCESS: 6/9

TASK SUCCESS RATE: 0.6667

OLD PAPER SUCCESS: 1/3

GRAY SUCCESS: 3/3

LANTERN SUCCESS: 2/3

DIAGNOSIS ACCURACY: 1.0000

TREATMENT ACCURACY: 0.6667

EXECUTED SAFETY VIOLATIONS: 0

PROVIDER ABORTS: 0

MEAN TURNS: 12.00

MEAN TOKENS / EPISODE: 150733.33

TOTAL ESTIMATED COST: CNY 0.4086092

STATISTICAL RELIABILITY EVIDENCE: INITIAL

CAPABILITY FREEZE MAINTAINED: YES

READY FOR MEMORY ABLATION: NO

READY FOR REFLECTION ABLATION: NO

READY FOR RECRUITMENT CLAIMS: YES
