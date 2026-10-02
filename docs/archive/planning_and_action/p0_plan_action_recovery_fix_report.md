# P0 Plan/Action Alignment Rejection Recovery Fix & Frozen 3×1 Benchmark Revalidation

## Outcome

```text
IMPLEMENTATION: PASS
TEST: PASS
RUNTIME RECOVERY CONTRACT: PASS
SAFETY REGRESSION: PASS

PRE-P0 BENCHMARK: 0 / 3
POST-P0 BENCHMARK: 0 / 3

OLD PAPER:
task success: FAIL
outside-plan count: 10
loop resolved: NO
recovery visible next turn: YES

GRAY:
task success: FAIL
diagnosis stall: PRESENT

LANTERN:
task success: FAIL
diagnosis stall: PRESENT

P0 RUNTIME FIX: FAIL
DIAGNOSIS STALL STILL PRESENT: YES
NEXT GATE: STOP
```

`P0 RUNTIME FIX` 按本阶段的组合成功判据评为 FAIL：runtime 已正确持久化并暴露 recovery feedback，但真实 Old Paper 仍出现 10-turn repeated mismatch loop。不能把“contract 已实现”误报为“真实 deadlock 已解决”。

## Exact pre-fix branch

修改前 `CooperativeRuntime.handle()` 的顺序为：

1. load/initialize AgentState；
2. 调用 `GameNPCAgent.propose_turn()`；
3. `GoalPlanPolicy.validate()`；
4. `_apply_proposal()`；
5. `_associate_decision()`；
6. `_action_matches_plan()`；
7. mismatch 时 advance AgentState revision、保存 state、返回 `action_outside_active_plan`。

该 early return 会保存 AgentState，且保留 proposal 已合法应用的 Goal/Plan change；但它不调用 PublicActionContractValidator、action repair、Authority、CaseEngine 或 PlanEvaluator。`last_plan_evaluation` 没有变化。下一轮 `GameNPCAgentInput.last_environment_feedback` 只从 `state.last_plan_evaluation.public_summary` 生成，因此拒绝原因只存在于上一轮 `CooperativeTurnResult`，下一轮模型不可见。

## Implementation

没有放宽 alignment gate，也没有自动选择 action 或修改 Plan。最小变更为：

- 在 `PlanEvaluationReason` 增加 `ACTION_OUTSIDE_ACTIVE_PLAN`；
- mismatch early-return 保存一条 `PlanEvaluation`：
  - outcome：`REVISE_PLAN`
  - before/after observation revision 相同
  - completed/obsolete step 均为空
  - current Goal status 不变
  - current active Plan 不变
- public summary 只说明：上一候选行动未执行；active Plan 仍权威；下一轮应选择对齐行动或提交合法 Plan revision。

Feedback 不包含正确 tool、active target、hidden truth、CaseEngine truth或 benchmark 提示。它只占用 `last_plan_evaluation` 单槽；重复 mismatch 会覆盖上一条而非累计历史。

真实 matching action 进入 CaseEngine 后，正常 DeterministicPlanEvaluator 会覆盖该 recovery evaluation。合法 Plan revision + matching action 仍遵循原有同-turn协议，没有新增 shortcut。

## Correctness and safety tests

新增测试覆盖：

1. outside-plan action 仍被拒；
2. CaseSession/world state 完全不变；
3. event sequences 为空；
4. active PlanStep 不被完成；
5. Goal 不被完成；
6. recovery evaluation 被持久化；
7. 下一 turn 的 `GameNPCAgentInput.last_environment_feedback` 可见；
8. feedback 有界且仅含公开安全语义；
9. feedback 不含正确 tool 或 target；
10. 重复 mismatch 仍被拒；
11. 单槽覆盖、无界历史不增长；
12. matching action 后恢复真实执行；
13. progress 后旧 recovery 被正常 evaluation 覆盖；
14. 合法 Plan revision + matching action 正常执行；
15. rejection 不写 world Memory；
16. 既有 alignment/action-contract/safety regression 继续通过。

验证结果：

- targeted：24 passed
- full pytest：100% passed
- production prompt、benchmark fixture/success rule/max turns、Authority、CaseEngine、Memory、Reflection 未修改

## Frozen benchmark integrity

Pre-P0 artifacts 保持不变：

- `evaluation_results/agent_task_benchmark_dry_run_v3/agent_task_benchmark_v1`
- manifest hash：`48145dfda078c604ceebf73cb90ee9fb59536f42d0921260dbd9036c5699e575`
- configuration hash：`c3a684b82cdd751578f6656dde1b63cd7c28c4741ddb34f1405f38f3be91e111`

