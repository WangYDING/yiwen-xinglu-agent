# E10 — Real-Agent Cross-Session Retrieval Exposure Pilot

## Verdict

The sequential paid pilot completed all three single-run gates within the CNY 0.20 hard budget.
Positive historical Memory was persisted, indexed, retrieved, selected by projection, and present in the real `GameNPCAgent` input.
The real Agent did not declare that it used the positive Memory, so runtime accepted-use was also empty.
This is the valid intermediate result defined before execution:
`REAL-AGENT CROSS-SESSION MEMORY EXPOSURE: PASS`
`OBSERVED MEMORY USE: NO`
No rerun, repeat, threshold change, fixture change, hidden-truth injection, or post-result success-rule change occurred.

## Frozen identity

- Pilot: `cross_session_memory_exposure_real_agent_pilot_v1`.
- E9 manifest SHA-256: `555c40960bc21d6dea6294477129f860273ac334e57c7a00e1cd2cc63c15123a`.
- E10 config SHA-256: `6d61c108bc1b6cfcceedebdec2a1acd50da4474e2f77b2fec785e6048568e73e`.
- Provider/model: production DeepSeek / `deepseek-v4-flash`.
- Session-B model runs: three, sequential, no repeats.
- Session A used deterministic public production actions; it made no provider request.
- Retrieval used the production BGE-M3 adapter, index, cosine retriever, threshold 0.35, and projection policy.
- E6 runtime hash preflight matched all eight frozen targets.
- Artifact root: `evaluation_results/cross_session_memory_exposure_real_agent_pilot_v1/`.

## Four evidence levels

### Level 1 — Persisted

Positive Session A produced `mem_1808413b7f925e99b28bd86696dcaf21` through CaseEngine committed events and `V1MemoryCoordinator`.

The harness verified the record and its current-space embedding before opening Session B; otherwise Gate 1 would have stopped with an error.

Session A and B used the same player and SQLite repository and different episode IDs (`eval_positive_transfer_2` and `eval_positive_transfer_3`).

### Level 2 — Exposed

The expected positive ID appeared in candidate IDs and selected IDs.

`retrieved_relevant_count=1`, `relevant_selected=true`, and the captured real-Agent input contained a non-empty `AgentMemoryContext`.

There was no current-session leakage, cross-player exposure, Authority violation, provider failure, or infrastructure failure.

### Level 3 — Declared used

The real Agent returned no declared-used Memory ID for the positive condition.

Exposure therefore must not be described as model-declared use.

### Level 4 — Accepted used

Runtime accepted-used IDs were empty because no use was declared.

The observed tool choice was `inspect_object`, targeting the public hearth inspection option. Its semantic consistency does not prove Memory influence.

`EXPOSED ≠ USED`; `USED ≠ BENEFICIAL`; no matched behavioral comparison was performed.

## Sequential gates

### Gate 1 — Positive transfer: PASS

- Candidate/selected: 1/1; expected ID present in both.
- Declared/accepted: 0/0.
- Action: `use_tool`; tool: `inspect_object`.
- Provider requests: 1.
- Tokens: 7,131 input + 753 output = 7,884.
- Estimated cost: CNY 0.00512468.

### Gate 2 — Irrelevant negative: PASS with false-positive exposure

- The irrelevant historical ID was a candidate and selected: 1/1.
- This is recorded as `false_positive_exposure=true`, not hidden or reclassified.
- Declared/accepted: 0/0; thus no accepted false-positive use.
- Action: `use_tool`; tool: `inspect_object`.
- Provider requests: 1.
- Tokens: 7,155 input + 801 output = 7,956.
- Estimated cost: CNY 0.00524468.
- Safety/Authority violations: 0.

### Gate 3 — Empty history: PASS

- Candidate/selected/declared/accepted: 0/0/0/0.
- Agent input contained no Memory context.
- Expected-empty correctness was true; leakage checks were clean.
- Action: `use_tool`; tool: `inspect_object`.
- Provider requests: 1.
- Tokens: 6,808 input + 782 output = 7,590.
- Estimated cost: CNY 0.00485968.

## Aggregate and boundary

Total provider requests: 3. Total tokens: 21,094 input + 2,336 output = 23,430.

Total estimated cost was CNY 0.01522904, below the CNY 0.20 hard budget.

All artifacts contain sanitized player IDs and bounded action/exposure telemetry; they contain no raw prompt, chain-of-thought, secret, or hidden truth.

This pilot proves the production cross-session path reached real-Agent input once under the frozen positive fixture. It does not estimate reliability, success improvement, behavioral benefit, or a causal Memory effect.

The irrelevant selection is useful diagnostic evidence: exposure filtering is imperfect in this tiny fixture, while the current Agent/runtime did not declare or accept its use. No tuning is authorized from this result.

PAID PILOT RUNS: 3
TOTAL ESTIMATED COST: CNY 0.01522904
POSITIVE MEMORY PERSISTED: YES
POSITIVE MEMORY INDEXED: YES
POSITIVE MEMORY RETRIEVED: YES
POSITIVE MEMORY SELECTED: YES
POSITIVE MEMORY IN AGENT INPUT: YES
POSITIVE MEMORY DECLARED USED: NO
POSITIVE MEMORY ACCEPTED USED: NO
IRRELEVANT FALSE-POSITIVE EXPOSED: YES
IRRELEVANT MEMORY ACCEPTED USED: NO
EMPTY HISTORY EXPOSURE ZERO: YES
SAFETY VIOLATIONS: 0
INFRASTRUCTURE FAILURES: 0
REAL_AGENT_RETRIEVAL_EXPOSURE: PASS
OBSERVED_MEMORY_USE: NO
BEHAVIORAL_BENEFIT_PROVEN: NO
PRODUCTION_BEHAVIOR_CHANGED: NO
READY FOR REFLECTION OFAT: YES
NEXT GATE: E11
