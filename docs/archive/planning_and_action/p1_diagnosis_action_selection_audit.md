# P1 Diagnosis Action Selection Root Cause Audit

## 1. P1 VERDICT

Gray Hearth 与 Lantern Alley 呈现同一个 production failure pattern：

```text
diagnosis-ready public Observation
→ Runtime creates active FORM_DIAGNOSIS Goal
→ LLM creates/keeps a 3-step Plan
→ fixed player asks for a diagnosis
→ LLM selects RESPOND
→ RESPOND is unconditionally schema-valid, plan-alignment-valid, and autonomous
→ no submit_diagnosis reaches validator/authority
→ state does not progress
```

直接观测原因是 `MODEL_DECISION_QUALITY`：十次独立真实 decision 均选择 `RESPOND`，没有形成 diagnosis tool action。

最强的共同上游因素是 `ACTION_SELECTION_CONTRACT_WEAKNESS`：当前 contract 没有约束 active `FORM_DIAGNOSIS` Goal、active PlanStep 与最终 action 之间的推进一致性；`RESPOND` 在任何 Goal/Plan 下都合法。

另有两个高度相关的 contributing factors：

- `LLM_CONTEXT_MISSING`：模型可见的 exact public action space 只投影 investigation calls，没有投影 exact `submit_diagnosis` calls。
- `ACTION_SCHEMA_AMBIGUITY`：通用 `ToolCallRequest.arguments` 是无类型字典；response schema 不表达 `submit_diagnosis` 所需的条件化参数结构。

Prompt 确实说明 diagnosis 是 proposal，但没有明确建立“diagnosis Goal/Plan ready → 应选择 diagnosis proposal，除非明确 revise/block”的 action-selection contract。因此 `PROMPT_INSTRUCTION_WEAKNESS` 是 contributing factor，不应在 contract/context 尚不对称时先用一句 benchmark-oriented prompt 修补。

## 2. Gray timeline

| Turn | Public/runtime state | Player input | Agent result |
|---:|---|---|---|
| 6 | rev5，7 clues，gather Goal | continue investigation | `question_patient` executed；1 event；Goal completed |
| 7 | rev6，8 clues，diagnosis-ready；`FORM_DIAGNOSIS` Goal | request diagnosis | new 3-step Plan；`RESPOND`；no event/error/repair |
| 8 | same rev6/clues8/Goal/Plan | request diagnosis | `RESPOND` |
| 9 | same | request diagnosis | `RESPOND` |
| 10 | same | request diagnosis | `RESPOND` |
| 11 | same | request diagnosis | `RESPOND` |
| 12 | same | request diagnosis | `RESPOND` |
| 13 | same | request diagnosis | `RESPOND` |
| 14 | same | request diagnosis | `RESPOND` |
| 15 | same | request diagnosis | `RESPOND` |
| 16 | same | request diagnosis | `RESPOND`；max turns |

Artifact 证明：Goal description 为“与玩家形成并协商公开诊断”，T7 plan changed=true、plan step count=3；T8–T16 plan unchanged；十轮 selected_tool均为空、authority均为 autonomous、无 error/fallback。

Active PlanStep 的 intent、suggested tool、target和public summary未写入 artifact：`NOT PROVEN BY CURRENT ARTIFACTS`。

LLM 的 contribution disposition、公开 dialogue、explanation及其是否在文字中识别出正确诊断未写入 artifact：`NOT PROVEN BY CURRENT ARTIFACTS`。

## 3. Lantern timeline

| Turn | Public/runtime state | Player input | Agent result |
|---:|---|---|---|
| 6 | rev5，6 clues，gather Goal | continue investigation | `observe_patient` executed；1 event；Goal completed |
| 7 | rev6，8 clues，diagnosis-ready；`FORM_DIAGNOSIS` Goal | request diagnosis | new 3-step Plan；`RESPOND`；no event/error/repair |
| 8 | same rev6/clues8/Goal/Plan | request diagnosis | `RESPOND` |
| 9 | same | request diagnosis | `RESPOND` |
| 10 | same | request diagnosis | `RESPOND` |
| 11 | same | request diagnosis | `RESPOND` |
| 12 | same | request diagnosis | `RESPOND` |
| 13 | same | request diagnosis | `RESPOND` |
| 14 | same | request diagnosis | `RESPOND`；structured-output repair occurred |
| 15 | same | request diagnosis | `RESPOND` |
| 16 | same | request diagnosis | `RESPOND`；max turns |

