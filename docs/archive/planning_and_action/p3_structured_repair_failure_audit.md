# P3 — Structured Repair Failure Audit

## Verdict

Gray/Lantern T7–T16 均记录 `repair_used=true`、`fallback_used=true`，随后得到
`RESPOND + analyze_evidence`。这证明 initial proposal 与唯一 repair proposal 都未通过，
但 artifact 没保存两次 validation error 或 repair 后 proposal 摘要，无法确定第二次失败的具体原因。

## Five answers

1. **repair 能看到具体 P2 error：YES，但仅当前首个 error。**
   `_parse_turn()` 让 `GoalPlanPolicyError` 原样抛给 `BoundedStructuredOutput`；repair request
   附加 `校验信息：{str(error)[:1000]}`，并包含 original request 与 invalid response。

2. **repair 是否知道完整一致性要求：NO。**
   对空 diagnosis step，fail-fast 的首个信息是：
   `propose_diagnosis PlanStep requires submit_diagnosis and a public target`。
   它说明 tool 与 public target 必填，但没有同时说明
   `PlanStep.public_target_id = Decision.diagnosis_id`；后者只有前序检查通过后才可能报出。
   单次 repair 没有第三次机会处理第二个新 error。

3. **schema 与 validator：不等价。**
   repair 使用原 `GameNPCTurnProposal` JSON schema；其中 `suggested_tool` 与
   `public_target_id` 均允许 null。P2 的 phase/intent/cross-object conditional invariant
   只存在于 `GoalPlanPolicy`，未编码进 response schema。二者不矛盾，但 schema 不足以表达 validator。

4. **为何 fallback 为 `RESPOND + analyze_evidence`：代码确定。**
   `BoundedStructuredOutput` 只允许 initial + one repair；repair 再失败时 `output=None`。
   `propose_turn()` 随后调用 `_fallback_turn_proposal()`：无 current Plan 时 CREATE
   `analyze_evidence`/`discuss_with_player` 两步；Decision 来自 `_fallback_proposal()`，固定为 RESPOND。
   后续已有 fallback Plan 时继续 KEEP，并再次 RESPOND，因此形成安全循环。

5. **direct root cause 是否可确定：NO。**
   当前只能证明 repair proposal 再次 validation failed，不能证明失败字段。
   最小缺失证据是每次 attempt 的脱敏：
   `initial_validation_error_code/path`、`repair_validation_error_code/path`，以及 repair proposal 的
   Plan first-step intent/tool/public-target 与 Decision action/tool/public-target；无需 raw response。

## Gray / Lantern evidence

- Gray T7–T16：10/10 `repair_used=true`、`fallback_used=true`、RESPOND、active step=`analyze_evidence`。
- Lantern T7–T16：同样 10/10。
- 两案均无 diagnosis tool、无 alignment rejection；`alignment_reason_code=not_applicable`。
- Artifact 无 attempt-level validation error，不能区分 P2 tool、target、cross-field 或其他错误。

```text
DIRECT ROOT CAUSE: INSUFFICIENT EVIDENCE — repaired proposal's validation failure is not serialized
REPAIR FEEDBACK SUFFICIENT: NO
SCHEMA/VALIDATOR CONSISTENT: NO
FALLBACK LOOP CONFIRMED: YES
EVIDENCE SUFFICIENT FOR FIX: NO
MINIMUM NEXT FIX: add sanitized per-attempt validation error/path and repaired PlanStep/Decision structural summaries
READY TO IMPLEMENT: NO
```
