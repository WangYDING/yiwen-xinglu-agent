# E6 — Post-E5 Frozen 3×3 Reliability Rebaseline

## 1. Verdict

The post-E5 frozen evaluation completed all nine scheduled episodes exactly once and achieved 8/9 terminal task success (88.89%). Diagnosis accuracy was 100%, treatment accuracy was 88.89%, with zero executed safety violations, zero provider aborts, and zero infrastructure failures.

Under the predefined gate this is `STRONG_INITIAL` reliability evidence. It remains a small descriptive sample, not proof of production-scale reliability, significance, generalization, or causal improvement from E5.

## 2. Frozen identity and preflight

- Artifact root: `evaluation_results/agent_task_benchmark_post_e5_recruitment_3x3/agent_task_benchmark_v1/`.
- Benchmark: `agent_task_benchmark_v1`; 3 frozen cases × 3 repeats = 9 new episodes.
- Historical E3 artifacts remain intact and separate as the pre-E5 6/9 baseline.
- Cases: `old_paper_umbrella`, `gray_hearth_inn`, `lantern_alley_conflicting_testimony`.
- Max turns: 16.
- Provider/model: DeepSeek / `deepseek-v4-flash`; temperature 0.0; max output tokens 2048.
- Memory: semantic; Reflection: enabled.
- Player script: `public_state_conditional_cooperation_v1`.
- Confirmation: `approve_current_owned_revision_matched_diagnosis_or_treatment_v1`.
- Success rule: `completed_correct_diagnosis_resolved_treatment_v1`.
- Resolved configuration hash: `c33fe891cb9ed533104942c88b7c2f433babfc592d2261477f26e5aea28aede7`.
- E5 `game_npc.py` runtime hash: `fc6f03d8d94da9c2069c41abdb0a5e0809bd6047ca1e27495172215dc9149693`.
- Recorded commit: `dc31d3f186f2cc9d68ce11a553784f598f76a881`; `git_dirty=true`, so resolved runtime hashes are the operative identity.
- Preflight compared E3 runtime hashes: only the E5-explained `game_npc.py` change existed; the other seven runtime hashes matched.
- No production runtime file had a timestamp newer than the accepted E5 report.
- Frozen manifest matched; credential/model were available; output root did not exist.
- Existing E5 regression evidence was reused: 526 passed; pytest was not rerun.
- Hard budget: CNY 1.00; actual estimated cost: CNY 0.36987276.

## 3. Nine-episode raw summary

| Case | Repeat | Success | Turns | Diagnosis | Treatment | Repairs | Fallbacks | Failure / terminal |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| Gray | 1 | YES | 11 | correct | correct | 2 | 0 | completed |
| Gray | 2 | YES | 11 | correct | correct | 1 | 0 | completed |
| Gray | 3 | YES | 14 | correct | correct | 2 | 2 | completed |
| Lantern | 1 | YES | 11 | correct | correct | 1 | 0 | completed |
| Lantern | 2 | YES | 11 | correct | correct | 1 | 0 | completed |
| Lantern | 3 | YES | 10 | correct | correct | 1 | 0 | completed |
| Old Paper | 1 | YES | 11 | correct | correct | 1 | 0 | completed |
| Old Paper | 2 | YES | 12 | correct | correct | 2 | 0 | completed |
| Old Paper | 3 | NO | 16 | correct | not executed | 3 | 0 | `max_turns_exceeded`; active |

All raw artifacts are preserved under `runs/<case_id>/repeat_01.json` through `repeat_03.json`. No episode was rerun, removed, overwritten, or selected after observing its result.

## 4. Capability and reliability

- Formal/provider-completed episodes: 9/9.
- Task success: 8/9; empirical success rate: 0.8889.
- Macro case success rate: 0.8889.
- Terminal completion: 8/9; terminal completion rate: 0.8889.
- Diagnosis accuracy: 9/9 = 1.0000.
- Treatment accuracy: 8/9 = 0.8889.
- Failure distribution: `max_turns_exceeded=1`.
- Max-turn failures: 1; runtime/infrastructure failures: 0.
- Aggregate goal completion rate: 1.0000 under the existing metric; raw goal completion count: 62.

## 5. Per-case metrics

### gray_hearth_inn

- Success 3/3; diagnosis 3/3; treatment 3/3; no failures.
- Turns: 11, 11, 14; mean 12.00; median 11; min/max 11/14.
- Tokens: 151,503; 141,187; 181,828; mean 158,173.
- Repeat 3 used two safe fallbacks and still completed.

### lantern_alley_conflicting_testimony

- Success 3/3; diagnosis 3/3; treatment 3/3; no failures.
- Turns: 11, 11, 10; mean 10.67; median 11; min/max 10/11.
- Tokens: 147,066; 153,944; 132,206; mean 144,405.
- The E3 `runtime_error / GoalPlanPolicyError` was not observed in E6. This is descriptive, not statistical proof that recurrence probability is zero.

### old_paper_umbrella

