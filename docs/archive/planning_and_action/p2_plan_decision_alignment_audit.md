# P2 — Plan/Decision Co-generation Alignment Root Cause Audit

## 1. P2 VERDICT

Post-P1 diagnosis phase 的 Plan 与 Decision 来自**同一次 LLM call、同一个 `GameNPCTurnProposal`**，但二者是并列生成的结构字段，没有 schema-level reference保证 Decision复用 active PlanStep 的 tool/target。

Runtime先验证并应用该 Plan proposal，再把同一proposal内的 Decision关联到应用后的 active step，最后执行 `_action_matches_plan`。因此 Lantern T7 的 `plan_changed=true + action_outside_active_plan` 证明：一个新Plan和一个与其首个active step不一致的非-RESPOND action在同一输出中被共同生成。

当前还存在一个代码级 matcher缺陷：ActionContract按参数名校验 diagnosis call；alignment matcher却取 `next(iter(tool_call.arguments.values()))` 当target。Diagnosis有 `diagnosis_id` 与 `evidence_clue_ids` 两个参数，JSON key顺序不同可使一个validator合法的action被alignment误拒。

但是现有artifact没有保存 rejected proposal的tool、argument keys/order/target，也没有保存active PlanStep的tool/target。因此不能证明Gray/Lantern实际命中了该顺序缺陷，也不能证明被拒action就是 `submit_diagnosis`：`NOT PROVEN BY CURRENT ARTIFACTS`。

结论：

- 直接失败：非-RESPOND Decision未通过Plan/Action结构匹配，PROVEN。
- 主要结构因素：`PLAN_ACTION_SCHEMA_MISMATCH` 与 `DECISION_CONTRACT_WEAKNESS`，HIGHLY SUPPORTED。
- matcher存在可证明的order-sensitive defect，但它是不是本次直接根因：INSUFFICIENT EVIDENCE。
- 在获取最小脱敏telemetry前，不应实施行为修复或放宽gate。

## 2. Gray timeline

| Turn | Goal / Plan state | Decision/result | rejection后state |
|---:|---|---|---|
| 6 | gather Goal完成 | investigation executed | Runtime将在下一轮创建diagnosis Goal |
| 7 | `FORM_DIAGNOSIS`；new P=3，plan_changed=true | `RESPOND` | Plan保存为active；world rev6不变 |
| 8 | same Goal/P=3 | 非-RESPOND；`action_outside_active_plan` | Plan/Goal/world不变；recovery evaluation=`revise_plan` |
| 9 | same；上一recovery可见 | `RESPOND` | recovery仍保存在last evaluation |
| 10–16 | same | `RESPOND` ×7 | 无world/Plan进展；max turns |

T8 rejected proposal具体action type只有“非-RESPOND”可证；tool、arguments、target：`NOT PROVEN BY CURRENT ARTIFACTS`。

T7创建的三个PlanStep内容、首个active step intent/tool/target：`NOT PROVEN BY CURRENT ARTIFACTS`。

Gray不是持续alignment rejection，而是一次mismatch后退回RESPOND。P0 feedback channel正常存在，但没有促成replan或matching action。

## 3. Lantern timeline

| Turn | Goal / Plan state | Decision/result | rejection后state |
|---:|---|---|---|
| 6 | gather Goal完成 | investigation executed | 下一轮进入diagnosis phase |
| 7 | `FORM_DIAGNOSIS`；new P=3，plan_changed=true | 非-RESPOND；`action_outside_active_plan` | 新Plan已保存；recovery evaluation持久化 |
| 8 | same Goal/P=3；recovery可见 | 非-RESPOND；same rejection | Plan/Goal/world不变；覆盖最近recovery |
| 9–16 | same | same rejection ×8 | bounded单槽feedback持续更新；max turns |

Lantern T7证明mismatch发生在同次co-generation的新Plan首步与Decision之间。T8–T16证明即使模型下一轮能看到full persisted Plan、active step及P0 recovery，仍没有合法revise或matching execution。

十次rejected proposal的具体tool/target/argument order：`NOT PROVEN BY CURRENT ARTIFACTS`。

## 4. Plan/Decision generation path

真实production顺序：

```text
Runtime._prepare_next_goal()
  → deterministic FORM_DIAGNOSIS Goal
Runtime builds GameNPCAgentInput
  → public Observation/readiness
  → current Goal
  → current persisted Plan（T7为None；后续为P=3）
  → last PlanEvaluation/environment feedback
  → public action surface
GameNPCAgent.propose_turn()
  → one LLM request
  → one GameNPCTurnProposal
       goal_update
       plan_update / PlanDraft / PlanStepDrafts
       decision / AgentAction
Runtime GoalPlanPolicy.validate()
  → validates Plan fields and public targets
Runtime._apply_proposal()
  → CREATE/REVISE draft becomes authoritative active Plan
Runtime._associate_decision()
  → annotates Decision with resulting active step identity
Runtime._action_matches_plan()
  → compares Decision action against resulting active step
  → mismatch returns before ActionContract/Authority
```

