# CE-2A 上下文行为对照工具实施报告

> 当前模块总览见[上下文工程模块主文档](../../architecture/CONTEXT_ENGINEERING_DESIGN.md)。本文第 1–8 节保留 v1 实施记录、第 9 节起记录 v2；当前 behavior fixture 身份已由后续 v3 账本修复更新。

日期：2026-09-26
范围：v1 保留、v2 案件绑定、离线 runner、默认禁用的真实 runner、预检、盲评与报告工具；未调用真实/付费模型，未实施 CE-2B。

> 本文第 1–8 节保留 v1 实施记录；第 9 节起是本轮 v2 修订的当前状态。v1 夹具未覆盖。

## 1. 交付结论

`ce2a_context_behavior_v1` 已可通过正式 `ClinicService -> CooperativeRuntime -> GameNPCAgent -> LLMAdapter` 路径离线运行。C/T 两组都开启协作记录，只有 T 开启 context v2；长期记忆与 Reflection 同时关闭。每个条件、场景和重复使用独立状态目录、Agent、SQLite 与 pending 字典。

工具没有真实 provider adapter。`run-real` 即使收到完整参数也会拒绝；缺少明确付费授权、模型、可核验价格来源或下一调用可靠 token 上界时更早拒绝。字符数从不当作 token 数。

## 2. 版本化输入

目录：`src/xuanyi_npc/evaluation/fixtures/ce2a_context_behavior/v1/`

- `scenarios.json`：12 个模型可见场景、真实案件及公开调查 ID、初始状态、人工历史、pending、当前输入和前置条件。
- `rubric_private.json`：模型不可见的可接受答案、禁止行为、评分标准和防泄漏 canary。
- `protocol.json`：A1、C/T、两次重复、固定 AB/BA 顺序、调用上限、开关和预算配置。
- `manifest.json`：夹具、runner、相关运行时、六案原文与测试的 SHA-256。

每次运行还复制上述夹具和选定源文件的完整内容，并保存原始 `git status --short`、commit 与逐文件 SHA-256。当前工作区有大量既有未提交内容，因此 commit 只作为辅助信息，不作为实验身份。

所有历史行都显式标记 `synthetic_evaluation_fixture`；它们不是实际玩家对话，也不会写入事实记忆或授权。rubric 不参与请求组装。

### 2.1 绑定摘要

| 场景 | 案件 | 公开对象 |
|---|---|---|
| H01 | `old_paper_umbrella` | `inspect_umbrella` / `ask_about_memory` |
| H02 | `moon_well_echo` | `inspect_wooden_slip` / `question_route` |
| H03 | `lantern_alley_conflicting_testimony` | `question_witness_yu` / `question_witness_shao` |
| H04 | `gray_hearth_inn` | `observe_cook` / `inspect_fuel_and_hearth` |
| H05 | `mist_ferry_borrowed_lantern` | `question_passengers` / `inspect_borrowed_lantern` |
| H06 | `returning_contract_nameless_shrine` | `inspect_nameless_stele` / `inspect_return_ledger` |
| P01 | `old_paper_umbrella` | 两个当前有效 pending：`observe_scholar` / `inspect_umbrella` |
| P02 | `moon_well_echo` | 已拒绝且不再 pending 的 `inspect_wooden_slip` |
| R01 | `gray_hearth_inn` | 重启前讨论 `inspect_fuel_and_hearth` |
| O01 | `old_paper_umbrella` | 长历史中的 `ask_about_memory` / `inspect_umbrella` |
| N01 | `lantern_alley_conflicting_testimony` | 当前明确 `inspect_alley_traces` |
| N02 | `returning_contract_nameless_shrine` | 当前明确 `observe_shrine_visitor` |

H02/H05 的当前 Plan 为空，不会由 Plan 单独泄露历史指代答案。H03 保留两个合理指向。H06 只纠正公开对象，不把线索事实注入历史。P01 当前类型是 `question`，不是 approval；现有 Clinic 在携带精确 pending 引用的回合完成后仍会移除被引用项，runner 将这个既有政策副作用单独记录，没有为探针修改政策。

