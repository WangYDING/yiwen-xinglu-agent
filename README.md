# 玄医问道：Human-Agent Cooperative Game NPC System

## Project in One Sentence

`xuanyi-npc` 是一个可运行、可审计的智能游戏 NPC 项目。玩家与一名游侠型自主 NPC 结伴调查古风志怪异案：玩家可以提出线索、质疑、判断和审批，但不能遥控 NPC；NPC 会结合眼前情况、自己的目标和计划、过去经验，自主选择下一步行动。LLM 不能直接修改游戏世界，真正的状态变化必须通过确定性代码规则。

技术上，这条主链由 `GameNPCAgent`、Goal/Plan、Memory、Tool Use、Authority Policy 和 `CaseEngine` 共同完成。主要可玩场景是本地六病例 Clinic；`MentorAgent` 是保留的教学与表达分支，`DoctorAgent` 是 V0 baseline。**This is not a Multi-Agent system.**

## Key Features

- **Human-Agent Cooperation**：玩家影响决策，但不能替 Agent 构造或执行工具调用。
- **Tool Use + Bounded Authority**：Agent 只能在公开行动空间中提议动作，高风险处置需要玩家确认。
- **Goal / Planning / Replanning**：Goal 和 Plan 是显式状态；新证据、拒绝或执行结果可以触发可观察的计划调整。
- **Long-term Memory**：只检索经过范围与来源约束的历史；Agent 必须显式声明并接受记忆后，记忆才能影响本次决策。
- **Outcome-grounded Reflection**：反思必须由结果证据支撑；弱证据被拒绝，不能污染未来经验。
- **Deterministic Safety + Benchmark**：LLM 负责 proposal，确定性策略、行动契约与 `CaseEngine` 负责验证和状态变更。

## 为什么它是 Agent，而不是固定 Workflow？

固定 Workflow 的下一步通常由预先写好的流程决定；这里的 NPC 则要根据当前 Observation 自己判断下一步，同时接受玩家影响但保留独立决定权：

- 它可以接受、部分接受、拒绝玩家建议，或者要求更多证据、提出替代方案；
- 它有显式 Goal 和 Plan，新证据出现后可以 Replan；
- 它可以在当前 Action Space 中选择不同 Tool，而不是沿固定脚本前进；
- 相关 Memory 可以改变未来 Plan 顺序或 Tool priority，但所有执行仍受 deterministic constraints 约束。

## 一回合里到底发生了什么？

1. 玩家提出判断、建议或审批。
2. NPC 获取当前允许看到的病例和环境信息。
3. NPC 查看当前目标、计划，以及有没有相关的过去经验。
4. NPC 自己判断是否接受玩家建议，并决定下一步想做什么。
5. 系统检查动作是否合法、参数是否正确、是否需要玩家确认。
6. 合法后才执行一个 Tool，并由 `CaseEngine` 更新状态。
7. 得到新结果后，NPC 判断继续原 Plan 还是 Replan。
8. 一个阶段结束后，系统可以根据真实结果形成新的经验。

对应的技术流程是：

```text
PlayerContribution
→ public Observation
→ Goal / Plan
→ scoped Memory Retrieval
→ GameNPCAgent proposal
→ cooperative Decision
→ deterministic validation
→ bounded Tool
→ CaseEngine
→ Plan Evaluation / Replanning
→ evidence-grounded Reflection
→ conservative Experience Consolidation
```

Plan 不等于执行权限。LLM proposes；deterministic system validates。模型输出必须先通过公开 Action Space、Goal/Plan 一致性和 Authority 检查，才能到达工具与规则引擎。

## Human-Agent Cooperation

玩家通过 `PlayerContribution` 提出建议、假设、风险意见或审批；玩家文本不会直接变成 `ToolCall`。Agent 独立评估贡献并返回：

- `ACCEPT`
- `PARTIAL_ACCEPT`
- `REJECT`
- `REQUEST_MORE_EVIDENCE`
- `PROPOSE_ALTERNATIVE`

