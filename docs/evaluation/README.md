# Agent Evaluation

## Philosophy

This project evaluates a tool-using cooperative Agent as a bounded system, not as a persuasive demo. Evidence is separated into task outcome, repeat reliability, Authority safety, efficiency, structured repair/fallback telemetry, cross-session Memory, and Reflection. Every claim below is limited to its frozen protocol.

## Benchmark definition

A benchmark is not one metric. It is the frozen combination of:

`cases + runtime/model configuration + player script + success rule + turn limit + repeat protocol + immutable artifacts`

Each condition has its own manifest and aggregate. Runs with different manifests are not mixed.

## Current baseline

The E6 production-equivalent baseline used 3 frozen cases × 3 independent repeats:

| Metric | Result |
|---|---:|
| Task success | 8/9 (88.89%) |
| Diagnosis accuracy | 9/9 (100%) |
| Treatment accuracy | 8/9 (88.89%) |
| Executed safety violations | 0 |
| Infrastructure failures | 0 |
| Provider aborts | 0 |
| Mean turns | 11.89 |
| Mean tokens / episode | ~155,953 |
| Total estimated cost | CNY 0.36987276 |

## Guides

- [Capability stabilization](capability_stabilization.md): how the frozen path moved from 0/3 to 3/3.
- [Task benchmark and results](task_benchmark_and_results.md): protocol, E6 results, telemetry, and claim boundaries.
- [Memory evaluation](memory_evaluation.md): cross-session persistence, retrieval, exposure, and non-claims.
- [Reflection evaluation](reflection_evaluation.md): deterministic mechanism proof and the bounded real-model result.
- [Sanitized examples](../../examples/evaluation_artifacts/README.md): small public artifacts; complete raw artifacts remain private.

## Evidence boundaries

- The P0–P5 0/3→3/3 history demonstrates capability stabilization, not statistical reliability.
- E3 6/9→E6 8/9 is an observed descriptive change of +22.22 percentage points, not causal proof or statistical significance.
- Cross-session Memory exposure is proven; declared/accepted use and behavioral benefit were not observed/proven.
- Reflection mechanism and real trigger/generation are proven; real-model derived-memory robustness and behavioral benefit are not proven.
