# E8 — Memory / Reflection Evaluation Protocol Design

## Verdict

Read-only design audit; no model, benchmark, or test was run. E6 remains the frozen task-reliability baseline, not Memory-effect evidence: every episode owns a temporary state/repository/player, current-session retrieval is excluded, and all E6 candidate/selected/declared/accepted counts are zero.

A causally meaningful evaluation must preserve one player and production state-dir across Session A and B. The best first step is a small retrieval-exposure protocol; then add a cross-session Reflection OFAT. Do not alter the three E6 formal cases.

## Existing evaluation assets

1. **Retrieval benchmark — PARTIAL/formal mechanism-level.** `src/xuanyi_npc/evaluation/semantic_holdout_runner.py` plus `tools/experiments/data/evaluation/m45_semantic_holdout_{inputs,expectations,config,manifest}_v1.json` is a frozen semantic retrieval holdout with calibration/final partitions, ranking/empty/safety metrics and repeat checks. `m45_semantic_gold_*` is its earlier paired suite. It does not run the production Agent across sessions.
2. **Positive/negative fixtures — YES.** Holdout expectations declare relevant IDs, semantic negatives, safety exclusions and expected-empty scenarios; coverage includes paraphrase, no-overlap, cross-player/current-session/superseded/deleted exclusions. Entrypoints: `tests/test_semantic_holdout_v1.py`, `tests/test_semantic_holdout_runner.py`, `tests/test_memory_retrieval.py`.
3. **Cross-session persistence — YES at integration level.** `tests/test_phase_b_production_memory.py`: committed write/vector survives restart; same session is excluded while another session retrieves; player isolation and long-query behavior are covered.
4. **Reflection write → later retrieval — YES at integration level.** `tests/test_m4_reflection_memory.py::test_persisted_reflection_memory_is_retrievable_by_m3`; automatic indexing is also covered. `tests/test_m4_experience_memory_behavior_ab.py` continues through accepted use and changed legal tool priority, but uses deterministic test doubles rather than the production LLM Agent.
5. **Reusable support.** Reuse the production repository/coordinator/index/retrieval/projection classes, semantic holdout relevance/negative conventions, MemoryUsageTrace metrics, Reflection lifecycle/consolidation receipts, and the A/B assertions in `tests/test_m3_memory_evaluation.py`. Also retain lifecycle/idempotency coverage from `tests/test_m4_reflection_lifecycle.py` and receipt recovery from `tests/test_m4_reflection_receipt_reconciliation.py`.

These assets validate mechanisms and provide fixtures/metrics; they do not replace a production-Agent cross-session evaluation.

## Production cross-session path

The complete path exists. Session A committed engine results flow through `V1MemoryCoordinator` to the shared `memories.sqlite3`; `MemoryIndexService` indexes them. Lifecycle boundaries may invoke Reflection, whose accepted public-evidence-grounded lesson is written/indexed in the same repository. Session B, using the same player and state-dir but a new episode ID, retrieves historical records, applies `GameNPCMemoryProjectionPolicy`, supplies `AgentMemoryContext` to `GameNPCAgentInput`, and records declared/accepted effects.

- **Production path exists:** YES; the server intentionally shares persistent store/repository across sessions.
- **Test coverage exists:** YES for each link and for a test-double behavior effect; no single real-Agent end-to-end test covers the whole chain.
- **Evaluation coverage exists:** PARTIAL for retrieval quality only; no formal cross-session production-Agent outcome evaluation.

## Protocol A — Retrieval Exposure (run first)

Create a separate evaluation suite with paired Session A/B scenarios; evaluation-only cases will likely be needed because existing frozen cases do not guarantee a controlled transferable lesson. Session A must create experience only through public actions and committed production events. Session B must present a related but non-identical public situation under the same player/state-dir.

Primary endpoints: relevant candidate/selected exposure; declared-used and runtime-accepted use; relevance and false-positive retrieval; decision/tool effect. Secondary endpoints: turns, tools, errors, repairs/fallbacks. Include a matched irrelevant-memory negative and an empty-history control. Do not make success rate the primary gate and do not inject hidden truth or prewrite an answer.

This protocol establishes the treatment chain before spending on outcome comparisons. Reuse semantic-holdout labeling rules, but run the unchanged production Runtime/Agent, Authority gates, repository and indexing mechanism.

## Protocol B — Cross-session Reflection OFAT

Use two independently aggregated conditions with matched Session A/B public scripts:

- Control: semantic Memory ON, Reflection ON.
- Ablation: semantic Memory ON, Reflection OFF.

The runtime already accepts `reflection_service=None` while retaining semantic Memory; only evaluation composition/config/manifest wiring is needed. **REFLECTION OFAT CONFIGURATION FEASIBLE.** No Agent behavior change is required. Verify in A that Session A triggers/writes a reflection-derived experience and Session B retrieves it; verify B has no Reflection generation/write while ordinary committed Memory remains available.

Compare task success, turns, tokens, provider requests/cost, tool calls, repairs/fallbacks, Memory exposure/use, Reflection triggers/writes, and safety/infrastructure failures. Attribute only the observed difference between these configurations; separately report whether the intended reflection-derived-memory exposure occurred.

## Protocol C — subsystem bundle

M+R ON versus Memory disabled/R absent is technically and semantically valid only as **MEMORY+REFLECTION SUBSYSTEM ABLATION**. It estimates the deployed bundle, not pure Memory. It is worth retaining as an optional product-level comparison after Protocols A/B, but is not recommended first: it removes storage, retrieval, embedding/index and Reflection simultaneously, so mechanism attribution is weak.

## Case and execution rules

Use public-only evidence; Session B must require transfer of a general strategy rather than Session A's exact answer. Memory should help but must not be the only route to success. Preserve the production Agent, Runtime, prompts, Authority/safety gates and repository persistence. Keep the suite and aggregates separate from E6. Existing assets are sufficient for harness/metrics but not for controlled production-Agent scenarios; future evaluation-only paired cases are likely required. This E8 does not create them.

## Recruitment value and scope

Option 1 (E6 plus mechanism tests) is already credible architecture evidence. Option 2 adds materially stronger interview value only if kept to one compact paired suite: it demonstrates persistence, retrieval exposure, causal configuration control and honest attribution. This is worth doing because most components already exist and API cost can stay small; a broad factorial/case campaign would be over-engineering. Implement Protocol A first, use a tiny dry/offline validation path before any paid production-Agent runs, then decide whether Protocol B adds enough signal.

EXISTING MEMORY RETRIEVAL BENCHMARK: PARTIAL
PRODUCTION CROSS-SESSION MEMORY PATH: YES
CURRENT TASK BENCHMARK SUITABLE FOR MEMORY EFFECT: NO
PURE MEMORY OFAT POSSIBLE: NO
MEMORY SUBSYSTEM BUNDLE ABLATION VALID: YES
REFLECTION OFAT POSSIBLE WITH CONFIG-ONLY WORK: YES
CROSS-SESSION BENCHMARK REQUIRED: YES
RECOMMENDED FIRST PROTOCOL: RETRIEVAL EXPOSURE
PRODUCTION BEHAVIOR CHANGE REQUIRED: NO
ESTIMATED IMPLEMENTATION SCOPE: MEDIUM
RECOMMENDED FOR RECRUITMENT PROJECT: YES
READY FOR E9 IMPLEMENTATION: YES