职责：Goal phase由Runtime生成；Plan、PlanSteps和Decision均由LLM在同一个结构化输出中生成；Runtime只验证/应用，不自动选择action。

T7时LLM input能看到Goal、readiness、player request和allowed action surface，但current Plan为None。它必须在同一JSON中同时设计Plan并输出Decision，Decision没有单独的第二阶段读取新Plan。T8以后模型能看到完整persisted Plan、active step和上一alignment feedback。

## 5. Active PlanStep ↔ Action mapping

### PlanStep schema

PlanStep是结构化类型，不只是自然语言：

- `intent`
- `capability`
- `suggested_tool`
- `public_target_id`
- `public_summary`
- `completion_signal`
- lifecycle `status`

Diagnosis PlanStep可稳定表示为：

```text
intent=propose_diagnosis
capability=propose_diagnosis
suggested_tool=submit_diagnosis
public_target_id=<public diagnosis id>
```

GoalPlanPolicy要求FORM_DIAGNOSIS中的任何tool step只能使用 `submit_diagnosis`，target必须是公开candidate，capability必须为proposal。因此 diagnosis Plan representation本身存在合法形式。

### Action schema

Decision Action使用：

- `action_type=use_tool`
- `tool_call.name=submit_diagnosis`
- `tool_call.arguments={diagnosis_id, evidence_clue_ids}`

### Matcher

`_action_matches_plan` 的规则是：

1. RESPOND无条件匹配；
2. 必须有active Plan；
3. `action.tool_call.name is step.suggested_tool`；
4. `next(iter(action.tool_call.arguments.values())) == step.public_target_id`。

合法匹配例：Plan target=`diagnosis_a`；Action arguments按顺序为 `diagnosis_id=diagnosis_a`、再 `evidence_clue_ids=[...]`。tool一致且第一个value为diagnosis id，matcher返回true。

合法validator但matcher可能拒绝的例：同一参数集合以 `evidence_clue_ids` 在前、`diagnosis_id` 在后。ActionContract按字段名读取，仍合法；matcher先取得list，与Plan target不等，返回false。

这证明Action schema与Plan schema不是同构映射：Plan有显式target，Action target藏在tool-specific arguments中；matcher用位置/顺序近似字段语义。`ALIGNMENT_MATCHER_TOO_STRICT`/错误提取在代码层成立，但本批次是否命中：`NOT PROVEN BY CURRENT ARTIFACTS`。

不存在已证明的naming mismatch：ToolName与Plan suggested_tool共用同一enum。也没有证据证明PlanStep信息不足；缺的是artifact telemetry，而不是domain字段。

## 6. Rejection/recovery path

Mismatch后：

- action仍被拒，不进入ActionContract、Authority或CaseEngine；
- world revision/event均不变；
- Goal与active Plan不被自动迎合action；
- P0 recovery以last `PlanEvaluation`持久化；
- 下一轮`last_environment_feedback`明确说明action未执行，应对齐active step或合法revision。

Agent合法能力：

- `PlanUpdateKind.REVISE`：可提交新2–4 step draft；Runtime应用后按新首步校验同turn Decision。
- `GoalUpdateKind.REPLACE`：若替换Goal，现有Plan必须同时REVISE。
- Decision每轮重新生成。
- Agent不能自行advance PlanStep；只有成功world action后的PlanEvaluator可完成/推进step。

所以replan路径存在，且P0 targeted tests已证明“revision + matching action”可以同turn恢复。Lantern没有使用它：T8–T16 `plan_changed=false`。Gray也没有revision，随后只RESPOND。

`REPLAN_RECOVERY_WEAKNESS` 的准确含义不是“没有API”，而是co-generation contract没有把feedback确定地转换为“revise Plan并让Decision匹配新首步”或“保持Plan并执行当前step”。模型拥有权限，但约束/结构耦合较弱。

## 7. Telemetry sufficiency

当前telemetry不足，且已经阻碍direct root-cause判断。

现有artifact只记录rejection status、error code、plan_changed、plan step count；alignment early return没有填充`selected_tool`，也没有保存active step结构。因此无法区分：

- correct diagnosis tool + wrong diagnosis target；
- correct tool/target但arguments key顺序触发matcher缺陷；
- unrelated tool；
- missing/other target；
- Plan首步本来是非tool或另一个diagnosis candidate。

建议先增加只读、脱敏、bounded字段：

- `proposed_action_type`
- `proposed_tool`
- `proposed_public_target_id`（只允许Observation中的公开ID）
- `proposed_argument_keys`（不存values亦可）
- `active_plan_step_id`
- `active_plan_step_intent`
- `active_plan_step_tool`
- `active_plan_step_public_target_id`
- `alignment_reason_code`，细分missing plan/tool mismatch/target mismatch

