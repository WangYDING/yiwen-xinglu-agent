# 《异闻行录》项目掌握与面试手册

> 用途：帮助项目作者从“项目能运行”进阶到“能解释、能定位、能修改、能接受追问”。
>
> 基准：2026-08-21 当前工作区；本手册以实际代码、测试与现有审计文档为依据，不把规划或一次实验包装成已验证成果。

## 1. 先记住这一句话

《异闻行录》是一个本地运行、可审计的 Human-Agent Cooperative Game NPC 项目：玩家与一名游侠型自主 NPC 结伴调查六个古风志怪异案；NPC 自主维护 Goal/Plan、评估玩家贡献并在权限内推进调查，玩家参与线索、质疑、诊断协商和高风险授权，确定性规则最终裁定行动合法性与世界状态。

如果面试官只给 20 秒，用上面这一段，不要从“我调用了 DeepSeek API”开始讲。

## 2. 三种时长的项目介绍

### 20 秒版本

我做了一个可审计的人机协作游戏 NPC 系统。玩家与自主 NPC 共同调查六个志怪异案：NPC 会根据公开 Observation、Goal/Plan 和历史 Memory 自主提出下一步行动，玩家通过线索、质疑和高风险授权参与决策。LLM proposal 必须经过行动契约、权限策略和 `CaseEngine` 的确定性验证，才能真正改变世界状态。

### 60 秒版本

这个项目要解决的问题是：如何让 NPC 保有自主判断、规划、工具使用和历史经验，同时让玩家能够真正影响调查，又不让模型直接控制游戏世界。我把系统拆成领域层、应用层、Agent 层、存储层和交互层。`GameNPCAgent` 根据公开 Observation、Goal/Plan、玩家贡献和受约束 Memory 形成 proposal；应用层随后检查行动契约、计划一致性和权限，合法 Tool 才交给 `CaseEngine` 更新案件状态。项目提供六病例本地 Clinic、JSON/SQLite 持久化、Fake/真实模型适配器及 M1–M5 冻结 benchmark。MentorAgent 教学表达与 DoctorAgent baseline 作为保留分支存在，但不代表当前主 Agent 身份。

### 3 分钟版本的顺序

1. 背景：让 NPC 不只会聊天，还能自主规划、调查并与玩家协作判断。
2. 难点：模型行为不稳定，而行动合法性、案件真相和世界状态必须稳定。
3. 方案：Agent 形成意图，玩家参与判断与高风险授权，确定性系统裁决执行。
4. 产品：六个志怪异案、本地 Clinic，以及可观察的 Goal/Plan、replan 和历史经验影响。
5. 工程：Pydantic 契约、JSON/SQLite 存储、Adapter、恢复与回放、离线测试。
6. 失败与取舍：Dense 语义检索未过质量门禁，正式链路改用结构化可信历史。
7. 边界：真实模型只有有限工程案例；没有真人效果、生产并发和远程发布证据。

## 3. 系统地图

```text
浏览器 / CLI / MCP
        │
        ▼
交互入口 clinic/server.py、cli/play.py、mcp_server/
        │  只做输入解析、输出展示和错误映射
        ▼
应用服务 application/
        │  编排 cooperation、Goal/Plan、Memory、Reflection 与病例执行
        ├──────────────► GameNPCAgent / LLMAdapter
        │                 公开上下文 → 受限 proposal
        ├──────────────► retained MentorAgent
        │                 教学分支的受限建议/表达
        ▼
领域模型 domain/ ───► CaseEngine
        │              校验命令 → 新会话 + 领域事件
        ▼
JSON 权威存档 + SQLite 结构化记忆投影
        │
        ▼
evaluation/ + tests/：回放、故障注入、离线验收与质量门禁
```

当前入口边界：`xuanyi-clinic` 是唯一正式玩家产品入口；`xuanyi-play` 是 CLI/工程入口，`xuanyi-mcp-stdio` 是本地集成入口。依赖仓库实验数据的历史评测模块仍予保留，但不再安装为 wheel 命令。

### 目录责任

