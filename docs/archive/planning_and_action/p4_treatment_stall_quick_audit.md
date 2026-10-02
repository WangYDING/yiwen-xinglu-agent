# P4 — Treatment Phase RESPOND Stall Quick Audit

## Verdict

Gray 的 diagnosis 在 T8 正确执行后，Runtime 下一轮确实创建 `SELECT_TREATMENT` Goal。
T9 创建两步 Plan，active step 是 `discuss_treatment`，tool/target 均为 null；T9–T16 Decision 均为 RESPOND。

直接缺口在 model-visible action surface + Plan/Decision contract：planning request 只拼接
investigation actions 与 diagnosis actions，没有投影任何 `execute_treatment(treatment_id=...)` call。
P3 schema 也只声明 diagnosis conditional，没有 treatment 对应约束。

## Six answers

1. **Treatment Goal：YES。** `_prepare_next_goal()` 在 `submitted_diagnosis_id != null`
   时创建 `SELECT_TREATMENT / CASE_COMPLETED / 与玩家协商安全处置`；T9 artifact 与之吻合。

2. **Active Goal/PlanStep：** Goal 为 `SELECT_TREATMENT`；Plan 有 2 steps；active step 为
   `discuss_treatment`，`suggested_tool=null`、`public_target_id=null`。第二步结构未保存：
   `NOT PROVEN BY CURRENT ARTIFACTS`。

3. **`execute_treatment` 可见性：NO（完整 action call surface）。** 模型能在 authority、
   ToolName schema、system wording 与 observation treatments 中看到名称/候选，
   但 `AUTHORITATIVE_PUBLIC_ACTION_SPACE_available_actions` 明确遗漏 treatment call 及 exact arguments。

4. **Treatment PlanStep 强约束：不完整。** Validator 在 step 已声明 tool 时要求
   `execute_treatment + public target + propose_treatment capability`，并校验公开 treatment；
   但 schema/validator 不要求 propose/discuss treatment step必须携带 tool/target，
   也没有 treatment PlanStep target = Decision treatment_id 的 cross-field contract。

5. **Stall layer：PLAN GENERATION / DECISION SELECTION，直接上游为 ACTION SURFACE +
   MODEL-VISIBLE CONTRACT 缺失。** T9 repair成功而非 exhausted；T10–T16无 repair。
   RESPOND 对非工具 discuss step 合法且 alignment=`not_applicable`，故不是 alignment rejection。

6. **最小修复：** 将公开 treatment candidates 投影为 exact
   `execute_treatment({treatment_id})` action surface；在同一 structured schema/validation path
   声明 propose_treatment step 必须使用该 tool/target，且同 turn Decision target一致。
   不复制 diagnosis 修复前，应复用同一通用 tool-step/action-reference表达。

## Diagnosis comparison

Diagnosis 已有 public call projection、phase action contract、schema descriptions 与 P2 alignment validation。
Treatment 只有 validator/Authority 后置合法路径，缺少前置 call projection和 model-visible conditional。
因此它存在同类型缺口，但不能声称 `execute_treatment` 执行路径不存在。

```text
TREATMENT GOAL CREATED: YES
EXECUTE_TREATMENT MODEL-VISIBLE: NO
DIRECT STALL LAYER: PLAN GENERATION / DECISION SELECTION (upstream action-surface/contract gap)
DIRECT ROOT CAUSE: treatment calls are omitted from the public action surface and treatment structural contract is incomplete
EVIDENCE SUFFICIENT: YES
MINIMUM FIX: project exact public treatment calls and add a shared tool-step/Decision target contract for propose_treatment
READY FOR P4 IMPLEMENTATION: YES
```
