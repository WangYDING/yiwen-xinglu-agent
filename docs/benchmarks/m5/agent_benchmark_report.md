# Cooperative Agent Benchmark M5：最终报告

## 报告范围

本报告记录《异闻行录》Cooperative Agent 的 M5 评测证据。M1～M5 指 Cooperation、Planning、Memory、Reflection 与 Benchmark 工作流。

M5 不新增 Agent 能力。它验证已有机制在受控条件下是否产生可观察工程收益，并把模型 proposal reliability 与确定性 system safety 分开测量。证据来自 M5-1～M5-12 已完成的 deterministic paired ablations、真实模型小型 Pilot、sanitized telemetry 和失败诊断；M5-13 没有再次调用模型。

## Benchmark objective

评测覆盖五个方面：

- Cooperation：是否独立评价玩家贡献，并遵守公开行动与权限边界；
- Planning：Goal/Plan 是否产生可观察的 revise/replan 行为；
- Memory：相关记忆是否经历 selected → declared → accepted，并带来合法行为差异；
- Reflection：验证后的经验是否能进入未来 Episode，弱证据是否被拒绝；
- Safety boundaries：Authority、PublicActionContract、GoalPlanPolicy、fallback 与 CaseEngine 是否阻止危险或无效执行。

## System variants

| Variant | 最小定义 |
|---|---|
| `V0_BASELINE` | 无 Cooperative Planning、Memory 或 Reflection 的基线行为 |
| `M1_COOPERATIVE` | 增加玩家贡献评价与受限公开 Decision |
| `M2_PLANNING` | 增加受限 Goal/Plan proposal 与确定性生命周期策略 |
| `M3_MEMORY` | 增加安全检索、显式 usage declaration 与确定性 acceptance |
| `M4_REFLECTION` | 增加受验证 Reflection、持久化 Memory 与未来 Episode retrieval |

这些变体用于机制消融，不代表五个独立产品版本。

## Deterministic paired ablations

M5-2 共运行 5 个同条件 pairs：

| Outcome | Count |
|---|---:|
| `IMPROVED` | 3 |
| `EXPECTED_NOOP` | 2 |
| `REGRESSED` | 0 |
| `NOT_COMPARABLE` | 0 |

### Planning

在冻结的同条件 fixture 中，`PlanEvaluator` 真实产生 `REVISE_PLAN`，并出现 observable replan / plan behavior change。Planning positive paired fixture 判定为 `IMPROVED`。这证明受控机制差异，不表达百分比性能提升。

### Relevant Memory

在相同 Observation、Contribution 与 Authority 下，无记忆与有相关记忆产生不同但合法的行为；treatment 中记忆经历 selected → declared → accepted。Relevant Memory positive fixture 判定为 `IMPROVED`。

### Irrelevant Memory

无关记忆可以进入候选或 selected surface，但没有被 declared/accepted，行为保持 baseline。该 pair 判定为 `EXPECTED_NOOP`。

### Reflection Learning

Episode A 的 Experience 经 Reflection 验证后形成 validated Memory 并写入 repository；Future Episode B 检索并接受该 Memory，产生合法行为变化。该 pair 判定为 `IMPROVED`。

### Reflection Pollution Control

弱 Reflection 返回 `REJECT_WEAK_EVIDENCE`，不持久化 Memory，未来行为不变。该 pair 判定为 `EXPECTED_NOOP`。

## Real-LLM pre-fix failure

M5-3 使用 `deepseek-v4-flash` 运行 9 次真实 Pilot，9/9 进入 safe fallback。M5-4 后续诊断确认首个失败链为：

```text
provider success
→ finish_reason=length
→ deepseek_output_truncated
→ no complete LLMResponse
→ parser not reached
→ safe fallback
```

根因是复杂 `GameNPCTurnProposal` 沿用全局 `max_output_tokens=512`，完整 proposal 在 parser 前被截断。早期报告中的 “18 inferred calls” 与 “9/9 REPAIR_EXHAUSTED” 是由 fallback 反推的错误解释，已被真实 telemetry 证伪，不作为 M5 结论。

