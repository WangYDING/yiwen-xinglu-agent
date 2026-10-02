# E12 — Real-Agent Cross-Session Reflection OFAT Pilot

## Verdict

The single authorized paid command ran CONTROL first and stopped before ABLATION exactly as required by the frozen sequential gate.
CONTROL did not establish Reflection-derived Memory exposure. The lifecycle trigger occurred and the production Reflection provider was called, but the final valid repaired proposal contained no reusable lesson, producing lifecycle status `no_write`. No Reflection-derived Memory was persisted, indexed, retrieved, selected, or placed in Session-B real-Agent input.
Therefore:
`REAL_AGENT_REFLECTION_EXPOSURE: FAIL`
This is not an infrastructure/provider failure and not a safety failure. It is an observed production Reflection generation/consolidation outcome under the one frozen scenario.
No rerun, tuning, fixture change, prompt change, threshold change, hidden-truth injection, or ABLATION run occurred.

## Frozen identity

- Pilot: `cross_session_reflection_ofat_real_agent_pilot_v1`.
- CONTROL configuration: Memory semantic / Reflection enabled.
- CONTROL hash: `ef6ba3a0fc0f27804bb2e8a9926ad2ca647a524a2b4b38e3324fdea7a0fc0975`.
- ABLATION hash: `7ea06d7a4fab1aa8c286beb240d534af0ffd44251e7bf774c61263cfe135f801`.
- Pilot config hash: `06f5c0b27a60740cb09d7373539416480eff770801691ce67529db576d8b0d2e`.
- Provider/model: production DeepSeek / `deepseek-v4-flash`.
- Hard budget: CNY 0.05.
- Preflight: all eight E6 production runtime hashes matched.
- Artifact root: `evaluation_results/cross_session_reflection_ofat_real_agent_pilot_v1/`.

## CONTROL Session A

The unchanged matched public script completed Old Paper through the production CaseEngine path.
Eight ordinary semantic Memory records were committed and indexed. Session A and B shared the same player/state-dir/repository and used different episode IDs.
The real `EPISODE_COMPLETED` Reflection trigger fired once.
Reflection generation used two production provider requests: one initial request and the bounded production repair.
Initial generation returned content but failed grounding validation with `required_action_evidence_missing`.
The repair returned successfully. Receipt status and lifecycle status became `no_write`; proposal status was `valid`, `repair_attempted=true`, and `repair_succeeded=true`.
This means real Reflection generation completed, but the repaired valid output proposed no accepted reusable lesson. Reflection write count was zero.
The lifecycle receipt was persisted and was readable without a provider call. There was no repository error, index error, or provider abort.

### Reflection generation usage

- Initial: 3,320 input tokens; 594 output tokens.
- Repair: 3,968 input tokens; 85 output tokens.
- Session-A Reflection subtotal: 7,288 input; 679 output; 2 requests.

## CONTROL Session B

The production BGE-M3 index/retriever, 0.35 threshold, projection policy, `AgentMemoryContext`, Runtime, Authority and real `GameNPCAgent` were used.
All eight retrieved candidates were ordinary historical Memory. Four ordinary IDs survived projection/selection and entered Agent input.
Reflection-derived IDs were empty at every stage because Session A wrote none:

- persisted: 0;
- indexed: 0;
- candidates: 0;
- selected: 0;
- declared used: 0;
- accepted used: 0;
- present in Agent input: 0.

The real Agent performed one provider request and selected the public `inspect_object` investigation for the hearth evidence target.
No Memory ID—ordinary or Reflection-derived—was declared or runtime-accepted as used.

### Session-B Agent usage

- Input tokens: 8,131.
- Output tokens: 769.
- Provider requests: 1.

## Sequential gate decision

CONTROL requirements 1–2 passed: trigger and real generation occurred.
Requirements 3–7 failed at the first dependency: there was no Reflection-derived persisted record. Consequently index, retrieval, selection and real-Agent exposure could not occur.
The runner preserved the CONTROL artifact and stopped. ABLATION was not run, so condition isolation was not empirically evaluated in E12.
The ordinary semantic Memory path remained operational in CONTROL, consistent with E11 deterministic evidence. This does not substitute for the unrun matched ABLATION condition.

## Cost, safety and inference boundary

Total paid usage: 3 provider requests, 15,419 input tokens and 1,448 output tokens, totaling 16,867 tokens.
Total estimated cost: CNY 0.0082798, below the CNY 0.05 cap.
Safety/Authority violations: 0. Infrastructure/provider failures: 0. Player, repository and current-session leakage: none.
This one result does not show that Reflection is generally unable to write useful Memory. It only shows that the frozen matched scenario did not produce a derived write in its one authorized real run. The deterministic E11 mechanism test remains valid but did not predict this model-output outcome.
No behavioral benefit, success improvement, reasoning improvement or causal OFAT conclusion is supported.

PAID PROVIDER REQUESTS: 3
TOTAL TOKENS: 16867
TOTAL ESTIMATED COST: CNY 0.0082798
CONTROL REFLECTION TRIGGERED: YES
CONTROL REFLECTION GENERATED: YES
CONTROL REFLECTION MEMORY PERSISTED: NO
CONTROL REFLECTION MEMORY INDEXED: NO
CONTROL REFLECTION MEMORY RETRIEVED: NO
CONTROL REFLECTION MEMORY SELECTED: NO
CONTROL REFLECTION MEMORY IN AGENT INPUT: NO
CONTROL REFLECTION MEMORY DECLARED USED: NO
CONTROL REFLECTION MEMORY ACCEPTED USED: NO
ABLATION REFLECTION GENERATION ZERO: NOT RUN
ABLATION REFLECTION EXPOSURE ZERO: NOT RUN
ABLATION ORDINARY MEMORY RETAINED: NOT RUN
CONDITION ISOLATION: NOT RUN
SAFETY VIOLATIONS: 0
INFRASTRUCTURE FAILURES: 0
REAL_AGENT_REFLECTION_EXPOSURE: FAIL
OBSERVED_REFLECTION_MEMORY_USE: NO
BEHAVIORAL_BENEFIT_PROVEN: NO
PRODUCTION_BEHAVIOR_CHANGED: NO
READY TO FREEZE MEMORY/REFLECTION EVALUATION: NO
NEXT GATE: READ_ONLY_ANALYSIS
