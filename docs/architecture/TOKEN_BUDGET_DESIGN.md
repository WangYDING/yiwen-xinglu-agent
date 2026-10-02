# Provider 请求预算与公开拒绝反馈

实施日期：2026-09-27。此文描述当前实现，不替代历史 CE-0/CE-1/CE-2A 冻结数据。

## 请求边界

`ContextAssembler` 构造完整公开请求和可信的裁剪候选；候选不是从模型输出推断的。`DeepSeekChatAdapter.complete()` 调用 `prepare_request()`，依次渲染候选，选择首个满足以下条件的最终 payload，随后费用预留和 HTTP 发送复用同一个 payload：

```text
sum(tokenizer(message.content)) + estimated_framing
    + max_output_tokens + safety_margin <= context_window
```

provider 已添加到 system 的完整 Schema 和 JSON-only 指令参与计数。HTTP 请求字段名、temperature 等不冒充模型输入 tokens。当前使用 DeepSeek 官方 V4 tokenizer，文件来源、日期和 SHA-256 记录在资源目录的 `provenance.json`；初始化只读本地资源，不联网下载。

framing 暂按基础 16 + 每条消息 16 估算，并非 provider 隐藏模板的精确复现。`ContextBudgetTrace` 明确标记估算方式；实际用量仍以 provider usage 为准。默认 65,536 是应用限制，不是声称 provider 仅支持这个窗口。更换模型/tokenizer 应重新校准。

## 配置与输出额度

| 配置 | 默认值 | 作用 |
|---|---:|---|
| `DEEPSEEK_CONTEXT_WINDOW` | 65536 | 应用输入加输出总窗口 |
| `DEEPSEEK_CONTEXT_SAFETY_MARGIN` | 1024 | 计数误差余量 |
| `DEEPSEEK_MAX_OUTPUT_TOKENS` | 512 | 无显式额度的通用请求默认值 |

Game NPC 请求显式覆盖输出额度：A1 initial/format repair 为 2048，A0 initial/format repair 和 action-contract repair 为 512。action-contract repair 保持既有 A0 Schema。repair 复用原快照与候选，加入无效输出及校验反馈后重新计数，不无限递归、不重读世界。当前不截断无效输出；repair 必选内容无法容纳时安全降级。

## 裁剪规则

1. 原始请求能放下时保持原始消息。
2. 移除 Memory 查询、候选统计和索引诊断，仅保留已过滤的 Memory 条目与 selected IDs。
3. 从最旧开始删除完整 user/assistant 历史 pair，保留时间顺序；显式说明旧历史选择元数据是预算裁剪前快照。
4. 逐条移除相关度最低 Memory，同分按 ID 确定顺序；保留条目的原始顺序和非权威标签。
5. 必选信息仍超限时抛出 `context_budget_exceeded`，不发送该次请求、不占用费用预留。BoundedStructuredOutput 记录原因并返回既有安全 fallback。

当前事实、完整 Goal/Plan/评价、用户贡献、权限、pending、公开动作参数、contracts 和输出 Schema 均不截断。候选生成使用 assembler 已知的字段边界，不解析用户伪造的分隔符。所有裁剪只影响当前视图，不修改持久状态或检索记录。模型 Memory 使用声明必须属于本次实际保留 ID；原有 MemoryUsageTrace 的 selected IDs 仍描述检索选择，最终暴露列表以 ContextBudgetTrace 为准。

`ChatMessage` 的输入字符保护为 2,000,000；响应 `PromptText` 仍为 20,000。上游 history、Memory 和 pending 的字符/条数限制继续保留。极端输入仍可能先触发独立输入保护；此机制不承诺任意大的必选状态都能调用模型。

## 审计与反馈

`ContextBuildTrace` 保持 assembler 字符/字节与来源记录。`ContextBudgetTrace` 记录最终内容 tokens、framing 估算、输出额度、安全余量、应用窗口、裁剪选择、保留 Memory IDs 和 tokenizer/payload 哈希；不保存密钥。adapter 提供当前线程的 `last_context_budget()`；有界调用的 attempt telemetry 保存每次成功响应或预算拒绝的预算记录。

`CooperativeAgentState.last_decision_feedback` 与 PlanEvaluation 分离，字段为 stage、reason_code、固定公开消息、retryable、action ID 和 observation revision。模型失败、预算拒绝、规划/对齐拒绝、行动契约 fallback、权限拒绝和工具失败可产生反馈。反馈在相同 observation revision 的下一轮注入，随后清除；新失败替换它，成功不会沿用旧反馈。它不授予权限，不暴露内部异常或隐藏规则，也不要求自动重试。

未提交完成、存储故障或提交结果不确定仍遵循原有恢复流程，不承诺所有异常都进入模型。A0 模型 fallback 使用通用模型失败分类；A1 预算失败有专门 budget 分类。没有付费模型行为实验，因此当前证据证明预算和安全不变量，不能证明裁剪提高任务成功率。

## 验证

`tests/test_context_token_budget.py` 覆盖完整 Schema 计数、精确边界、超限无 HTTP/费用预留、history pair 裁剪、Memory 排序、原状态不变、repair 增量和发送 payload 一致性。既有 CE 冻结文件不改写；测试对显式输出额度迁移单独断言，并继续验证历史 messages/Schema 等价。Runtime 测试检查反馈持久化、下一轮注入、成功清除和无工具副作用。
