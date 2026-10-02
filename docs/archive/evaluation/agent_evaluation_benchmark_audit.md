# 《异闻行录》Agent Evaluation & Benchmark Audit

审计日期：2026-08-26  
范围：当前工作树中的 `src/xuanyi_npc/evaluation/`、`tests/`、`tools/experiments/`、`docs/benchmarks/`、`runtime_data/`、CaseEngine/Agent telemetry。  
约束：严格只读审计；未修改 production code、测试、prompt、配置、Memory、Reflection、CaseEngine、Agent Runtime 或现有数据。本文件是唯一新增产物。

## Executive conclusion

当前仓库能够可靠回答：

- Agent/Runtime 的契约和安全边界是否按设计工作；
- 正式 executable、真实 DeepSeek、BGE-M3、SQLite、restart/new-session 链路是否真实闭合；
- 在一个冻结案例的少量真实模型 runs 中，proposal 是否有效、prompt injection 是否被安全处理、注入的相关 Memory 是否与合法行为差异同时出现；
- semantic retriever 在冻结 Gold/Holdout 上的 ranking/classification 与隔离指标。

当前仓库**不能**可靠回答总体问题“这个 Agent 的任务表现有多好”：没有覆盖六个正式 case 的统一 terminal task benchmark，没有标准化的完整 investigation→diagnosis→treatment 玩家脚本，没有当前可复跑的 production-equivalent multi-run harness，没有 Memory/Reflection 对 CaseEngine terminal success 的公平消融，也没有 mean/std、置信区间或 bootstrap。

最重要的审计发现是：`real_agent_benchmark.py` 名称大于其真实能力。其历史 M5-12 artifact 是有价值的 9-run real-LLM bounded pilot，但：

1. 只使用 `old_paper_umbrella`；
2. 每 run 通常只有一个 turn；
3. `task_completed/scenario_success` 实际由“没有危险治疗执行且能独立判断”构造，不等于 `CaseSessionState.COMPLETED`；
4. Memory 是 `_ControlledMemoryService` 直接注入的 synthetic `AgentMemoryContext`，不经过 SQLite/BGE retrieval；
5. 没有 Reflection service；
6. 当前 executor 运行时依赖已删除的 `xuanyi_npc.evaluation.m5_p4b_runner.build_service`，所以历史 real pilot 不能由当前工作树原样复跑。

因此其最终分类为：

```text
REAL_AGENT_BENCHMARK_CLASSIFICATION: ACCEPTANCE HARNESS
```

更精确地说：它是**历史可运行、当前 wiring 失效的 bounded real-LLM proposal/safety/memory-influence acceptance harness**，不是完整 Agent task benchmark。

## 1. Evaluation vs Test vs Acceptance

### 1.1 在本项目中的严格定义

| 概念 | 《异闻行录》中的定义 | 能回答 | 不能回答 |
|---|---|---|---|
| Unit / Contract Test | 单个 Pydantic/domain/policy/validator/repository 函数在固定输入下是否满足契约 | schema、规则、边界是否正确 | 真实模型整体任务表现 |
| Integration Test | 多个真实 application/runtime 组件在临时 store 中协作，通常注入 Stub/Fake Agent/embedding | 组件 wiring、状态/失败语义 | provider/BGE/生产分布表现 |
| Production Acceptance | 正式 executable 与真实依赖在少量人工流程中是否闭环 | “能不能真实运行”、具体链路是否发生 | 平均水平、泛化、显著性 |
| Regression Test | 固定历史 bug/边界不会复发 | correctness 未倒退 | Agent 是否优于 baseline |
| Agent Evaluation | 在明确任务、输入、终止与评分规则下观察 Agent 行为质量 | 某任务维度做得怎样 | 若无 baseline/repeats，不能给普遍结论 |
| Benchmark | 冻结 scenario、variant、runner、metric、artifact 和可重复执行协议 | 可比较的跨 run/variant 结果 | 不自动等于统计推断 |
| Ablation | 除被研究能力外，其他起点/输入/runtime/model 尽量相同的 paired comparison | Memory/Reflection 等机制的增量作用 | 非等价产品模式间的因果结论 |
| Statistical Performance Evaluation | 多 case、多独立 run，报告分布、不确定性与 paired effect | 均值/方差/CI、效果稳定性 | 单次 smoke 无法替代 |

### 1.2 469 pytest 证明什么

当前审计前一轮实跑为 `469 passed`。它证明当前测试所覆盖的 domain contracts、CaseEngine规则、Goal/Plan、Action/Authority、Memory/Reflection、SQLite migration/reconciliation、Web/application wiring 与 evaluation runner contracts 没有触发已编码断言。

它不证明：

- 469 个独立“玩家任务”成功；
- 真实 DeepSeek 在 469 个 episodes 上表现良好；
- 所有正式 case 均被 Agent 完整通关；
- Memory/Reflection 提升 task success；
- 真实模型输出分布或生产延迟稳定。

大量 tests 使用 `StubAgent`、`FakeRealExecutor`、scripted adapter、`DeterministicFakeEmbedding`。这是正确的工程测试方法，但不能转写成模型 benchmark。

### 1.3 Production acceptance 证明什么

现有 acceptance 证明正式 `yiwen-xinglu.exe` 能调用真实 DeepSeek、production BGE-M3、SQLite，在真实 CooperativeRuntime/CaseEngine 路径中完成事件、Memory/Reflection、restart/new session、exact Memory ID 和 accepted-used attribution。

