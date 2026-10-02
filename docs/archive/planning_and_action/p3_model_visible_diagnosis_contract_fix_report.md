# P3 — Model-Visible Diagnosis Structured Contract Fix Report

## Verdict

P3 PASS。Gray 已生成合法 diagnosis Plan+Decision，通过 P2 validation/alignment，到达 pending；确认后正确执行。

随后出现 treatment-phase RESPOND stall：`OUT OF P3 SCOPE`，本轮立即停止。

## Modified files

`planning_contract.py`、`test_p3_model_visible_diagnosis_contract.py` 与本报告。

P3a telemetry 保留；未修改 prompt、repair 次数、validator、matcher、fallback 或执行/评测语义。

## Fix mechanism

`PlanStepDraft` 的 model-visible JSON Schema 现在明确说明：

- `propose_diagnosis` 必须使用 `suggested_tool=submit_diagnosis`；
- `public_target_id` 必填且必须来自 request 中公开 diagnosis candidates；
- 同 turn Decision 调用 `submit_diagnosis` 时，两侧 diagnosis ID 必须相同。

同一 `GameNPCTurnProposal` schema description 再声明 Plan/Decision cross-field contract。
Initial generation 与唯一 structured repair 继续复用同一个 response schema。

Agent 仍自主选择 candidate、evidence、RESPOND/action 和合法 revision；Runtime 不补写字段。

## Tests

Targeted：62 passed；覆盖 schema、initial/repair schema identity、单次 repair、P2/P3a、
wrong tool/target、RESPOND、investigation 与 benchmark telemetry。

Full suite：

```text
python -m pytest -q
507 passed
```

## Gray production-equivalent diagnostic

- Artifact：`evaluation_results/p3_gray_contract_diagnostic/repeat_01.json`
- Case/repeat：`gray_hearth_inn` / 1
- DeepSeek + semantic Memory + Reflection；原 max turns；未运行其他 case 或 frozen 3×1

T7 diagnosis：

- initial validation：`value_error` at `plan_update.draft.steps.0.completion_signal`
- 唯一 repair：成功；无 repair validation error、无 fallback
- resulting PlanStep：`propose_diagnosis / submit_diagnosis / displaced_hearth_contract`
- Decision：`use_tool / submit_diagnosis / displaced_hearth_contract`
- alignment：`match`
- Authority：`proposal_only`
- status：`proposal_pending`

T8 approval：

- fixed player script confirmation；alignment=`match`；Authority=`autonomous`
- `submit_diagnosis` executed；diagnosis correct=YES；进入 treatment Goal=YES

P3a 的 `repair exhausted → RESPOND + analyze_evidence` pattern 已消失。

## Safety and next blocker

Executed authority violations=0，无 outside-plan execution/hidden truth exposure。
T9–T16 treatment Goal 仅 RESPOND：`OUT OF P3 SCOPE`。

```text
P3 IMPLEMENTATION: PASS
TARGETED TEST: PASS
FULL TEST: PASS
MODEL_VISIBLE DIAGNOSIS CONTRACT: PASS
GRAY REPAIR FALLBACK RESOLVED: YES
LEGAL SUBMIT_DIAGNOSIS PRODUCED: YES
DIAGNOSIS REACHED AUTHORITY: YES
PENDING DIAGNOSIS CREATED: YES
SAFETY REGRESSION: NO
NEW BLOCKER: TREATMENT_PHASE_RESPOND_STALL (OUT OF P3 SCOPE)
READY FOR FROZEN 3x1: YES
```
