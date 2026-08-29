# 技术总览

《异闻行录》的运行链是：

```text
玩家贡献
  → CooperativeRuntime
  → GameNPCAgent（Goal / Plan / Memory / Reflection）
  → 结构、公开行动和计划策略校验
  → CaseToolExecutor
  → CaseEngine
  → JSON / SQLite 权威状态与事件
```

## 权威边界

- LLM 只能提出公开行动，不能直接修改案件、玩家或记忆。
- 隐藏真相不进入 Agent 公开视图。
- 玩家文本不会直接转换成工具调用。
- `CaseEngine` 负责调查前置、诊断、处置、评分和领域事件。
- 长期记忆只从已经提交的公开领域事实与经验证 Reflection 投影。
- 检索先做玩家、生命周期、类型和当前 Episode 隔离，再进行向量排序。

## 产品边界

正式入口提供六案调查、NPC 协作、Campaign、Memory 和 Reflection。不提供修习、课程、考试、传承、师徒关系成长或自动解题 CLI。

## 资源边界

运行时只打包六个病例、Campaign 规则、案件引导、Web 静态资源和 DeepSeek 预算策略。实验 Gold、模型文件、结果、玩家数据和环境文件均不进入 wheel。

M4.5 BGE-M3 资料保留在 `docs/archive/` 与 `tools/experiments/`，用于当前语义记忆回归，不是另一条产品路线。
