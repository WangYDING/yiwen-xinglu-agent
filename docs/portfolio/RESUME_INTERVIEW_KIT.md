# 《异闻行录》简历与面试作战包

## 项目定位

推荐标题：

**异闻行录｜可审计的 Human-Agent Cooperative Game NPC（Python / Pydantic / SQLite / LLM）**

不要用“AI 问诊系统”作为标题。它会把面试引向现实医疗合规，也会掩盖项目真正的 Agent、规则引擎与人机协作价值。

## 简历版本 A：Agent 应用开发

- 设计并实现可审计的人机协作游戏 NPC：Agent 基于公开 Observation、Goal/Plan、玩家贡献与受约束长期 Memory 自主提出 Tool action，支持 6 个志怪案件的调查、诊断协商与高风险处置确认。
- 构建 `PublicActionContract + GoalPlanPolicy + Authority Policy + CaseEngine` 四层执行边界，将 LLM proposal 与权威状态写入分离，覆盖隐藏目标、非法参数、计划漂移、越权处置和模型失败等风险。
- 实现结果驱动的 Planning / Memory / Reflection 闭环：相关 Memory 经 `selected → declared → accepted` 才能影响决策；Reflection 需结果证据验证后方可保守写入未来 Episode，避免历史经验污染。
- 建立确定性消融、Fake 故障注入与真实模型小型 Pilot：5 组 paired fixtures 获得 3 个机制改进、2 个预期不变、0 回归；修复输出截断、Tool 参数和 Plan target 三类故障后，冻结的 9 次真实模型运行均直接通过结构与策略校验。
- 以 Pydantic 领域契约、命令/事件、JSON 权威快照和 SQLite 可恢复记忆投影支持本地持久化、幂等协调与事件回放；当前仓库全量 906 项测试通过。

## 简历版本 B：游戏 AI / 游戏客户端工具方向

- 独立设计 6 案件可玩纵向切片，让玩家通过线索、质疑、诊断协商和处置授权影响自主 NPC，同时保留 NPC 的 Goal、Plan、replan 与 Tool choice。
- 将剧情内容数据化为病例、线索、调查前置、诊断候选、处置结果与跨案规则，由确定性 `CaseEngine` 控制真相、评分和状态变化，LLM 只负责角色化决策提议。
- 构建本地 Clinic Web、CLI、存档恢复和事件回放链路；每回合限制一个 Tool，高风险行为要求玩家确认，模型不可直接修改世界状态。
- 设计可观察的 Agent 评测与故障遥测，验证 Planning、相关/无关 Memory、Reflection 学习与污染控制，并保留 Dense 语义检索未过门禁的负结果。
- 使用 Python、Pydantic、SQLite 和适配器模式实现可替换 Fake/真实模型路径；906 项自动化测试覆盖领域规则、Agent 边界、恢复、MCP、产品验收与真实模型传输契约。

## 数字使用规则

| 可以写 | 准确含义 |
|---|---|
| 6 个案件 | 当前本地 Clinic 的可玩病例数 |
| 906 项测试通过 | 2026-08-21 当前环境全量 pytest 结果 |
| 5 组 paired fixtures | 3 `IMPROVED`、2 `EXPECTED_NOOP`、0 回归 |
| 9 次真实模型 Pilot | 单模型、3 条件 × 3 repeats 的描述性工程证据 |
| 3 类真实故障修复 | 截断、Tool arguments、Plan target |

不要写“准确率 100%”“性能提升 60%”“生产级”“高并发”“证明提升用户体验”。这些都没有相应证据。

## 20 秒介绍

我做了一个可审计的人机协作游戏 NPC。玩家可以提供线索、质疑和高风险授权，NPC 则根据当前观察、Goal/Plan 和历史经验自主提出下一步工具行动。模型不能直接改游戏状态，所有 proposal 都要经过动作契约、计划一致性、权限策略和确定性病例引擎验证。

## 60 秒介绍

这个项目解决的是“自主性”和“可控性”之间的矛盾：NPC 不能只是固定流程，也不能让 LLM 随意改变世界。我把系统分成 Agent 意图层和确定性执行层。`GameNPCAgent` 读取公开 Observation、Goal/Plan、玩家贡献和受约束 Memory，生成结构化 proposal；应用层依次检查公开行动空间、计划目标一致性和权限，高风险处置必须玩家确认，最后只有 `CaseEngine` 能提交状态。项目还有结果驱动 Reflection、事件回放、失败恢复，以及 5 组确定性消融和 9 次真实模型小型 Pilot。当前是本地六案件产品，不声称生产并发或真人效果。

## STAR 主故事：最值得讲的故障排查

**S**：真实模型接入后，最初 9/9 运行都进入安全 fallback，表面看像模型不遵守 Schema。

**T**：在不放宽安全校验的前提下，找到 proposal 失败的第一原因，并恢复直接有效输出。

