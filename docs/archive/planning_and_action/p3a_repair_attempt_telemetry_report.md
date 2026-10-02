# P3a — Structured Repair Attempt Telemetry Report

## Implementation
仅增加脱敏旁路 telemetry：

- `BoundedAttemptTelemetry` 保存 initial/repair validation code、path 与 proposal 结构摘要。
- P2 policy exception 附带已解析 proposal 的 public-only 摘要。
- `CooperativeTurnResult` 与 benchmark turn artifact 投影这些字段。
- 未保存 raw prompt/response、hidden truth、reasoning 或 secret。

未修改 repair prompt、次数、schema、P2 validator、fallback 或任何执行行为。

## Targeted verification
```text
python -m pytest -q tests/test_p3a_repair_attempt_telemetry.py \
  tests/test_p2_plan_decision_alignment.py \
  tests/test_p2a_alignment_telemetry.py tests/test_agent_task_benchmark.py
29 passed
```

测试证明同一 invalid initial/repair 仍产生原 `RESPOND + analyze_evidence` fallback；
attempt 数、validation 结果不变，telemetry 字段不进入任何 LLM request。

按要求未运行 full pytest 或 frozen 3×1。

## Single-case diagnostic
使用现有 `ProductionEquivalentEpisodeExecutor`，仅运行 Gray、repeat=1、
DeepSeek + semantic Memory + Reflection；未运行 Lantern/Old Paper/aggregate runner。

首轮 Gray 因较早调查期 schema failure 未到 diagnosis，保留其 artifact；
第二个独立 Gray diagnostic 在 T7 取得首个可判定 P2 repair failure后停止扩展运行。

Artifact：`evaluation_results/p3a_gray_repair_diagnostic_retry/repeat_01.json`。

## Proven failure — Gray T7

- Initial error：`goal_plan_propose_diagnosis_PlanStep_requires_submit_diagnosis_and_a_public_target`
- Initial path：`plan_update.draft.steps`
- Initial step：`propose_diagnosis / tool=null / target=null`
- Initial Decision：`respond / tool=null / target=null`
- Repair error/path：与 initial 完全相同
- Repaired step：`propose_diagnosis / tool=null / target=null`
- Repaired Decision：`respond / tool=null / target=null`
- Result：bounded repair exhausted → `RESPOND + analyze_evidence` fallback

Repair request 已包含上述具体 error；当前失败不涉及尚未暴露的 target-equality error。
Direct cause 是 repair response 原样保留了 validator 明确指出的缺失字段。

```text
P3A TELEMETRY: PASS
BEHAVIOR NEUTRAL: YES
INITIAL FAILURE: propose_diagnosis PlanStep omitted submit_diagnosis and public target
REPAIR FAILURE: repaired proposal repeated the same null tool/target structure
REPAIRED PLAN STEP: propose_diagnosis / tool=null / public_target=null
REPAIRED DECISION: respond / tool=null / public_target=null
DIRECT ROOT CAUSE NOW PROVEN: YES
MINIMUM BEHAVIOR FIX: make the diagnosis PlanStep tool/target conditional invariant model-visible in the structured response schema
READY FOR P3 FIX: YES
```
