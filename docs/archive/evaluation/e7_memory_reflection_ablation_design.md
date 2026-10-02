# E7 — Memory / Reflection Ablation Design Audit

## Verdict and scope

Read-only audit only; no provider/model call or evaluation was run. E6 is the sole reliability baseline: M=semantic, R=ON, 3 cases × 3 repeats, success 8/9, diagnosis 9/9, treatment 8/9, safety/infrastructure failures 0.

The present `agent_task_benchmark` cannot express an ablation: its manifest types require `memory_mode="semantic"` and `reflection_mode="enabled"`; its CLI accepts only `--memory-mode semantic`; its executor always constructs repository, embedding/index, retrieval, coordinator, and Reflection. Production exposes Memory `disabled`, but Reflection is then automatically absent. There is no independent production Reflection switch. Therefore neither requested OFAT cell is presently available without evaluation-configuration work.

## What `memory_mode=semantic` actually means

1. **Memory write:** ON. `V1MemoryCoordinator` projects committed engine results into the per-player SQLite repository; indexing follows commits.
2. **Semantic retrieval:** ON. Each cooperative turn calls the cosine retriever (`top_k=8`, threshold 0.35) through the production projection policy.
3. **Agent injection:** ON. The projected `AgentMemoryContext` is assigned to `GameNPCAgentInput.memory_context`.
4. **Cross-turn:** Repository state persists across turns, but retrieval excludes the current episode; consequently memories written by this episode do not feed later turns of the same episode.
5. **Cross-session/case:** Production state-dir can support it for the same player. The benchmark cannot: every case/repeat creates a fresh `TemporaryDirectory`, `JsonStateStore`, `memories.sqlite3`, repository, and player; nothing is shared across repeats or cases.
6. **Reflection-derived memory:** ON. Lifecycle reflections can consolidate accepted experience candidates into the same repository.
7. **Embedding/index:** ON. Local BGE-M3 is loaded; normal and reflection-derived writes are indexed (with pending-index reconciliation).
8. **Acceptance/use tracking:** ON. Per-turn traces record candidate, selected, model-declared-used, and runtime-accepted IDs/effects.

E6 artifacts report candidates/selected/declared/accepted as zero. Thus E6 demonstrates the enabled write/reflection pipeline, but supplies no observed Agent-visible retrieved-memory exposure. Any success comparison that calls this “retrieval benefit” would lack treatment contrast.

## Is Memory OFF a clean ablation?

Production formally accepts `memory_mode=disabled` (not `off`/`none`). It returns no retrieval service, coordinator, index service, or repository: storage, retrieval, embedding/index, and Agent-visible memory are all disabled. Runtime still emits an unavailable/rejected memory trace. This is the whole production memory subsystem, not retrieval-only.

However, production Reflection construction requires semantic Memory and returns no Reflection service when Memory is disabled. Therefore `disabled` changes M and R together, and the frozen benchmark cannot select it at all. **MEMORY ABLATION NOT CLEANLY AVAILABLE.**

## Reflection dependency and OFF semantics

Reflection triggers after deterministic lifecycle boundaries: episode completed, goal completed, plan abandoned, or a plan's third revision. It generates a structured proposal with the Game NPC adapter, builds public evidence, consolidates accepted candidates into the SQLite Memory repository, indexes them, and persists lifecycle receipts there. Generation, persistence, derived-memory writes, and later retrieval/use are distinct stages.

- **M OFF + R ON:** Not a valid production configuration. The builder returns R=None before generation; R cannot persist without repository/index. It is neither a “generated but unused” cell nor technically expressible by the benchmark.
- **M ON + R OFF:** Runtime classes can operate with `reflection_service=None`, and this meaning is clear (semantic write/retrieval remains; no reflection generation/persistence/writes). But there is no formal production CLI/config flag or benchmark condition that selects it. It is therefore not presently an available frozen evaluation cell.

Within isolated benchmark episodes, reflection-derived memories cannot be retrieved in a later session/case, and current-episode exclusion prevents within-episode use. Reflection can still affect efficiency through its generation provider requests/tokens/cost, but not later Agent behavior in the same benchmark episode.

## Design decision

- **Design A (OFAT):** desired lowest-cost design, but unavailable now: M OFF also turns R OFF, while independent R OFF has no formal config.
- **Design B (2×2):** invalid because M OFF/R ON has no product semantics or wiring; do not manufacture it.
- **Recommendation:** `NOT READY`. First add/approve evaluation configuration that maps only to already-existing runtime compositions (no new behavior): at minimum formal M ON/R OFF. A clean M-only OFAT additionally needs an already-supported M OFF/R ON product meaning; it does not exist, so do not claim one.

## Control, aggregation, sample and cost

E6 may serve as the M ON/R ON control only if the later conditions use exactly the same resolved runtime version/hashes, cases, script, success rule, turn limit, model/provider parameters, and differ only in the approved ablation config. A different condition manifest/configuration hash is expected. Aggregate every condition independently; never mix episodes from different manifests into one benchmark aggregate.

Once a valid cell exists, start at 3 cases × 3 repeats (9 new episodes), not 3×5. A valid two-cell OFAT would require 18 new episodes because E6 is reusable, roughly `2 × ¥0.3699 = ¥0.7398` at the E6 rate. Present runnable requirement is 0 because no ablation is authorized/configurable; this is not a zero-cost completed design.

## Metrics and inference boundary

Compare per-condition and per-case: task success, diagnosis accuracy, treatment accuracy; turns, tokens, cost, provider requests; repair and fallback frequency; memory candidates/selected/declared/accepted; reflection triggers/writes; authority violations and infrastructure/provider failures. Include exposure checks: a Memory-effect claim requires nonzero retrieval/use exposure, and a Reflection-effect claim must distinguish generation/writes from later retrieval/use.

Report small-sample results only as an **observed ablation difference**. Even 8/9 versus 6/9 does not establish statistical significance or a 22% causal improvement.

MEMORY OFF CONFIG EXISTS: NO
REFLECTION OFF CONFIG EXISTS: NO
MEMORY OFF + REFLECTION ON SEMANTICALLY VALID: NO
MEMORY ON + REFLECTION OFF SEMANTICALLY VALID: YES
E6 CAN SERVE AS CONTROL: YES
RECOMMENDED DESIGN: NOT READY
FIRST ABLATION TO RUN: NONE
NEW EPISODES REQUIRED: 0 now; 18 for a future valid two-cell OFAT
ESTIMATED ADDITIONAL COST: ¥0 now; approximately ¥0.7398 for that future 18-episode OFAT
READY TO RUN ABLATION: NO
