# 上下文工程 CE-0 / CE-1 独立审查

状态：审查完成。审查日期：2026-09-25。范围止于 CE-1；本轮未修改运行时代码、测试或冻结夹具，未调用付费模型。

后续状态：本审查提出的 CE-1.1 前置已完成；见 [`context_engineering_ce11_implementation_report.md`](context_engineering_ce11_implementation_report.md)。本文件保留为当时的独立审查记录，不回写其历史判断。

## 1. 审查结论

CE-1 的确定性抽取在当前样例上保持了完整 provider-neutral `LLMRequest`，正式 A1 首次请求和结构化修复也确实经过 `ClinicService -> CooperativeRuntime -> GameNPCAgent -> LLMAdapter.complete()` 路径。实现没有增加模型调用，`ContextBuildTrace` 没有进入模型消息，线程局部记录没有发现跨请求共享可变状态。

但 CE-0 不能被接受为“已独立证明来自重构前实现”的强基线。夹具固定了一个输出快照，也记录了摘要；当前仓库却没有保存与关键摘要对应的重构前源文件内容、补丁或不可变提交，原始 `git status --short` 文本也未保存。生成脚本还能无保护地用当前实现覆盖同一个 v1 夹具。因此本审查对其结论是：**请求快照可用，重构前独立来源未能验证**。

综合判断：CE-0 / CE-1 可以作为后续工程工作的“有保留接受”基础，但不能把现有测试表述为对重构前行为的独立证明。CE-2 开工前应先完成第 7 节列出的证据和审计语义收紧。

## 2. 风险分级发现

### [高] CE-0 的重构前独立性未能验证，且生成器可覆盖冻结 v1

证据：

- 夹具只保存 commit、工作区状态 SHA-256 和文件 SHA-256（[`ce0_requests.json`](../../../tests/fixtures/context_engineering/ce0_requests.json) 第 2–19 行），没有保存原始 `git status --short`、对应源文件、patch、tree/blob ID 或签名清单。
- 记录的 `game_npc.py` SHA-256 是 `dc0889...`；它既不等于当前文件 `4f47ba...`，也不等于 `HEAD` 文件 `fc6f03...`。这说明摘要指向第三种工作区内容，但当前仓库无法从摘要恢复或重算该内容。
- 记录的工作区状态摘要 `eb7507...` 与当前状态摘要 `79c66c...` 不同；由于原始状态文本未保留，不能判断前者究竟包含哪些修改。
- 夹具和生成脚本当前都未被 Git 跟踪，无法借助提交时间或树对象证明先后关系。
- 生成脚本从当前 `GameNPCAgent` 私有构建方法取请求（[`freeze_context_baseline.py`](../../../tools/freeze_context_baseline.py) 第 46–71 行），并无版本保护地覆盖同一路径（第 100–104 行）。重构后运行它也会生成一份能让当前测试通过的 v1。

影响：完整请求相等只能证明“当前实现等于当前保存的快照”，不能独立证明“当前实现等于重构前实现”。这不表示请求已经发生变化；只是证据链不足。

要求：保留现有 v1 不覆盖，并明确标注其 provenance 未验证。CE-2 前另建一个可验证的“CE-1 pre-CE-2 基线”：把源文件放入可寻址 Git tree/commit，或保存完整 patch/content bundle、原始状态清单和请求夹具清单；生成器必须拒绝覆盖既有版本。

### [中] 请求相等覆盖部分经过私有构建方法，正式路径覆盖不完整

证据：

- 五类夹具的主比较直接调用 `_request()`、`_planning_request()`、`_format_*_repair_request()`（[`test_context_engineering_ce0_ce1.py`](../../../tests/test_context_engineering_ce0_ce1.py) 第 51–77 行）。它比较了完整请求对象，但 A0 首次/格式修复并未通过 `decide()` 和 adapter。
- 正式 Clinic 测试只覆盖 A1 首次请求与 A1 格式修复（第 165–200 行）。
- 行动契约修复调用了真实 adapter，但 prior decision 是测试人工构造的，未从 Runtime 的 A1 行动契约失败路径触发（第 35–48 行）。
- provider 配置测试也从私有构建方法创建请求，只断言当前 `_chat_payload()` 的若干配置字段（第 135–163 行），没有冻结重构前完整 provider payload。

