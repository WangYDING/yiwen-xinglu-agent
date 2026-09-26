# CE-2A completed replay 与 pending 响应标记修补

日期：2026-09-25
范围：CE-2A 有限修补；未实施 CE-2B。

## 1. 复现结论

两个问题均已通过正式 `ClinicService.submit_player_contribution()` 路径复现。

1. 旧顺序先读取 `cooperative_pending`，再读取 SQLite operation。批准或拒绝完成后 pending 已按现有语义移除，相同 operation 重试因此返回 `confirmation_unavailable`，无法抵达 completed replay；重启后 pending 字典为空时结果相同。修改文本、贡献类型或响应 ID 的同 operation 请求也可能先得到 pending 错误，而不是 payload conflict。
2. `project_pending_snapshot()` 只比较 `responds_to_decision_id`。只要 decision ID 相同，即使 confirmation ID 缺失或错误，也会把 view 标成正在响应。

修补前新增的聚焦测试得到 13 个预期失败：approval/rejection replay、重启 replay、四类 payload conflict、新 operation 生命周期，以及五种 confirmation/decision 组合。

## 2. 修复后的检查顺序

player/case/session ownership 始终最先校验。之后分两种模式：

- 记录关闭：保留原路径，先检查当前 pending，再创建 contribution 并进入 Runtime。
- 记录开启：先构造不含服务端时间戳的稳定 payload，取得同进程 operation 归属并调用 repository `begin()`。
  - completed + 相同 payload：直接 replay；不要求原 pending 仍存在。
  - payload 不同：`operation_payload_conflict`。
  - 原请求仍运行：`operation_in_progress`，不改原生命周期。
  - interrupted/recovery：沿用保守恢复，不重放。
  - 只有新建记录：读取并验证当前 pending，然后才构造上下文并执行 Runtime。

新 operation 引用不存在、已消费或 revision 失效的 pending 时，repository 行转为 `failed_before_reply` 后返回原 pending 错误，不留下会在下次被误判为中断的 `started` 行。

completed result 仍只是历史结果。replay 不插入、消费或恢复 pending；历史 `pending_action` 只有在当前进程内来源仍存在完全相同且 revision 有效的项时才可对外保留，否则清除。

## 3. 响应标记

Clinic 将当前请求的 `pending_confirmation_id` 显式传给一次性 `build_context_snapshot()`。公开 view 的 `responds_to_current_contribution` 现在要求：

- confirmation ID 相同；
- decision ID 相同；
- player/case/session scope 相同；
- case revision 有效。

任一 ID 缺失或不匹配均为 false。该值只进入非授权公开上下文；Runtime 的 pending 对象仍是唯一现有授权输入。首次请求构建一次 snapshot，format/action repair 沿用同一对象，不重新读取字典。

## 4. Fixture

CE-0、CE-1 和 `ce2a_requests_v1.json` 均未覆盖。新增 `tests/fixtures/context_engineering/ce2a_requests_v2.json`：v1 没有“正在响应”的 pending，v2 以固定 confirmation/decision/scope/revision 正确组合冻结 A0 initial/format repair 请求身份，并验证标记只出现一次且 repair 复用 original messages。

## 5. 验证与限制

实际运行：

- 修补前聚焦复现：13 个预期失败，分别证明 replay 顺序、conflict 优先级、新 operation 生命周期和 marker 双 ID 问题；
- `pytest -q tests/test_context_engineering_ce2a.py`：31/31 通过；其中批准场景包含一次真实离线工具执行，并证明 replay 不产生第二次模型或工具调用；
- 既有正式拒绝/重提案/确认链专项：通过；
- `pytest -q`：637/637 通过；
- `git diff --check`：通过；
- `python tools/freeze_ce2a_context_fixture.py ce2a_requests_v2`：按预期 `REFUSE_OVERWRITE`。

冻结文件复核：CE-0 v1、CE-1 manifest、CE-2A v1 的 SHA-256 分别仍为 `6e7711d19d1957c3dd60f8a0fceb2e9b27669b2d91bf2bf78f6d45cbe568eba6`、`025f52248f55d1e2711d8216f37cc3b2526fee6eda28129cd0740d7fe6eb3f77`、`04725681123a8d69fa229d056fa0af82604f261f22ffe33439eeb316f4bee2ee`。新增 CE-2A v2 为 `b044a153e58ff07d7518c983a0d38d8caca8dd3ee98c256fde373c5d299c8349`。

验证全部离线，不调用真实或付费模型。

本修补不增加 durable pending、claim/consume、跨进程锁、讨论回合、意图识别、自动摘要或记忆调整。SQLite 与 JSON 世界状态仍无跨存储原子事务；不确定操作仍不自动重放或推断成功。
