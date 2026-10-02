# V2.1 精简首轮冻结说明

状态：`READY / AWAITING_NEW_PAID_AUTHORIZATION`。预检没有发起模型请求。

## 冻结范围

- G：T01、T07、T09、T16、T17、T23，A1 各 3 次，共 18 个 episode。
- C：C01、C02（证据冲突）和 C09、C10（多步依赖），A0/A1 各 3 次，共 24 个 episode。
- M：MV01（相关历史）和 MV06（相似但结论不同），M0/M1 各 3 次，共 12 个目标 episode。源历史由同一确定性公开执行准备；无源模型生成、无 Reflection。
- 合计 54 个目标 episode，回合上限 16。完整 162 个目标 episode 的方案不在本批次执行。

冻结清单见 [frozen_slim_plan_20260920.json](frozen_slim_plan_20260920.json)，实际预检输出见 [preflight_slim_20260920.json](preflight_slim_20260920.json)，任务规格见 [slim_first_round_catalog.json](slim_first_round_catalog.json)。

## A0 与共享安全语义

A0 使用 `SimpleActionGameNPCAgent`，每轮直接请求模型生成一个当前动作，不暴露 `propose_turn`，也不包含脚本诊断、治疗或规划。`CooperativeRuntime` 在 A0/A1 分支之后只调用一套公开行动契约校验、NPC 权限策略、pending 确认校验和 `submit_action_with_receipt` 世界提交路径。

离线反例覆盖自主调查、仅提案诊断、需确认治疗、错误 decision 绑定、fixture 依赖可达性和成对分母。相关回归 47 项通过，另一次包含更多场景检查的相关回归 50 项通过。该证据支持“共享确定性安全语义”，不把 A0 说成与 A1 使用相同生成入口。

## 预算

估算基于上一批真实实测和 2026-09-20 复核的 DeepSeek Flash 价格。冻结价格按高峰费率计：缓存命中输入 0.04 元/百万 token、缓存未命中输入 2 元/百万 token、输出 8 元/百万 token。官方价格页为 <https://api-docs.deepseek.com/zh-cn/quick_start/pricing/>。

|池|目标 episode|期望成本|独立硬上限|每 episode 停止线|
|---|---:|---:|---:|---:|
|G|18|3.30 元|4.50 元|0.25 元|
|C|24|3.70 元|6.00 元|0.25 元|
|M|12|2.50 元|4.00 元|0.3333 元|
|合计|54|9.50 元|14.50 元|—|

三池不得互转、追加或选择性补跑。达到单 episode 停止线会保留该次失败并结束 episode；达到 provider 池上限则不再启动请求。单 episode 截止时间为 300 秒。

## 可执行入口

以下命令都会在启动 provider 前重新核验冻结文件哈希，并拒绝覆盖已有池产物。它们只在收到针对本冻结批次、包含具体池预算的新付费授权后执行。

```powershell
.\.venv\Scripts\python.exe -m xuanyi_npc.evaluation.v21_execute --plan docs/evaluation/v2_design/revision_20260920/frozen_slim_plan_20260920.json --track G --confirm-paid-agent
.\.venv\Scripts\python.exe -m xuanyi_npc.evaluation.v21_execute --plan docs/evaluation/v2_design/revision_20260920/frozen_slim_plan_20260920.json --track C --confirm-paid-agent
.\.venv\Scripts\python.exe -m xuanyi_npc.evaluation.v21_execute --plan docs/evaluation/v2_design/revision_20260920/frozen_slim_plan_20260920.json --track M --confirm-paid-agent
```

运行完成后使用 `v21_report` 离线汇总可靠性、安全性、任务完成度、可观测性、A1−A0、M1−M0、成本以及 T16 拒绝后的重新提案与确认链。结论限定为探索性首轮，不外推新任务普遍泛化、Reflection 有效或工程全面发布就绪。