**A**：我增加分阶段 telemetry，按 `provider → completion → parser → schema → action contract → goal/plan policy` 定位第一失败点；先发现 512 token 导致输出截断，单独提高复杂 planning proposal 的 bounded output budget。随后暴露 Tool 参数与公开行动空间不一致，再统一 authoritative action-space projection；最后让 Plan step 与 Decision 复用同一 tool/target binding。每次只改一个变量并重跑同一路径。

**R**：冻结的 post-fix 9 次运行全部获得完整、可解析、通过 Action Contract 和 GoalPlanPolicy 的直接 proposal，repair、fallback 和 truncation 均为 0；所有 validator 与权限边界保持原强度。结论仅限这次单模型小样本工程验证。

## 高频追问与答题要点

### 1. 为什么这是 Agent，不是 Workflow？

下一步不是固定节点预先决定。NPC 会根据 Observation、Goal/Plan、玩家贡献和相关 Memory，在当前公开 Action Space 中选择 Tool，并可能接受、部分接受、拒绝建议或 replan。确定性系统限制“能做什么”，不替 Agent 决定“此刻想做什么”。

### 2. 为什么不用 LangChain / LangGraph？

核心流程规模可控，但领域、安全和回放契约很严格。直接用 Pydantic + Adapter + 显式应用服务让依赖更小、失败位置更可观察。如果以后出现并行长流程、分布式人工审批或复杂持久图，再评估图编排框架。

### 3. 四层安全边界分别是什么？

- Action Contract：Tool、target、arguments 是否来自当前公开行动空间。
- GoalPlanPolicy：Goal/Plan 是否引用合法、当前可见且一致的动作目标。
- Authority：调查能否自主，诊断是否需协商，处置是否需确认。
- CaseEngine：前置、证据、规则、评分和最终世界状态是否成立。

### 4. Prompt Injection 怎么防？

不是只靠 system prompt。隐藏答案不进入公开 View；玩家文本不能直接构造 ToolCall；模型输出必须过结构、行动、计划和权限校验；引擎仍独立检查世界规则。真实 Pilot 中模型拒绝了越权建议，但系统安全不依赖模型每次都拒绝。

### 5. Memory 为什么不是普通 RAG？

它有玩家/病例/来源范围与使用归因。检索到只代表候选；Agent 必须声明使用，系统再验证是否与实际 Goal/Plan/Decision 对齐，才记为 accepted。Memory 是历史经验，不能覆盖当前 Observation 或扩大权限。

### 6. Reflection 如何避免自我污染？

只有真实 Episode 结果触发候选；validator 检查证据、因果边界和过度推断；通过后形成候选 Memory，再做保守 consolidation。弱证据会被拒绝，不能直接写长期库。

### 7. 为什么 JSON + SQLite？

JSON 保存本地产品的权威状态和可检查快照；SQLite 保存可索引、可重建的结构化记忆投影。两者不是双主。世界事实先提交，投影失败可凭稳定来源 ID 幂等恢复。

### 8. 最大失败是什么？

Dense-only 语义检索在冻结 Gold/holdout 中没有稳定过质量门禁，所以没有上线到正式 Prompt。项目保留负结果，当前正式链依赖来源明确的结构化历史。这证明我会设置停止条件，而不是为了技术标签强行上线。

### 9. 906 个测试主要测什么？

覆盖领域模型和规则、拒绝零写入、事件回放、Agent action/plan/authority 边界、Memory/Reflection 生命周期、故障恢复、MCP 契约、Clinic 产品验收和真实模型 Adapter/runner。数量不是质量本身，关键是每个简历结论能指向测试或冻结证据。

### 10. 下一步怎么做成生产系统？

优先补：真人玩法研究与指标；并发控制、事务、备份恢复；认证、租户隔离和 Web 安全；远程 CI 与跨平台验证；模型 latency/token/cost 可观测；多模型和更广场景评测。当前 loopback 单机架构不能直接宣称生产可用。

## AI 辅助开发怎么诚实回答

推荐表述：

> 这个项目大量使用了 Codex 辅助实现。我负责产品目标、约束定义、架构取舍、验收标准和最终交付，并通过测试、故障注入和真实模型小型 Pilot 验证系统。为了避免“代码生成了但我不会”，我正在按主链逐层接管，能现场解释并修改核心规则。对还没亲手改过的模块，我不会声称完全掌握。

面试官真正关心的不是你是否用 AI，而是你能否：发现错误、定义边界、验证结果、解释取舍、现场修改。不要说“全部独立手写”，也不要把自己说成只会写 Prompt。

## 面试前检查表

- 不看稿讲 20 秒、60 秒、3 分钟三个版本。
- 白板画主链，并说出四层确定性边界。
- 准备一次真实故障、一次失败实验、一次跨层修改。
- 能打开代码指出每个论点的位置。
- 能现场新增一个规则测试并解释拒绝后零写入。
- 主动说出：单机、单模型小样本、无真人效果、无生产并发四项限制。
- 根据目标岗位删减到 3–4 条简历 bullet，不把整份技术清单塞进简历。
