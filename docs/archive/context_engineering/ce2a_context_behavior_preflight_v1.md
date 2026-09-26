# CE-2A 上下文行为离线预检（v1）

> 历史预检记录。当前模块状态见[上下文工程模块主文档](../../architecture/CONTEXT_ENGINEERING_DESIGN.md)，当前 behavior fixture 身份为 v3。

日期：2026-09-26
总体：**ready for offline controlled-adapter runs；blocked for real/paid runs**

| 检查 | 状态 | 结论 |
|---|---|---|
| 12 场景集合 | ready | H01–H06、P01–P02、R01、O01、N01–N02 完整 |
| 公开绑定 | ready | 六个真实案件的公开 investigation ID 与描述逐字匹配资源原文 |
| 私有答案 | ready | 每个场景一条私有 rubric；canary 不进入 adapter 请求 |
| 人工历史 | ready | 全部显式标记 `synthetic_evaluation_fixture` |
| 固定顺序 | ready | 两次重复，确定性 AB/BA，共 48 回合 |
| 调用上限 | ready | 当前 A1 边界最多 2 次/回合；上限 96，无 adapter 重试层 |
| 条件开关 | ready | C=`record on/context off`；T=`record on/context on` |
| 可选能力 | ready | Memory disabled；Reflection disabled |
| C/T 起点与隔离 | ready | 24 个场景条件起点均可独立建立且身份等价 |
| pending | ready | P01 两项有效；R01 服务重建后为零，不恢复授权 |
| 既有政策 | recorded | P01 的 question 回合完成后，现有 Clinic 会移除被精确引用的 pending；未修改该政策 |
| O01 | ready with documented substitution | 两个合法长回合触发较旧完整回合字符裁剪 |
| 冻结身份 | ready | 夹具、runner、相关运行时、案件资源和测试 SHA-256 匹配；运行时另复制全文及工作区状态 |
| 真实运行 | blocked as designed | 未指定模型、可核验价格、可靠 token 上界或付费授权；工具本身也没有真实 adapter |

预检没有发送网络请求，真实模型调用为 0。它只说明离线构建与运行边界具备执行条件，不评价模型理解。
