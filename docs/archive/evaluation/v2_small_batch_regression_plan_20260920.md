# V2 fallback 修复后小批量验证计划

状态：离线预检 `READY`，等待新的费用授权。此批次不并入正式 T/M 成绩，不补跑替换失败，不启动全量评测。

## 清单

|场景|旧 run|用途|
|---|---|---|
|T01|`t01_r01`|本轮第 9 回合失败；检查旧纸伞诊断后、治疗确认与 fallback 修订|
|T07|`t07_r01`|本轮第 9 回合失败；检查不同病例的诊断前推进|
|T16|`t16_r01`|本轮第 9 回合失败；必须实际触达拒绝、pending 失效、再提案与确认|
|T17|`t17_r01`|本轮第 9 回合失败；检查另一病例的诊断后路径|
|T23|`t23_r01`|本轮第 9 回合失败；检查 validation 病例的诊断前推进|
|T09|`t09_r01`|原完成路径控制，检查无回归|
|M01 M0/M1/M2|`m01_m0_r01`、`m01_m1_r01`、`m01_m2_r01`|完整隔离配对、真实 BGE、曝光边界与 M2 源 Reflection|

源历史仍由公开动作夹具构造，不调用模型；M2 源 Reflection 为 1 次初始调用、最多 1 次修复，已纳入 M 预算。每个目标从初始状态开始，保持冻结输入协议、权限、评分器和 16 回合上限。

预计 190–230 次调用，契约最坏 290 次；历史完整对应样本费用约 CNY 2.1529。建议硬预算 T CNY 2.00、M CNY 1.00，互不转移。

## 获得授权后的命令

先再次执行不访问 provider 的预检；它会强制项目 `.venv` 并真实运行一次 BGE embedding：

```powershell
.\.venv\Scripts\python.exe -m xuanyi_npc.evaluation.v2_regression_preflight --plan evaluation_results\v2\v2_regression_batch_20260920_02\batch_plan.json
```

仅当输出 `READY` 且收到新的费用授权后，才可执行：

```powershell
.\.venv\Scripts\python.exe -m xuanyi_npc.evaluation.v2_runner --phase full --experiment-id v2_regression_batch_20260920_02 --confirm-paid-agent --budget-cny 2.00 --model deepseek-flash --max-turns 16 --seed 20260920 --repeats 1 --scenario-id T01 --scenario-id T07 --scenario-id T16 --scenario-id T17 --scenario-id T23 --scenario-id T09

.\.venv\Scripts\python.exe -m xuanyi_npc.evaluation.v2_memory_pairs --experiment-id v2_regression_batch_20260920_02 --confirm-paid-agent --budget-cny 1.00 --scenario-id M01 --repeat 1
```