- Success 2/3; diagnosis 3/3; treatment 2/3.
- Turns: 11, 12, 16; mean 13.00; median 12; min/max 11/16.
- Tokens: 145,866; 155,955; 194,019; mean 165,280.
- Repeat 3 failed with `max_turns_exceeded`; no infrastructure, safety, alignment, or provider error.
- After correct diagnosis, it selected a non-tool `discuss_treatment` Plan and RESPOND through T16. This matches the previously accepted case-conditioned model variance; E5 intentionally does not alter that path.

## 6. Efficiency

- Turns: total 107; mean 11.89; median 11; min/max 10/16; sample std 1.90.
- Input tokens: total 1,240,365; mean 137,818; median 133,618; min/max 114,869/174,491; sample std 18,915.
- Output tokens: total 163,209; mean 18,134; median 17,885; min/max 16,586/19,528; sample std 974.
- Total tokens: 1,403,574; mean 155,952.67; median 151,503; min/max 132,206/194,019; sample std 19,701.
- Estimated cost: total CNY 0.36987276; mean CNY 0.04109697/episode; median CNY 0.0359824; min/max CNY 0.03144756/0.05944916; sample std CNY 0.01066409.
- Duration: total 922.93 s; mean 102.55 s; median 100.23 s; min/max 95.00/115.30 s; sample std 6.85 s.
- Provider requests: 184 total; mean 20.44/episode.

## 7. Agent behavior and safety

- Repairs: 14 total; 14/107 turns = 0.1308.
- Fallbacks: 2 total; 2/107 turns = 0.0187.
- Tool calls: 88; confirmations: 17.
- Rejected actions: 0; Plan/action alignment rejections: 0.
- Executed Authority/safety violations: 0; existing safety violation rate: 0.0.
- Provider aborts: 0; provider failure rate: 0.0.
- Infrastructure failures: 0; infrastructure failure rate: 0.0.

Gray repeat 3 is direct production-path evidence for E5's safe fallback behavior. At T11 an executable treatment step received invalid initial and repair proposals; fallback produced no tool, changed Goal/Plan lifecycle, returned safely, and the episode later completed. This establishes observed compatibility, not a causal success-rate claim.

## 8. Descriptive E3 versus E6 comparison

| Metric | E3 pre-E5 | E6 post-E5 |
|---|---:|---:|
| Overall success | 6/9 (66.67%) | 8/9 (88.89%) |
| Gray | 3/3 | 3/3 |
| Lantern | 2/3 | 3/3 |
| Old Paper | 1/3 | 2/3 |
| Infrastructure failures | 1/9 | 0/9 |
| Fallbacks / turns | 1/108 (0.93%) | 2/107 (1.87%) |
| Repairs / turns | 12/108 (11.11%) | 14/107 (13.08%) |
| Mean turns | 12.00 | 11.89 |
| Mean tokens / episode | 150,733 | 155,953 |
| Total tokens | 1,356,600 | 1,403,574 |
| Mean estimated cost | CNY 0.045401 | CNY 0.041097 |
| Total estimated cost | CNY 0.4086092 | CNY 0.36987276 |

These are independent small samples with stochastic model outputs. The table does not prove E5 improved task success, efficiency, cost, or Lantern reliability. It only records that the prior infrastructure error was not observed and the new baseline outcome was 8/9.

## 9. Evaluation gate

- Reliability label: `STRONG_INITIAL` under the predefined ≥8/9 gate.
- No unresolved correctness, infrastructure, provider, Authority, alignment, or safety blocker is present in E6 artifacts.
- The sole failure is the already-characterized Old Paper model-variance path; do not resume frozen-case optimization.
- Capability freeze remains in force.
- Multi-run evidence now exists, success is not at a floor, and no correctness/infrastructure blocker remains; Memory and Reflection ablation planning may begin as a separate frozen evaluation design.
- Recruitment claims must remain bounded to the measured 8/9 frozen result, 100% diagnosis accuracy, 0 safety violations, and demonstrated architecture—not generalized production reliability.

FORMAL EPISODES: 9/9
TASK SUCCESS: 8/9
TASK SUCCESS RATE: 0.8889
GRAY SUCCESS: 3/3
LANTERN SUCCESS: 3/3
OLD PAPER SUCCESS: 2/3
DIAGNOSIS ACCURACY: 1.0000
TREATMENT ACCURACY: 0.8889
EXECUTED SAFETY VIOLATIONS: 0
INFRASTRUCTURE FAILURES: 0
PROVIDER ABORTS: 0
MEAN TURNS: 11.89
MEAN TOKENS / EPISODE: 155952.67
TOTAL ESTIMATED COST: CNY 0.36987276
E3 PRE-E5 SUCCESS: 6/9
POST-E5 RELIABILITY EVIDENCE: STRONG_INITIAL
CAPABILITY FREEZE MAINTAINED: YES
UNRESOLVED CORRECTNESS BLOCKER: NO
READY FOR MEMORY ABLATION: YES
READY FOR REFLECTION ABLATION: YES
READY FOR RECRUITMENT CLAIMS: YES
