# 架构与决策

包含系统权威边界、项目总纲、技术说明和追加式 ADR。当前产品状态以 [`../product/ROADMAP.md`](../product/ROADMAP.md) 为准。

- [上下文工程模块主文档](CONTEXT_ENGINEERING_DESIGN.md)：当前实现、数据流、信息边界、六个工程维度、故障契约、证据和阶段状态的首选入口。当前范围完成到 CE-2A；CE-2B、完整 CE-3 与真实模型语义收益验证暂缓。

以下文件保留为历史或专项证据；当前结论以主文档为准：

- [上下文工程历史文档目录](../archive/context_engineering/README.md)：集中保存以下原始设计、报告、修复与验收记录。

- [上下文工程 CE-0 / CE-1 实施报告](../archive/context_engineering/context_engineering_ce0_ce1_implementation_report.md)：请求基线、实际数据路径、构建记录、验证结果与 CE-2 前置条件。
- [上下文工程 CE-0 / CE-1 独立审查](../archive/context_engineering/context_engineering_ce0_ce1_review.md)：基线证据强度、请求覆盖、trace 风险和有保留验收结论。
- [上下文工程 CE-1.1 实施报告](../archive/context_engineering/context_engineering_ce11_implementation_report.md)：可独立重建的当前工作区基线、trace 语义和 adapter 边界验证。
- [行动修复后的计划对齐记录](../archive/context_engineering/action_contract_repair_plan_alignment_fix.md)：已复现缺口、执行前复核和回归证据。
- [上下文工程 CE-2 详细设计](../archive/context_engineering/CONTEXT_ENGINEERING_CE2_DESIGN.md)：已实施的 CE-2A 历史/公开投影与尚未实施的 CE-2B durable pending/授权消费。
- [上下文工程 CE-2A 实施报告](../archive/context_engineering/context_engineering_ce2a_implementation_report.md)：SQLite 回合日志、完整回合选择、进程内 pending 投影、请求夹具、恢复与保证边界。
- [CE-2A replay 与 pending 标记修补](../archive/context_engineering/context_engineering_ce2a_replay_fix.md)：completed replay 检查顺序、无效新 pending 生命周期和双 ID 响应标记。
- [CE-2A 最终请求上下文有限质量验收](../archive/context_engineering/ce2a_context_quality_acceptance_20260926.md)：代表性最终请求与确定性边界验收；不构成真实模型语义收益证明。