### 2.2 O01 的最小替换

原方案要求“一个最新完整回合单独超过 12,000 字符”。实际领域 `NonEmptyText` 单字段最多 2,000 字符，当前历史投影一个合法回合无法合理超过该预算。实现没有制造非法对象，而是冻结两个合法长回合：最新回合可完整注入，加上较旧回合会超过预算，于是连续后缀算法完整省略较旧回合并注入 omission/重述提示。它验证同一裁剪与恢复边界，但不是原文字面场景；该差异同时记录在夹具和预检中。

## 3. runner 行为

`src/xuanyi_npc/evaluation/ce2a_context_behavior.py` 提供：

- `preflight`：校验 12 场景集合、公开 ID/描述、人工历史标记、私有 rubric 配对、C/T 合法组合、独立起点、R01 pending 清空、P01 多 pending、48 回合顺序、96 次硬上限、冻结 SHA 和真实运行拒绝。
- `run-offline`：按固定 AB/BA 顺序跑 48 回合，使用无网络可控 adapter；H02 触发一次成功格式修复，H03 触发修复失败后的 deterministic fallback，其余给出合法文字决策。
- `report`：汇总完成/失败/中断/未评分、修复、fallback、调用数、Plan/权限阻塞、usage 已知/未知以及有效人工评分后的 T 胜/平/负。
- `run-real`：稳定拒绝。该工具不包含真实网络执行实现。

每个运行 artifact 保存实际 provider-neutral 请求（含 repair）、ContextBuildTrace、最终公开回复、Plan 变化、真实 action history 增量、world revision、pending、错误、fallback、调用数与 usage。`pair_differences.json` 分别核对首次/repair 请求：C 不含 CE-2A 后缀，T 包含；schema 相同；repair 以首次消息为不可变前缀。它不要求请求只差一个字段，允许 v2 规则、历史 envelope、pending view 和 omission metadata。

离线 adapter 不执行工具，语义输出固定声明“未评分”。因此它只能证明构建与执行边界，不能证明 v2 理解能力提高。

## 4. 重复启动与中断

输出目录必须不存在；已有完整或中断目录一律拒绝覆盖。开始时写 `RUNNING.json`，成功后改为 `COMPLETE.json`。中断目录标为 `resume_allowed=false`：必须选择全新输出目录从冻结起点重跑，不能在原 operation 上自动续跑可能已经越过的工具或付费边界。

这不是跨进程 exactly-once。离线工具不共享状态目录，且不调用付费模型；未来真实 runner 仍需单独完成 provider 幂等与 durable operation correlation，不能由本工具的目录保护替代。

## 5. 盲评与评分

`blind_review.json` 隐藏 C/T，只保留场景号、重复号、公开背景、当前请求、最终回复和真实执行边界。评分初始均为 `null`；人工只能填 0/1/2，并必须写理由。`blind_mapping_private.json` 单独保存 blind ID 到条件的映射。

没有完整 C/T 或任一侧未评分的 pair 不参与胜/平/负；分别计为 missing 或 unscored。两次重复仍只属于同一个场景覆盖，报告明确保持 12 个独立场景。关键词命中不被当作语义正确率。

## 6. 预算与 usage

当前代码路径核验结果：一次 A1 初始调用失败后最多一次格式修复；已发生格式修复时不会再进行行动契约 repair。可控 adapter 没有网络重试层，所以冻结上限为 48 × 2 = 96 次。

`BudgetGuard` 要求显式 input/output token 上界并先预留最坏成本；不足时拒绝。usage 缺失按预留额保守结算，不按零费用。协议中的 `algorithm-test-only` 价格只用于单元测试预算算术，明确不是当前报价。离线运行没有 usage 的调用全部列为 unknown，不从字符数估算 token 或费用。

建议的 10 元总上限与 0.50 元单回合上限仍只是未授权方案。未来真实运行前必须另行冻结并批准：模型/provider、可核验价格来源及日期、输入/输出/缓存/推理计价口径、每次调用可靠 token 上界、批次和付费授权。

