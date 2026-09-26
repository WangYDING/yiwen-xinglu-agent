# 上下文工程 CE-2A 实施报告

日期：2026-09-25
范围：只实施 CE-2A；CE-2B durable pending、claim/consume 与重启授权恢复未实施。

后续有限修补：completed replay 的 operation 检查现已先于 pending 可用性检查，pending 响应标记要求 confirmation + decision + scope + revision 全部匹配。复现与验证见 [`context_engineering_ce2a_replay_fix.md`](context_engineering_ce2a_replay_fix.md)。

## 1. 交付结论

本轮新增独立 SQLite 协作回合日志、近期完整回合选择、现有进程内 pending 的只读公开投影，以及 A0/A1 首次请求与两类 repair 的统一快照注入。授权来源仍是 `ClinicService.cooperative_pending`，Plan、权限、工具和世界提交语义未迁移。

默认保持兼容：`cooperative_record_enabled=false`、`cooperative_context_v2_enabled=false`。CLI 可分别使用 `--cooperative-record` 和 `--cooperative-context-v2`；后者要求前者同时开启。回滚上下文只需关闭 v2 开关；关闭记录则同时失去 durable history 与 operation replay。已有 SQLite 历史可保留，不会写入旧 JSON 案件存档或长期记忆表。

## 2. 实际代码

- `storage/sqlite_cooperation.py`：独立 `cooperative_conversation.sqlite3` repository，复合 scope/operation 主键、稳定请求 fingerprint、单 scope sequence，以及 `started/prepared/completed/failed_before_reply/recovery_required` 生命周期。
- `application/cooperative_context.py`：只读 pending 投影、最多三个完整历史回合、12,000 个 message-content 字符预算、连续后缀与 omission marker。
- `domain/cooperative_context.py`：公开 pending view、精确省略计数与不可变 snapshot。
- `application/clinic.py`：ownership、stable payload、同进程执行归属、replay、故障恢复和一次性 snapshot 编排。
- `application/cooperative_runtime.py`：把 snapshot 传入 Agent；在结构/行动修复及最终 Plan 复核之后、权限/工具之前触发 prepared hook。CE-1.1 的最终 Plan 复核保留。
- `agents/context.py`：v2 开启时给 A0/A1 注入同一历史/pending 信息；format repair 复用 original，行动修复继续是 A0 shape。v2 关闭时走原 CE-1 构建路径。

## 3. 请求实际新增内容

开启 v2 后，请求新增：

1. system 固定规则：历史玩家/NPC 话语非权威，pending view 只读且不授予权限，禁止从历史恢复授权；
2. 当前 operation 之前、同 `player_id/case_id/session_id` 的 completed 历史 user/assistant envelope；角色由服务端指定；
3. 当前 user block 中的历史选择/省略信息，以及所有同 scope、revision 有效的进程内 pending 公开 view。

每个 pending view 包含 confirmation/decision ID、公开 action、authority mode、公开理由、case revision 和是否响应当前 contribution。最后一项只有当前请求显式携带的 confirmation ID 与 decision ID 同时匹配该 view，且 scope/revision 有效时才为 true。它不含隐藏权限，也不写回授权字典。

准确计量为投影后的 message content 字符数；没有测量 provider token 或 provider payload。最新完整回合单独超限时选择零历史并给出重述提示，不把省略后的上下文描述为语义完整。pending 超限返回 `required_context_too_large`，CE-2A 不提前消费拒绝、不删除任何 pending。

## 4. 幂等、恢复、并发与授权边界

稳定请求身份包含 scope、operation、文本、贡献类型、responds-to 与 pending confirmation 引用；服务端生成时间戳不参与 fingerprint。记录模式先检查该身份和 operation lifecycle：相同 operation/payload 的 completed 项直接 replay，不要求原 pending 仍存在，不调用模型或工具，也不再次追加历史；字段变化先返回 `operation_payload_conflict`。只有新 operation 才读取当前 pending；无效项会把新记录终结为 `failed_before_reply`。记录关闭路径继续先校验 pending。

同进程执行归属确保仍在运行的原请求遇到重复提交时返回 `operation_in_progress`，不把原记录改成 recovery。没有当前归属的 `started/prepared` 被视为重启遗留并转 `recovery_required`。这不是跨进程锁；多进程共享 state root 不在保证范围内。