它仍不能替代 Agent benchmark，因为输入不是覆盖任务分布的冻结 suite，样本少，case coverage有限，无并行 variant control、重复次数、统计 aggregation 或统一 terminal success rule。Acceptance 回答“链路是真的”；benchmark 才回答“在固定任务集合上表现怎样”。

## 2. Existing Evaluation Assets

### 2.1 资产总表

| 文件/模块 | 类型 | 输入 | 输出 | 真实 LLM | 真实 BGE | 多 case | 多 run | 指标 | 真正 Agent Evaluation |
|---|---|---|---|---:|---:|---:|---:|---:|---:|
| `tests/test_case_engine.py`、`test_domain_models.py` | unit/regression | 固定 command/state | event/state/assertion | 否 | 否 | 否 | 否 | domain correctness | 否 |
| `tests/test_m1_*`～`test_m4_*` | contract/integration/regression | fixed contributions、Stub/scripted Agent | turn/state/receipt assertions | 通常否 | 通常 fake | 主体单案 | 否 | 机制指标/断言 | 部分机制评估 |
| `tests/test_m5_agent_benchmark.py` | benchmark contract test | synthetic runs | stable aggregate/failure taxonomy | 否 | 否 | 模型字段支持，fixture单案 | synthetic | 是 | 否；验证 evaluator |
| `tests/test_m5_agent_benchmark_pairs.py` | deterministic paired mechanism harness | paired fixed fixtures | improved/noop/regressed | 否 | fake | 单案 | 固定 pair | 是 | 是，机制级，不是任务级 |
| `tests/test_m5_real_agent_benchmark.py` | runner test | `FakeRealExecutor` | repeat/aggregate/error mapping | 否 | 否 | 否 | 是 | 是 | 否；验证 harness contract |
| `src/.../evaluation/agent_benchmark.py` | observer/scorer library | `CooperativeTurnResult[]` | metrics/run/pair summary | 中立 | 中立 | 支持字段 | 支持 aggregation | 是 | 可作为组成部分 |
| `src/.../evaluation/real_agent_benchmark.py` | bounded pilot harness | 4 scenario types；CLI实际选2类 | JSON/JSONL summaries | 设计上是 | 否，controlled context | **否** | 1–3 | proposal/safety/memory行为 | **Acceptance harness** |
| `docs/benchmarks/m5/m5_12_postfix_real_benchmark.json` | frozen historical artifact | 9 old-paper-umbrella runs | sanitized run+telemetry | 是 | 否 | 否 | 3/condition | 是 | 小型描述性 Agent evaluation |
| `docs/benchmarks/m5/agent_benchmark_report.md` | historical report | M5 deterministic + real pilot | 人工总结 | 部分 | fake/no BGE | 否 | 部分 | 是 | 部分；非当前可执行证明 |
| `semantic_holdout_runner.py` + 36-scenario data | retriever benchmark | synthetic public query/candidates，12 calibration+24 final | R@1/R@3/MRR、macro/micro P/R/F1、安全计数、资源指标 | 否 | **是** | synthetic case IDs | 单冻结向量run | 是 | Memory retriever evaluation，不是 Agent task eval |
| M4.5 Gold v1/v2（15 scenarios） | semantic retrieval calibration/regression | 5 calibration+10 test | ranking/classification metrics | 否 | 可用真实 BGE | synthetic | 否 | 是 | 否 |
| `tests/test_semantic_holdout_*` | holdout contract/regression | frozen data/config | threshold/identity/repro checks | 否 | 测试不等于真实run | synthetic | 否 | 是 | 否 |
| `smoke_bge_m3_offline.py` / `m45_p1_bge_smoke.json` | component smoke | known texts/model manifest | vector identity/dimension/resource | 否 | 是 | 否 | 否 | 资源/一致性 | 否 |
| `runtime_data/phase_b_smoke_v2` | production acceptance | 手工 Session A/B | SQLite/BGE/restart/use artifacts | 是 | 是 | 单案 | 少量 turns | lifecycle telemetry | 否 |
| `runtime_data/phase_c_*smoke` | diagnostic smoke sequence | 单个固定流程 | failure stage/Memory/receipt | 是 | 是 | 主要单案 | 否 | diagnostics | 否 |
| `phase_c_incremental_index_acceptance` / `receipt_final_acceptance` | production acceptance | old umbrella + gray hearth staged flow | Reflection/index/restart receipts | 是 | 是 | 2案 artifact | 少量 | lifecycle fields | 部分链路评估，非任务 benchmark |
| `tests/fixtures/event_replay/*.json` | safety regression fixtures | unsafe treatment/repeated investigation | expected replay result | 否 | 否 | 单案 | 否 | rule outcome | 可复用 scenario，不是现成 benchmark |
| `structured_output_diagnostics.py` | diagnostic evaluator | model/parse attempt telemetry | failure stage/code | 可观察真实调用 | 否 | 无关 | 可聚合 | reliability metrics | proposal reliability 子评估 |
| `evaluation/costing.py` | cost helper | `ModelUsage`/price config | cost projections/usage summary | 不调用 | 否 | 无关 | 可聚合 | token/cost | 辅助，不是 Agent eval |

### 2.2 名称不能替代分类

- semantic holdout 是严肃的 retriever benchmark，但评的是 retrieval，不是 Agent task completion。
- M5 real benchmark artifact 是真实 LLM 小样本评估，但 runner 的 success 不是 case success。
- smoke/acceptance 是 production truth evidence，不是 performance benchmark。
- pytest 中的 paired tests 是机制消融证据，不是生产模型统计结果。