Lantern 的调查顺序、case内容与 Gray 不同，但 diagnosis phase state完全同构。T14 有一次 repair，最终仍为非fallback `RESPOND`；其原始校验错误内容未保存：`NOT PROVEN BY CURRENT ARTIFACTS`。

Active PlanStep 与 raw model rationale同样是：`NOT PROVEN BY CURRENT ARTIFACTS`。

## 4. Runtime State

两案进入 stall 时：

- Current Goal：确实是 active `FORM_DIAGNOSIS`。Runtime `_prepare_next_goal()` 在 prior Goal completed、session active、`can_submit_diagnosis=true` 时确定性创建它。
- Goal completion condition：`DIAGNOSIS_SUBMITTED`。
- Diagnosis readiness：成立。Benchmark script 只有在 public `can_submit_diagnosis` 为 true 时进入 `request_public_diagnosis`；两案均在 T7进入该分支。
- Remaining prerequisite：没有公开可用 investigation。生产 readiness policy以此作为开放 diagnosis 的条件。
- Runtime permission：允许。GoalPlanPolicy明确接受 `FORM_DIAGNOSIS` iff `can_submit_diagnosis=true`。
- Active Plan：存在且 active；T7新建3 steps，后续保持。
- Active PlanStep实际内容：`NOT PROVEN BY CURRENT ARTIFACTS`。

因此没有证据支持 `RUNTIME_STATE_BUG` 或尚未满足的 case前置状态。

## 5. LLM-visible context

必须区分 Runtime state 与实际 request。Production `_planning_request()` 确实序列化并发送：

| Information | Runtime exists | Enters LLM request | Finding |
|---|---:|---:|---|
| current Goal | yes | yes | 完整 JSON，含 type/status/condition |
| current Plan | yes | yes | 完整 JSON，含 active step、tool/target（若有） |
| active PlanStep | yes | yes, inside current Plan | 具体真实内容未保存在 artifact |
| diagnosis-ready | yes | yes | 完整 CaseObservation含 `can_submit_diagnosis` |
| diagnosis candidates | yes | yes | Observation中公开 ids/descriptions |
| discovered evidence | yes | yes | Observation中公开 clues |
| player diagnosis request | yes | yes | `PLAYER_BELIEF_player_contribution` |
| authority for diagnosis | yes | yes | authority view列 `submit_diagnosis` 为 proposal-only |
| previous environment feedback | optional | yes if state has it | stall turns为 null/no evaluation；具体 request未落 artifact |
| generic action/tool schema | yes | yes | response JSON schema含 RESPOND/USE_TOOL及 ToolName enum |
| exact investigation calls | yes | yes | 单独投影到 public action space |
| exact diagnosis calls | validator can derive | **no** | 没有对应 projection |

所以不能归类为“模型完全看不到 diagnosis”。它看到 Goal、readiness、candidates、authority和 tool enum。缺失的是与 investigation 同等级、可直接复制且与 validator一致的 diagnosis executable affordance。

## 6. RESPOND vs `submit_diagnosis` contract

### RESPOND

- `AgentActionType.RESPOND` 只要求 `tool_call=None`。
- PublicActionContractValidator 遇到 RESPOND立即接受。
- Runtime `_action_matches_plan()` 遇到 RESPOND立即返回 true，不检查 active PlanStep。
- Authority 将 RESPOND判为 autonomous social action。
- RESPOND 不要求 Goal/Plan revision、blocked reason或 evidence gap。

这使“继续讨论”在 `FORM_DIAGNOSIS` + ready状态下仍是无限合法的局部选择。

### `submit_diagnosis`