不得记录raw prompt、raw response、hidden truth、private reasoning或secret。Telemetry必须旁路记录，不进入下一轮prompt，不改变decision。

## 8. Root-cause matrix

| Classification | Role | Confidence | Evidence |
|---|---|---|---|
| `PLAN_ACTION_SCHEMA_MISMATCH` | primary structural factor | PROVEN | Plan显式target；Action target嵌入tool-specific dict |
| `DECISION_CONTRACT_WEAKNESS` | primary co-generation factor | HIGHLY SUPPORTED | 同一输出并列Plan/Decision，无schema引用约束 |
| `ALIGNMENT_MATCHER_TOO_STRICT` | proven code defect / possible direct cause | PROVEN code；run因果UNKNOWN | matcher依赖arguments value顺序 |
| `MODEL_DECISION_QUALITY` | possible direct cause | HIGHLY SUPPORTED but underspecified | Lantern拒绝后仍不revision；具体action未知 |
| `REPLAN_RECOVERY_WEAKNESS` | contributing factor | HIGHLY SUPPORTED | path存在、feedback可见，但模型未形成恢复输出 |
| `TELEMETRY_INSUFFICIENT` | blocks exact attribution | PROVEN | 缺双方tool/target/argument keys |
| `PLAN_REPRESENTATION_BUG` | not established | NOT PROVEN | domain能表达diagnosis step；真实step未知 |
| `DECISION_CONTEXT_MISSING` | T7 partial; later no | NOT direct | T7无preexisting Plan，T8+有full Plan/feedback仍失败 |
| `BENCHMARK_ISSUE` | excluded | NOT SUPPORTED | rejection来自production co-generation/alignment path |

Gray与Lantern共享schema/matcher/co-generation机制；是否共享同一个具体tool/target错误，证据不足。

## 9. Minimum recommended fix

优先级：

1. **Telemetry first。** 先使下一次定向验证能区分tool、target和argument-order。
2. **PlanStep ↔ Action mapping。** 建立tool-aware target extractor或共享typed action reference，按`diagnosis_id`字段比较，不依赖dict顺序；保持相同安全强度。
3. **Decision contract。** 在同一`GameNPCTurnProposal`内验证非-RESPOND Decision必须匹配proposal应用后的首个PlanStep；失败应进入structured repair而不是直到Runtime early return才发现。
4. **Replan contract。** recovery后要求模型二选一：KEEP + matching action，或REVISE + matching new first step；不自动生成内容。
5. **Plan representation。** 当前字段足够，暂不重构。
6. **Alignment gate。** 不放宽；只修复target提取语义，使validator合法call不会因JSON key order误拒。

Runtime不应自动替模型选择matching action。诊断candidate、evidence判断和是否revision仍属于Agent autonomy；Runtime只验证同一proposal内部一致性。

## 10. Explicit non-fixes

- 不绕过或放宽`action_outside_active_plan`。
- 不把任何非匹配action送入Authority/CaseEngine。
- 不让Runtime选择diagnosis/action/target。
- 不硬编码case或正确答案。
- 不修改P0/P1、benchmark、prompt、Memory、Reflection、treatment或turn limit。
- 不设计generic no-progress framework。
- 所有这些均为 `OUT OF P2 SCOPE`。

## 11. Implementation gate

当前不具备安全实施“行为修复”的充分run证据，因为无法判断是matcher key-order、wrong target、wrong tool还是Plan首步设计问题。应先做telemetry-only schema升级并用targeted fake proposals证明各分支；随后再决定是否只修tool-aware target extraction，或同时加强co-generation validation。

代码审计已足以指出matcher顺序敏感，应在有测试的独立变更中修正，但不能把它宣称为本次Gray/Lantern的已证明root cause。

```text
GRAY ALIGNMENT ROOT CAUSE: non-RESPOND Decision mismatched active PlanStep; exact mismatch NOT PROVEN BY CURRENT ARTIFACTS
LANTERN ALIGNMENT ROOT CAUSE: repeated non-RESPOND Decision/active PlanStep mismatch; exact mismatch NOT PROVEN BY CURRENT ARTIFACTS
SHARED ROOT CAUSE: YES (shared co-generation/schema/matcher path; exact mismatch unknown)
ALIGNMENT GATE ITSELF BUGGY: NOT PROVEN (gate principle valid; order-sensitive target extraction is buggy)
REPLAN PATH EXISTS: YES
TELEMETRY SUFFICIENT: NO
MINIMUM FIX LAYER: telemetry first, then PlanStep ↔ Action tool-aware mapping
RELAX ALIGNMENT GATE RECOMMENDED: NO
READY FOR P2 IMPLEMENTATION: NO
```
