# E2 — Recruitment Evaluation Freeze & Low-Cost Statistical Evaluation Plan

## E2 verdict

当前 P5 版本应冻结为 recruitment evaluation capability baseline。最终 frozen 3×1 证明了三个正式病例的 production-equivalent 完整任务链路，但样本量只有三个 episode，因此结论是 `TASK COMPLETION PATH PROVEN`，不是 `STATISTICAL RELIABILITY PROVEN`。

本轮未调用模型、未运行 benchmark/pytest，也未修改 production behavior、测试、benchmark、case 或 success rule。

## 1. Baseline identity

- Evidence root: `evaluation_results/agent_task_benchmark_post_p5_final/agent_task_benchmark_v1/`.
- Benchmark: `agent_task_benchmark_v1`; 3 cases × repeat 1; max turns 16.
- Cases: `old_paper_umbrella`, `gray_hearth_inn`, `lantern_alley_conflicting_testimony`.
- Model: `deepseek-v4-flash`; temperature 0.0; max output tokens 2048.
- Memory: semantic; Reflection: enabled.
- Player/confirmation: `public_state_conditional_cooperation_v1` and `approve_current_owned_revision_matched_diagnosis_or_treatment_v1`.
- Success rule: `completed_correct_diagnosis_resolved_treatment_v1`.
- Configuration hash: `9d3f3b3f2442e0ba8a24e2c539b130bf2f7e127d22d186bd3e2b185d11f0af10`.
- Manifest hash: `7b36ff8a5e226ec619cc6d639c8d7336dded642f631156eb81fb6fed5d648d35`.
- Repository commit recorded by artifact: `dc31d3f186f2cc9d68ce11a553784f598f76a881`; artifact also records `git_dirty=true`.
- Baseline outcome: success 3/3; diagnosis accuracy 1.0; treatment accuracy 1.0; provider aborts 0; executed safety violations 0.
- Regression evidence from P5 report: full pytest 521 passed.

The freeze identity is the resolved manifest plus its runtime file hashes, not the commit alone, because the captured worktree was dirty.

## 2. Metrics currently supported

### Task capability

| Metric | Support | Source |
|---|---|---|
| Task success rate/count | YES | run `success`; aggregate `success_count/rate` |
| Per-case and macro success rate | YES | aggregate `per_case`, `macro_case_success_rate` |
| Diagnosis accuracy | YES | run `diagnosis_correct`; aggregate accuracy |
| Treatment accuracy | YES | run `treatment_correct`; aggregate accuracy |
| Terminal completion rate | YES, derivable | run `terminal_completed` / episode count |
| Final terminal status/failure distribution | YES | run `terminal_status/failure_reason`; aggregate distribution |

### Efficiency

| Metric | Support | Source |
|---|---|---|
| Turns per episode | YES | `turn_count`; aggregate success mean/median and per-case min/max |
| Tool calls | YES | `tool_call_count` |
| Confirmations | YES | `confirmation_count` |
| Provider requests | YES | `provider_request_count` |
| Input/output/total tokens | YES | run token fields; aggregate totals/means/medians |
| Estimated cost | YES when provider pricing is available | run `estimated_cost_cny`; aggregate total |
| Wall-clock duration | YES | `duration_ms` |

### Agent behavior

| Metric | Support | Qualification |
|---|---|---|
| Repair count/frequency | YES | run count; aggregate repairs per turn |
| Fallback count/frequency | YES | run count; aggregate fallbacks per turn |
| Rejected actions | YES | `rejected_action_count` |
| Alignment rejection count | YES | `action_outside_plan_failure_count`; per-turn reason codes |
| Tool/target mismatch breakdown | YES | per-turn `alignment_reason_code` and sanitized tool/target fields |
| Goal completion count/rate | YES | run count and aggregate rate |
| Plan changed turns | YES | per-turn `plan_changed` |
| Plan revision count | NOT CURRENTLY MEASURED | `plan_changed` conflates create/revise/advance/complete |
| Goal/Plan update-operation distribution | NOT CURRENTLY MEASURED in final run artifact |

### Memory and Reflection

| Metric | Support |
|---|---|
| Memory candidate/selected/declared/accepted counts | YES, run and per-turn |
| Reflection trigger/write counts | YES, run and per-turn |
| Memory or Reflection causal benefit | NOT CURRENTLY MEASURED |

### Safety and infrastructure

| Metric | Support |
|---|---|
| Executed authority violations/count/rate | YES |
| Rejected action count and error code | YES |
| Provider abort/count/rate | YES; rate is derivable |
| Infrastructure error code/rate | YES; rate is derivable |
| Provider request IDs/system fingerprints | YES |
| Non-authority safety categories | NOT CURRENTLY MEASURED as separate aggregate classes |

