# V2 修复后小批量端到端回归计划

状态：**离线准备完成，等待预算授权**。本轮没有调用付费模型。冻结配置见 [`batch_plan.json`](../../../evaluation_results/v2/v2_regression_batch_20260919_01/batch_plan.json)，结果目录独立于全部旧 V2 产物。

本批次是修复后的探索性回归，不并入正式 T/M 成绩。所有目标任务从 V2 规定的初始状态开始，不使用诊断后 checkpoint；保留原玩家输入协议、16 回合上限、权限策略、评分器和成功标准。每个目标只运行一次，失败或供应商错误原样保留，不追加替换运行。

## T：6 个目标运行

|角色|新场景|病例/profile|对应旧 run|旧结果|本次重点检查|
|---|---|---|---|---|---|
|诊断前停滞 1|T07|`gray_hearth_inn` / `wrong_hypothesis`|`t07_r01`|未提交诊断|错误先验下调查步骤、非工具讨论步骤和诊断步骤能否持续推进；是否出现新契约拒绝|
|诊断前停滞 2|T23|`returning_contract_nameless_shrine` / `wrong_hypothesis`|`t23_r01`|未提交诊断|不同 validation 病例中能否由调查进入诊断；排除修复只对旧纸伞有效|
|诊断后停滞 1|T01|`old_paper_umbrella` / `cooperative`|`t01_r01`|已提交诊断、未治疗|与 stall probe 对照，但从初始状态运行；重点看诊断后讨论 PlanStep、治疗 pending、确认和真实提交|
|诊断后停滞 2|T17|`mist_ferry_borrowed_lantern` / `cooperative`|`t17_r01`|已提交诊断、未治疗|不同病例的诊断后状态推进；检查治疗选择没有被旧纸伞特例硬编码|
|旧成功控制|T09|`lantern_alley_conflicting_testimony` / `cooperative`|`t09_r01`|完成|检查修复没有破坏原可完成路径、权限链或评分结果|
|拒绝后确认|T16|`moon_well_echo` / `deny_then_confirm`|`t16_r01`|未提交诊断|首次 pending 被拒绝后的失效、重新提案、后续有效确认及至多一次权威提交|

六个角色互不复用场景，并恰好覆盖六个基础病例，因此无需再补第七个场景。T16 的旧结果也属于诊断前停滞，但这里只作为独立的拒绝/确认角色；两个诊断前主样本仍是 T07 与 T23。

## M：一个完整配对组

选择 `M01/r01`：源病例 `old_paper_umbrella`，目标病例 `gray_hearth_inn`，类型为 `same_owner_related`。旧 run 为：

- `m01_m0_r01`：M0，旧终态已有诊断、无治疗尝试；
- `m01_m1_r01`：M1，旧终态已有诊断、无治疗尝试；
- `m01_m2_r01`：M2，旧终态已有诊断、无治疗尝试，源 Reflection 为 `no_write`。

选择依据：这是相关同 owner 的标准正向配对，三条件旧运行均越过诊断边界，适合检查修复后的治疗阶段，同时仍能验证 M0/M1/M2 的状态隔离和曝光差异。

协议保持不变：先用生产病例组件构造一份可审核的公共源执行历史，再克隆到 M0/M1/M2 三个隔离 store；M0 关闭检索，M1 开启普通记忆检索但不运行源反思，M2 开启检索并仅让通过门控的源反思写入；目标 episode 内 Reflection 仍关闭。

源历史执行采用冻结的公开动作夹具，不需要模型调用。M2 源 Reflection 需要 1 次模型调用，若初次结构化输出无效则最多再修复 1 次；这 1–2 次调用已计入 M 预算和 Trace，不会重复为 M0/M1 生成源历史。

## 调用量与费用

旧对应运行共发生约 213 次模型调用：选定 T 为 149 次，M 三个目标为 63 次，M2 源 Reflection 为 1 次；旧实际总成本为 CNY `2.15292616`。这比 continuation probe 更接近本批次，因为它包含完整初始调查、诊断、结构化修复、确认和 M 源阶段。

- 预计调用量：190–230 次。修复后成功运行可能提前结束，但诊断前样本仍可能耗尽 16 回合。
- 契约上限：T 为 `6×16×2=192` 次；M 目标为 `3×16×2=96` 次；M2 源 Reflection 最多 2 次；合计最多 290 次。每回合至多两次，涵盖格式修复或行动契约修复。
- 预计费用：CNY 1.9–2.5。建议总硬上限 CNY 3.00，拆分为 T CNY 2.00、M CNY 1.00；两个进程的上限之和就是批次总上限，未用额度不跨进程转移。
- 旧 M2 源 Reflection 单次按全 cache-miss 高峰价计算约 CNY 0.007296；若发生修复，保守按两次计入 M 余量。

## Trace 与产物

两个 runner 都写 `v2_diagnostic`：逐回合公开观测、Goal/Plan、模型初次及修复输出、校验错误、fallback、最终动作、权限/确认、工具前后状态、`turn_completed` 的 Agent/世界前后状态，以及每次调用 usage、成本和耗时。新增的日志字段只增强证据，不改变生产决策、评分器或回合上限。

正式运行将分别写入：

- `evaluation_results/v2/v2_regression_batch_20260919_01/real_model_trials`
- `evaluation_results/v2/v2_regression_batch_20260919_01/real_model_memory_pairs`

目录创建使用不可覆盖模式。不要用新 experiment ID 重跑失败项来替换结果。

## 获得预算授权后的命令

先运行纯离线冻结检查（不会访问 provider）：

```powershell
$env:PYTHONPATH='src'
python -m xuanyi_npc.evaluation.v2_regression_preflight --plan evaluation_results/v2/v2_regression_batch_20260919_01/batch_plan.json
```

检查返回 `READY` 后运行 T 子批次：

```powershell
$env:PYTHONPATH='src'
python -m xuanyi_npc.evaluation.v2_runner --phase full --experiment-id v2_regression_batch_20260919_01 --confirm-paid-agent --budget-cny 2.00 --model deepseek-flash --max-turns 16 --seed 20260919 --repeats 1 --scenario-id T07 --scenario-id T23 --scenario-id T01 --scenario-id T17 --scenario-id T09 --scenario-id T16
```

随后运行 M 配对子批次：

```powershell
$env:PYTHONPATH='src'
python -m xuanyi_npc.evaluation.v2_memory_pairs --experiment-id v2_regression_batch_20260919_01 --confirm-paid-agent --budget-cny 1.00 --scenario-id M01 --repeat 1
```

本计划只准备命令；尚未获得新的预算授权，因此没有执行后两条付费命令。
