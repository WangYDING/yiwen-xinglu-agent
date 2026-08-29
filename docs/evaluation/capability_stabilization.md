# Capability Stabilization

## Scope

The initial frozen 3-case run completed 0/3 tasks. After P0–P5, the same capability check completed 3/3. This history shows the task path became executable end to end; it is not a multi-run reliability estimate.

## Condensed engineering history

| Phase | Problem | Root cause | Generic fix | Result |
|---|---|---|---|---|
| P0 | Invalid or incomplete actions stopped progress | Structured proposals lacked a bounded recovery path | Added schema-aware repair and safe fallback telemetry | Invalid proposals became observable and recoverable |
| P1 | Correct evidence did not reliably lead to diagnosis execution | Action selection could remain conversational when a diagnosis action was available | Made diagnosis selection explicit within the public action contract | Diagnosis could be proposed, confirmed, and executed |
| P2/P2a | Plan and Decision could disagree | Planning intent and executable action were validated separately | Added Plan/Decision alignment validation and reason-coded telemetry | Misalignment was rejected or repaired before execution |
| P3/P3a | Model could not reliably satisfy the diagnosis contract | The model-visible schema did not fully express the runtime validator's requirements | Aligned initial and repair schemas; recorded repair attempts and outcomes | Diagnosis contract failures became bounded and diagnosable |
| P4 | Correct diagnosis could stall before treatment | Treatment candidates and exact arguments were not sufficiently explicit to the model | Projected the current public treatment action space into the contract | Treatment actions could reach confirmation and execution |
| P5 | Agent could keep discussing when an executable step existed | Plan commitment did not force the current legal action into Decision | Required executable-step commitment and safe rejection on mismatch | Frozen 3×1 completed 3/3 |

## Result and boundary

`initial frozen 3×1: 0/3 → post-P0–P5 frozen 3×1: 3/3`

The defensible claim is that structured contracts, repair/fallback, alignment checks, and executable-step commitment stabilized the tested task path. It does not establish statistical reliability, generalization to unseen cases, or the causal contribution of any single phase.