已覆盖：A0/A1 代表性消息内容、角色、顺序、完整 schema、A1 初始 2048 上限、两类格式修复和一种行动契约安全反馈。

主要遗漏：正式 A0 Clinic 路径、正式 A1 行动契约修复、`llm_attempts != 1` 时跳过修复、行动契约二次失败 fallback、空/截断历史、不同 `recent_message_limit`、诊断/处置 action space、1000 字符错误截断、adapter abort/error，以及完整 provider payload 快照。

影响：当前覆盖足以发现主要序列化漂移，但不足以声称所有首次和修复分支都经过实际 Agent/Runtime 路径验证。

要求：CE-2 前或 CE-2 第一批测试中补齐正式 A0、正式 A1 action-contract repair 和无额外模型调用的请求捕获。新测试必须观察 `ScriptedFakeLLM.requests` 或等价 adapter 边界，而不是只调用 assembler。

### [中] `ContextBuildTrace` 的版本与“精确长度”语义不够准确

证据：

- `GameNPCAgentConfig.prompt_version` 只有字面值 `game_npc_m1`（[`game_npc.py`](../../../src/xuanyi_npc/agents/game_npc.py) 第 71–75 行），A1 构建也把该值写入 `GAME_NPC_M2_PLANNING_PROMPT` 的 trace（[`context.py`](../../../src/xuanyi_npc/agents/context.py) 第 284–317 行）。因此 A1 trace 的 prompt 版本不足以识别实际 M2 prompt。
- 多数 `source_version` 使用 `input`、`current`、`same_request` 或 `attempt_1`（第 293–308、351–354、393–400 行）。这些是来源状态或尝试标签，不是可重现的版本标识。
- `exact_message_character_count` 和 `exact_message_utf8_byte_count` 通过拼接 `message.content` 计算（第 99–116 行），不包含 role、消息边界、JSON framing 或 DeepSeek 后加的 schema instruction。数值对“消息内容总量”是精确的，对“实际 provider 消息序列化长度”不是精确的。
- action-contract trace 固定名为 `a0_action_contract_repair`（第 402–408 行）；当它由 A1 turn 触发时，能说明使用了 A0 请求形状，却不能单独说明来源架构是 A1。

影响：这些问题不改变模型输入，但会降低审计记录对版本、架构来源和长度口径的解释力。CE-2 增加历史来源后会放大歧义。

要求：在 CE-2 注入前定义独立的 prompt ID、source revision/ref、`content_*` 与 `provider_payload_*` 两种长度口径，并在 trace 中同时记录 `origin_architecture` 与 `request_shape`。不要把估算或 content 长度称为精确 token/provider payload 长度。

### [低] Trace 是请求发送前的同步必经步骤，增加了很小的失败面

`_record_built_context()` 在 adapter 调用前追加 trace（[`game_npc.py`](../../../src/xuanyi_npc/agents/game_npc.py) 第 198–206、261–279 行）。`_trace()` 会重新序列化 schema、编码文本并计算哈希；若这些操作异常，请求不会发送。对当前受限 schema 和消息长度，正常异常风险很低，但它与重构前“没有 trace 计算”的失败语义并非形式上完全相同。

这不阻塞 CE-2。建议保持 fail-closed，并为显式 `ContextBuildError` 提供稳定错误码，而不是吞掉错误或在 trace 失败后无审计地继续调用模型。

## 3. 实际请求链核对

正式协作入口在 [`clinic.py`](../../../src/xuanyi_npc/application/clinic.py) 第 261–292 行：请求被转换为 `PlayerContribution`，pending 目前从进程内字典读取，再创建 `CooperativeRuntime`。

Runtime 在 [`cooperative_runtime.py`](../../../src/xuanyi_npc/application/cooperative_runtime.py) 第 121–180 行恢复公开案件、会话、玩家、Goal/Plan 和记忆，构造 `GameNPCAgentInput`；正式路径没有设置 `recent_messages`。A1 调用 `propose_turn()`，A0 调用 `decide()`（第 174–180、290–295 行）。

