# 实验工具边界

- `runners/`：实验执行、冻结和诊断脚本。
- `data/evaluation/`：当前语义记忆 Gold 与 Holdout。
- `model_manifests/`：本地模型身份清单。

这些内容属于工程与研究实验资产，不进入 wheel 或 sdist，也不由正式产品运行时导入。正式产品资源的唯一真源仍是 `src/xuanyi_npc/resources/`。