- ToolName enum包含 `submit_diagnosis`。
- Agent capability enum包含 `propose_diagnosis`。
- GoalPlanPolicy允许 `FORM_DIAGNOSIS` plan使用该 tool，并要求 target为公开 diagnosis candidate、capability为 proposal。
- ActionContract要求 `diagnosis_id`；可选 `evidence_clue_ids`必须来自 discovered clues。
- Authority view把该 tool标为 proposal-only。

但通用 `ToolCallRequest` 只有 `name + dict arguments`，没有 discriminated per-tool schema。Prompt只说 diagnosis“仍只是 proposal”，没有正向规定在 ready diagnosis Goal 下如何从候选形成可审批 action。Exact public action space又只列 investigation calls。

因此 `RESPOND` 的低承诺路径在 schema、validator和prompt上都比 diagnosis action更直接。这构成 `ACTION_SELECTION_CONTRACT_WEAKNESS`；是否是模型十次选择的心理原因无法由 artifacts证明。

## 7. Post-decision legality

如果模型输出合法 `submit_diagnosis`：

1. plan/action alignment会接受，前提是应用后的 active PlanStep使用相同 tool/diagnosis target；
2. ActionContract会接受公开 candidate、ready=true和已发现 evidence subset；
3. Authority返回 `PROPOSAL_ONLY`，创建revision-bound pending action；
4. fixed harness检测 pending并发送匹配 decision id、confirmation id、owner和case revision的 `APPROVAL`；
5. 下一次 Agent若重现同一 tool call，Authority转 autonomous；
6. CaseEngine记录 submitted diagnosis并开放相应 treatments。

已有 cooperative web测试证明完整 diagnosis proposal/approval路径会增加session revision并记录 diagnosis。两案 artifacts没有 diagnosis action、pending、validator error或authority rejection。

结论：`POST_DECISION_BLOCKER = NOT SUPPORTED`；Runtime不阻止合法 diagnosis。

## 8. Two-case comparison

| Dimension | Gray | Lantern | Same mechanism? |
|---|---|---|---:|
| ready turn | T7 | T7 | yes |
| public clues | 8 | 8 | yes count；content不同 |
| Goal | FORM_DIAGNOSIS | FORM_DIAGNOSIS | yes |
| Plan | new P=3 | new P=3 | structural yes；step content unproven |
| player branch | diagnosis request ×10 | diagnosis request ×10 | yes |
| decisions | RESPOND ×10 | RESPOND ×10 | yes |
| validator/authority errors | 0 | 0 | yes |
| fallback | 0 | 0 | yes |
| repair | 0 in stall | 1 in stall | difference does not change final behavior |

相同 case-independent request builder、schema、validator和runtime处理这两案。独立 case内容下产生相同 phase-level行为，强力支持共享 contract/context pattern；但 raw responses与active steps缺失，不能证明每次模型内部理由完全相同。

## 9. Root-cause matrix

| Classification | Role | Confidence | Evidence |
|---|---|---|---|
| `MODEL_DECISION_QUALITY` | direct cause | PROVEN behavior | 两案各10次真实非fallback RESPOND |
| `ACTION_SELECTION_CONTRACT_WEAKNESS` | primary upstream cause | HIGHLY SUPPORTED | RESPOND无条件合法；Goal/Plan与action无progress约束 |
| `LLM_CONTEXT_MISSING` | contributing factor | PROVEN narrow gap | exact action space只含investigation，不含diagnosis calls |
| `ACTION_SCHEMA_AMBIGUITY` | contributing factor | PROVEN | tool arguments为generic dict，无per-tool conditional shape |
| `PROMPT_INSTRUCTION_WEAKNESS` | contributing factor | HIGHLY SUPPORTED | 只说明权限边界，没有ready diagnosis action-selection规则 |
| `GOAL_PLAN_REPRESENTATION_BUG` | unproven | INSUFFICIENT EVIDENCE | Goal正确；active step内容未保存 |
| `RUNTIME_STATE_BUG` | excluded | NOT SUPPORTED | ready/Goal/session均正确 |
| `POST_DECISION_BLOCKER` | excluded | NOT SUPPORTED | 没有action到达后置层；合法路径有测试 |
| `BENCHMARK_HARNESS_ISSUE` | excluded | NOT SUPPORTED | public natural-language request有效，approval协议完整 |

