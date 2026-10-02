# V2.1 C/M recovery freeze v3

Experiment: `v2_1_slim_cm_recovery_20260920_03`

Frozen plan SHA-256: `3E711AC286AACFF25EFA2283588EB4D61755E31DD5A7CEED4402E77B5AE799E9`

This recovery batch contains only the complete new C and M pairs: C 24 and M 12, 36 target episodes total. G is excluded and the 18 completed/attempted G episodes from `v2_1_slim_first_round_20260920_02` remain independent. The old unpaired M request is excluded.

## Frozen changes from v2

- C now uses a validated evaluation campaign file whose references are limited to the four C fixtures. Campaign reference validation remains enabled.
- MV01/MV06 are accepted consistently by scenario and artifact contracts and are loaded from the frozen V2.1 catalog.
- The frozen schedule is the sole execution sequence for both pools. The new plan preserves the C/M subsequence, pairing, conditions, and three repeats from v2.
- Every completed provider response is fsync-appended to a request ledger before control returns to the agent. Ledger reconciliation uses only request-level cost and never reconstructs missing rows from aggregate spend.
- Fixture, contract, permission, trace, usage, request-evidence, and artifact-write failures stop the affected pool and produce an execution status with the remaining entries marked unstarted. Ordinary model outcomes such as `max_turns_exceeded` continue.
- The offline formal-entry preflight ran all C24 and M12 entries with a fixture-aware substitute. It covers production clinic setup, A0/A1 branches, M0/M1 memory paths, confirmation and controlled commits, artifact writing, reading, grading, and regrading. It proves execution-chain readiness only; it is not model-capability evidence.

## Scope and budget

- C: 24 episodes; expected 3.70 CNY; hard cap 6.00 CNY.
- M: 12 episodes; expected 2.50 CNY; hard cap 4.00 CNY.
- Total expected 6.20 CNY; hard cap 10.00 CNY. Pools are non-transferable.

Paid execution remains `FROZEN_AWAITING_PAID_AUTHORIZATION`. No provider call was made while preparing this package.
