# 架构与决策

包含系统权威边界、模块主文档、项目总纲、技术说明和追加式 ADR。当前产品状态以 [`../product/ROADMAP.md`](../product/ROADMAP.md) 为准。

## 模块主文档

以下八份文档是理解当前实现的首选入口：

- [案件与 Campaign](CASE_AND_CAMPAIGN_DESIGN.md)：案件定义、权威执行、评分、Campaign、入口与持久化边界。
- [协作运行时](COOPERATIVE_RUNTIME_DESIGN.md)：单回合编排、玩家贡献、pending、提交顺序、账本和恢复。
- [提交一致性与失败安全](COMMIT_CONSISTENCY_DESIGN.md)：world-first 提交、Session 串行、提交三态、入口幂等与恢复边界。
- [Planning 与行动契约](PLANNING_AND_ACTION_DESIGN.md)：Goal/Plan、公开行动空间、修复、对齐、Authority 与计划评估。
- [Context Engineering](CONTEXT_ENGINEERING_DESIGN.md)：最终模型请求、信息边界、选择/排序/预算、快照和版本轴。
- [Memory](MEMORY_DESIGN.md)：权威记录、投影、索引、跨 Session 检索、安全曝光和使用归因。
- [Reflection](REFLECTION_DESIGN.md)：触发、evidence、生成/修复、consolidation、幂等和失败隔离。
- [Evaluation](EVALUATION_SYSTEM_DESIGN.md)：冻结身份、执行保障、artifact、版本轴和结论边界。

Web/CLI/MCP 是入口适配层，JSON/SQLite 是横切持久化边界，分别在案件、运行时和 Memory 文档中说明，不单独包装成业务模块。全系统关系仍以 [`PRODUCT_SYSTEM_ARCHITECTURE.md`](PRODUCT_SYSTEM_ARCHITECTURE.md) 为准。

## 历史与专项证据

模块主文档描述当前状态；实施报告、修复记录、评测报告保留各自形成时的范围、测试数量和结论，不应被当作当前总状态。

- [上下文工程历史文档目录](../archive/context_engineering/README.md)：集中保存 CE 原始设计、实施、修复、预检和验收。
- [协作运行时历史目录](../archive/cooperative_runtime/README.md)：M1–M5 综合架构与面试指南。
- [Planning 与行动契约历史目录](../archive/planning_and_action/README.md)：P0–P5 修复链。
- [Memory 历史目录](../archive/memory/README.md)：Phase B 与 E9–E10。
- [Reflection 历史目录](../archive/reflection/README.md)：Phase C 与 E11–E13。
- [Evaluation 历史目录](../archive/evaluation/README.md)：早期 benchmark、E2–E8 和最终 3×1。
- [评测历史入口](../evaluation/README.md)：M/E/V2/V2.1、Memory、Reflection 与 Context 行为证据。
- [第一步提交一致性审计](COMMIT_CONSISTENCY_FAILURE_SAFETY_AUDIT_STEP1.md)：故障注入、修复前反例和当轮测试记录；当前设计口径以模块主文档为准。
- [产品路线图](../product/ROADMAP.md)：跨模块已实现、评测状态和明确缺口。