调查动作可在权限边界内自主执行；诊断通过协商形成；处置属于高风险动作，必须经过明确确认。玩家可以影响 Agent，但不能绕过 Agent 判断、工具契约或病例规则。每个 cooperative turn 最多执行一个 Tool，避免一次模型输出连续改变多处状态。

## Planning, Memory and Reflection

### Planning

Planning 让 NPC 不只是“每回合临时猜一步”，而是能先问患者、再检查物品、最后观察状态。如果中途出现新证据，原来的顺序不再合适，它可以调整计划。

技术上，`Goal` 表示当前想完成什么，`Plan` 保存有序步骤；`GoalPlanPolicy` 检查目标、步骤和公开 target 是否与当前合法行动一致，`PlanEvaluator` 根据执行结果和新 Observation 决定继续、修订、完成或结束。Replanning 是可观察的状态转换，不是藏在自然语言里的推断。

### Memory

Memory 是过去经历形成的历史经验，不是当前世界真相。系统“检索到了”某段历史，不代表 Agent 真正使用了它；只有完成 `selected → declared → accepted`，才认为该记忆影响了本次行为。也就是说，retrieved/selected ≠ used。

技术上，长期记忆会先按玩家、病例、类型和来源过滤，再进入候选选择和显式使用声明。Memory 带有来源记录，但不能覆盖当前 Observation、注入新指令或扩大 Agent 权限。

### Reflection

项目不会让 LLM 随便总结一句话就写进长期 Memory。正确流程是：真实结果 → 候选经验 → 检查有没有证据 → 检查是否过度推断 → 合格后才进入长期记忆。这样可以避免一次错误总结持续污染未来决策。

技术上，Episode 结果先形成可验证 evidence，再生成 Reflection proposal；validator 拒绝弱证据和越界推断，通过后形成 `MemoryCandidate`，并经过保守 consolidation 才能进入未来检索。Reflection 不能直接写长期 Memory。

## 为什么不能让 LLM 想做什么就做什么？

> LLM 只有“提出下一步行动”的权力，没有直接修改游戏世界状态的权力。

| 通俗理解 | 技术实现 | 作用 |
|---|---|---|
| 现在有哪些动作能做 | Public Action Space | 只暴露当前合法、公开的动作和目标 |
| 参数对不对 | `PublicActionContract` | 拒绝非法 tool、target 和 arguments |
| Goal/Plan 是否一致 | `GoalPlanPolicy` | 防止计划与当前状态或行动脱节 |
| NPC 有没有权限 | Authority Policy | 控制调查、诊断协商和处置确认边界 |
| 世界最终怎么变化 | `CaseEngine` | 掌握病例规则、事件和状态变化 |
| 历史能不能凌驾于现实 | Memory boundary | 当前 Observation 始终优先，记忆不能扩大权限 |
| 总结能不能成为经验 | Reflection validator | 只有有证据的候选才能进入 consolidation |

即使模型输出无效或被 Prompt Injection 诱导，fallback、Authority 和 `CaseEngine` 仍保持独立的确定性安全边界。

## Evaluation

Benchmark 不是为了证明“这个 Agent 比别的系统强多少”，而是验证 Planning、Memory、Reflection 是否真的改变了可观察行为，以及安全边界面对真实 LLM 输出时是否仍然有效。

### Deterministic Ablation

M5 在冻结的同条件 fixtures 上完成 5 个 paired experiments：

| Outcome | Count |
|---|---:|
| `IMPROVED` | 3 |
| `EXPECTED_NOOP` | 2 |
| `REGRESSED` | 0 |
| `NOT_COMPARABLE` | 0 |

三个 `IMPROVED` 分别覆盖 observable replanning、相关记忆引起的合法行为差异，以及 validated Reflection 对未来 Episode 的影响；两个 `EXPECTED_NOOP` 验证无关记忆和弱 Reflection 不应改变行为。这些结果证明受控机制差异，不应换算成“60% 提升”。

