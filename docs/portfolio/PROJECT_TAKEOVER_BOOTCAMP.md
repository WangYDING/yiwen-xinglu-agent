# 《异闻行录》项目接管训练营

## 目标

这不是阅读清单，而是一套 ownership 训练。完成后，你应能不依赖 Codex：

1. 用白板讲清一回合从玩家输入到世界状态变化的完整链路；
2. 在 30 分钟内定位并修改一个跨层规则；
3. 解释 Planning、Memory、Reflection 为什么不是 Prompt 装饰；
4. 用测试、事件和 benchmark 证明结论；
5. 主动说清项目的失败、限制和下一步。

## 先建立正确心智模型

项目的核心不是“古风问诊网页”，也不是“调用 DeepSeek 聊天”。它是一个受约束的 Agent 决策系统：

```text
玩家贡献
  → 公开 Observation
  → 受范围约束的历史 Memory
  → GameNPCAgent 提出 Goal / Plan / Decision
  → PublicActionContract 校验动作与参数
  → GoalPlanPolicy 校验计划与当前公开行动空间
  → Authority Policy 判断自主、协商、确认或禁止
  → Tool / CaseEngine 改变权威世界状态
  → PlanEvaluator 判断继续、修订或完成
  → 有结果证据时生成并验证 Reflection
```

必须始终区分三类东西：

| 类别 | 例子 | 谁说了算 |
|---|---|---|
| 当前事实 | 已发现线索、病例状态、可用调查 | `CaseEngine` 与领域状态 |
| Agent 意图 | Goal、Plan、下一步 Tool proposal | LLM/Fake Agent 提议，策略层验证 |
| 历史经验 | 过去 Episode 的 Memory/Reflection | 可检索但非权威，当前事实优先 |

## 14 天路线

每天以“先预测 → 再运行 → 看状态/测试 → 用自己的话复盘”完成。只看文档不算完成。

### 第 1–2 天：产品与地图

- 启动 `xuanyi-clinic`，完成一案；记录一次调查、诊断、确认处置。
- 找到对应玩家、会话和 Agent 状态文件，比较操作前后差异。
- 手绘五层：交互层、应用编排层、Agent 层、领域/引擎层、存储层。
- 交付：一张系统图 + 3 分钟录音，不照稿讲项目。

### 第 3–4 天：确定性病例链

- 阅读 `application/clinic.py`、`application/multicase.py`、`engine/case_engine.py`。
- 跟踪一个 `question_patient` 如何变成 command、event 和新 session revision。
- 再跟踪一次非法诊断，说明为什么拒绝后零状态写入。
- 交付：一张时序图；指出权威状态真正提交的位置。

### 第 5–6 天：Cooperative Agent 主链

- 阅读 `agents/game_npc.py` 与 `application/cooperative_runtime.py`。
- 对照 `action_contract.py`、`goal_plan_policy.py`、`npc_authority.py`、`plan_evaluator.py`。
- 分别制造：非法参数、隐藏 target、未确认高风险处置；观察被哪一层拒绝。
- 交付：能回答“为什么模型不能直接调用引擎”。

### 第 7–8 天：Memory 与 Reflection

- 阅读 `game_npc_memory.py`、`memory_coordination.py`、`reflection.py`、`reflection_memory.py`。
- 解释 `retrieved/selected ≠ used`，并找到 `selected → declared → accepted` 的代码与测试。
- 跑一次弱证据 Reflection 拒绝用例，确认没有写入未来 Memory。
- 交付：用一个真实例子说明历史如何改变 Plan，但不能覆盖 Observation。

### 第 9–10 天：存储、事件与恢复

- 阅读 `storage/json_store.py`、`storage/sqlite_memory.py`、`engine/replay.py`。
- 人为注入记忆投影失败，观察权威世界提交与派生投影恢复。
- 重放一条事件 fixture，核对事件序列与最终状态。
- 交付：解释为什么 JSON 和 SQLite 不是双主数据库。

### 第 11–12 天：评测与失败分析

- 阅读 `docs/benchmarks/m5/agent_benchmark_report.md`。
- 复述三次真实故障：输出截断、Tool 参数错误、Plan target 不合法。
- 解释为什么 3 个 `IMPROVED` 不能写成“提升 60%”，9/9 也不能写成生产准确率 100%。
- 交付：一页“证据层级”：确定性证明、真实模型观察、尚未证明。

### 第 13–14 天：真正改一次项目

- 为一个病例新增有前置条件的调查项，连带更新资源、公开视图和测试。
- 再写一个你自己设计的负向测试，验证拒绝后 revision、events 和存档均不变。
- 跑全量测试并记录影响面。
- 交付：一次 10 分钟代码讲解，包含需求、改动、测试和取舍。

## 八个毕业实操

| 实操 | 通过标准 |
|---|---|
| 完成一案 | 能解释每次状态变化，不只会点页面 |
| 跟踪一次合法 Tool | 能指出 proposal、validation、commit、replan 四个位置 |
| 跟踪一次拒绝 | 证明没有危险执行和状态污染 |
| 新增规则测试 | 测试不是复制现有用例 |
| 制造 Adapter 错误 | 能区分 repair、fallback、system safety |
| 制造投影失败 | 能解释权威事实与可恢复投影 |
| 修改病例规则 | 资源、领域、展示、测试一致更新 |
| 口头答辩 | 3 分钟介绍 + 15 分钟追问不依赖文档 |

## 代码导航锚点

| 问题 | 首先打开 |
|---|---|
| 一回合谁编排？ | `application/cooperative_runtime.py` |
| Agent 输入输出是什么？ | `agents/game_npc.py` |
| 当前动作是否合法？ | `application/action_contract.py` |
| Plan 是否引用公开目标？ | `application/goal_plan_policy.py` |
| 是否需要玩家确认？ | `application/npc_authority.py` |
| 世界最终如何变化？ | `engine/case_engine.py` |
| 多病例与存档怎么协调？ | `application/multicase.py` |
| Memory 如何进入上下文？ | `application/game_npc_memory.py` |
| Reflection 如何防污染？ | `application/reflection.py` 与 `reflection_memory.py` |
| 证据在哪里？ | `tests/`、`docs/benchmarks/m5/`、`docs/evaluation/` |

## Ownership 自测

如果以下任何一题答不出来，就回到对应实操，而不是背答案：

1. 玩家文本为什么不能直接转成 ToolCall？
2. `GameNPCAgent` 合法输出为什么仍可能不执行？
3. Action Contract、GoalPlanPolicy、Authority、CaseEngine 各拦什么？
4. 世界提交成功但 Agent 投影保存失败时，系统如何处理？
5. 为什么 Memory 必须显式 declared/accepted？
6. Reflection 为什么不能直接写长期记忆？
7. Dense 语义检索为什么被停用，产品当前依赖什么？
8. 9/9 real-model Pilot 能证明什么、不能证明什么？
9. 为什么项目不是 Multi-Agent？
10. 如果要公网多人化，前三个工程缺口是什么？

完成标准不是“全部看过”，而是你能现场画、现场改、现场测，并且知道哪里还没被证明。
