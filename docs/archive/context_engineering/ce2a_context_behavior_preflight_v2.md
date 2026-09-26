# CE-2A 上下文行为评测预检（v2）

> 历史预检记录。当前模块状态见[上下文工程模块主文档](../../architecture/CONTEXT_ENGINEERING_DESIGN.md)，当前 behavior fixture 身份为 v3；真实运行仍默认禁用。

日期：2026-09-26
总体：**离线 ready；真实/付费运行 blocked by default**

| 检查 | 状态 | 结论 |
|---|---|---|
| v2 场景集合 | ready | 13 场景：H01–H06、P02、R01、O01、N01–N02、P01O、P01A |
| v1 保留 | ready | v2 以带 SHA-256 的 overlay 引用 v1；未覆盖 v1 文件 |
| 私有答案 | ready | 13 条私有 rubric 与 canary 均不进入 public fixture 或 adapter 请求 |
| 泄漏审计 | ready | P01O 当前文本不写目标且 Plan 为空；H04 已改为当前明确指令负对照 |
| pending 合法性 | ready | P01O/P01A 通过正式调查、Runtime 与权限策略产生诊断 pending；每个 C/T 起点恰有一项，未提交诊断 |
| 公开绑定 | ready | 案件、调查/诊断 ID 与公开描述匹配资源原文；人工历史有来源标记 |
| 条件隔离 | ready | 26 个 C/T 起点独立可写且身份等价；C/T 均记录，只切换 context v2 |
| 固定顺序 | ready | 13 × 2 条件 × 2 重复 = 52 回合，确定性 AB/BA |
| 调用上限 | ready | 每回合最多 2 次，共 104 次；DeepSeek adapter 无隐式网络重试 |
| 预算边界 | ready | provider 完整 payload 和实际 `max_tokens` 用于保守预留；测试价格明确不是真实报价 |
| Memory/Reflection | ready | 两条件均关闭 |
| O01 替换 | ready with documented substitution | 两个合法长回合触发较旧完整回合裁剪 |
| 冻结身份 | ready | v2 manifest 覆盖 overlay、v1 原文、runner、预算适配器、运行时、案件和测试内容 |
| 真实入口 | blocked as designed | 默认 `enabled=false`；未指定付费模型、有效价格、预算、批次、授权 ID 或双重付费确认 |

预检使用可控离线 adapter，没有读取密钥、没有网络请求，真实模型调用为 0。它只证明场景、上下文构建和确定性执行边界可运行，不证明模型理解或任务成功率提升。

真实运行前仍须由用户另行确认：具体支持模型；与该模型匹配、来源可核验且未过期的价格快照；总预算与单回合预算；唯一授权 ID；冻结场景子集；协议内授权与命令行 `--confirm-paid`。任一缺失均在 provider adapter 创建前拒绝。
