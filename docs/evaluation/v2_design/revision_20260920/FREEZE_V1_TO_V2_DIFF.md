# V2.1 精简首轮冻结 V1→V2 差异

## 保留项

- 原 V1 计划 SHA-256 仍为 `5B3C2A02E7C4C6AE3A77D8686993FFFC8A1794DD95AB2A9A4EAF971002BE4C32`。
- V1 启动停止记录未覆盖；机器证据 SHA-256 为 `3164F10D34663CB4F21608C7C41EA3444512D043DA518BCC2AD066EA81C87BF1`。
- 新旧 `execution_order` 完全相同。
- 新旧任务范围、条件、配对、三次重复、模型配置、16 回合上限及 G/C/M 预算完全相同。

## 代码差异

- 新增 `v21_schedule.py`，集中生成和验证唯一的 54 项调度。
- `v21_freeze.py` 改为使用共享调度，不再维护私有调度实现。
- `v21_execute.py` 在任何 provider 初始化前验证完整调度，并把冻结子序列传入 runner。
- `v2_runner.py`、`v21_architecture_runner.py`、`v2_memory_pairs.py` 收到冻结序列时直接消费，不再重新随机化。
- `v21_preflight.py` 增加逐项全序列、唯一性、遗漏、条件串组和入口展开检查。

V2 新增一个哈希目标 `v21_schedule.py`。发生变化的既有运行文件为 `v21_architecture_runner.py`、`v21_execute.py`、`v21_preflight.py`、`v2_memory_pairs.py`、`v2_runner.py`。病例、提示、评分器和价格快照未改变。

## 新冻结结果

- V2 计划 SHA-256：`CC03954CFF992101B5D179BA0C6529A7A9EC74522D79FABA9F424C1E85A0EF5D`
- 预检：`READY`
- 付费模型调用：0
- 新付费授权：尚未取得