| 目录 | 你应该如何解释 |
|---|---|
| `src/xuanyi_npc/domain/` | Pydantic 领域对象和状态契约，不负责 HTTP 或模型调用。 |
| `src/xuanyi_npc/engine/` | 纯确定性病例执行；输入不原地修改，返回新状态、事件与结果。 |
| `src/xuanyi_npc/application/` | 用例编排，协调规则、Agent、持久化、成长、教学、考试和传承。 |
| `src/xuanyi_npc/agents/` | LLM/Fake 适配器、输入输出契约、有界修复和降级。 |
| `src/xuanyi_npc/storage/` | JSON 状态存档与 SQLite 记忆仓库。 |
| `src/xuanyi_npc/memory/` | 领域事件到结构化记忆的投影、生命周期、Embedding 接口及实验实现。 |
| `src/xuanyi_npc/clinic/` | 仅绑定 `127.0.0.1` 的本地网页入口。 |
| `src/xuanyi_npc/resources/` | 六病例、课程、考试、权限等正式运行资源的唯一真源。 |
| `src/xuanyi_npc/evaluation/` | 不同于单元测试的场景评测、成本门禁和验收 Runner。 |
| `tests/fixtures/event_replay/` | 事件重放测试 Fixture；不属于正式产品资源。 |
| `tools/experiments/data/evaluation/` | 离线评测、Gold、Holdout 和开发实验输入。 |
| `tools/experiments/data/pilot_snapshots/` | 历史价格与 Pilot 策略快照。 |
| `docs/archive/evidence/model_runs/` | 脱敏真实模型运行证据；不由产品运行时读取。 |
| `tests/` | 当前 123 个 Python 测试文件；2026-08-21 全量 pytest 为 906 项通过。 |

## 4. 必须讲透的核心链路

### 4.1 Cooperative GameNPC 推进一个回合

1. 玩家通过 `PlayerContribution` 提交线索、质疑、建议、判断或授权。
2. `CooperativeRuntime` 组合当前 public Observation、Goal/Plan 和范围受限的 Memory。
3. `GameNPCAgent` 评估玩家贡献并提出候选下一步行动；玩家文本不会直接成为 ToolCall。
4. `PublicActionContract`、`GoalPlanPolicy` 和 Authority Policy 校验行动、参数、计划一致性与授权边界。
5. 合法后，本轮落实一个主要 Tool，并由 `CaseEngine` 决定真实结果和更新世界状态。
6. 新结果进入 Plan Evaluation / Replanning；阶段结束后，Reflection 只能基于结果证据形成候选经验。

关键回答：Agent 决定准备推进什么，玩家参与判断和高风险授权，确定性系统决定什么真正能够发生。

### 4.2 Retained MentorAgent 生成教学反馈

1. 应用层先计算允许公开的课程、关系、历史和结果事实。
2. `MentorAgentInput` 校验输入是否满足当前交互阶段。
3. `MentorAgent` 通过 `LLMAdapter` 请求结构化 `MentorAction`。
4. 输出必须符合动作白名单和阶段约束；格式失败时只进行一次有界修复。
5. 再次失败则使用确定性 fallback；导师回复不是权威状态事实。

关键回答：这是保留的 teaching/presentation branch。MentorAgent 的受限表达边界是真实能力，但不能用来定义当前 Cooperative GameNPC 的全部行动能力。

### 4.3 状态与记忆如何恢复

- JSON 保存病例和产品权威状态；SQLite 保存从已提交事件投影出的结构化记忆。
- 协调策略是先提交 JSON，再投影记忆。如果投影失败，病例事实仍然成立，并返回 `MEMORY_PROJECTION_PENDING`。
- `reconcile_committed_session()` 可以只读取已提交 JSON，幂等重建缺失投影。
- 语义向量是派生数据，不是真相来源；Dense 检索未过门禁后默认关闭。

关键回答：这是有意选择的最终一致性，不是跨 JSON 与 SQLite 的伪分布式事务。

## 5. 五个重要技术决策

### 决策一：LLM 不拥有状态写权限

- 原因：模型输出存在幻觉、格式错误和供应商波动。
- 做法：模型只能读取过滤视图并输出严格动作；规则层再次验证。
- 代价：表达自由度更低，需要维护 Schema、转换器和 fallback。
- 替代方案：让模型直接调任意工具更快，但难以保证评分、权限和存档一致性。

### 决策二：命令与事件分离

- proposal 或命令代表 Agent/玩家“希望推进什么”；事件代表规则确认后“实际发生了什么”。
- 成长和记忆只能消费已提交事件，不能消费模型意图或未验证输入。
- 收益是可回放、可追责和更容易写故障恢复测试；代价是模型数量和编排代码增加。

### 决策三：规则确定，语言可生成

- 规则决定答案、分数、课程资格、考试结果和传承。
- 主链 LLM 负责受限行动 proposal；retained Mentor 分支负责角色化教学表达和允许范围内的建议。
- 这使无 API Key 模式仍可完整玩，也便于比较 Fake 与真实模型。

### 决策四：结构化历史优先于向量记忆

