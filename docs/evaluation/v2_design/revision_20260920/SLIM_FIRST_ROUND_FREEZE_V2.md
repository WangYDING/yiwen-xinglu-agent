# V2.1 精简首轮冻结执行包 V2

状态：`READY / AWAITING_NEW_PAID_AUTHORIZATION`。本次修复与预检未连接付费 provider。

## 新冻结身份

- 实验 ID：`v2_1_slim_first_round_20260920_02`
- 计划文件：[frozen_slim_plan_20260920_v2.json](frozen_slim_plan_20260920_v2.json)
- 计划 SHA-256：`CC03954CFF992101B5D179BA0C6529A7A9EC74522D79FABA9F424C1E85A0EF5D`
- 实际预检：[preflight_slim_20260920_v2.json](preflight_slim_20260920_v2.json)
- 预检状态：`READY`；`paid_model_calls=0`

## 范围与预算

任务、配对、重复、模型设置、回合上限和预算均与原冻结版本一致：G 18、C 24、M 12，共 54 个目标 episode；G 4.50 元、C 6.00 元、M 4.00 元，合计硬上限 14.50 元，三池不得互转或追加。

## 调度修复

`v21_schedule.py` 现在是唯一调度来源。冻结器用它生成原冻结顺序；预检用它逐项验证完整 54 项；执行入口从计划中切出 G/C/M 子序列并直接传给对应 runner。runner 收到冻结序列后不再使用自身随机种子或固定条件顺序。

离线检查验证：

- G 18、C 24、M 12 的执行入口展开结果分别与冻结清单逐项一致。
- 54 个 `(track, task, condition, repeat)` 身份无重复、遗漏或额外项。
- C 与 M 每个配对的两个条件齐全、相邻且 `pair_id` 正确。
- 人为交换冻结顺序中的两项时，预检返回 `FAIL`，执行入口在 provider 初始化之前抛出顺序错误。

负向探针证据见 [schedule_drift_rejection_20260920_v2.json](schedule_drift_rejection_20260920_v2.json)：`provider_initialized=false`、`paid_model_calls=0`。

## 执行命令

以下命令仅供收到针对本 V2 计划哈希的新明确付费授权后使用：

```powershell
.\.venv\Scripts\python.exe -m xuanyi_npc.evaluation.v21_execute --plan docs/evaluation/v2_design/revision_20260920/frozen_slim_plan_20260920_v2.json --track G --confirm-paid-agent
.\.venv\Scripts\python.exe -m xuanyi_npc.evaluation.v21_execute --plan docs/evaluation/v2_design/revision_20260920/frozen_slim_plan_20260920_v2.json --track C --confirm-paid-agent
.\.venv\Scripts\python.exe -m xuanyi_npc.evaluation.v21_execute --plan docs/evaluation/v2_design/revision_20260920/frozen_slim_plan_20260920_v2.json --track M --confirm-paid-agent
```

完整 162-episode 评测、Reflection、真实攻击、并发与重启恢复仍不在本执行包范围内。
