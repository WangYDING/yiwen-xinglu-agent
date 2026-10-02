# E11 — Cross-Session Reflection OFAT Harness Implementation

## Result

Implemented an evaluation-only matched Reflection OFAT without changing production behavior or calling DeepSeek.

The two frozen conditions are:

- CONTROL: Memory=`semantic`, Reflection=`enabled`.
- ABLATION: Memory=`semantic`, Reflection=`disabled`.

Reflection OFF is expressed solely by omitting the existing `ReflectionLifecycleService` composition. Repository, ordinary committed writes, embedding/index, semantic retrieval at the production 0.35 threshold, projection, `AgentMemoryContext`, usage tracking, Runtime, Authority and deterministic Agent remain identical and enabled.

## Added assets

- Harness/schema: `src/xuanyi_npc/evaluation/reflection_ofat.py`.
- CONTROL config: `tools/experiments/data/evaluation/cross_session_reflection_ofat_control_v1.json`.
- ABLATION config: `tools/experiments/data/evaluation/cross_session_reflection_ofat_ablation_v1.json`.
- Validation: `tests/test_reflection_ofat.py`.

The E9 harness gained optional evaluation callbacks for driving and observing Session A. Default E9/E10 behavior is unchanged; their tests passed unchanged.

## Frozen condition identity

Both configs share suite/scenario, public script, Memory mode, retrieval threshold, embedding path, model placeholder, Authority and case inputs. Only `condition` and `reflection_mode` differ.

- CONTROL hash: `ef6ba3a0fc0f27804bb2e8a9926ad2ca647a524a2b4b38e3324fdea7a0fc0975`.
- ABLATION hash: `7ea06d7a4fab1aa8c286beb240d534af0ffd44251e7bf774c61263cfe135f801`.

Each artifact records its condition, Reflection/Memory modes, manifest/configuration identity and metrics. Future runs must aggregate CONTROL and ABLATION independently; episodes from the two identities must not be mixed.

## Matched Session A/B protocol

Session A uses the unchanged Old Paper case and public actions through `ClinicService`/CaseEngine. It performs the same six investigations, diagnosis and treatment in both conditions, producing a real `EPISODE_COMPLETED` lifecycle boundary.

All eight ordinary Memory records are committed and indexed through `V1MemoryCoordinator`/`MemoryIndexService`. Their semantic IDs are identical across ON/OFF.

Session B uses the same player, state-dir and repository, a new episode ID, and the unchanged Gray Hearth public situation. It executes the normal E9 semantic retrieval → projection → `AgentMemoryContext` path.

No evaluation-only case is registered in the production catalog, and no formal frozen case is modified.

## CONTROL evidence

- Completed lifecycle trigger count: 1.
- Deterministic scripted Reflection generation count: 1.
- Valid Reflection-derived write count: 1.
- Receipt persistence: verified by a new lifecycle service receiving an idempotent replay without invoking its adapter.
- Derived embedding/index count: 1.
- Session B retrieved the derived ID as a candidate and retained it in selected IDs.
- Ordinary and Reflection-derived candidate IDs are reported separately.

This proves `trigger → generation → receipt/write → index → later retrieval` under deterministic evaluation composition. It does not prove Agent use or benefit.

## ABLATION evidence

- The identical completed lifecycle boundary exists: trigger count 1.
- Reflection service is absent: generation 0, derived writes 0, receipt absent and derived exposure 0.
- Ordinary writes remain 8 and indexed.
- Session B retrieves and selects ordinary historical Memory.
- Repository, player and current-session leakage checks remain clean.

The observed difference is therefore isolated to Reflection composition; Memory is not disabled.

## Metrics and artifacts

The artifact schema separates trigger/generation/write/receipt/index counts, ordinary/derived writes, ordinary/derived candidate and selected IDs, declared/accepted IDs, duration, future provider/token/cost placeholders, Authority/infrastructure failures, and repository/player/session leakage.

E11 did not persist formal result artifacts: deterministic validation ran only in temporary directories. A future E12 runner can write separate immutable CONTROL and ABLATION roots using this schema.

## Verification and future cost

Targeted E11/E9/E10/Reflection/E6 regression: 55 passed. Full `python -m pytest -q`: 100% passed.

All E6 production runtime hashes remain unchanged. E10 paid artifacts and fixture semantics were not modified or rerun.

E12 requires at most two real Session-B Agent runs, one per condition. CONTROL Session A additionally needs one real Reflection generation call; ABLATION Session A needs none. Expected total is three provider requests. Using E10 request costs as a rough guide, budget approximately CNY 0.02; freeze a conservative hard cap before running.

No outcome, reasoning, turn-efficiency or success improvement is claimed. E11 establishes only: `REFLECTION OFAT CONDITION IS EXPERIMENTALLY VALID`.

E11 IMPLEMENTATION: PASS
PRODUCTION BEHAVIOR CHANGED: NO
REFLECTION OFF CONFIG AVAILABLE: YES
MEMORY REMAINS ON WHEN REFLECTION OFF: YES
CONTROL REFLECTION WRITE: PASS
CONTROL REFLECTION LATER RETRIEVAL: PASS
ABLATION REFLECTION GENERATION ZERO: PASS
ABLATION ORDINARY MEMORY RETAINED: PASS
CONDITION ISOLATION: PASS
E10 REGRESSION: PASS
TARGETED TEST: PASS
FULL TEST: PASS
REAL MODEL RUN PERFORMED: NO
READY FOR E12 REFLECTION OFAT PILOT: YES
ESTIMATED E12 PAID RUNS: 2 Session-B Agent runs; 3 provider requests including CONTROL Reflection generation
ESTIMATED E12 COST: approximately CNY 0.02
NEXT GATE: E12
