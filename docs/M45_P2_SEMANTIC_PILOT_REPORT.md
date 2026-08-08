# M4.5-P2 本地语义 Pilot 停止记录

- **冻结提交**：`e81331255945e3baba34a0525b3c2f338321d841`
- **运行日期**：2026-08-08
- **结论**：第一次正式运行在评测器安全汇总阶段停止；P2 未完成，第二次重复性运行未启动

## 冻结身份

| 项目 | 值 |
|---|---|
| 输入 SHA-256 | `ca55bebdafaa59c06eab156c44316c2f862264e9082c71b768ab54d867674f3d` |
| Gold SHA-256 | `ee68a03de2e4a3adbd6fd81d9f751a94f1f504e37cf7e33573a7fcb0ae79ef80` |
| manifest SHA-256 | `9c17fbcc4f5f867ddcf40cf4ef056ab5299d65173595910d3312c97b4cccb9ef` |
| 配置 SHA-256 | `1c302cb2155260812278a70defae23d869aee094b1a28523210fb826a332fda8` |
| 模型 revision | `142964af7e05de16511657561de8e8750fc153a0` |
| 模型 manifest SHA-256 | `d4ee3716bb6c6c5dd850ea0cf1d64f0218aed9cfbbc52a6e8061f439a05965a4` |
| 主权重 SHA-256 | `993b2248881724788dcab8c644a91dfd63584b6e5604ff2037cb5541e1e38e7e` |
| 依赖锁 SHA-256 | `8e4179d4177fbafb62d6e1e17878ca7a71bb12c2d3d7d2747cf7ab83a1ffc0a6` |
| Embedding 空间 | `bge_m3_142964af7e05_dense_fp32_d1024_cuda_l512_v1` |

运行前 HEAD 精确等于冻结提交、工作树干净；15 个场景、60 个候选和 75 个唯一公开文本通过严格 Schema 与离线投影/检索预检。固定模型文件、依赖锁、CUDA 12.6 与 RTX 4070 SUPER 身份均通过。

## 实际停止事实

第一次正式运行加载本地模型 1 次并开始生成真实 BGE-M3 向量。完成场景检索后，冻结运行器抛出 `semantic Pilot safety stop condition triggered`。第一次运行记为 **stopped**，不能改写为模型通过或模型失败；第二次重复性运行、自动重跑和第三次运行均为 0。DeepSeek `/models`、Chat、外部 Embedding API 和网络模型请求均为 0，费用为 `0 CNY`。

忽略目录中的失败检查点 SHA-256 为 `6B7E35CD8A8F712061FA0576E7B6352F061C1494E8455008EB75893B6C7C1BA5`。冻结运行器在安全停止后、原始结果序列化前抛错，因此内存中的向量、15 条逐项排序、阈值与指标没有安全写出。不能补造这些数据，也不能使用这次停止记录计算 Recall、MRR、F1、False Memory Rate、Fake/BGE 差异或重复性结论。

## 离线根因

根因属于评测器契约，不属于 P1–P3 产品实现：`forbidden_candidate_ids` 同时承载了“语义上不相关的高字面重合诱饵”和“必须在候选阶段排除的生命周期/权限对象”；汇总代码把任意 `forbidden` 命中都计为 `inactive_memory_recall`。`semantic_lexical_distractor_001` 的活跃高字面诱饵本来用于测量排序质量，即使进入 ranking Top-3 也不等于失效记忆安全违规，因此标签复用误触了安全硬门槛。

下一次运行前需要把“语义负例”与“候选前必须排除项”拆成不同严格字段，增加契约测试，形成新的冻结检查点，并重新获得明确授权。不得反向修改已冻结 Gold 或把停止结果解释成通过。

## 当前边界

M4 与 M4.5-P1 仍保持完成。M4.5-P2 未产生可用正式指标，P3 准入线无法判断；M4.5-P3 和 M5 均未开始。此次停止不修改 M4 的 14 条工程 Gold、P1–P3 产品实现、Top-K、阈值网格、查询或模型空间。
