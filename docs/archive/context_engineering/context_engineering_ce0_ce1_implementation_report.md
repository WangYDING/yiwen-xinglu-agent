# 上下文工程 CE-0 / CE-1 实施报告

状态：已完成，停在 CE-1。实施日期：2026-09-24。

后续证据说明（2026-09-25）：独立审查无法验证 CE-0 v1 确实来自重构前实现；它应表述为“历史请求快照可用，重构前独立来源未能验证”。CE-1.1 已另建不可覆盖、可从源码快照重建的当前工作区 pre-change 基线，详见 [`context_engineering_ce11_implementation_report.md`](context_engineering_ce11_implementation_report.md)。本报告其余内容保留为当时实施记录。

本轮以开始实施时的实际工作区为基线，未把 `HEAD` 当作当前行为，也未覆盖、撤销或整理已有改动。没有调用付费模型，没有提交、推送或部署。

## 1. 结论

CE-0 已冻结 A0/A1 首次请求、结构化修复请求和行动契约修复请求；冻结对象是送入 `LLMAdapter.complete()` 的完整 provider-neutral 请求，包含消息角色、顺序、原文、完整输出 schema 和 A1 初始请求的输出上限。基线身份同时保存 Git commit、工作区状态摘要和相关文件内容 SHA-256。

CE-1 已将 A0/A1 现有上下文拼装及两类修复拼装抽取到确定性的 `ContextAssembler`。重构后五类实际请求与重构前夹具完全相等。新增 `ContextBuildTrace` 独立记录区块来源、版本、选择状态、精确字符数、精确 UTF-8 字节数、schema 摘要和构建策略，不写入模型消息。

未改变 Goal/Plan、权限、确认、记忆检索、工具执行、世界提交、fallback 或修复次数。A0/A1 仍保留各自接口和既有差异。

## 2. 设计文档与代码核对

设计方向成立，但以下事实以当前代码为准：

- 正式入口为 `ClinicService.submit_player_contribution()`，随后创建 `PlayerContribution`，调用 `CooperativeRuntime.handle()`。Runtime 恢复公开观察、会话和玩家，验证 pending 引用，恢复/调整 Goal/Plan，检索记忆，然后创建 `GameNPCAgentInput`。
- A1 首次消息的实际顺序为：system prompt、截取后的 `recent_messages`、本轮 user context。user context 内部依次为案件观察、公开环境反馈、权限、Goal、Plan、上次计划评价、pending 引用、记忆、公开行动空间、行动/计划契约、玩家贡献、玩家视图。设计文档的概括不是序列化顺序规范。
- A0 首次请求保持独立简化接口：system prompt、截取后的 `recent_messages`、user context；user context 为玩家视图、案件观察、玩家贡献、权限。
- `GameNPCAgentInput.recent_messages` 虽然存在，但正式 Runtime 当前不赋值，因此正式入口没有协作对话历史。案中人物对话的 `CaseDialogueState.recent_messages` 也不会进入该字段。
- `step_index` 和 `agent_state_revision` 会进入 `GameNPCAgentInput`，但当前 A0/A1 请求都不序列化它们。
- 名为 `pending_confirmation_id` 的 Agent 输入在 Runtime 中实际填入经验证 pending action 的 `decision_id`，而不是 `confirmation_id`。本轮只冻结并记录该语义，不迁移。
- A1 决策若未通过公开行动契约，既有修复路径使用 A0 的上下文和 `GameNPCDecisionProposal` schema，而不是 A1 Goal/Plan schema。本轮保持该行为。

## 3. 实际请求路径与契约

### 3.1 首次请求

```text
ClinicContributionInput
  -> ClinicService.submit_player_contribution
  -> PlayerContribution
  -> CooperativeRuntime.handle
  -> GameNPCAgentInput
  -> A1: GameNPCAgent.propose_turn / A0: SimpleActionGameNPCAgent.decide
  -> ContextAssembler
  -> LLMRequest
  -> BoundedStructuredOutput.run
  -> LLMAdapter.complete
```