## 3. `real_agent_benchmark.py` Audit

### 3.1 十六个答案

1. **评什么**：prompt injection/wrong suggestion 下 proposal与system safety；新证据后的 replan；相关/无关 controlled Memory 下 selected/declared/accepted 与 tool/plan差异；repair/fallback/一致性。
2. **输入来源**：代码内 `_contribution()` 固定自然语言；case 固定 `old_paper_umbrella`；Memory 由 `_memory_context()` 代码内构造。
3. **正式 CooperativeRuntime**：是，直接实例化当前 `CooperativeRuntime`；但 service builder 来自历史 evaluation helper，而不是正式 `clinic.server:main` composition。
4. **真实 GameNPCAgent**：设计上是 `GameNPCAgent(adapter)`。
5. **真实 DeepSeek**：CLI 通过 `DeepSeekChatAdapter.from_env()`；历史 M5-12 artifact 确实为 `deepseek-v4-flash`。
6. **Goal/Plan**：是，走 `propose_turn()` 和 policy/runtime state。
7. **Action Contract/Authority**：是，走 CooperativeRuntime 默认 validator/policy。
8. **CaseEngine**：设计上会通过 `MultiCaseEpisodeService` 执行合法调查；历史 artifact 有 `action_executed`。但当前 helper 缺失，无法从当前代码原样复跑到此处。
9. **Memory**：只用 `_ControlledMemoryService` 注入 synthetic already-selected context；不走 SQLite、BGE、真实 query/filter/index。
10. **Reflection**：不使用；未向 Runtime 注入 `reflection_service`。`variant=M4_REFLECTION` 标签因此会误导。
11. **多个 case**：否，只写死 `old_paper_umbrella`。
12. **重复运行**：支持 1–3 repeats；CLI实际 Prompt Injection 与 Relevant Memory baseline/treatment 共9 runs（repeats=3）。
13. **seed**：不支持 seed；repeat index只改变 identity，不控制 provider RNG。
14. **输出 metrics**：scenario success、legal tool、authority violation、fallback/repair、behavior consistency、selected/declared/accepted Memory、tool distribution、paired behavior/legal change、token/latency totals（有值才聚合）、failure distribution。
15. **能否回答任务性能**：不能。`task_completed` 是 `authority_safe and independent`，没有检查 CaseEngine terminal state、diagnosis/treatment correctness或score；通常一轮即止。
16. **本质**：历史上是 bounded smoke/acceptance + proposal behavior pilot；当前是 runner contracts仍受测试、真实 executor wiring失效的 acceptance harness。

### 3.2 当前可执行性缺口

`DeepSeekCooperativePilotExecutor.execute()` 运行时导入：

```python
from xuanyi_npc.evaluation.m5_p4b_runner import build_service
```

当前 `src/xuanyi_npc/evaluation/m5_p4b_runner.py` 不存在。CLI `--help` 可工作，runner用 fake executor 的 tests可通过，但配置真实 adapter后执行 scenario会在调用 provider之前/附近因缺模块失败。旧 artifact 仍是历史证据，不能宣称当前 harness 可复跑。

### 3.3 最终分类

```text
REAL_AGENT_BENCHMARK_CLASSIFICATION: ACCEPTANCE HARNESS
```

原因：真实 LLM + Runtime + policy + engine 的小型固定场景是实质性 acceptance；但它无 terminal task metric、单案/单轮、Memory绕过真实 retrieval、无Reflection，且当前 wiring broken，不满足 FULL/PARTIAL task benchmark 的最低可执行条件。

## 4. Case Coverage

### 4.1 正式 case 数量与 ID

当前 package resources 有 **6** 个正式可运行 case：

1. `old_paper_umbrella`
2. `gray_hearth_inn`
3. `moon_well_echo`
4. `lantern_alley_conflicting_testimony`
5. `mist_ferry_borrowed_lantern`
6. `returning_contract_nameless_shrine`

每案资源均提供 investigation、diagnosis candidates、treatments 与 CaseEngine completion规则；但“资源可运行”不等于“被Agent benchmark覆盖”。

### 4.2 Case × Evaluation Coverage Matrix

| Case | Unit/domain tests | M5 deterministic pairs | M5 real LLM | Production acceptance | 完整 task completion benchmark |
|---|---:|---:|---:|---:|---:|
| `old_paper_umbrella` | 强 | 是 | **是，唯一** | 强（Phase B/C） | 否 |
| `gray_hearth_inn` | resource/service级 | 否 | 否 | 有后到 Reflection acceptance | 否 |
| `moon_well_echo` | resource/helper级 | 否 | 否 | 未见完整 Agent acceptance | 否 |
| `lantern_alley_conflicting_testimony` | resource/package级 | 否 | 否 | 未见 | 否 |
| `mist_ferry_borrowed_lantern` | resource/package级 | 否 | 否 | 未见 | 否 |
| `returning_contract_nameless_shrine` | resource/package级 | 否 | 否 | 未见 | 否 |

现有 real evaluation 主要覆盖初始 investigation；Prompt Injection覆盖危险 treatment诱导，但没有完成真实 confirmation→treatment闭环。diagnosis correctness、treatment correctness与全 episode terminal completion没有进入 M5 real pilot。不同权限模式主要由tests覆盖，失败情形由 contract/replay/diagnostic tests覆盖。

## 5. Current Metric Capability

优先使用 CaseEngine/domain权威字段，不另造 success。

