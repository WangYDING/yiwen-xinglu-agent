# Reflection Evaluation

## Mechanism and OFAT design

E11 built a deterministic, cross-session harness that separates:

`trigger → generation → validation/repair → receipt → derived write → index → later retrieval/exposure/use`

The clean OFAT conditions keep semantic Memory ON in both cells and vary only Reflection: CONTROL is ON, ABLATION is OFF. This avoids confusing Reflection removal with removal of ordinary Memory.

The deterministic proof exercised a grounded reusable lesson through persistence, indexing, later retrieval, and Agent-input exposure. It also verified condition identity, repository/player/session isolation, and separate ordinary versus Reflection-derived telemetry.

## Frozen real-model observation

In E12 CONTROL, Reflection triggered and the production provider generated output. The initial proposal failed grounding with `required_action_evidence_missing`. One bounded repair succeeded and returned a valid proposal with no reusable lesson. The receipt persisted and lifecycle safely returned `no_write`:

- trigger/generation: observed;
- grounding validation and repair: observed;
- Reflection-derived write/index/retrieval/exposure: zero;
- Authority violations, infrastructure failures, and provider aborts: zero.

E13 found no schema, validator, consolidation, repository, indexing, or lifecycle correctness bug. The empty lesson set was a valid conservative model choice: unsupported content was not written to long-term Memory.

## Evidence boundary

- Deterministic mechanism: **PROVEN**.
- Clean Reflection ON/OFF harness: **PROVEN**.
- Real trigger and production generation: **PROVEN**.
- Grounding repair and safe `no_write`: **OBSERVED**.
- Real-model Reflection-derived Memory robustness: **NOT PROVEN**.
- Behavioral benefit: **NOT PROVEN**.

The frozen result is intentionally not rerun or tuned toward a favorable write.