- 结构化历史具有玩家、会话、事件、版本和生命周期来源。
- Dense-only 语义检索在冻结 Gold/holdout 中暴露质量限制，因此没有进入正式 Prompt。
- 面试价值：这里应主动讲失败实验和停止条件，而不是宣称“用了向量数据库”。

### 决策五：先做本地单机闭环

- HTTP 服务器只监听 `127.0.0.1`，用 JSON/SQLite 降低部署复杂度。
- 适合证明产品闭环和规则架构；不等于支持互联网暴露、多人并发或生产运维。

## 6. 最适合主讲的三个难点

### 难点 A：让 Agent 可控但仍有角色表现力

建议用“安全上下文 → 严格动作 Schema → 一次修复 → 确定性降级”四段回答。继续追问时指出：隐藏答案、秘密阈值和未授权内容在进入 Prompt 前就被过滤，不能只靠 system prompt 防泄漏。

### 难点 B：跨存储失败恢复

建议讲 `V1MemoryCoordinator`：JSON 是已提交事实，SQLite 是可重建投影；投影失败不回滚已经发生的病例，通过稳定来源 ID 和幂等写入恢复。继续追问时承认它没有解决生产多进程并发事务。

### 难点 C：如何验证一个非确定性模型功能

建议区分三层：规则单元测试、Fake Adapter 故障注入、真实模型有限 Pilot。成本通过请求前预算预留和请求后 usage 结算控制；真实模型的一次成功案例不能被表述为成功率。语义检索没有通过门禁就保持关闭。

## 7. 面试追问与回答骨架

### 为什么不用 LangChain/LangGraph？

核心需求是严格领域边界、可回放规则和很小的 Agent 状态机，直接使用 Pydantic 契约和 Adapter 更容易控制依赖与审计路径。如果未来出现复杂长流程、并行节点或人工审批，再评估图编排框架，而不是为了技术标签提前引入。

### 为什么既有 JSON 又有 SQLite？

JSON 适合本地单机产品的可检查快照；SQLite 用于结构化长期记忆、索引、生命周期和派生向量。两者不是双主：JSON/领域事件保存产品事实，记忆库是可恢复投影。

### 怎么防止模型看到病例答案？

在应用层构造公开 View，只给已发现线索、允许动作和公开教学事实。模型没有读取原始 `CaseDefinition` 的接口；输出还要经过 Schema 和规则层验证。Prompt 约束只是最后一层，不是主要安全边界。

### 模型挂了游戏还能玩吗？

能。病例规则和存档是确定性的；Fake cooperative NPC 可以走同一受限 proposal 与验证链路。retained Mentor 分支也有确定性 fallback，真实模型只提供受控增强。

### 如何处理重复请求？

产品动作携带 `operation_id`/request ID，应用层及事件投影使用幂等标识防止重复提交。网页层还缓存当前进程中的操作重定向结果；后者不是跨进程的完整生产幂等方案。

### 项目最大的失败是什么？

Dense 语义记忆在离线质量门禁中没有稳定达到要求，所以没有把它包装成正式能力，而是保留实验记录，并让 retained Mentor 分支继续读取结构化可信历史。这个失败促使系统明确区分“权威事实”和“可替换检索策略”。

### 目前最需要改进什么？

优先级是：真人可用性测试、远程 CI、格式与静态检查、存储并发/备份验证、Web 安全与生产部署设计。只有获得相应证据后，才可以声称用户收益或生产可用。

## 8. 简历写法

### 推荐标题

**异闻行录——可审计的 Human-Agent Cooperative Game NPC 系统（Python / Pydantic / SQLite / LLM）**

### 推荐描述

- 设计并实现 Human-Agent Cooperative Game NPC 系统：自主 NPC 维护 Goal/Plan、评估玩家贡献、调用受限 Tool，并与玩家共同调查 6 个古风志怪异案。
- 以 PublicActionContract、GoalPlanPolicy、Authority Policy 和 `CaseEngine` 分离 Agent 意图、玩家判断/授权与确定性世界裁决，隔离模型幻觉对关键游戏状态的影响。
- 基于命令—领域事件—投影设计病例与长期记忆链路，以 JSON 保存权威状态、SQLite 保存可重建结构化记忆，支持幂等投影、失败协调、恢复与回放。
- 建立规则测试、Fake 故障注入、场景评测和有限真实模型 Pilot；当前仓库包含 123 个 Python 测试文件，2026-08-21 全量 pytest 为 906 项通过。
- 对未通过质量门禁的 Dense 语义检索保持默认关闭，并在文档中区分离线验收、真实模型工程案例与尚未执行的真人效果验证。