### Real LLM Validation

`deepseek-v4-flash` 的 post-fix small real-model pilot 共 9 runs：Prompt Injection、Relevant Memory baseline、Relevant Memory treatment 各 3 repeats。

| Metric | Result |
|---|---:|
| Complete initial response | 9/9 |
| Parser reached / schema valid | 9/9 |
| `PublicActionContract` pass | 9/9 |
| `GoalPlanPolicy` pass | 9/9 |
| Direct proposal success | 9/9 |
| Repair attempted | 0/9 |
| Fallback used | 0/9 |
| Output truncation | 0/9 |

Prompt Injection 条件中，模型 proposal 以 `REJECT` 拒绝越权建议 3/3，确定性系统保持无危险执行 3/3。Relevant Memory treatment 中，记忆 `selected` 3/3、`declared` 3/3、`accepted` 3/3，并伴随合法的 Plan 顺序与 tool-priority 变化 3/3。

这是单一真实模型、每条件 3 repeats、有限场景下的描述性工程证据，不具有统计显著性，也不代表生产分布成功率或玩家收益。完整方法、artifacts 与限制见 [M5 Agent Benchmark and Failure Analysis](docs/benchmarks/m5/agent_benchmark_report.md)。

### Failure Analysis

这是一次保留下来的真实排障案例。最初，9/9 real-model runs 都进入 safe fallback；stage telemetry 随后依次定位到：

1. 输出被 512 token 截断，parser 没有拿到完整 proposal；
2. Tool 参数格式不符合 contract；
3. Plan 使用了当前不合法的 target。

每次只修一个变量，再从同一路径重新运行：

```text
observe
→ locate first failure
→ single-variable fix
→ re-run the same path
```

最终，post-fix Pilot 获得 9/9 direct valid proposals，repair、fallback、truncation 均为 0/9。这个结果不是通过放宽 validator、schema、`PublicActionContract`、`GoalPlanPolicy` 或 Authority 来“刷通过率”。

## Playable Product

本地 Clinic 将 cooperative Game NPC 主链放入六个志怪病例：玩家与自主 NPC 组成调查搭档，共同调查异事、协商诊断、确认高风险处置，并看到 Goal、Plan、replan 和公开历史的变化。规则层保存事件和结果，页面仅通过 loopback `127.0.0.1` 提供本地体验。

保留的产品与工程入口包括：

- 六病例 Clinic Web：主要可玩入口，承载玩家与自主 NPC 的合作调查；
- Mentor teaching/presentation：保留的课程、提示、师评、考试和传承表达分支；
- manual/Fake/DeepSeek V0 CLI：手动体验、回归与受控实验；
- MCP stdio：本地工具集成入口；
- deterministic acceptance 和 real-model pilot：评测入口，不是玩家入口。

## Quick Start

当前可复现环境为 Windows 和 Python 3.12。核心本地体验不需要 API Key、GPU、Torch 或 BGE。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
New-Item -ItemType Directory -Force .\runtime_data\clinic | Out-Null
.\.venv\Scripts\xuanyi-clinic.exe --state-dir .\runtime_data\clinic
```

终端会输出 `http://127.0.0.1:<port>/`。详细安装、存档与恢复说明见 [START_HERE.md](START_HERE.md) 和[医馆用户指南](docs/product/R5_CLINIC_USER_GUIDE.md)。

Secondary commands：

| Command | Role |
|---|---|
| `xuanyi-play` | manual、Fake、DeepSeek V0 与工程调试 CLI |
| `xuanyi-mcp-stdio` | 本地 MCP stdio 集成 |
| `xuanyi-m5-acceptance` | M5 确定性验收 |
| `xuanyi-product-acceptance` | 产品离线验收 |
| `xuanyi-case-demo` | DoctorAgent V0 历史演示 |
| `xuanyi-real-mentor-pilot` | 显式授权的受控真实模型 Mentor Pilot |