| 指标 | 分类 | 权威来源/限制 |
|---|---|---|
| case completion | AVAILABLE DIRECTLY | `CaseSessionState.status == COMPLETED` |
| episode completion | AVAILABLE DIRECTLY | public observation/session status；本项目case episode同一边界 |
| goal completion | AVAILABLE DIRECTLY | `AgentGoalState.status` / `PlanEvaluationOutcome.COMPLETE_GOAL` |
| diagnosis correctness | DERIVABLE | completed result/CaseEngine score、case正确 diagnosis定义；须明确分母与是否允许错误后修正 |
| treatment correctness | DERIVABLE | `selected_treatment_id`、`TreatmentOutcome`、score breakdown/case rules |
| reward/score | AVAILABLE DIRECTLY（terminal） | `ScoreBreakdown`/completed episode result；当前benchmark未收集 |
| action success | DERIVABLE | `CooperativeTurnStatus.ACTION_EXECUTED` + event sequences；RESPOND不能混入分母 |
| plan completion | AVAILABLE DIRECTLY | `AgentPlan.status` / evaluation outcome；历史 observer标过not observable是旧snapshot投影限制，不是当前state完全缺失 |
| number of turns | DERIVABLE | contribution/result序列；需固定turn定义 |
| tool calls | AVAILABLE DIRECTLY | selected tool/action history/events；需区分proposal与execution |
| invalid actions | UNSAFE / AMBIGUOUS | current turn result只保留最终repaired/fallback decision；首次非法proposal细节需diagnostic hook汇总 |
| rejected actions | AVAILABLE DIRECTLY | `ACTION_REJECTED` + error code |
| confirmation count | DERIVABLE | `CONFIRMATION_REQUIRED`/`PROPOSAL_PENDING` turn count |
| fallback count | AVAILABLE DIRECTLY per in-memory result | `used_fallback`/planning diagnostics；长期artifact需显式持久化/runner收集 |

“success”必须至少定义为 CaseEngine权威 terminal completion，并可辅以正确 diagnosis/treatment/score阈值。M5旧 `task_completed=authority_safe` 不能复用于任务完成率。

## 6. Planning Evaluation

| 指标 | 当前直接计算 | 需要新增 evaluator | 需要新增 telemetry | 说明 |
|---|---:|---:|---:|---|
| goal completion rate | 状态/turn可取 | 是（跨episode聚合） | 否 | 需定义每episode goals分母 |
| plan completion rate | 状态可取 | 是 | 建议保留历史 transitions | 只看最终state会漏中间废弃plan |
| plan revision count | 当前revision近似 | 是 | **是，若要精确事件数** | revision含create/other update，不能盲当revision次数 |
| plan abandonment count | terminal state/turn可取 | 是 | 建议 lifecycle event | 多plan历史可能丢失 |
| repeated revision | Reflection trigger/receipt部分可取 | 是 | 是 | 当前trigger仅特定revision语义 |
| active step success rate | post evaluation可取 | 是 | 建议逐turn plan step receipt | 当前final AgentState不足以还原所有steps |
| action outside active plan | result error可取 | 是 | 需要保存每turn结果 | production state不长期保存全部turn result |
| average steps per goal | DERIVABLE for retained plan | 是 | 需要历史plan | revise会覆盖旧plan版本 |
| average turns per completed goal | DERIVABLE | 是 | 需要turn/goal lifecycle log | 现有JSON最终state不足 |

结论：模型/Runtime具备产生这些信号的基础，但需要只读 observer/evaluator和append-only run artifact，不能只在run结束读取最终 AgentState。

## 7. Action / Safety Evaluation

### 7.1 可评能力

| 指标 | 当前支持程度 | 关键问题 |
|---|---|---|
| invalid action rate | PARTIAL | final result有reject；首次proposal若repair成功需diagnostic telemetry |
| contract rejection rate | PARTIAL | error/recovery path存在；需区分first proposal与terminal outcome |
| authority violation attempts | PARTIAL | agent proposal可分类；当前标准result不总保留pre-policy attempt |
| unsupported tool rate | PARTIAL | schema/contract可能先挡住；需统一proposal denominator |
| confirmation-required compliance | AVAILABLE | pending/approval decision ID+revision与executed action可关联 |
| diagnosis proposal-only compliance | AVAILABLE | authority mode/status/tool |
| treatment confirmation compliance | AVAILABLE | confirmation receipt与execution |
| suggestion accept/reject | AVAILABLE | `PlayerContributionEvaluation.disposition` |
| tool execution success rate | AVAILABLE/DERIVABLE | executed vs rejected，并用CaseEngine receipt |

### 7.2 必须分开的两个指标

```text
LLM proposal violation rate
= 非法/越权 first proposals ÷ LLM action proposals

Executed authority violation rate
= 最终实际执行的越权 actions ÷ executed actions
```

第一个可以大于0，用来评价模型 proposal quality；第二个目标必须为0，用来评价Runtime安全。当前 Runtime边界可保证/测试后者，diagnostic hook能支持前者的一部分，但production默认持久化不足以稳定重建所有pre-repair proposals。

## 8. Memory Evaluation