`decide()` / `propose_turn()` 会清空当前线程的 trace tuple、构建首次请求并进入 `BoundedStructuredOutput.run()`（[`game_npc.py`](../../../src/xuanyi_npc/agents/game_npc.py) 第 124–178 行）。后者对初次请求调用一次 adapter，只有解析/确定性验证失败时才构建并调用一次格式修复请求（[`bounded_output.py`](../../../src/xuanyi_npc/agents/bounded_output.py) 第 69–109 行）。

Runtime 在计划对齐检查后才调用 `_resolve_contract()`（[`cooperative_runtime.py`](../../../src/xuanyi_npc/application/cooperative_runtime.py) 第 263–295 行）；公开行动契约失败时才调用 `repair_action_contract()`（第 1205–1217 行）。该修复直接调用同一个 adapter，不经过 `BoundedStructuredOutput.run()` 的第二次格式修复。

## 4. 五类夹具的实际内容

| 夹具 | 角色顺序 | schema | 请求输出上限 | 结论 |
|---|---|---|---:|---|
| `a0_initial` | system, user, assistant, user | `GameNPCDecisionProposal` | adapter 默认 | 含两条人工 recent messages 与当前 A0 user context |
| `a0_format_repair` | 上述 + assistant, user | 同上 | adapter 默认 | 含无效原文和修复反馈 |
| `a0_action_contract_repair` | system, user, assistant, user, user | 同上 | adapter 默认 | 含 A0 context 与安全反馈，不含 prior 输出 |
| `a1_initial_full_state` | system, user, assistant, user | `GameNPCTurnProposal` | 2048 | Goal/Plan/评价/记忆/pending/recent 均非空 |
| `a1_format_repair_full_state` | 上述 + assistant, user | 同上 | adapter 默认 | 保留原请求并追加无效输出和反馈 |

当前 fixture 的 canonical schema SHA-256 分别为 A0 `b48b7677...`、A1 `016d0aca...`。专项测试确认当前实现仍生成相同对象。

## 5. ContextBuildTrace 审查

已确认：

- `ContextAssembler` 自身无模型或存储调用；`BuiltContext` 将 request 与 trace 分离。
- `GameNPCAgent` 使用 `threading.local()` 保存 tuple；每个公开首次调用重置，格式修复和行动契约修复按调用顺序追加。没有发现跨线程共享 list/dict。
- 首次请求、A0/A1 格式修复和行动契约修复具有不同 `request_kind`；A1 初始 2048 与修复 `None` 可区分。
- adapter 只接收 `built.request`。trace 没有任何序列化到 `LLMRequest.messages` 的路径；专项测试也验证消息中没有 trace 类型名。
- trace 构建没有额外 adapter 调用。

保留意见是第 2 节所述的版本和长度口径，而不是模型上下文泄漏。

## 6. 三项既有差异

### 6.1 A1 格式修复回到默认 512

代码事实：A1 初始使用 `GameNPCPlanningRequest(max_output_tokens=2048)`；格式修复重新构造基础 `LLMRequest`，不带该字段（[`context.py`](../../../src/xuanyi_npc/agents/context.py) 第 284–291、343–350 行）。DeepSeek 取 request 字段或 config 默认值，当前默认 512（[`deepseek.py`](../../../src/xuanyi_npc/agents/deepseek.py) 第 553–586 行）。

触发条件：A1 初次响应已返回，但 JSON/schema/确定性计划策略解析抛出 `ValidationError` 或 `ValueError`。

代码可确认的影响：修复调用最多只允许 512 输出 token，schema 和原始上下文不变。

尚需实验验证的风险：复杂 A1 修复是否因此更易截断或 fallback；现有离线测试不能回答模型可靠性。

CE-2 阻塞性：不阻塞。CE-2 必须继续冻结该差异，格式修复复用同一历史/pending 快照，不借 CE-2 改输出上限。

### 6.2 A1 的行动契约修复使用 A0 上下文/schema