## 3. Claims supported now

### PROVEN NOW

- The production-equivalent Agent completed all three frozen formal cases in this 3×1 run.
- Diagnosis proposal, confirmation, execution, and correctness paths ran successfully in all three episodes.
- Treatment proposal, pending confirmation, execution, and resolved terminal paths ran successfully in all three episodes.
- Goal/Plan and PlanStep↔Decision paths supported terminal completion for these observed runs.
- Authority and player confirmation were not bypassed in the recorded diagnosis/treatment executions.
- This run had zero executed authority/safety violations and zero provider aborts.
- The frozen 3×1 result is 3/3 and the P5 full regression suite is 521 passed.
- Therefore: `TASK COMPLETION PATH PROVEN`.

### NOT YET PROVEN

- Statistical reliability or a stable success probability.
- Variance across independent repeated runs, including per-case variance.
- Generalization beyond the three frozen cases.
- Robustness to alternative player behavior, case distributions, prompts, providers, or models.
- Memory improves task success, efficiency, or safety.
- Reflection improves task success, efficiency, or safety.
- Any model-to-model superiority.
- Statistical significance, confidence-bound precision, or production-scale reliability.

## 4. Lowest-cost statistical evaluation

Target the next formal stage at 3 cases × 3 independent runs = 9 episodes. Do not jump to 3×5. Keep all frozen runtime, model, Memory, Reflection, confirmation, max-turn, player-script, and success-rule parameters unchanged.

The existing final 3×1 cannot safely serve as repeat 1 inside the current formal 3×3 artifact set:

- `TaskBenchmarkRunner` creates an immutable new root and always executes repeat indexes `1..repeats`; it has no append/start-index mode.
- `repeats` participates in `configuration_hash`, and the resolved manifest participates in `manifest_hash`.
- The pure aggregator rejects run artifacts with different manifest hashes.

Therefore the statistically clean minimum is one fresh frozen `--repeats 3` run (9 new episodes). The existing 3×1 remains baseline provenance but is not pooled into the formal 3×3 estimate. Reusing it would require a separately frozen evaluation-only composition protocol; do not improvise that during execution.

For overall and per-case results report episode count, successes/rate, diagnosis/treatment accuracy, and provider/safety failures. For turns, total tokens, cost, repairs, and fallbacks report count, mean, median where useful, min/max, and sample standard deviation where defined. Also report raw episode rows. With n=3 per case, use descriptive statistics only—no claims of significance or tight reliability bounds.

Primary metrics: task success rate, per-case success rate, diagnosis accuracy, treatment accuracy, mean/median turns, mean tokens/episode, mean estimated cost/episode, repair/fallback frequency, executed safety violation rate, and provider failure rate.

Stop after the first formal 3×3 result. Preserve failures; do not rerun until success or alter frozen behavior. Any proposed fix must be driven by reproducible correctness/safety evidence, not frozen-case score chasing.

## 5. Ablation gate

Do not run Memory or Reflection ablations now. First establish the multi-run baseline and inspect whether there is measurable outcome/efficiency variance. The current 3×1 ceiling result cannot establish causal benefit and may conceal a ceiling effect. Any later ablation must use a separately frozen factorial design, unchanged cases/scripts, and sufficient budget; it must not reuse incompatible manifest hashes as one sample.

## 6. Recruitment capability freeze

- Stop behavior optimization targeted at these frozen cases: **YES**.
- Treat P0–P5 as capability stabilization history: **YES**.
- Permit subsequent work only for evaluation, regression protection, or fixes justified by reproducible correctness/safety evidence: **YES**.
- Do not change frozen production behavior merely to improve the 3-case score.
- Recruitment use is appropriate as a demonstrable engineering/evaluation artifact, with the explicit limitation that reliability and generalization remain unproven.

CORE E2E CAPABILITY PROVEN: YES
FINAL FROZEN 3x1: 3/3
CAPABILITY FREEZE RECOMMENDED: YES
STATISTICAL RELIABILITY PROVEN: NO
NEXT MINIMUM EVALUATION: fresh unchanged frozen 3 cases × 3 independent runs, descriptive statistics only

RECOMMENDED TOTAL EPISODES: 9 new formal episodes; existing 3 baseline episodes retained separately

MEMORY ABLATION READY: NO

REFLECTION ABLATION READY: NO

READY FOR RECRUITMENT PROJECT USE: YES
