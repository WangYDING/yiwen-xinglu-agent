# 异闻行录

《异闻行录》是一个可在本地运行的古风志怪调查游戏，也是一套可审计的 Human-Agent Cooperative Game NPC 系统。玩家与由单一 `GameNPCAgent` 驱动的调查搭档共同观察、推理、质疑并处置六个异案；仓库同时包含用于检查 Agent 可靠性、安全边界和架构差异的评测体系。

本项目不是通用 Agent 平台，也不是多 Agent 系统。正式运行时每个合作回合只有一个主 Agent 参与决策；普通案件角色不是 Agent。产品不包含现实医疗能力、修习、课程、考试、师徒成长或传承系统。

## 启动

```powershell
python -m pip install -e ".[dev]"
yiwen-xinglu
```

服务只绑定 `127.0.0.1`。正式 LLM 模式需要 API Key、显式付费授权和预算上限；协作回合记录与 CE-2A 上下文默认启用，可分别用 `--no-cooperative-record` 和 `--no-cooperative-context-v2` 显式关闭。详见[首次启动说明](START_HERE.md)。`xuanyi-clinic` 是同一入口的兼容命令，`xuanyi-mcp-stdio` 提供独立的本地 MCP stdio 接口。

## 玩家实际体验

- 六个可独立完成的古风志怪案件，以及跨案件 Campaign 连续性；
- 玩家通过自然语言提交建议、假设、质疑、证据解释和问题；
- NPC 独立评价玩家贡献，并与玩家协商诊断和下一步行动；
- 诊断与不可逆处置受确认约束，拒绝会使旧确认失效；
- 玩家隔离的长期记忆、受证据约束的 Reflection，以及 JSON/SQLite 持久化；
- 已持久化的玩家、案件、Agent 和 Campaign 状态可在本地恢复。

## Agent 核心运行链

```text
PlayerContribution
  → CooperativeRuntime
  → Observation / Authority / Goal / Plan / Memory
  → GameNPCAgent proposal
  → GoalPlanPolicy
  → PublicActionContractValidator
  → NPCAuthorityPolicy
  → CaseToolExecutor
  → CaseEngine
  → world commit / memory projection
  → refreshed Observation / plan evaluation / Agent state
  → reflection
```

玩家文本不会直接转换为工具调用，隐藏真相也不会进入 Agent 的公开视图。模型输出必须先经过结构、规划、公开行动和权限校验，才能进入确定性执行链。

## 权责边界

LLM 负责评价玩家贡献、提出 Goal/Plan 变更、选择候选行动、解释判断，并依据公开环境反馈重新规划。确定性系统负责裁剪可见信息、验证数据和业务契约、执行权限与确认策略、调用工具、写入权威世界、判断计划是否真正完成，以及控制 Memory 和 Reflection 的写入。

`Plan != Permission`：计划中的步骤不能自行扩大工具权限。模型声明“已经完成”也不会改变案件；只有 `CaseEngine` 接受的合法命令和成功提交的领域事件才是权威结果。

## Agent 能力

- **Human-Agent Cooperation**：玩家贡献有明确类型，Agent 可以接受、部分接受、拒绝、请求更多证据或提出替代方案。
- **Goal / Plan / Replanning**：A1 Agent 维护持久 Goal 和有序 Plan；模型提出更新，`GoalPlanPolicy` 校验，确定性评估器依据环境结果推进、修订或结束计划。
- **Structured Output**：模型提交严格结构化 proposal；一次有限修复仍失败时进入不执行工具的 safe fallback。每次请求、修复、错误、usage 和费用均可记录。
- **Authority / Confirmation**：普通可逆调查可自主执行；诊断需要协商确认；不可逆处置需要匹配具体 decision、action digest 和 world revision 的确认。
- **CaseEngine**：统一检查调查前置、诊断、处置和评分，并独占权威案件状态写入。
- **Long-term Memory**：从已提交领域事实和通过验证的 Reflection 投影记忆；先执行玩家、Episode、类型、来源和生命周期隔离，再使用 BGE-M3 稠密向量排序。
- **Reflection**：从真实 Episode 结果构造证据包，生成候选经验，经确定性验证和保守 consolidation 后才允许进入未来检索；合法 `no_write` 是允许结果。

## A0 / A1 架构对照