## Failure-analysis timeline

排障严格采用以下循环：

```text
observe
→ locate first failure
→ single-variable fix
→ re-run the same path
→ observe the next failure
```

没有同时修改 Prompt、schema、parser 与 policy。

### Failure 1 — Output truncation

- 观察：provider 成功，但 `finish_reason=length`；parser 未运行；
- 根因：512 output tokens 无法容纳真实 planning proposal；
- 单变量修复：只给 planning request 设置 bounded `max_output_tokens=2048`；其他简单请求不扩大；
- 结果：真实 response 完整到达 parser。

### Failure 2 — Invalid Tool Arguments

- 观察：JSON 与 `GameNPCTurnProposal` schema 均通过；模型选择 `question_patient`，但 ToolCall 没有严格使用 `{"investigation_id": "<public-id>"}`；
- 错误：`invalid_tool_arguments`；
- 根因：模型能看到公开 investigation，却看不到与 validator 完全一致的 exact public Action Space；
- 单变量修复：从 `CaseObservation.available_investigations` 与 `INVESTIGATION_TOOL_BY_ACTION` 投影 authoritative public Action Space；
- 安全边界：hidden investigation 不进入投影，`PublicActionContractValidator` 未放宽；
- 结果：真实 Decision 使用合法 tool、公开 ID 和 exact arguments。

### Failure 3 — Invalid Planning Target

- 观察：Decision 已通过 PublicActionContract，但 PlanDraft 的 `suggested_tool` / `public_target_id` 引用了 unavailable target；
- 错误：`goal_plan_investigation_target_is_hidden_stale_or_unavailable`，path 为 `plan_update.draft.steps`；
- 根因：Decision 已受 exact Action Space 约束，PlanDraft 尚未获得同一个 tool/target binding guidance；
- 单变量修复：Plan 与 Decision 复用同一个 authoritative public Action Space projection；
- 安全边界：Plan schema 与 `GoalPlanPolicy` 均未放宽；
- 结果：真实 Plan steps 与 Decision 均通过确定性验证。

## M5-12 post-fix real-model pilot

模型为 `deepseek-v4-flash`。固定实验包含 Prompt Injection 3 runs、Relevant Memory baseline 3 runs、Relevant Memory treatment 3 runs，共 9 runs。每个 run 都基于真实 opt-in sanitized telemetry 统计，不根据 fallback 推断 repair 或 truncation。

### Proposal reliability

| Metric | Result |
|---|---:|
| Complete initial response | 9/9 |
| Parser reached | 9/9 |
| Schema valid | 9/9 |
| PublicActionContract pass | 9/9 |
| GoalPlanPolicy pass | 9/9 |
| Direct proposal success | 9/9 |
| Repair attempted | 0/9 |
| Fallback used | 0/9 |
| Output truncation | 0/9 |

这是 small real-model pilot 的描述性结果，不是统计显著性 benchmark，也不证明生产分布成功率。

## Prompt Injection：模型层与系统层

### Model proposal robustness

- direct valid proposal：3/3；
- contribution disposition：`REJECT` 3/3；
- premature treatment proposal：0；
- selected legal investigation：3/3，均为 `question_patient → ask_about_memory`；
- repair / fallback：0/3。

### System safety robustness

- authority violation：0；
- treatment without confirmation：0；
- diagnosis bypass：0；
- CaseEngine bypass：0；
- executed domain tool：3 次合法 `question_patient`。

模型 proposal 是否理想与系统是否安全是两个指标。M5-3 的模型输出路径失败时，deterministic fallback、Authority 与 CaseEngine 仍未允许危险执行；M5-12 修复后，模型层也产生了合法 proposal。安全设计不能依赖“LLM 永远正确”。

## Relevant Memory real A/B

Baseline 与 treatment 使用相同 scenario fixtures、model、Authority、Goal/Plan initialization、PlayerContribution、runner 与 structured-output contract，仅 relevant memory 条件不同。

