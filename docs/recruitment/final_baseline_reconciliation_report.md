# Final Production Baseline Reconciliation

Internal baseline report. This document is not intended for future public publication.

## Scope and boundary

- Reconciled the frozen production baseline without changing Agent behavior, prompts, policy, Memory/Reflection behavior, benchmark cases, scripts, rules, or turn limits.
- No provider/model calls or paid evaluation were executed.
- No Git staging, commit, push, reset, or history rewrite was performed.

## Dependency reconciliation

- Removed the obsolete `real_agent_benchmark` chain and its two private diagnostic helpers/tests. It depended on the already-removed `m5_p4b_runner`; no production or current evaluation caller remained.
- Removed the obsolete `diagnose_m45_semantic_results` runner. Current semantic holdout evaluation is independent of the deleted `semantic_memory_diagnostics` module.
- Removed legacy exports from `xuanyi_npc.evaluation`; current Agent task, E9/E10, E11, and E12 evaluation modules remain importable.
- Updated two documentation references to identify the deleted M5 raw artifact as private archive evidence rather than an active repository file.
- Updated the repository-layout assertion from six to five intentional experiment runners.

## Coverage reconciliation

- Memory coordination now directly covers JSON commit followed by projection failure, pending receipt state, explicit reconciliation, idempotent replay, and exactly-one-row persistence.
- Model usage now directly covers cost/currency pairing, cache-token accounting, and JSON round-trip stability.
- Existing suites continue to cover production Memory retrieval/acceptance, Reflection generation/persistence, P2-P5/E5 behavior, semantic holdout, Agent task evaluation, and E9-E12 harnesses.

## Package and resource closure

- Source distribution and wheel built successfully from the current worktree.
- The wheel installed into a temporary verification environment without network dependency resolution.
- Core production and current evaluation modules imported successfully from the installed wheel.
- Installed console entry points are `xuanyi-clinic`, `xuanyi-mcp-stdio`, and `yiwen-xinglu`.
- Active clinic JSON/CSS/JS package resources loaded successfully.
- Static scan found no active imports of the removed legacy chains. Historical prose references and a negative source assertion are non-executable evidence.

## Verification

- Targeted reconciliation/regression suite: PASS.
- Full `pytest`: PASS, 535 passed, 0 failed, 0 skipped.
- Package build: PASS (sdist and wheel).
- Isolated wheel install/import/resource verification: PASS.
- E6 runtime integrity: all 8 manifest runtime hashes match current files.
- The large pre-existing worktree diff was preserved. Reconciliation changes are limited to legacy dependency removal, exports/docs/layout wiring, and focused regression coverage.

LEGACY REAL_AGENT_BENCHMARK CHAIN CLOSED: YES
LEGACY SEMANTIC DIAGNOSTIC CHAIN CLOSED: YES
MEMORY_COORDINATION COVERAGE SUFFICIENT: YES
MODEL_USAGE COVERAGE SUFFICIENT: YES
PYPROJECT RECONCILED: YES
ACTIVE RESOURCES CLOSED: YES
ACTIVE DANGLING IMPORTS: 0
TARGETED TESTS: PASS
FULL PYTEST: PASS
FULL PYTEST PASSED COUNT: 535
PACKAGE BUILD: PASS
ISOLATED WHEEL INSTALL: PASS
CURRENT ENTRY POINTS VALID: YES
E6 RUNTIME HASH INTEGRITY: PASS
PRODUCTION BEHAVIOR CHANGED: NO
UNEXPECTED DIFF REMAINING: NO
READY FOR FINAL BASELINE HUMAN REVIEW: YES
READY TO STAGE: NO