## 7. 使用方法

在项目根目录 PowerShell 中：

```powershell
$env:PYTHONPATH = "src"
python -m xuanyi_npc.evaluation.ce2a_context_behavior preflight --report runtime_evaluations/ce2a_preflight.md
python -m xuanyi_npc.evaluation.ce2a_context_behavior run-offline --output runtime_evaluations/ce2a_offline_v1_20260926_01
```

人工填写导出的 `blind_review.json` 副本后：

```powershell
python -m xuanyi_npc.evaluation.ce2a_context_behavior report --output runtime_evaluations/ce2a_offline_v1_20260926_01 --scores path/to/scored_blind_review.json
```

真实入口的预期结果是拒绝：

```powershell
python -m xuanyi_npc.evaluation.ce2a_context_behavior run-real --config src/xuanyi_npc/evaluation/fixtures/ce2a_context_behavior/v1/protocol.json
```

## 8. 验证与限制

专项测试覆盖 12 场景、oracle canary 不进入请求、C/T 起点与写入隔离、最终 adapter 差异、repair/fallback 计数、R01 重启、O01 裁剪、P01 精确响应标记、预算拒绝/usage 缺失、输出保护、盲评未评分与缺失 pair。

本次实际结果：

- 新工具专项：8/8 通过；与既有 CE-2A 合并专项：39/39 通过。
- 全量离线回归：645/645 通过。
- `git diff --check`：通过。
- 离线 48 回合 dry-run：48 completed、0 failed、0 interrupted；56 次 adapter 调用，8 个 format-repair 回合，4 个 fallback 回合，0 个案件工具执行；48 个输出和 24 个配对均保持未评分。56 次 usage 全部未知，费用没有按零或字符估算。
- v1 预检：offline `ready`；real/paid `blocked as designed`。

未验证：真实 provider token/usage、真实价格、网络重试、真实延迟、真实模型语义理解、任务成功率、跨进程并发和 CE-2B durable pending。当前工具不会对这些事项给出成功结论。

## 9. v2 场景冻结

v2 位于 `src/xuanyi_npc/evaluation/fixtures/ce2a_context_behavior/v2/`。它用带 SHA-256 的只读 overlay 引用 v1 公共场景和私有 rubric；加载时先验证 v1 原文哈希，再解析删除、覆盖和新增项。运行输出同时复制 overlay 原文与解析后的完整场景/rubric，因此可以独立重建本次输入，又不改写 v1。

v2 为 13 个场景、52 个 C/T 回合、最多 104 次 adapter 调用。P01O 和 P01A 都先通过正式 `Clinic.submit_case_action` 完成实际公开调查，再通过 `CooperativeRuntime` 的 A0 合法诊断提案产生 process-local pending；没有人工提升普通调查权限。P01O 当前文本不写诊断名、Plan 为空，pending 投影才把引用 ID 关联到 `exam_exhaustion`。P01A 的 `question` 不是 approval，确定性权限链不得提交诊断。两者分别统计语义理解与权限边界。

H04 的当前输入已经明确给出新目标，v2 将其标为 `explicit_current_input_negative_control`，不计入历史依赖能力。其他场景在 public fixture 中逐项记录 `information_sources` 与 `expected_information_path`；人工标准答案仍只在模型不可见 rubric 中。

## 10. 真实 runner 与预算保护

`run-real` 复用 `DeepSeekChatAdapter`、`DeepSeekPilotPricing`、`DeepSeekRequestBudgetGuard`、`ModelUsage` 和 `DurableRequestLedger`，仍经过正式 `Clinic -> Runtime -> GameNPCAgent -> adapter`。它不读取或打印密钥值；只有所有非秘密条件先通过后，才从既有环境配置构造 adapter。

启动条件全部必须满足：协议 `enabled=true`、协议 `paid_authorized=true`、命令行 `--confirm-paid`、唯一 `authorization_id`、显式模型/base URL/temperature/thinking/output limits、正数总预算与单回合预算、未过期且 SHA 匹配的价格快照、非空冻结场景子集。当前 v2 protocol 均保持未授权默认值，因此入口默认拒绝。