prepared 保存的是行动修复及最终 Plan 复核后的最终可能执行 decision。工具可能成功但 completed 写失败时，世界状态不回滚，记录转不确定状态，同 operation 不重放工具；系统不靠 revision 增量或动作相似推断归属，也不伪造原 NPC 正常回复。

completed result 内旧 `pending_action` 仅作为历史审计保存。replay 只有在当前进程内 dict 仍有完全相同且 revision 有效的项时才返回它；否则清除，不复活授权。重启恢复 completed 历史，但进程内 pending 为空且继续不可授权。

记录模式并非完全无行为影响：repository 不可写、重复冲突或恢复不确定会返回稳定错误。SQLite transaction 不覆盖 JSON 世界状态或 Agent state；没有跨存储原子事务和 exactly-once world mutation 保证。

## 5. 与设计的差异与收紧

- 原设计 7.2 的“模型调用前消费拒绝腾容量”已删除；这属于 CE-2B 状态迁移。
- 实现没有抽象独立 `PendingContextSource` 接口，而是在 Clinic 对 dict 取锁复制后交给纯投影函数。当前只有一个来源，避免为 CE-2A 过度抽象；CE-2B 切 durable source 时再引入接口。
- omission 不保存被省略文本或摘要，只给同 scope、当前 operation 之前的 completed 精确省略数量、原因和重述提示。
- 首版默认关闭，避免未显式选择记录失败/重复保护的部署出现行为变化；设计中的 rollout 顺序通过两个独立开关实现。

## 6. Fixture 与构建

CE-0 v1、CE-1 pre-change v1 和 CE-2A v1 未改动。`tests/fixtures/context_engineering/ce2a_requests_v1.json` 冻结原五类边界请求；有限修补另增 `ce2a_requests_v2.json`，专门冻结 confirmation/decision 正确组合下 A0 initial 与 format repair 中唯一且一致的 `responds_to_current_contribution=true`。v1 不含正在响应的 pending，不能证明该标记。

重建逻辑位于 `tests/test_context_engineering_ce2a.py::test_versioned_ce2a_request_fixture_matches_all_request_boundaries`。它构造固定历史 pair 与 omission snapshot，经真实 Agent adapter 边界重建五类请求。`tools/freeze_ce2a_context_fixture.py` 对既有版本明确 `REFUSE_OVERWRITE`；新增版本必须换新文件名并人工审查差异。

## 7. 验证结果与未验证事项

专项覆盖包括：A0/A1 initial/format repair、行动契约 repair 的同快照注入；completed replay；运行中重复提交；payload conflict；started 遗留；工具后完成写失败；重启只恢复历史；多个 pending 与 scope/revision 过滤；超长最新回合零历史及精确 omission；版本化请求身份。CE-1/CE-1.1 请求回归在 v2 默认关闭时保持通过。

实际运行：

- `pytest -q tests/test_context_engineering_ce2a.py`：有限修补后 31/31 通过；
- `pytest -q`：有限修补后 637/637 通过；
- `git diff --check`：通过；
- `python tools/freeze_ce2a_context_fixture.py ce2a_requests_v1`：按预期以 `REFUSE_OVERWRITE` 拒绝覆盖。

冻结身份复核：CE-0 v1 SHA-256 仍为 `6e7711d19d1957c3dd60f8a0fceb2e9b27669b2d91bf2bf78f6d45cbe568eba6`；CE-1 pre-change manifest SHA-256 为 `025f52248f55d1e2711d8216f37cc3b2526fee6eda28129cd0740d7fe6eb3f77`；CE-2A v1 SHA-256 仍为 `04725681123a8d69fa229d056fa0af82604f261f22ffe33439eeb316f4bee2ee`；新增 CE-2A v2 SHA-256 为 `b044a153e58ff07d7518c983a0d38d8caca8dd3ee98c256fde373c5d299c8349`。

所有测试均为离线测试；它们只证明注入内容、顺序、边界与调用次数，不证明真实模型理解、指代恢复或任务成功率提高。本轮没有调用付费模型。

## 8. CE-2B 前置条件

CE-2B 仍需单独实现并验收 durable pending authority、原子 claim/consume/reject、权限单源切换、重启有效性与故障注入。若要从不确定记录自动恢复正常成功或支持多进程 exactly-once，还需把 durable operation correlation 写入所有权威 mutation receipt/ActionRecord，并建立共享 CAS/锁边界；本轮未实施，也未以启发式推断替代。
