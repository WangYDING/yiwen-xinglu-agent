# E13 — Real Reflection `no_write` Differential Audit

## Verdict

E12 is explained without a production correctness defect. The direct cause was the real model's bounded proposal choice: its initial output included an action-dependent finding without available `ACTION` evidence; after receiving the exact grounding error, repair produced a valid proposal with no reusable lesson candidate. Consolidation consequently had zero candidates and lifecycle conservatively labeled the result `no_write`.

E11 proved the write/index/retrieval mechanism using a scripted, validator-perfect outcome lesson. It did not prove that the production model would robustly construct that lesson from the same evidence.

## Exact E12 chain

1. Trigger: real `EPISODE_COMPLETED` boundary for the completed public Session A.
2. Model-visible bundle: exactly one `TOOL_OUTCOME` and one `ASSESSMENT`; receipt provenance confirms their two ref IDs. No `ACTION`, plan, contribution, observation-delta, or Memory-use ref was supplied.
3. The raw initial proposal was intentionally not persisted, so its lesson/finding text and complete shape are unknown. Telemetry proves that some initial finding/lesson required `ACTION`: validation failed at `reflection_grounding_validation` with `required_action_evidence_missing`.
4. The repair request appended the invalid JSON and the validation exception. `ReflectionGenerationValidationFailure` stringifies to the rule code, so repair explicitly saw `required_action_evidence_missing` plus the instruction to delete unsupported findings/lessons.
5. Repair returned normally: `proposal_status=valid`, `repair_succeeded=true`, no final failure code.
6. Final receipt has `candidate_ids=[]`, `write_decisions=[]`, `written_memory_ids=[]`, and `index_status=not_required`. Candidate construction deterministically creates a first candidate for any valid reusable lesson, so this proves the repaired proposal had empty `reusable_lesson_candidates`. Findings may also have been empty, but artifacts do not establish that.
7. There is no explicit model `no_write` field. The model selected an empty lesson set; validator accepted that safe structure; consolidation produced zero candidates; lifecycle then assigned `NO_WRITE`. It was not a runtime fallback and no write policy rejection occurred.

## Contract and evidence consistency

The model-visible system contract explicitly states:

- successful/failed/unnecessary-action findings require `ACTION` plus `TOOL_OUTCOME` or `ASSESSMENT`;
- an outcome reusable lesson requires authoritative outcome evidence plus either `ACTION` or a second independent authoritative ref;
- unsupported content must be omitted, and empty findings/lessons are valid.

The validator enforces those same roles. The domain JSON schema alone cannot encode every cross-field evidence rule, but the system prompt supplies them explicitly. Classification is **B** for the initial error: schema/prompt and validator are consistent; the model did not obey the visible finding contract.

Required `ACTION` evidence was not available in this E12 bundle. That is not evidence-builder loss: the evaluation lifecycle call supplied only outcome and assessment, and the builder faithfully projected both. The caller did not supply a `GameNPCDecision`; Session A's scripted public actions were not represented as Reflection `ACTION` refs.

This absence did not make a write impossible. The two independent authoritative refs satisfy the visible and runtime contract for an `OUTCOME` lesson without `ACTION`. Thus a cautious transferable lesson was structurally available, exactly as E11 demonstrated.

## E11/E12 differential

Both used the same episode-completed trigger and the same public outcome/assessment evidence shape. E11's scripted proposal directly supplied one high-confidence `OUTCOME` lesson, referenced both complete authoritative refs, used a matching tool-outcome scope tag, and therefore passed validation, consolidation, write, index and later retrieval.

E12 used the production model. Its initial action-dependent finding was invalid; its repair chose the permitted empty-lesson resolution rather than the also-permitted two-authoritative-ref outcome lesson. No candidate reached consolidation policy.

Therefore: **MECHANISM PROVEN, MODEL ROBUSTNESS NOT PROVEN**. The differential is not caused by different validator, repository, indexing, retrieval, threshold, or lifecycle policy.

## Is `no_write` reasonable?

Supported reusable lesson classification: **YES, clearly supported**, but narrowly. The two public refs support the conservative strategy “gather reversible evidence before intervention”; they do not support stronger causal or success claims.

Even so, empty output is an explicitly valid conservative choice. Given one stochastic production output, `no_write` is safe and acceptable behavior, not proof of a defect. The system prefers omission over unsupported long-term Memory.

## Root cause and decision

Direct root cause: `MODEL_DECISION_QUALITY`—the initial contract violation followed by a conservative empty repair despite an available valid lesson.

Systemic contributing factor: `SCENARIO_EVIDENCE_INSUFFICIENT` for action-dependent findings—the bundle omitted `ACTION`, narrowing the model's valid options and making repair-to-empty attractive. This is an evaluation composition limitation, not a proven production evidence-builder bug.

No schema/validator contradiction, missing supplied evidence, consolidation correctness error, or unsafe write was observed. The repair path behaved as designed. Do not modify production Reflection and do not rerun E12.

For recruitment, freeze the evaluation honestly: Memory persistence→retrieval→real-Agent exposure passed; Reflection trigger→real generation passed, while one frozen real run produced safe `no_write` and no derived exposure. This is more credible than tuning toward a favorable result and is sufficient for packaging with explicit boundaries.

E12 INITIAL FAILURE EXPLAINED: YES
REPAIR SAW GROUNDING ERROR: YES
REPAIR RESULT: NO_WRITE
SCHEMA/VALIDATOR CONSISTENT: YES
REQUIRED ACTION EVIDENCE AVAILABLE: NO
E11/E12 MECHANISM DIFFERENCE: scripted validator-perfect outcome lesson vs real-model invalid finding then empty valid repair
DIRECT ROOT CAUSE: MODEL_DECISION_QUALITY
SYSTEMIC CONTRIBUTING FACTOR: SCENARIO_EVIDENCE_INSUFFICIENT for action-dependent findings
CORRECTNESS BUG PROVEN: NO
PRODUCTION FIX JUSTIFIED: NO
RERUN JUSTIFIED: NO
MEMORY EVALUATION FREEZE READY: YES
REFLECTION EVALUATION FREEZE READY: YES
RECOMMENDED NEXT STEP: RECRUITMENT PACKAGING