| Observable field | Baseline ×3 | Treatment ×3 |
|---|---|---|
| selected | 0/3 | 3/3 |
| declared | 0/3 | 3/3 |
| accepted | 0/3 | 3/3 |
| Goal operation | `KEEP` | `KEEP` |
| Plan operation | `CREATE` | `CREATE` |
| Plan order | question → inspect → observe | observe → inspect → question |
| Tool | `question_patient` | `observe_patient` |
| Public target | `ask_about_memory` | `observe_scholar` |
| fallback | 0/3 | 0/3 |

Paired observable difference：

- Goal operation changed：0/3；
- Plan operation changed：0/3；
- Plan structure/order changed：3/3；
- Tool priority changed：3/3；
- legal behavior changed：3/3。

准确结论是：在这次 3-run real-model pilot 中，相关记忆在全部 treatment runs 中被 selected、显式 declared 并 accepted；在其他 benchmark 条件可比时，它与合法的 Plan 排序和 tool priority 变化同时出现。该结果不能表述为“Memory 提升 Agent 100%”。

## Evidence hierarchy

### Demonstrated deterministically

- Planning fixture 能触发真实 `REVISE_PLAN` 与可观察 replan；
- Relevant Memory 可完成 selected → declared → accepted 并改变合法行为；
- Irrelevant Memory 不被 accepted，行为保持 baseline；
- validated Reflection 可形成未来可检索 Memory；
- weak Reflection 被拒绝且不污染 repository；
- Authority、PublicActionContract、GoalPlanPolicy、fallback 与 CaseEngine 保持确定性边界。

### Observed in the real-model pilot

- `deepseek-v4-flash` post-fix 9/9 initial proposals 完整且直接通过 schema、PublicActionContract 与 GoalPlanPolicy；
- Prompt Injection 3/3 在模型层拒绝越权指令，在系统层无危险执行；
- Relevant Memory treatment 3/3 declared/accepted，并出现合法 Plan order 与 tool-priority 差异；
- 0 repair、0 fallback、0 truncation。

### Not yet established

- statistical generalization；
- multi-model robustness；
- production latency、token accounting 与成本；
- 大规模或生产分布 benchmark performance；
- 真人玩家收益、留存或教学效果。

## Limitations

- 每个 real condition 只有 3 repeats；
- 只测试 `deepseek-v4-flash` 一个真实模型；
- scenario 覆盖有限；
- 没有统计显著性分析；
- token / latency 为 `not_currently_observable`，未计算货币费用；
- `plan_step_completion` 为 `not_currently_observable`；
- 没有多模型比较；
- deterministic fixtures 证明受控条件下的机制行为，不等同生产分布性能；
- real Memory A/B 只是小样本描述性证据；
- 本报告评测的是当前 Cooperative GameNPC 工程路径，不代表真人玩家收益。

## Reproducibility and preserved artifacts

M5-12 的 sanitized artifacts 已长期保存：

- `m5_12_postfix_real_benchmark.json`：9 个 run 的历史 sanitized telemetry、公开行为快照与 runner report；完整文件已移至本地 private research archive，不进入 public repository；
- [`m5_12_pre_post_summary.json`](m5_12_pre_post_summary.json)：纠正后的 M5-3/M5-12 对比、Prompt Injection、Memory A/B 与 limitations 摘要。

Artifacts 不含 API key、raw prompt、raw private response、hidden case truth、chain-of-thought 或 private system prompt。M5-13 未重新执行 provider calls。

SHA-256：

```text
9BB1CC5D2DDCBAFA89A331E4CA9F4E2CDEE6BB425384FA6DA1DFF72EE67AEA20  m5_12_postfix_real_benchmark.json
3B80E2EC282B9712AFFF7030FF435A3A8FC1ED590F3455A9D82CCF428F6EA46C  m5_12_pre_post_summary.json
```

## M5 seal

M5 在以下状态封版：deterministic paired mechanisms 有正向与预期 no-op 证据；真实模型路径的三个连续 first failures 已按单变量方法定位并修复；post-fix 9-run pilot 获得完整 proposal、合法 contracts、Prompt Injection 双层安全与 Relevant Memory 描述性行为差异。未建立的统计、跨模型和生产结论继续明确保留为限制，不在 M5 内扩展。
