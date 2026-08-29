# Task Benchmark and Results

## Protocol

The current reliability baseline is E6: three frozen cases, three independent repeats per case, a public-state-conditional player script, a fixed success rule, a 16-turn limit, frozen runtime/model configuration, and per-run plus aggregate artifacts. Each episode uses isolated state.

Benchmark ground truth exists in CaseEngine resources, but model-visible observations are projected through the public-state boundary; hidden truth is not exposed to the Agent input. Production construction occurs in `application/cooperative_runtime.py`, public action contracts in `application/action_contract.py`, and isolation is covered by projection/repository tests that inject hidden sentinels.

## E6 current baseline

| Metric | Result |
|---|---:|
| Cases × repeats | 3 × 3 = 9 episodes |
| Task success | 8/9 (88.89%) |
| Diagnosis accuracy | 9/9 (100%) |
| Treatment accuracy | 8/9 (88.89%) |
| Executed safety violations | 0 |
| Infrastructure failures | 0 |
| Provider aborts | 0 |
| Repairs / fallbacks | 14 / 2 |
| Mean turns | 11.89 |
| Mean tokens / episode | 155,952.67 (~155,953) |
| Total estimated cost | CNY 0.36987276 (~CNY 0.37) |

The one unsuccessful episode reached the turn limit after a correct diagnosis but did not execute treatment. It was model-path variance, not an infrastructure failure or Authority violation.

## Historical comparison

| Metric | E3 pre-E5 | E6 current | Observed change |
|---|---:|---:|---:|
| Task success | 6/9 (66.67%) | 8/9 (88.89%) | +22.22 pp |
| Diagnosis accuracy | 100% | 100% | 0 pp |
| Treatment accuracy | 66.67% | 88.89% | +22.22 pp |
| Infrastructure failures | 1/9 | 0/9 | −1 observed |

These are independent small samples with stochastic model outputs. The +22.22 percentage-point difference is descriptive only: it is neither statistical significance nor proof that E5 causally produced the change.

## Evidence boundary

The benchmark supports measured claims about end-to-end completion, diagnosis/treatment correctness, executed safety, recovery telemetry, and cost under one frozen protocol. It does not establish universal safety, unseen-case generalization, production-scale reliability, or causal feature effects.

