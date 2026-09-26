# Agent Evaluation

## CE-2A context behavior pilot

- [上下文工程模块主文档](../architecture/CONTEXT_ENGINEERING_DESIGN.md)：当前模块状态与证据边界的首选入口。
- [CE-2A 最终请求上下文有限质量验收](../archive/context_engineering/ce2a_context_quality_acceptance_20260926.md)：当前离线验收结论；证明请求构建和确定性边界，不证明模型理解或协作成功率提升。
- [CE-2A 上下文行为对照方案](../archive/context_engineering/ce2a_context_behavior_pilot.md)：历史试验设计与结论边界。
- [CE-2A 离线工具实施报告](../archive/context_engineering/ce2a_context_behavior_pilot_implementation.md)：v1/v2 工具与离线运行历史。
- [CE-2A v1 离线预检](../archive/context_engineering/ce2a_context_behavior_preflight_v1.md)与 [v2 预检](../archive/context_engineering/ce2a_context_behavior_preflight_v2.md)：对应冻结身份形成时的历史预检。
- [CE-2A v3 账本写入失败修复](../archive/context_engineering/ce2a_ledger_failure_fix_v3.md)：当前 behavior fixture 身份与评测运行 fail-closed 保障；真实运行仍默认禁用。

## V2 evaluation and revised design

See [V2.1 revised design](v2_design/revision_20260920/README.md) for the current design direction: regression, capability and architecture comparisons, memory/reflection benefit, and engineering/interaction safety. The complete design remains design-only; its corrected [54-episode slim first-round V2 package](v2_design/revision_20260920/SLIM_FIRST_ROUND_FREEZE_V2.md) is implemented, frozen, and awaiting a new explicit paid authorization. The [original V2 design](v2_design/README.md), its completed historical runs, subsequent corrections, and results below remain available; they are not new V2.1 results.

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