| 指标 | 当前能力 | 说明 |
|---|---|---|
| candidate recall | 有独立Gold/Holdout；Agent turn无gold | retrieval benchmark可算R@K；production只知candidate IDs |
| selected rate | 可算 | selected turns / retrieval-eligible turns，必须固定分母 |
| declared-used rate | 可算 | declared / selected turns或IDs |
| accepted-used rate | 可算 | accepted / selected或declared；报告分母 |
| retrieval-to-use conversion | 可算 | accepted-used retrievals / successful nonempty retrievals |
| cross-session retrieval rate | 可算 | source_session与current_session |
| current-session exclusion correctness | 可直接安全检查 | recalled current-session count目标0 |
| irrelevant memory rate | 只在有gold/label suite可算 | production无相关性ground truth |
| conflicting memory rejection | 部分可算 | projection conflict flag/rejection；需记录pre-filter候选 |
| influence types | 可算 | goal/plan/decision/tool priority/communication flags |

现有证据：

- semantic Gold/Holdout是真BGE retriever benchmark；
- deterministic M5 pairs验证Memory机制；
-历史M5-12做了3× baseline/treatment真实LLM controlled-context paired pilot；
- production acceptance证明真实SQLite/BGE/new-session/accepted-used。

**GAP**：没有当前可复跑、走production SQLite+BGE、以CaseEngine task success为结果的 Full Memory vs No Memory benchmark。历史 `_ControlledMemoryService` A/B只研究上下文存在与否对proposal的影响，不是完整Memory subsystem消融。

## 9. Reflection Evaluation

| 指标 | 当前能否统计 | 来源/缺口 |
|---|---:|---|
| trigger count | 是 | turn results/SQLite receipts |
| proposal generation success rate | 是 | proposal status/receipt |
| repair rate | 是 | generation attempt telemetry |
| fallback rate | 是 | lifecycle/proposal status |
| finding validation pass rate | PARTIAL | accepted proposal包含通过者；被逐finding拒绝的完整分母未独立持久化 |
| lesson validation pass rate | PARTIAL | candidate/write decisions；schema阶段被删/整包fallback需统一分母 |
| write_new / reject_weak_evidence | 是 | write decisions |
| Learning Memory write rate | 是 | written IDs / valid triggers或candidates，需明确分母 |
| index success/pending/recovery | 是 | receipt index status/reconciliation fields |
| cross-session retrieval rate | 是 | Memory source/current session |
| accepted-used Reflection Memory rate | 是 | accepted IDs join `projection_version=reflection_memory_v1` |

**GAP**：没有 Reflection ON vs OFF 的可重复、公平、跨Session任务消融。M5 deterministic reflection pair使用 scripted/fake components；production acceptance只证明ON链路；`real_agent_benchmark.py`没有注入Reflection，即使variant标签叫M4也不是Reflection组。

## 10. Latency / Cost Evaluation

| 指标 | 状态 | 说明 |
|---|---|---|
| GameNPCAgent latency | AVAILABLE in `ModelUsage`, but not reliably persisted by default UI/state | runner必须从decision usages/diagnostic hook收集 |
| Reflection latency | PARTIAL | adapter usage对象有latency，但当前 persisted lifecycle projection主要保留tokens/request metadata，未稳定暴露总latency |
| LLM request count | DERIVABLE | attempts/usages + Reflection receipts；需避免repair/fallback反推 |
| input/output tokens | AVAILABLE | `ModelUsage`; Reflection receipt有input/output tokens；历史M5 report run字段却为null |
| repair/fallback count | AVAILABLE | structured output/lifecycle telemetry |
| per-turn token cost | DERIVABLE | usages含provider pricing算出的estimated cost；必须按实际usage聚合 |
| per-completed-case token cost | DERIVABLE with new evaluator | 需要episode join和terminal completion；现有无报告 |
| embedding latency | AVAILABLE in semantic holdout adapter | production Memory path未作为turn telemetry |
| retrieval latency | NOT AVAILABLE as standard production metric | 需要observer timing |
| end-to-end turn latency | NOT AVAILABLE as persisted standard metric | HTTP/Runtime需外部harness计时 |

项目有 `DeepSeekPilotPricing` 与 paid-agent budget guard，可对已捕获token usage按明确price snapshot算费用；本报告不擅自给人民币数。Budget是上限/停机保护，不是实际case成本统计。

## 11. Statistical Evaluation Readiness

| 能力 | 当前状态 |
|---|---|
| repeated runs | 历史real pilot支持1–3；不足以做稳健统计 |
| fixed scenario | 有少量代码内scenario与semantic frozen suites |
| fixed player input | M5有单turn固定文本；无完整episode script |
| seed | 无 |
| temperature control | production DeepSeek adapter固定`temperature=0` |
| multiple LLM runs | 历史有3/condition |
| aggregation | 有rates/count/distribution |
| mean/std | 无通用实现 |
| confidence interval | 无 |
| bootstrap | 无 |
| paired comparison | 有repeat-index pairing，但不是随机seed配对 |

可固定：case JSON、初始state、玩家脚本、model name、temperature=0、max tokens、public action space、Runtime版本、Memory snapshot、run order和budget。

仍有stochasticity：DeepSeek API没有在当前adapter暴露seed；服务端模型版本/系统fingerprint、并发/基础设施与即使temperature=0时的tie/nondeterminism仍可能变化。因此应保存provider model、system fingerprint、request ID、时间和完整sanitized outcome，并报告分布，不能声称bitwise reproducible。

## 12. Existing Baselines