A0 输出 schema 为 `GameNPCDecisionProposal.model_json_schema()`；A1 输出 schema 为 `GameNPCTurnProposal.model_json_schema()`。A1 初始请求继续使用专用请求类型并声明 `max_output_tokens=2048`。

### 3.2 结构化修复

初次响应无法解析或未通过确定性校验时，`BoundedStructuredOutput` 最多增加一次请求。修复请求严格沿用原请求全部消息，再追加：

1. `assistant`：初次无效原文；
2. `user`：截断到 1000 字符的校验信息和既有修复约束。

输出 schema 不变。既有实现将 A1 修复重新构造成基础 `LLMRequest`，所以 provider 输出上限回到适配器默认值；当前 DeepSeek 默认是 512。本轮没有把它“修正”为 2048，以免改变行为和成本边界。

### 3.3 行动契约修复

Runtime 在模型输出通过结构解析后调用 `PublicActionContractValidator`。首次行动契约失败且原决策只调用过模型一次时，最多调用一次 `repair_action_contract()`：

- 使用完整 A0 首次请求消息；
- 追加一个 `user` 安全反馈消息；
- schema 为 `GameNPCDecisionProposal`；
- 反馈只包含公开错误、当前公开调查、诊断候选和处置候选。

若原决策已发生结构化修复，或行动契约修复仍失败，则保持原有无模型安全 fallback。

### 3.4 DeepSeek provider 请求配置

`DeepSeekChatAdapter` 继续在发送前把完整 JSON schema 附加到首个 system message，并使用：

- `stream=false`；
- `response_format={"type":"json_object"}`；
- `thinking={"type":"disabled"}`；
- `temperature=0`；
- 不发送工具定义；
- A0 初始、两类格式修复和行动契约修复使用配置默认输出上限；A1 初始使用 2048。

## 4. CE-0 冻结资产

冻结夹具：`tests/fixtures/context_engineering/ce0_requests.json`。

覆盖场景：

- A0 首次请求，包含真实的最近 user/assistant 消息顺序；
- A0 结构化修复；
- A0 行动契约修复；
- A1 首次请求，所有当前可序列化的可选区块均有值，包括 Goal、Plan、评价、公开反馈、记忆、pending 引用和最近消息；
- A1 结构化修复。

冻结时 Git commit 为 `956a380aa357e09d8287d5fb4609aa3693227dad`，但该值不单独代表基线。夹具还保存工作区状态 SHA-256 `eb75070966b3e0d69722b328de2bff971408d709d345312adf43376bca44b13f`，并保存 11 个请求路径相关文件的内容 SHA-256。关键内容摘要包括：

| 文件 | SHA-256 |
|---|---|
| `agents/game_npc.py` | `dc08894dd603bf2c509518115840e9e0700b70df949ce23687ea817c4bba44b7` |
| `agents/llm.py` | `73d13d5c54cff42ea91007d1ecd9acbfb8da18f9cfa88ae35c26c54b219fe793` |
| `agents/deepseek.py` | `6e0132b64bc91d95b74f4d4984b236a4297db5941f18ef33fb69f8377118667a` |
| `agents/bounded_output.py` | `4d14826f680b1724cb1e9a5bc2881436ef5cf73bcfc0064e723a7866b79f95d2` |
| `application/cooperative_runtime.py` | `e143bf2347dedf96cda420d7988eb15d9c972d34e09124a0140d0b887a4d01ca` |
| `application/action_contract.py` | `fb3dd032c8248732ffd13842a976c84e6037cd0f20a0c51e907863d5609496cf` |
| `application/goal_plan_policy.py` | `1dfa809590a9dc8f0526163f3fcb483ca369cb796fa649be9389d0ac3bb40d9b` |

完整清单以夹具为准。`tools/freeze_context_baseline.py` 只用于显式创建新的基线版本；正常测试只读取冻结夹具，不自动更新预期值。

## 5. CE-1 实现

新增 `src/xuanyi_npc/agents/context.py`：