费用上界基于 adapter 实际将发送的完整 provider payload：包含 schema 与 provider 附加 JSON 指令，输入采用该适配器价格政策限定的 `UTF-8 bytes + framing allowance` 保守 token 上界；输出采用每个实际请求的 `max_tokens`。本轮修复了此前只取 adapter 默认 512、可能低估 A1 首次 2048 上限的问题。该方法只对价格快照明确允许的 DeepSeek 模型/政策成立，字符数不是精确 token 数。

每次调用先检查单回合剩余上限，再由既有总预算 guard 预留。调用前 durable ledger 写 `started`；成功或错误后写 terminal 行。usage 缺失、超时或结果不确定时保守停止并要求人工核对，不按零费用处理，不自动重发。provider adapter 本身没有重试；Agent 每回合最多首次请求加一次格式或行动契约修复。`authorization_id` 具有独立排他 claim；换输出目录不能掩盖相同授权的重复收费。输出目录和中断运行均不可覆盖、不可自动续跑。

这不是 provider 幂等键、跨进程锁或世界 exactly-once。ledger terminal 写失败发生在模型返回后、工具执行前时会阻止该回复进入 Runtime；若工具或后续 artifact 写入已跨过边界，运行整体标为不可自动恢复。真实工具只写该回合独立创建的评测状态目录，不接触玩家生产数据。

## 11. 最小真实链路试运行（仅计划，未执行）

建议冻结子集为 H02（唯一指代）、H05（改口后的间接引用）、H03（信息不足时澄清）、P01A（权限边界），每个 1 次、C/T 各一回合：8 回合，最多 16 次调用。这只验证真实运行链和产物，不能证明整体收益。

先复制 v2 protocol 到新的不可覆盖目录，填写但不要提交密钥：`model`、价格快照路径及 SHA、价格核验/失效日期、总预算、单回合预算、`authorization_id`、上述 `scenario_ids`，并将两个协议确认开关改为 true。密钥仍只放既有环境变量。待用户另行明确批准后，命令模板为：

```powershell
$env:PYTHONPATH = "src"
python -m xuanyi_npc.evaluation.ce2a_context_behavior run-real `
  --config path/to/frozen-v2-real-protocol.json `
  --output runtime_evaluations/ce2a_v2_real_<new_run_id> `
  --confirm-paid
```

本轮没有选择付费模型、没有确认价格、没有批准预算，也没有执行该命令。

## 12. 当前命令

```powershell
$env:PYTHONPATH = "src"
python -m xuanyi_npc.evaluation.ce2a_context_behavior preflight --report runtime_evaluations/ce2a_preflight_v2.md
python -m xuanyi_npc.evaluation.ce2a_context_behavior run-offline --output runtime_evaluations/ce2a_offline_v2_<new_run_id>
```

离线 adapter 的人为格式失败与固定回复只存在于 `run-offline`；真实模式直接使用 provider adapter，不读取场景的 `adapter_mode`。无人工评分时所有语义结果仍为 `unscored`。

## 13. v2 实际离线验证

- 专项：`tests/test_ce2a_context_behavior_evaluation.py` 与 `tests/test_deepseek_adapter.py`，40 项通过。
- 相关规划/权限/上下文专项：99 项通过。
- 全量离线回归：651 项通过。
- `git diff --check`：通过。
- v2 预检：`ready for offline`；真实入口因冻结配置 `enabled=false` 而按设计阻断。
- 52 回合 dry-run：52 completed、0 failed、0 interrupted；60 次离线 adapter 调用，8 个 repair，4 个 fallback；26 个 C/T pair 全部未评分。真实模型调用与费用均为 0。

未验证事项：任何真实模型语义理解、真实 provider usage/延迟/错误分布、当前真实价格、真实付费预算是否充分、跨进程 claim、provider 幂等、崩溃后的世界 exactly-once，以及 CE-2B durable pending。模拟 adapter 结果不得用于宣称 v2 能力提升。