| 模式 | 当前真实可配置 | 公平ablation? | 说明 |
|---|---:|---:|---|
| A Full Agent (`llm + semantic + Reflection`) | 是 | 目标treatment | production默认组合 |
| B offline deterministic NPC | 是 | 仅粗baseline | 模型、策略行为全变，不是单变量消融 |
| C LLM + semantic Memory | 是 | 是，若Reflection控制一致 | production中semantic会自动启用Reflection，需注意 |
| D LLM without Memory (`--memory-mode disabled`) | 是 | 可作为No-Memory | 同时Reflection也关闭，因此不是纯Memory-only变量 |
| E LLM with Memory but Reflection off | **否，CLI无此开关** | 理想No-Reflection | REQUIRES IMPLEMENTATION/benchmark-only composition |
| F LLM with Reflection | 是（要求semantic） | Full | Reflection不可脱离semantic repository |
| G manual/baseline `/cases/action` | 是 | 否 | 玩家直接选择，不是NPC Agent；用于规则/UI sanity |

未来最小variants：Full、No Memory、No Reflection、Offline。No Reflection需要evaluation composition显式传`reflection_service=None`但保留同一semantic Memory；不应修改production默认行为。No Memory会同时拿掉Reflection，解释时要注明能力组合差异。

## 13. Player Input / Scenario Standardization

现有M5有代码内固定单turn contributions、initial-condition fingerprint和repeat index；event replay有固定command sequences；semantic suites有固定queries/candidates/gold。缺少：六案完整player contribution scripts、可重放approval/rejection、每阶段ground-truth acceptable action set、统一max-turn terminal protocol。

可信设计应：

1. 每case从全新相同player/session snapshot开始；
2. player script由外部fixture定义，不由被测Agent生成；
3. 采用“状态条件脚本”：同一公开阶段给同一句 contribution，Agent行为造成不同state时按预定义branch或判failure，避免脚本引用不存在target；
4. 固定approval policy，例如对合法diagnosis proposal统一approve、对treatment在满足条件时统一approve；
5. terminal只用CaseEngine `COMPLETED`/score与max turns；
6. 保存每turn Contribution、pre/post Observation fingerprint、proposal diagnostics、final action/event、AgentState/usage；
7. variant共享同一Session A snapshot、Session B起点、脚本、model config与run order。

Agent不能作为唯一player simulator；否则会把NPC与player model共同变化混进结果。

## 14. Benchmark Design

### 14.1 最小可信 Agent Task Completion Benchmark

推荐先做 **3 cases × 5 repeats × 2 variants = 30 episodes**，而不是一开始六案全量。选择不同推理结构的：`old_paper_umbrella`、`gray_hearth_inn`、`lantern_alley_conflicting_testimony`。求职前最小版也可先做3 cases ×3 repeats ×Full单variant=9 episodes，但它没有baseline。

每case：

- 起点：全新player/session，固定case revision 0；无历史Memory的task benchmark先隔离长期学习影响；
- 输入：3–6条状态条件式fixed contributions，覆盖 investigation、形成diagnosis、确认treatment；
- max turns：建议12（以实际case最短合法路径预检后冻结）；
- success：`CaseSessionState.status == COMPLETED`，同时单独报告diagnosis/treatment correctness与score，不把“安全但未完成”算成功；
- failure：max turns、terminal错误处置、无法继续、provider episode abort；
- repeats：最低5作描述性分布；10更适合稳定性，不声称显著性；
- artifacts：每episode JSONL + aggregate JSON + immutable config/hash。

输出：Case Success Rate、Goal Completion Rate、Mean/median Turns to Completion、executed safety violation rate、invalid first-proposal rate、fallback rate、tool count、diagnosis/treatment accuracy、token usage。

### 14.2 Success rule

Primary success必须来自CaseEngine terminal state。若错误treatment也可使session terminal，则Case Success应进一步要求case-defined correct/acceptable treatment outcome或score threshold；阈值必须在benchmark manifest中预注册，不能看结果后调整。

## 15. Ablation Design

### 15.1 Memory：Full Memory vs No Memory

1. **相同Session A experience**：先用完全确定性、相同command/event脚本生成一个frozen authoritative Session A snapshot；复制相同JSON/SQLite source Memory到两个variant的独立目录。No-Memory组保留source snapshot但在Runtime禁用retrieval，避免上游experience不同。
2. **Session B标准化**：同case/new case、相同revision-0 world snapshot、相同player、相同fixed contribution state machine、相同approval policy、max turns。
3. **控制输入**：用外部fixture；paired repeat index使用相同起点和run order交错；保存provider fingerprint。
4. **success**：CaseEngine terminal success + correct outcome/score；辅助turns/tool count。
5. **retrieved ≠ helpful**：分别报告 available/candidate/selected/declared/accepted；“helpful”还需paired task metric改善，不能仅由accepted-used定义。
6. **runs**：每case每variant最低5只作描述统计；推荐10。如果要CI/显著性，先做power/variance pilot再定样本，不能预称显著。

当前能以evaluation-only composition实现，但production CLI的No-Memory同时关闭Reflection；做纯Memory ablation时必须固定Reflection off或使用预生成Memory且不触发新Reflection。

### 15.2 Reflection ON vs OFF

Reflection是跨Session处理，实验单位必须是两阶段pair：

```text
相同 Session A authoritative experience
→ ON: production Reflection；OFF: reflection_service=None
→ 保存两组普通episodic Memory；仅ON可新增Learning Memory
→ 完全restart
→ 相同 Session B world/player script
→ terminal evaluation
```

比较：Session B Case Success、turns、score、合法action quality、Learning Memory selected/accepted-used、tokens/cost、Reflection repair/fallback/index recovery。两组GameNPCAgent/Memory retrieval/BGE/SQLite/输入必须相同；唯一变量是Session A是否运行Reflection。当前无CLI E模式，需`REQUIRES IMPLEMENTATION`的evaluation-only factory或配置，不能改核心Runtime行为。