Gray与Lantern共享上述根因组合。Direct cause不是笼统“模型不智能”，而是可观察的 action selection：在充分公开phase信号下选择了无进展但完全合法的 RESPOND。

## 10. Minimum recommended fix

优先级如下，只建议、不实施：

1. **Decision/action contract。** 定义 phase/active-step一致性：当 active plan step为 tool-oriented时，decision应执行同一合法tool，或显式 REVISE/BLOCK；不能以 KEEP plan + RESPOND无限规避active step。仍允许解释型PlanStep使用RESPOND。
2. **LLM context representation。** 将 validator-derived diagnosis proposals加入统一的 model-visible public action catalog，提供公开 `diagnosis_id` 与可引用 evidence ids；不要提供正确答案标记。
3. **Action/tool schema。** 使用按tool区分的参数schema或等价的typed public call representation，消除generic dict猜参。
4. **Prompt。** 只有在前述contract/action surface明确后，才用通用阶段语义说明“ready且Goal要求诊断时，应形成可审批proposal或显式说明并revision”，不得写case答案或benchmark特判。
5. **Runtime deterministic policy。** 不建议自动选择 diagnosis action；Runtime只应验证一致性和权限。
6. **Model replacement。** 当前没有足够证据先换模型；应先消除contract/context不对称后再比较。

最小第一 intervention应落在 **decision/action contract + model-visible action surface**。它保留 diagnosis候选与证据选择由Agent自主推理，只让可执行选择与当前Goal/Plan清晰对齐。

## 11. Explicit non-fixes

- 不实现 `FORM_DIAGNOSIS -> submit_diagnosis` deterministic rule。
- 不由Runtime选择 diagnosis id或evidence。
- 不将玩家自然语言直接转为tool call。
- 不在prompt加入Gray/Lantern答案或“调查完必须诊断”的无条件硬编码。
- 不改fixed script、max turns、success rule或case data。
- 不处理Old Paper、P0、Memory、Reflection、token或generic no-progress。
- 以上旁支均为 `OUT OF P1 SCOPE`。

Deterministic phase-to-tool rule不推荐，因为 `FORM_DIAGNOSIS` 表示Agent应推理并协商候选，不表示Runtime已经知道应选择哪个诊断；强制tool会把Agent的判断权转移给状态机，并可能在证据语义仍有歧义时制造自动提案。应确定性约束“行动与意图一致”，而非确定性生成“诊断内容”。

## 12. P1 implementation gate

可以进入一个严格版本化、单变量的P1实现：先统一 model-visible diagnosis action surface，并加强Goal/Plan/action一致性contract；补测试证明不泄露正确答案、RESPOND仍可用于合法解释步骤、diagnosis内容仍由Agent选择、后置authority不变。然后才允许新的3×1验证。

由于 active PlanStep内容与raw proposal未保存在现有 artifacts，P1不得声称已证明“active step就是submit_diagnosis”。实施前/同时应增加不进入prompt的脱敏 telemetry，以便下一次artifact直接验证step/action关系。

```text
GRAY ROOT CAUSE: MODEL_DECISION_QUALITY (direct) + ACTION_SELECTION_CONTRACT_WEAKNESS (primary upstream)
LANTERN ROOT CAUSE: MODEL_DECISION_QUALITY (direct) + ACTION_SELECTION_CONTRACT_WEAKNESS (primary upstream)
SHARED ROOT CAUSE: YES
RUNTIME BLOCKS DIAGNOSIS: NO
BENCHMARK ISSUE: NO
MINIMUM FIX LAYER: decision/action contract + model-visible diagnosis action surface
DETERMINISTIC FORM_DIAGNOSIS -> SUBMIT_DIAGNOSIS RECOMMENDED: NO
READY FOR P1 IMPLEMENTATION: YES
```