- **A0 — `SimpleActionGameNPCAgent`**：模型只生成当前行动，不维护显式跨回合 Goal/Plan。
- **A1 — `GameNPCAgent`**：模型生成当前行动，同时维护持久化 Goal/Plan 并接受计划契约校验和确定性评估。

两者共享公开行动校验、权限、确认、工具执行和 `CaseEngine` 世界提交链。它们的提示、输出结构和持久状态不同，因此比较对象是两套完整行动架构，不是单一 planning module 的纯消融。现有 V2.1 C 批次还发现 A0 与 A1 的动作接口说明不对称；已观察结果不能单独归因于显式规划。

## 当前验证证据

- 当前工作区测试：`657 passed`（2026-09-26 当前工作区实测）；该数字是代码回归规模，不替代真实模型或真人体验证据。
- E6 历史冻结基线：3 个案件 × 3 次独立重复，Task Success 8/9；只适用于该冻结协议，不是线上成功率。
- 早期 V2 全量运行暴露了严重的任务推进和评测实现问题，随后完成 P0–P5 诊断、计划—动作对齐、结构化修复和处置承诺修复。
- 诊断修复小批次：指定的 6 个 T 任务与 M01 三条件共 9/9 完成；它只证明该批次关键路径恢复，不是正式可靠性或 Memory 收益结论。
- V2.1 原 54-episode 精简首轮已经执行：G 得到 17/18 严格成功；原 C/M 因评测实现缺陷不能形成有效比较。后续 C/M recovery 中，M 完成 12/12；C 只完成 8 个配对，4 个配对未启动，而且 A0/A1 接口不对称影响归因。不存在可合并的“V2.1 总成功率”，也没有证据证明 A1 的规划本身优于 A0。

完整协议、历史阶段、失败审计和结果边界见[证据导航](docs/INDEX.md)。

## 当前明确限制

- JSON 状态写入有 revision 检查和原子文件替换；正常单进程产品入口还使用按 state root + session_id 共享的 `RLock` 串行化同一 session 的完整读改写链，并已有并发冲突测试。该锁不跨进程，`save_case_session()` 本身也不是数据库级原子 CAS，因此多进程或绕过受控入口的严格并发安全仍未完成。
- pending confirmation 主要保存在进程内，尚不能在重启后完整恢复原确认流程。
- world、AgentState 与 SQLite memory 分属不同提交边界；已有权威快照、事件回放、记忆投影对账和部分故障恢复，但跨存储恢复尚未完全闭环。
- 模型原始 structured output 的 schema 遵循仍不稳定，系统仍依赖有限修复和 safe fallback。
- 已验证 Memory 的持久化、隔离、检索和曝光，但尚未证明稳定的行为收益；当前 V2.1 M 配对没有观察到任务成功收益。
- 已验证 Reflection 的机制和有限真实生成，尚未证明稳定的下游行为收益或持续自我进化。
- V2.1 没有完整、无混杂的 54 项统一结果；C 架构比较仍需修正接口后重新冻结和执行。
- 尚未完成真实攻击轨道、充分的 prompt injection 覆盖、身份认证、多租户隔离、OS/container sandbox、公网部署安全验证以及系统性的并发/崩溃演练。

## 目录

| 路径 | 作用 |
|---|---|
| `src/xuanyi_npc/agents` | A0/A1 GameNPC 与 LLM Adapter |
| `src/xuanyi_npc/application` | 协作、规划、权限、记忆、Reflection、Campaign 编排 |
| `src/xuanyi_npc/domain` | 严格领域契约与事件 |
| `src/xuanyi_npc/engine` | 确定性案件规则与权威状态提交 |
| `src/xuanyi_npc/clinic` | 本地 Web 产品入口 |
| `src/xuanyi_npc/memory` | 权威记忆投影、向量表示与安全检索 |
| `src/xuanyi_npc/evaluation` | M1–M5、V2/V2.1 runner、grader、冻结与报告工具 |
| `src/xuanyi_npc/resources/cases` | 六个正式产品案件 |
| `src/xuanyi_npc/evaluation/fixtures/v21` | 四个 V2.1 评测专用案件及规则 |
| `tests` | 产品、Agent、存储和评测基础设施回归 |

## Documentation

- [正式证据导航](docs/INDEX.md)
- [产品与架构总纲](docs/architecture/PROJECT_MASTER_BLUEPRINT.md)
- [当前路线图](docs/product/ROADMAP.md)
- [开始游戏](START_HERE.md)