## Repository Map

| Path | Role |
|---|---|
| `src/xuanyi_npc/agents/` | `GameNPCAgent`、Mentor/Doctor baselines、LLM adapters |
| `src/xuanyi_npc/application/` | cooperative runtime、planning/memory/reflection coordination、Clinic composition |
| `src/xuanyi_npc/domain/` | cooperation、Goal/Plan、actions、events、memory/reflection contracts |
| `src/xuanyi_npc/engine/` | 确定性病例规则、结果与 replay |
| `src/xuanyi_npc/memory/` | long-term memory storage、projection、retrieval 与 embedding boundaries |
| `src/xuanyi_npc/evaluation/` | deterministic ablations、real-model validation、failure diagnostics |
| `docs/` | 架构、benchmark、产品说明与历史证据 |

## 项目术语速查

| 术语 | 在本项目里的意思 |
|---|---|
| Observation | NPC 当前被允许看到的真实世界状态 |
| Goal | NPC 当前想完成的目标 |
| Plan | 为实现 Goal 准备的有序步骤 |
| Replanning | 新证据或执行结果出现后调整 Plan |
| Proposal | LLM 提出的候选决策，尚未执行 |
| Decision | 经过贡献评估、但仍需系统验证的结构化决定 |
| Tool | NPC 可以调用的一项实际能力；每回合最多执行一个 |
| Action Space | 当前允许选择的公开动作集合 |
| Authority | NPC 当前是否有权限执行某类动作 |
| Memory | 过去经历形成的、非权威的历史经验 |
| Reflection | 根据已发生结果总结候选经验 |
| `CaseEngine` | 真正掌握病例规则和世界状态的确定性代码 |
| Fallback | LLM 输出失败或不合格时采用的安全兜底路径 |

## Evolution and Retained Baselines

| Role | Status |
|---|---|
| `GameNPCAgent` | Current cooperative main Agent |
| `MentorAgent` | Retained teaching / presentation branch |
| `DoctorAgent` | V0 baseline / legacy benchmark Agent |

三个名称代表不同职责和历史阶段，不代表多个 Agent 在同一回合协作。R-series 是历史 product/teaching evolution；M-series 是最终 Cooperative Agent engineering milestones。R1–R6、M4.5、DoctorAgent、旧 Pilot 与语义检索负结果的详细记录保存在[文档导航](docs/INDEX.md)和[历史归档](docs/archive/README.md)，不在首页展开阶段流水。

当前封版 tags：`m1-cooperative-agent`、`m2-goal-planning-agent`、`m3-memory-driven-agent`、`m4-reflection-learning-agent`、`m5-agent-benchmark`。

## Limitations

- Real LLM evidence 只覆盖 `deepseek-v4-flash` 一个模型、每条件 3 repeats 和有限场景。
- 结果是 descriptive engineering evidence，没有统计显著性或跨模型泛化结论。
- token、latency 与货币成本目前未完整可观测。
- deterministic fixtures 证明受控机制行为，不等于生产分布性能。
- 没有生产并发、长期运行、备份恢复或公网安全 benchmark。
- 没有真实玩家收益、教学效果、留存或用户研究证据。
- 存在本地 loopback Clinic Web 界面；没有公网部署或独立游戏引擎 UI。
- 内容全部为古风志怪架空世界，不提供现实医疗诊断、处方或剂量建议。

## License and Content Rights

程序代码、测试和工程脚本采用 [Apache License 2.0](LICENSE)。病例、世界观、Campaign、文档和演示文案为 `© 2026 WangYDING. All rights reserved.`，不随代码许可证授权；详见 [NOTICE](NOTICE) 与 [CONTENT_RIGHTS](CONTENT_RIGHTS.md)。第三方归属见 [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES.md)。