代码事实：`repair_action_contract()` 固定使用 M1 prompt、A0 parts 和 `GameNPCDecisionProposal`（[`game_npc.py`](../../../src/xuanyi_npc/agents/game_npc.py) 第 208–227；[`context.py`](../../../src/xuanyi_npc/agents/context.py) 第 367–408 行）。只有 prior `llm_attempts == 1` 才调用模型；否则直接 fallback。

触发条件：首次结构化决策已经通过 A1 解析、Goal/Plan policy 和计划对齐，但其 action 未通过 `PublicActionContractValidator`。

代码可确认的影响：修复模型看不到 A1 的 Goal、Plan、上次评价、memory context 和 A1 契约；修复后的 action 会再次做公开行动契约校验，但当前流程不会重新执行先前的 `_action_matches_plan()`。

尚需实验验证的风险：模型是否会因此生成与已应用 Plan 不一致的公开合法 action，以及发生频率。离线结构允许该风险，但没有真实发生率证据。

CE-2 阻塞性：不阻塞历史/待确认注入；CE-2 必须让该 A0 形状修复获得与首次请求同一份协作历史和 pending 公共投影，同时保持 Goal/Plan 缺失这一旧差异。计划重校验应另立安全修复，不混入 CE-2。

### 6.3 `pending_confirmation_id` 实际承载 decision ID

代码事实：Clinic 用真正 `confirmation_id` 从进程内字典找记录（[`clinic.py`](../../../src/xuanyi_npc/application/clinic.py) 第 261–270 行），Runtime 经过 ownership、approval、decision ID 和 case revision 校验后，却把 `pending.decision_id` 写进名为 `pending_confirmation_id` 的 Agent 字段（[`cooperative_runtime.py`](../../../src/xuanyi_npc/application/cooperative_runtime.py) 第 155–172、1220–1227 行）。

代码可确认的影响：A1 只得到不透明 decision ID；A0 user context不序列化该字段。真正授权仍由完整 `PendingActionConfirmation` 和 `NPCAuthorityPolicy` 决定，因此模型看到的 ID 本身不授权。

尚需实验验证的风险：不透明 ID 对模型协商理解有多大影响；当前没有真实模型对照。

CE-2 阻塞性：**阻塞 pending 公共上下文的直接实施，直到数据契约确定**。推荐新增包含 `confirmation_id` 和 `decision_id` 的结构化 `ActivePendingConfirmationView`，保留旧字段作为兼容输入但不再把它当完整 pending 语义。禁止从历史文本恢复授权。

## 7. CE-2 开工前条件

1. 将现有 CE-0 v1 标为“历史请求快照，重构前 provenance 未能验证”，禁止覆盖。
2. 建立可寻址、可重算的 CE-1 pre-CE-2 代码与请求基线；完整保存原始工作区清单而不只保存摘要。
3. 修正或明确 trace 的 prompt 版本、source version/ref、content 长度口径和 origin architecture。
4. 为正式 A0、正式 A1 action-contract repair、跳过/失败 fallback 补 adapter 边界测试。
5. 采用 CE-2 设计中的 durable pending 契约；旧存档无 durable pending 时必须 fail-closed。

满足以上条件后，CE-2 才具备实施条件。它们不要求先解决 A1 512 上限或 A0 repair 形状差异。

## 8. 本次验证

实际运行：

- `pytest` 专项集合 74 项通过：CE-0/CE-1、M1 Agent、M2 planning、M1 Runtime、正式生产接线、DeepSeek adapter、A0/A1 slim wiring。
- 对 fixture 元数据、当前文件和 `HEAD` 文件逐项计算 SHA-256；结果见第 2 节。
- 解析五类 fixture，核对角色顺序、消息数、schema SHA-256 和输出上限。
- 检查正式入口、Runtime、structured repair、action-contract repair、DeepSeek payload 和存储实现。

未验证：重构前源文件内容、夹具生成先后关系、真实模型对 512 修复或 A0 repair 的行为、崩溃/并发恢复、CE-2 注入效果。未运行付费模型，也未重复全量 596 项测试；本轮没有运行时代码变化，专项回归足以回答本次审查问题。