## 16. Safety Benchmark

### 16.1 Scenario suite

至少包含：

- unsupported tool（需要在LLM proposal transport层构造/诱导）；
- diagnosis before ready；
- treatment without confirmation；
- stale confirmation（case revision变化）；
- wrong/hidden target；
- action outside active plan；
- 玩家强制要求危险action/prompt injection；
- mismatched player/session/decision confirmation。

每scenario执行真实LLM repeats，同时用scripted malicious Agent做deterministic worst-case。复用资产：`unsafe_treatment.json`、M1 authority tests、M2 action-outside-plan tests、M5 prompt-injection/wrong-suggestion fixtures、PublicActionContract negative tests。

### 16.2 指标

- LLM first-proposal violation rate；
- repair recovery rate；
- terminal action rejection/pending rate；
- **executed authority violation rate（目标0）**；
- CaseEngine bypass count（目标0）；
- false positive block rate：合法action被错误阻止；
- safety fallback rate与added turns。

当前有安全contract tests和3-run prompt-injection pilot，但没有覆盖上述suite、可复跑真实LLM、同时记录pre-repair proposal与execution结果的独立Safety Benchmark，因此最终状态为NO。

## 17. Recommended Metrics

### Primary Metrics（6）

| 指标 | 回答的问题 |
|---|---|
| Case Success Rate | Agent能否在max turns内达到CaseEngine权威正确terminal outcome？ |
| Goal Completion Rate | Agent是否能完成其持久化阶段目标？ |
| Executed Safety Violation Rate | 即使模型犯错，Runtime是否仍保持最终安全？目标0 |
| Turns to Successful Completion | 完成任务的交互效率；同时报告median/分布 |
| Correct Diagnosis/Treatment Rate | 完成是否建立在正确关键决策上，而非仅terminal |
| Cross-session Memory Accepted-use Rate | 长期Memory是否真正进入并被Runtime验收影响输出？仅在Memory benchmark作为primary |

Reflection不宜作为通用task primary metric；“写了多少lesson”可能奖励过度学习。Reflection应在Reflection ablation中作为机制/诊断指标，并以Session B task outcome为主。

### Secondary Metrics（9）

1. CaseEngine score distribution；
2. successful episode tool count；
3. plan completion/revision/abandonment rate；
4. first-proposal legal action rate；
5. confirmation compliance rate；
6. fallback/repair rate；
7. input/output tokens per successful case；
8. retrieval-to-accepted-use conversion；
9. Learning Memory write/index success rate。

### Diagnostic Metrics

- contract/policy error-code distribution；
- proposal vs executed tool/target confusion matrix；
- Memory candidate/selected/declared/accepted IDs和influence types；
- Reflection trigger/proposal/finding/lesson/write/index lifecycle；
- provider latency、end-to-end latency、system fingerprint、abort原因。

## 18. Benchmark Matrix

| Variant | Memory | Reflection | LLM | Runtime | 当前可配置 | Purpose |
|---|---|---|---|---|---:|---|
| Full | semantic SQLite+BGE | ON | DeepSeek | production | YES | 目标系统表现 |
| No-Memory | OFF | OFF（随Memory关闭） | DeepSeek | production | YES | 能力组合baseline；非纯Memory单变量 |
| No-Reflection | semantic SQLite+BGE | OFF | DeepSeek | production-equivalent | **REQUIRES IMPLEMENTATION** | Reflection纯消融 |
| Memory-only controlled context | synthetic injected | OFF | DeepSeek | CooperativeRuntime | historical only/current runner broken | 重现M5 proposal影响，不评retrieval |
| Offline | disabled默认 | OFF | deterministic NPC | production | YES | 低成本/确定性产品baseline，非单变量 |
| Manual | N/A | N/A | 无 | CaseEngine path | YES | world rule upper/lower sanity，不是Agent variant |

所有variant应共用case snapshot、player script、max turns、authority、CaseEngine、metric evaluator。Evaluation layer只能配置/inject已公开依赖和观察结果，不得加入benchmark-only policy帮助某variant。

## 19. Cost / Run Scale

不报货币金额；先按episode/call数量级规划。每个Agent turn通常至少1次GameNPCAgent call，repair最多再1次；Reflection只在trigger时调用1次，失败repair最多再1次。假设每episode平均6–10 Agent turns、1–3 Reflection triggers：

| 档位 | 设计 | Episodes | GameNPC calls量级 | Reflection calls量级 | 求职前适合度 |
|---|---|---:|---:|---:|---|
| MINIMAL | 3 cases × 3 repeats × Full | 9 | 54–90（repair另计） | 9–27 | **适合，先建立task基线** |
| RECOMMENDED | 3 cases × 5 repeats × 4 variants | 60 | 360–600 | Full/ON相关约30–90 | 时间/预算允许时；可做描述性ablation |
| EXTENDED | 6 cases × 10 repeats × 4 variants | 240 | 1,440–2,400 | 120–360 | 不建议仅为求职仓促执行 |

若只做题目示例的6 cases ×5 repeats ×3 variants，则是90 episodes，约540–900 GameNPC initial calls；加repair后上界更高。执行前应先用已有pricing snapshot与request reservation估token/budget，并把provider abort当结果而非偷偷重跑。

## 20. Top Evaluation Gaps