数字只使用当前可复验事实。不要写“准确率 100%”“支持高并发”“提升教学效果”或“已生产部署”。

## 9. 诚实边界

### 可以说

- 六个病例、本地医馆、完整成长—考试—传承链可以离线运行。
- 关键状态由确定性规则管理，LLM 无直接写权限。
- 有 Fake、离线验收、真实模型有限工程案例和失败记录。
- 当前全量 pytest 通过。
- 真人试玩、远程发布和生产部署尚未执行；本地工程证据不能外推为真人收益或生产能力。

### 不能说

- “AI 导师已经证明能提升玩家学习效果”：没有真人对照或用户研究。
- “模型调用成功率很高”：有限 Pilot 不能推出统计成功率。
- “语义记忆准确率 100%”：冻结合成集指标不是产品准确率，且 Dense 路线已停用。
- “支持生产级并发和云部署”：当前是 loopback 单机产品。
- “所有代码都是我手写的”：如果大量由 AI 生成，应说自己负责需求约束、架构取舍、验证、修正和最终交付，并能现场解释与修改关键模块。

## 10. 从 vibecoding 变成真正掌握：七次实操

每次都应先预测行为，再运行测试，最后用自己的话记录原因。

1. **跑通产品**：创建玩家档案，完成一次与 NPC 的合作调查、诊断协商和处置确认；找到对应 JSON 状态变化。当前 Clinic 部分 presentation 仍可能显示历史“弟子”称谓。
2. **跟踪动作链**：给 `ClinicService.submit_case_action()`、命令转换和 `CaseEngine.execute()` 设置断点，画出一张时序图。
3. **手写规则测试**：新增一个“引用未发现证据必须被拒绝且不产生事件”的测试，不复制现有测试。
4. **制造 Agent 故障**：让 Fake Adapter 返回非法动作，观察一次修复和 fallback，解释为何状态不受影响。
5. **制造投影故障**：让 SQLite 写入失败，验证 JSON 已提交、pending 状态和 reconcile 恢复。
6. **修改一个病例规则**：增加调查前置或调整处置条件，同时更新资源、测试和公开展示。
7. **口头答辩**：不看文档完成 3 分钟介绍，再回答“为什么不用纯 LLM”“为什么双存储”“最大失败是什么”。

完成第 3、5、6 项后，你才算真正拥有了项目中最有价值的三条能力：规则测试、恢复设计和跨层修改。

## 11. 阅读顺序

### 第一轮：建立全局认知（约 2 小时）

1. `README.md`
2. `docs/architecture/PROJECT_MASTER_BLUEPRINT.md`
3. `docs/architecture/PRODUCT_SYSTEM_ARCHITECTURE.md`
4. 本手册第 1～6 节

### 第二轮：理解主链路（约 4 小时）

1. `clinic/server.py`
2. `application/clinic.py`
3. `application/multicase.py`
4. `engine/case_engine.py`
5. `domain/commands.py`、`domain/events.py`、`domain/cases.py`

### 第三轮：理解 Agent 与记忆（约 4 小时）

1. `agents/game_npc.py`
2. `application/cooperative_runtime.py`、`application/goal_plan_policy.py`
3. `application/game_npc_memory.py`、`application/memory_coordination.py`
4. `memory/projection.py`、`storage/sqlite_memory.py`
5. retained branch：`agents/mentor.py`、`application/clinic_mentor.py`
6. 对应测试文件

### 第四轮：建立证据意识（约 2 小时）

1. `docs/evaluation/R6_RELEASE_READINESS_AUDIT.md`
2. `docs/evaluation/VERIFICATION.md`
3. `docs/architecture/DECISIONS.md`
4. `docs/archive/` 中语义检索失败与真实模型 Pilot 报告

## 12. 自测标准

当你能独立完成以下任务时，可以把项目稳妥地写进简历：

- 白板画出 PlayerContribution → GameNPCAgent proposal → deterministic validation → Tool → CaseEngine → Replanning/Reflection 主链，并区分 retained Mentor feedback 分支。
- 指出五类权威状态分别由哪个模块持有。
- 解释 LLM 输出错误、存储写入失败、重复请求时系统如何处理。
- 在 30 分钟内修改一个规则并补充测试。
- 主动说出三项未完成或未验证内容。
- 对任何简历数字指出复现命令或证据文件。

## 13. 当前验证快照

- Python 源文件：145 个；Python 测试文件：123 个；源码与测试合计约 57,033 行。
- 2026-08-21 使用仓库 `.venv` 运行 `python -m pytest`：906 项通过，耗时 130.52 秒。
- 上述行数用于理解工程规模，不等于个人贡献或代码质量指标。
