# 《异闻行录》文档导航

《异闻行录》的唯一正式身份是 Human-Agent Cooperative Game NPC System。玩家与 `GameNPCAgent` 组成调查搭档；Agent 维护 Goal/Plan、使用受限 Memory，并在确定性 Authority 与 `CaseEngine` 边界内自主推进调查。

## 当前权威文档

- [项目总纲](architecture/PROJECT_MASTER_BLUEPRINT.md)
- [产品系统架构](architecture/PRODUCT_SYSTEM_ARCHITECTURE.md)
- [路线图](product/ROADMAP.md)
- [项目首页](../README.md)
- [开始游戏](../START_HERE.md)

## 当前 Cooperative Agent 验证

- [M5 Agent Benchmark 与失败分析](benchmarks/m5/agent_benchmark_report.md)
- M5-12 post-fix 完整原始材料因体积与数据边界不随仓库分发；仓库仅提供脱敏结果与可复现协议。
- [M5-3 / M5-12 pre-post summary](benchmarks/m5/m5_12_pre_post_summary.json)

M1–M5 分别覆盖 Human-Agent Cooperation、Planning/Replanning、Long-term Memory、Reflection 和 Agent Benchmark / Real LLM Validation。这是《异闻行录》自己的正式评测链。

## 架构与案件

- [架构决策记录](architecture/DECISIONS.md)
- [产品案件设计](product/R5_CASE_DESIGN.md)

## 语义 Memory 实验依据

M4.5 的 BGE-M3、语义 Gold、Holdout、负结果和终止审计继续保留，因为当前生产 Memory 路径仍使用这些模型身份、数据门禁和失败分析作为回归依据。它们属于《异闻行录》的 Memory 工程证据，不是独立历史产品。

相关执行工具与冻结数据位于 [`tools/experiments/`](../tools/experiments/README.md)。

## 本地生成内容

`.venv/`、`runtime_models/`、`runtime_data/`、`results/` 和 `.env` 不进入 Git。环境、模型和当前玩家存档继续保留；`results/` 目前只保留仍用于 Memory 审计的 M4.5 结果。
