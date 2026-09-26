# 上下文工程 CE-1.1 实施报告

日期：2026-09-25。范围：可信当前基线、ContextBuildTrace 语义、请求边界测试。CE-2 未实施。

## 1. 基线结论

原 `tests/fixtures/context_engineering/ce0_requests.json` 保持原样，SHA-256 为 `6e7711d19d1957c3dd60f8a0fceb2e9b27669b2d91bf2bf78f6d45cbe568eba6`。它仍可作为五类历史请求快照，但没有保存足以证明“来自重构前”的独立材料，因此其重构前独立来源仍是**未能验证**，不得用当前实现重新生成的结果补写该结论。

本轮在任何运行时代码和测试修改之前新增独立目录：

```text
tests/fixtures/context_engineering/ce1_pre_change_v1/
```

它明确属于“CE-1.1 修改前的当前工作区基线”，不是 CE-0 或重构前基线。身份材料包括：

- `workspace_status.txt`：原始 `git status --short --branch --untracked-files=all`；
- `environment.json`：Git HEAD `956a380aa357e09d8287d5fb4609aa3693227dad`、Python 与依赖版本、分类和排除项；
- `snapshot/`：请求生成所需的源码 package import closure、配置、病例资源、输入构造和自带重建程序；没有复制 `.env`、凭据、玩家运行数据、模型结果目录或工作区外文件；
- `requests.json`：A0 initial/format repair、A1 initial/format repair、A1-origin A0-shape action-contract repair；
- `provider_payloads.json`：同五类请求经离线 DeepSeek adapter 形成的 payload；placeholder key 不进入 payload；
- `sha256s.json`：138 个源/配置/产物文件的大小和 SHA-256；生成的 Python bytecode 不属于签名集合；
- `manifest.json`：基线分类和关键产物摘要。`requests.json` SHA-256 为 `ae11bf9e98cf1e54274edd69d3044a88f3730977e73c08d4f64c15bd8ae79841`。

冻结时从 `snapshot/rebuild_requests.py` 在 snapshot 工作目录独立运行两次，并与保存的 provider-neutral requests 和 provider payloads 做完整结构比较；不是只比较摘要。专项测试还会再次从 snapshot 重建，并用修改后的当前代码通过公共 Agent 方法重建相同五类请求，二者都必须等于冻结文件。

新增 `tools/freeze_ce1_context_baseline.py` 和 `tools/context_request_rebuild.py` 供未来创建新的版本目录。新工具及旧 CE-0 工具在目标已存在时均以 `REFUSE_OVERWRITE` 失败；测试确认失败前后冻结文件字节不变。

## 2. ContextBuildTrace 修订

`ContextBuildTrace` 仍只保存在 `GameNPCAgent` 的 thread-local build records 中，不写入 `LLMRequest.messages`，不增加模型调用或输出字段。

语义修订如下：

- `origin_architecture`：请求所属的 A0/A1 调用路径；
- `request_shape`：实际为 `a0_decision` 或 `a1_turn`；
- `request_stage`：`initial`、`format_repair` 或 `action_contract_repair`；
- A1 的行动契约修复现在准确记录为 `origin_architecture=A1`、`request_shape=a0_decision`，没有改变既有 repair shape；
- prompt 使用实际首条 system message 的 SHA-256 和源码引用作为身份；保留的 `prompt_config_version` 被明确标为配置值，不再冒充 M2 prompt 身份；
- 每个 block 的 `source_ref` 与 `source_revision=sha256:<exact content>` 分离；不再使用含义不清的 `input/current` 版本占位；
- 长度字段明确限定为“拼装后 message content”或“canonical schema JSON”，分别保存精确字符数和 UTF-8 字节数；角色/envelope/provider payload 不在这些数字内；
- `token_count_method` 和 `provider_payload_measurement` 都明确为 `not_measured`。provider payload 只在独立基线/adapter 测试中测量，trace 不宣称测量。

Agent 在 `decide()` 和 `propose_turn()` 入口分别保存 A0/A1 origin，action-contract repair 沿用该 origin。thread-local 容器仍按每次入口清空，没有共享可变列表、跨线程串请求或新的异常传播点。

## 3. 请求等价与边界覆盖

新增 `tests/test_context_engineering_ce11.py`，覆盖：

- 公共 `GameNPCAgent.decide()` 的 A0 initial + format repair；
- 公共 `GameNPCAgent.propose_turn()` 的 A1 initial + format repair；
- 正式 Clinic + `SimpleActionGameNPCAgent` A0 入口，在 adapter 边界捕获 initial/repair 与调用次数；
- Runtime 实际 `_resolve_contract()` 路径触发 A1-origin action-contract repair，并在 adapter 边界捕获请求；
- 已经发生格式 repair 时跳过 action repair；
- action repair 输出无效时 fallback，不执行工具；
- A0 action repair 后仍按无显式 Plan 的既有行为执行合法动作。

修改后当前代码产生的五类完整 `LLMRequest.model_dump()` 和五类 adapter payload 与 pre-change 冻结文件完全相等。因此 CE-1.1 的 trace 变更保持消息角色、内容、顺序、schema、max output 和 provider 请求配置等价。既有 A1 initial 2048、格式 repair 默认 512、行动 repair A0 shape 均未更改。

## 4. 与独立行为修复的边界

同轮另有一项 Runtime 行为修复：行动契约 repair 替换 action 后重新做 Plan 对齐。它有意把“执行不匹配工具”改成拒绝，不能归入“请求等价”的 trace 结论。复现、风险与验证单独记录在 [`action_contract_repair_plan_alignment_fix.md`](action_contract_repair_plan_alignment_fix.md)。

无需新增 post-fix 请求基线：该修复发生在最后一次模型请求返回之后，不改变任何模型请求；CE-1 pre-change 请求基线和 adapter 等价测试已直接覆盖这一点。行为变化由独立 Runtime 回归冻结。

## 5. 已知限制与 CE-2 前置

- CE-0 v1 的重构前来源仍未能验证；CE-1 pre-change v1 只能证明本轮修改前后的等价。
- A1 format repair 的默认 512 上限和 A1 action repair 使用 A0 shape 是保留的兼容事实，不在本轮修正。
- `pending_confirmation_id` 当前仍实际承载 decision ID；CE-2 设计要求用结构化 pending view 演进，但本轮未实施。
- trace 不计算 provider token，也不测量最终 HTTP body；这两项必须继续标为未测量。
- CE-2 可在 CE-1.1 和计划复核已完成的前提下进入 CE-2A；durable 授权、exactly-once world mutation 与自动正常恢复仍受 operation correlation/CAS 限制，见修订设计。

## 6. 验证记录

已运行的专项组包括 context、规划、权限、结构化 fallback、治疗行动契约、A0/A1 Runtime 和正式 Clinic wiring，共 81 项通过（3.70 秒）。完整离线 pytest 共 606 项通过（42.02 秒）。另运行 `git diff --check` 与本轮文本文件尾随空白检查。未调用真实或付费模型。