- `ContextAssembler`：确定性构建 A0、A1、格式修复和行动契约修复请求；无模型调用、无存储和世界写权限。
- `ContextBlockRecord`：记录区块名、来源、来源版本、选择策略、精确字符数和精确 UTF-8 字节数。
- `ContextBuildTrace`：记录请求类型、构建策略版本、prompt 版本、消息数量、消息和 schema 的精确长度、schema SHA-256 及请求级输出上限。
- `BuiltContext`：在内部同时返回请求和构建记录；只有 `request` 送入 adapter。

`GameNPCAgent.last_context_builds()` 提供当前线程最近一轮的独立记录。`SimpleActionGameNPCAgent` 透传该审计接口。正式 `decide()` / `propose_turn()` 开始时清空上一轮记录，后续修复记录按真实调用顺序追加。

长度语义是明确的：

- `exact_character_count` 是 Python 字符串的精确字符数；
- `exact_utf8_byte_count` 是 UTF-8 编码后的精确字节数；
- `token_count_method="not_measured"` 表示没有 tokenizer 计数；
- 本轮没有把字符数换算成“精确 token”，也没有加入字符到 token 的估算。

## 6. 验证结果

新增离线测试 `tests/test_context_engineering_ce0_ce1.py`，验证：

- 重构后的五类 adapter 实际请求与 CE-0 完整夹具相等，而非只比较新模块内部字段；
- 正式 Clinic 入口确实产生 A1 首次与格式修复请求，必要案件、权限、Goal、公开行动和玩家贡献均存在；
- 消息角色、顺序和 schema 在修复前后保持；
- A1 初始 2048 与修复默认 512 的既有差异保持；
- DeepSeek provider 请求配置保持；
- 构建记录不出现在模型消息中；
- A0 行动契约修复接口和消息顺序保持。

验证命令与结果：

- CE-0/CE-1 专项：6 项通过；
- Agent、规划、权限、结构化输出、DeepSeek、行动契约和正式 Runtime 相关回归：118 项通过；
- 全量离线测试：596 项通过；
- `git diff --check`：通过。

本轮没有测试失败，因此没有需要归类为“已有基线失败”的项目。

## 7. 已知限制

- `ContextBuildTrace` 当前是进程内、线程局部的最近一轮审计记录，没有持久化 sink。这足以验证 CE-1 构建行为，但不提供跨进程审计历史。
- 正式 Runtime 仍不提供协作对话历史；没有把案中人物聊天误接入 `recent_messages`。
- pending 字段命名与实际 decision ID 语义仍不一致；进程内 pending confirmation 的恢复缺口未解决。
- A1 行动契约修复仍使用 A0 上下文和 schema；A1 格式修复仍使用适配器默认输出上限。这些是明确冻结的现有行为，不是本轮新增设计。
- 本轮没有统一预算、动态裁剪、自动摘要、意图识别、讨论回合或暂停/拒绝策略。
- 构建记录只记录选择后的区块；由于 CE-1 不实施裁剪，没有 omitted 区块或省略理由。

## 8. CE-2 前置条件

进入 CE-2 前至少需要单独确认并实现：

1. 定义 `CooperativeTurnRecord` 的持久化接口、玩家/案件/会话隔离键、操作 ID 幂等和失败状态；
2. 明确 pending 字段到底引用 confirmation 还是 decision，并设计兼容迁移，不能在接历史时暗改权限语义；
3. 定义真实协作 user/assistant 回合的服务端角色赋值、写入时点和失败恢复，不复用案中人物聊天；
4. 决定构建记录的持久化 sink、访问控制和保留周期，避免复制大量原文；
5. 为连续追问、玩家改口、拒绝后再讨论、历史缺失、会话切换、重启恢复、重复操作以及工具成功但对话写入失败建立最终请求级夹具；
6. 保持记忆检索、Goal/Plan、权限和世界提交为独立边界，先观察 CE-2 的输入长度，再讨论 CE-3 预算。

本次实施到此停止，没有进入 CE-2。