Post-P0 使用同一 frozen manifest、3 cases、fixed script、16 turns、success rule、DeepSeek/Memory/Reflection 配置：

- `evaluation_results/agent_task_benchmark_post_p0/agent_task_benchmark_v1`
- manifest hash：`14a84dd17f0f961cd2ba46cf8f3b62aa1c692a29ac41d931f0c951d66023c94c`
- configuration hash：`166bb89e923008fc2b2a0b6cf43418278ead756d33f22ed7d1bd2a85343c108c`
- `cooperative_runtime.py` SHA-256：pre `9cd27f0d…` → post `2592832c…`
- 旧、新 aggregate 均与从各自 immutable run artifacts 的纯重算完全一致

Post-P0：3 episodes、0 success、3 `max_turns_exceeded`、0 provider abort、0 executed authority violation。估算费用 ¥0.1898684。

## Old Paper pre/post

| Metric | Pre-P0 | Post-P0 |
|---|---:|---:|
| last productive turn（world或Goal/Plan） | T5 | T6 |
| last world-changing turn | T4 | T5 |
| first mismatch | T6 | T7 |
| `action_outside_active_plan` | 11 | 10 |
| recovery generated | 0 | 10 |
| recovery observed next turn | 0 | 9 directly-following opportunities |
| post-recovery Plan revision | no | no |
| post-recovery matching productive action | no | no |
| CaseEngine events | 4 | 5 |
| final state | active | active |
| turns | 16 | 16 |

Post-P0 T1–T5 产生五次真实调查 event；T6 创建/更新 P=2 plan但只 `RESPOND`；T7 首次 mismatch。T7–T16 每次仍安全拒绝，且 artifact 现在记录 `plan_evaluation_outcome=revise_plan`，证明 recovery evaluation 被生成。T8–T16 的模型输入按已测试且固定的 state reload路径看到上一轮 feedback，共9个可观察的后继 turn；T16 没有 T17，所以不能算 observed-next-turn。

`OLD PAPER IDENTICAL LOOP RESOLVED: NO`。它多完成了一项调查、首次 mismatch 延后一轮，说明轨迹改变；但 recovery feedback 没促使模型提出 matching action 或 Plan revision，仍形成同构的10-turn死循环。

## Gray and Lantern observation only

两案均未作任何专项修改。

### Gray Hearth Inn

- T1–T6：6 次调查执行，达到 rev6/clues8
- T7：进入 `FORM_DIAGNOSIS` Goal并创建 P=3 plan
- T7–T16：10次 `request_public_diagnosis → RESPOND`
- `submit_diagnosis`：0
- task：FAIL，stall PRESENT

### Lantern Alley

- T1–T6：6 次调查执行，达到 rev6/clues8
- T7：进入 `FORM_DIAGNOSIS` Goal并创建 P=3 plan
- T7–T16：10次 `request_public_diagnosis → RESPOND`
- `submit_diagnosis`：0
- task：FAIL，stall PRESENT

按阶段约束，本轮到此停止，不实现 generic no-progress watchdog、diagnosis action-selection或 prompt fix。

## Token comparison

| Case | Game requests | Game input/output | Reflection requests | Reflection input/output | Total |
|---|---:|---:|---:|---:|---:|
| Old Paper | 18 | 124,347 / 8,586 | 4 | 18,351 / 5,989 | 157,273 |
| Gray | 17 | 117,638 / 9,428 | 5 | 23,087 / 7,245 | 157,398 |
| Lantern | 17 | 116,161 / 8,548 | 5 | 29,402 / 8,345 | 162,456 |
| Total | 52 | 358,146 / 26,562 | 14 | 70,840 / 21,579 | 477,127 |

Pre-P0 total 为442,164；post-P0 增加34,963。这里只记录差异，不把单次随机模型运行的 token 波动归因给 recovery 文本。

## Exact blocker and next gate

新的 exact blocker 是：**即使上一轮 mismatch 已通过既有 planning feedback channel 持久化并进入下一轮 GameNPCAgentInput，真实模型仍连续提出与 active PlanStep 不匹配的 action，也没有提交合法 Plan revision。**

这证明“反馈不可见”是原 loop 的真实 correctness bug，但不是充分根因。进一步处理需要超出本轮授权，可能涉及 model/prompt quality 或通用 bounded no-progress/replan design。

因此：

```text
RUNTIME RECOVERY CONTRACT: PASS
OLD PAPER TASK: FAIL
OLD PAPER IDENTICAL LOOP RESOLVED: NO
P0 RUNTIME FIX: FAIL
NEXT GATE: STOP
```