| Rank | Gap | Priority | Resume impact | 理由 |
|---:|---|---:|---:|---|
| 1 | 无统一CaseEngine terminal Task Success benchmark | P0 | HIGH | 不能量化回答“Agent能否完成异案” |
| 2 | 当前real benchmark executor wiring失效，历史pilot不可原样复跑 | P0 | MEDIUM | 可重复性与可信演示受损，但不影响production产品链 |
| 3 | 无production-equivalent Memory/Reflection task ablation | P1 | HIGH | 只能证明使用/影响，不能证明任务收益 |
| 4 | 无完整episode标准玩家脚本与六案覆盖 | P1 | HIGH | case/输入偏差大，现有real evidence集中old umbrella |
| 5 | 无统计不确定性、seed/paired run protocol与持久化全链latency/cost | P2 | MEDIUM | 不能安全报告均值/CI/成本 |

## 21. Pre-Recruitment Recommendation

### A. 没有正式task benchmark是否影响其作为核心项目？

不阻止。《异闻行录》已有真实production acceptance和强工程边界，仍可作为Agent应用开发核心项目。但缺benchmark会削弱“效果量化”和面对“做得好不好”追问时的证据力度；简历必须继续使用架构/链路事实，不能写成功率提升。

### B. 建议级别

**STRONGLY RECOMMENDED**。

不是架构blocker，也不建议为评测修改核心Agent；但求职前补一个小而可信的task benchmark，性价比高于继续重构Reflection。

### C. 时间有限时最小必须做什么

实现一个 **3个正式case × 3–5 repeats × 固定玩家脚本 × Full Agent** 的CaseEngine terminal Task Completion benchmark，报告Case Success、正确diagnosis/treatment、turns、executed safety violations、fallback和tokens。若时间只够一个variant，先建立可信绝对基线，不先做复杂消融。

### D. 何时可在简历加入量化结果

至少满足：

- benchmark code从当前clean/worktree可一键复跑；
- 任务、case、repeats、max turns、success/failure rule预先冻结；
- success来自CaseEngine terminal/outcome，不是自定义“安全即成功”；
- raw per-run artifacts与aggregate report均保存；
- 报告样本量和model/version，不把描述性比例称统计显著；
- 若写“Memory/Reflection提升”，必须有同起点paired ablation，报告absolute counts与不确定性，不能只看accepted-used。

安全简历句式示例：`在3个冻结异案、每案5次的描述性评测中，报告X/15正确完成、median Y turns、executed authority violation 0/…；样本不用于统计泛化。` 数字只能在真实运行后填写。

## 22. Implementation Roadmap

### Phase E0 — Harness truth cleanup

- 修复/替换evaluation层对已删除`m5_p4b_runner`的依赖，直接复用当前production composition的公开factory或等价只读assembly；
- 把历史M5 success重命名/限定为scenario safety success，禁止映射成case task success；
- 冻结benchmark manifest、schema、artifact hashes与environment metadata；
- 加入append-only per-turn observer，不修改Runtime行为。

### Phase E1 — Task benchmark

- 建立3-case fixed contribution state-machine fixtures；
- 用CaseEngine terminal/outcome/score定义success；
- 收集Goal/Plan/action/safety/turn/token指标；
- 先跑Full Agent 3–5 repeats，发布raw JSONL+aggregate Markdown/JSON。

### Phase E2 — Memory / Reflection ablation

- 复制相同Session A source snapshot；
- 实现evaluation-only Full/No-Memory/No-Reflection composition；
- 完全restart后运行相同Session B scripts；
- paired比较task outcome、turns、Memory usage和tokens，先作描述统计。

### Phase E3 — Safety evaluation

- 把现有negative tests/replay fixtures提升为冻结scenario manifest；
- scripted malicious Agent做确定性worst-case，真实DeepSeek做重复诱导；
- 同时记录first-proposal violations与executed violations；
- gate仅约束system safety必须0，不为让模型分数好看修改prompt/policy。

### Evaluation architecture rule

```text
Frozen scenario/config
→ production-equivalent composition
→ external observer/collector
→ authoritative CaseEngine/Runtime telemetry
→ immutable per-run artifact
→ pure scorer/aggregator
```

Evaluation layer只能观察、配置公开variant和复位状态；不得篡改ActionContract、Authority、CaseEngine、Goal/Plan、Memory/Reflection结果，不得按结果后改success阈值，也不得对失败run静默重试后只保留最好结果。

## 23. Final Status Summary

```text
CURRENT AGENT EVALUATION STATUS:
PARTIAL

CURRENT PRODUCTION ACCEPTANCE STATUS:
PARTIAL

TASK PERFORMANCE BENCHMARK:
NO

MEMORY ABLATION:
NO

REFLECTION ABLATION:
NO

SAFETY BENCHMARK:
NO

STATISTICAL MULTI-RUN EVALUATION:
NO

PRE-RECRUITMENT EVALUATION RECOMMENDATION:
STRONGLY RECOMMENDED

MINIMUM BENCHMARK TO ADD:
用3个正式case、每案3–5次、固定玩家脚本和CaseEngine权威terminal/outcome规则，运行可复现的Full Agent任务完成benchmark并保存逐run artifacts。
```

`CURRENT PRODUCTION ACCEPTANCE STATUS` 判为PARTIAL，不是否定已完成的核心链：LLM、Runtime、Memory、Reflection、BGE、restart/accepted-used均有真实证据；“PARTIAL”只表示acceptance尚未覆盖六案完整任务、重复生产分布、latency/cost与公平variants。
