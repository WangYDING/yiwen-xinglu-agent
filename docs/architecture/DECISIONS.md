# 当前架构决策

## ADR-001：产品身份固定为《异闻行录》

产品是玩家与自主 NPC 协作调查六个志怪异案。修习、教学、考试、传承和师徒成长不属于产品范围。

## ADR-002：模型提议，规则提交

GameNPCAgent 只输出结构化 proposal。公开行动契约、计划策略和 `CaseEngine` 必须全部通过后才能产生状态事件；模型文本不是权威事实。

## ADR-003：玩家贡献不是工具命令

玩家输入被记录为 suggestion、hypothesis、challenge、evidence interpretation 或 question。NPC 独立评价并选择行动，应用层不把自然语言直接拼成 ToolCall。

## ADR-004：案件无需成长解锁

六案从产品入口直接可玩。旧 Apprenticeship/Progression 投影、Foundation 自动解锁和能力成长存档已经移除。病例仍可声明静态行动前置，但不会要求玩家完成外部课程。

## ADR-005：长期记忆来自可信来源

权威记忆只从成功提交的领域事件和通过证据校验的 Reflection 产生。聊天、模型自由文本、拒绝动作和错误日志不能写成事实。

## ADR-006：语义检索默认安全失败

检索必须执行玩家隔离、当前 Episode 排除、生命周期过滤、索引完整性检查和结果二次校验。任何异常都不得发送部分或越界历史给模型。

## ADR-007：M1–M5 是项目自己的评测链

M1–M5 分别验证 Cooperation、Planning/Replanning、Long-term Memory、Reflection 和 Agent Benchmark/Real LLM。旧 Doctor、导师教学和历史发布验收不再作为项目证据。

## ADR-008：M4.5 只作为当前 Memory 回归资料

保留 BGE-M3 模型身份、Gold、Holdout 和负结果，因为当前检索实现仍依赖这些边界。不得把有限合成实验描述为生产质量或玩家收益。
