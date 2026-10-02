# E9 — Cross-Session Memory Retrieval Exposure Implementation

## Result

Implemented the independent evaluation-only `cross_session_memory_exposure_v1` suite. No DeepSeek/provider call or paid evaluation was made. Production Agent prompts, Runtime behavior, Goal/Plan/Decision semantics, Authority, CaseEngine, Memory/Reflection algorithms, embedding model, E6 runner, and the three frozen case files were not changed.

The harness lives in `src/xuanyi_npc/evaluation/cross_session_memory_exposure.py`; its frozen evaluation manifest is `tools/experiments/data/evaluation/cross_session_memory_exposure_v1.json`. Tests are in `tests/test_cross_session_memory_exposure.py`.

## Composition and persistence

Each scenario creates one evaluation state-dir, one `JsonStateStore`, one `memories.sqlite3`, one repository/index/retrieval pipeline, and one player. Session A and B use different episode IDs while retaining that player and repository. Session A uses a public investigation through `ClinicService`/CaseEngine; its committed result is projected by `V1MemoryCoordinator` and indexed by `MemoryIndexService`. Session B runs the existing offline deterministic Agent through `CooperativeRuntime`, production semantic retrieval (`top_k=8`, threshold `0.35`), `GameNPCMemoryProjectionPolicy`, and `GameNPCAgentInput.memory_context`.

The evaluation wrapper only records the Agent input and delegates decisions to the existing `DeterministicCooperativeNPC`; it adds no production fake or decision semantics. `DeterministicFakeEmbedding` is injected only by offline tests. The harness imports the production scorer/projection classes rather than copying them.

## Scenario family

- `positive_transfer`: Session A records a public observation from Old Paper; Session B is a non-identical Gray Hearth situation. The expected historical ID is written/indexed, retrieved as a candidate, selected/projected, and present in Agent input. The fixture represents transferring the strategy of separating ordinary explanations from stable external evidence—not an exact diagnosis.
- `irrelevant_negative`: Session A records a real public lantern observation; Session B uses the same target structure as positive. Exposure is explicitly counted as a false positive, while the offline Agent declares/accepts no use.
- `empty_history`: a fresh player/repository starts at Session B; candidate, selected, declared, and accepted counts are all zero.

Scenarios are manifest records marked `evaluation_only=true`; they are not production case definitions, are absent from the production catalog, and are not referenced by `agent_task_benchmark_v1`. Frozen formal cases are only consumed unchanged as public event sources.

## Artifacts and endpoints

`run_suite` writes a separate root at `evaluation_results/cross_session_memory_exposure_v1/`, with a resolved `manifest.json` and `scenarios/<scenario_id>/artifact.json`. Tests use temporary output roots; no formal result was produced in E9.

Artifacts contain sanitized player identity; A/B episode IDs; expected/candidate/selected/declared/accepted IDs and counts; relevant/irrelevant retrieval, false-positive and expected-empty results; Agent-input exposure; same-repository, current-session leakage and player-isolation checks; Authority/infrastructure/provider status. They exclude hidden truth, raw prompts, chain-of-thought, credentials, and provider secrets.

Retrieval exposure is not labeled behavioral benefit. Declared/accepted use remains zero with the offline Agent and is reserved as stronger evidence for a later real-Agent pilot.

## Verification

Targeted command covered the E9 suite plus production Memory persistence, Reflection-derived retrieval, and frozen task benchmark contracts: 45 passed. Full `python -m pytest -q` completed at 100%. Tests verify write/index, A→B persistence, distinct episodes, current-session exclusion, player isolation, positive selection, negative non-acceptance, empty history, one repository per A/B pair, stable canonical manifest hash, production class reuse, E6 identity, and catalog separation.

A smallest paid pilot would execute three scenario conditions: two A/B pairs plus the empty B control, totaling five sessions. Only the three Session B episodes need model-facing exposure if Session A remains a scripted public-action setup. Run it only under a separately frozen paid-pilot gate.

E9 IMPLEMENTATION: PASS
PRODUCTION BEHAVIOR CHANGED: NO
CROSS_SESSION HARNESS: PASS
POSITIVE TRANSFER FIXTURE: PASS
IRRELEVANT NEGATIVE FIXTURE: PASS
EMPTY HISTORY CONTROL: PASS
SAME PLAYER PERSISTENCE: PASS
CURRENT_SESSION EXCLUSION: PASS
PLAYER ISOLATION: PASS
TARGETED TEST: PASS
FULL TEST: PASS
REAL MODEL RUN PERFORMED: NO
READY FOR PAID RETRIEVAL EXPOSURE PILOT: YES
ESTIMATED PAID PILOT EPISODES: 5 sessions total; 3 model-facing Session B episodes
NEXT GATE: E10 PILOT
