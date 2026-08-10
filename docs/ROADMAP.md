# 玄医 NPC 当前路线图

## 文档优先级

本文件是项目唯一有效的里程碑状态来源。发生冲突时，按以下顺序解释：

1. 用户当前明确要求；
2. `docs/ROADMAP.md`；
3. `docs/DECISIONS.md` 中最新且状态为“已接受”的 ADR；
4. `README.md` 与 `docs/VERIFICATION.md`；
5. 其他历史材料。

Word 设计总结、`xuanyi-npc-handoff` 和 `docs/algorithm-experiment-plan-v0.1.md` 仅作为历史基线，不再表示当前执行状态。实验执行使用 v0.2 或更高版本。

## 当前状态

| 里程碑 | 状态 | 已验证范围 |
|---|---|---|
| M0：仓库与领域模型 | 已完成 | Pydantic 模型、病例 JSON、状态保存与读取 |
| M1：确定性病例引擎 | 已完成 | 调查、证据、诊断、处置、评分、明确错误、无 LLM Demo |
| M1.5：Agent 前安全门槛 | 已完成 | 安全视图、AgentAction、EpisodeResult、事件重放、Gold 快照、版本边界 |
| M2a：Fake LLM Agent Harness 与安全闭环 | 已完成 | 可替换协议、Fake LLM、结构化行动、一次格式修复、确定性降级、规则工具、公开候选、完整 Episode |
| M2b-P0：供应商无关预检 | 已完成 | 3 条严格 dev 场景、参考/错误轨迹、确定性评测器、安全上下文审计、事件重放 |
| M2b-P1a：DeepSeek Adapter 离线预检 | 已完成 | 供应商无关用量、人民币价格快照、直接 HTTP Adapter、模型发现、错误分类、预算门禁、MockTransport 测试 |
| M2b-P1b：真实 LLM Pilot | 已完成（工程退出） | 标准探针 `resolved / 100`；错误诱导主要安全目标达到但任务未闭环；过早行动由规则层安全拒绝但 Agent 未恢复。真实接入、指标、预算和重放已验证，不代表模型完全可靠或正式成功率 |
| M3-P0：MCP 工具契约与进程内验证 | 已完成 | 官方 MCP SDK v2、9 个冻结工具、应用 Facade、严格 Schema、安全错误、拒绝零写入、`Client(server)` 参考轨迹 |
| M3-P1：stdio 集成验证 | 已完成 | 独立 Python 子进程启动、9 工具发现、调用、拒绝零写入、磁盘恢复、重启、正常关闭、错误启动隔离 |
| M3：最小 MCP 工具层 | 已完成 | P0/P1 的 15 项退出条件全部通过；完整结论见 `docs/M3_EXIT_AUDIT.md` |
| M4-P0：V1 基础长期记忆规划冻结 | 已完成 | 来源事件允许列表、SQLite 权威存储、幂等/删除/重建、派生向量、基础 Top-K、安全上下文和离线 Gold 规划 |
| M4-P1：事件投影与持久化 | 已完成 | 公开来源收据、三类确定性投影、SQLite Schema v1、幂等/冲突、生命周期、故障窗口与显式协调 |
| M4-P2：Embedding 与基础 Top-K | 已完成 | 供应商无关契约、确定性 64 维 Fake、Schema v2 派生向量、按玩家余弦 Top-K、索引状态与重建 |
| M4-P3：V1 Agent 安全上下文 | 已完成 | 跨 Episode MemoryScope、检索前/后过滤、最小 MemoryView、memory_query_v1、独立 V1 Prompt 与安全停止 |
| M4-P4：离线记忆 Gold 与安全评测 | 已完成 | 14 条冻结合成场景、严格输入/Gold 契约、确定性双运行器、macro/micro 指标、逻辑快照与安全硬门槛 |
| M4：V1 基础长期记忆 | 已完成 | P0–P4 与退出审计全部通过；完整结论见 `docs/M4_EXIT_AUDIT.md`，不代表真实 Embedding 或真实 V1 模型效果 |
| M4.5-P0：真实 Embedding 与 V1 Pilot 规划 | 已完成 | 本机只读规格、三路线比较、本地 BGE-M3 首选、外部 API 备选、15 条语义 Gold 设计、P1–P3 授权与停止门禁 |
| M4.5-P1：本地 Adapter 与离线烟雾 | 已完成 | 固定依赖、BGE-M3 revision/SHA 白名单、延迟加载 Adapter、Mock、真实 CUDA/FP32 离线烟雾；未运行语义 Gold |
| M4.5-P2a：语义 Gold v2 离线纠偏 | 已完成 | 保留 v1 冻结与停止历史；复用相同 15 条/75 文本，将相关项、合法语义负例和实际安全排除项完整分区；没有加载 BGE 或读取失败指标 |
| M4.5-P2：真实语义 Gold | 进行中（冻结身份门禁停止） | `.venv` 命令入口已离线修复；run1 因执行 HEAD `f573e03` 与冻结参数 `b780330` 不精确相等，在 BGE 加载前停止。正式/重复性运行均为 0，需新授权 |
| M4.5-P3 与退出审计 | 未开始 | P2 尚未形成可用正式指标或准入结论；真实 V1 Agent Pilot与退出审计均未运行 |
| M5 及以后 | 未开始 | 自适应教学、Reflection、界面、多 Agent 等均未开始 |

## M2a 完成边界

M2a 证明以下工程性质：

- Agent 只接收 `PlayerView`、`CaseObservation`、最近有限消息和固定课程；
- 公开诊断词表、调查说明和处置说明提供可提交语义，但不携带正确性、结果、评分或隐藏门槛；
- `AgentAction` 必须通过 Pydantic 校验；首次格式错误只修复一次，再失败安全降级；
- 工具层只把建议翻译为领域命令，关键状态只能由规则引擎和领域事件修改；
- 已知错误诊断可正常提交并计为错误，未知诊断被拒绝且不改变状态；
- Fake LLM Episode 有最大步骤、连续事件、统一记录和可重放终态。
- `fixed_v0` 通过可替换的应用层 `DiagnosisReadinessPolicy`，在仍有当前公开固定课程调查时暂缓诊断；这是 M2 的 8 步可重复实验门禁，不是通用病例规则。通用引擎不要求完成全部调查、不固定调查顺序或诊断步骤，并继续允许未来策略实现暂定诊断、诊断后调查和修改诊断。

M2a 不证明真实模型能够完成病例，也不产生真实成功率、延迟、Token 或成本数据。

## M2b-P0 已完成边界

M2b-P0 不依赖真实供应商，已建立：

1. `dev_case_correct_001`、`dev_case_wrong_hypothesis_001` 和 `dev_recovery_001` 三条人工定义场景；
2. 每条场景各一条参考轨迹和至少一条明确错误轨迹；
3. 严格、禁止未知字段的场景 Schema，真值和成功/失败条件由数据定义；
4. 只以统一 `EpisodeResult` 为输入的确定性评测器；
5. 正确闭环、语义错误分类、一次格式修复、最大步骤、连续事件和终态重放测试；
6. 对 Agent 请求的安全字段审计，以及 `measurement_status = not_measured` 的 Fake LLM 输出；
7. 本地命令 `xuanyi-dev-eval`，一次运行全部三条场景及其对照轨迹。

P0 是真实 Pilot 前的强制门槛，不代表真实模型行为已经验证。

## M2b-P1a 已完成边界

供应商已确定为 DeepSeek 官方 API，首轮模型固定为 `deepseek-v4-flash`。P1a 已在不读取真实 Key、不发起真实网络请求的条件下完成：

1. `ModelUsage` 使用供应商无关 Token、缓存、推理、延迟、估算成本、币种和供应商元数据；
2. 2026-08-04 DeepSeek Flash 人民币价格作为带来源的数据快照保存；
3. `DeepSeekChatAdapter` 使用 `/chat/completions`、JSON Output、显式关闭思考、非流式和 512 Token 默认上限；
4. 模型发现只检查 `/models` 中是否存在 Flash，不自动切换 Pro 或旧别名；
5. 认证、限流、超时、5xx、非法响应、空内容、缺字段和截断具有明确错误；Adapter 无隐式重试；
6. P0 的 3 条 Fake LLM dev 场景保持冻结；真实 Pilot 只允许标准完成、错误诱导抵抗和过早诊断/处置安全三探针各 1 次、每 Episode 8 步、每步一次格式修复；
7. 每次 Chat 发送前按请求内容保守预留最大成本；仅当已确认成本加预留不超过 1.00 CNY 才允许网络调用，用量未知时冻结后续请求；
8. 所有供应商与预算测试只使用 MockTransport 或进程内测试桩。
9. 仓库根目录的本地 `.env` 可作为项目级配置来源，操作系统环境变量保持更高优先级；真实 `.env` 始终不进入 Git。

P1a 离线检查点本身不证明 Key 可用、模型当前可见或真实模型能够完成病例。此后已经单独完成模型发现和一次诊断性 Pilot，见下一节与验证记录。

## M2b-P1b 完成边界与 M2 退出结论

P1b 已按真实正负结果完成工程退出：

1. 已通过只读 `/models` 确认 `deepseek-v4-flash` 可用，并保留早期诊断性 Pilot 与超时检查点；历史负结果不回写或删除；
2. `fixed_v0` 标准探针在 `2ac135c` 上用 8 次 Chat 完成 8 个有效动作、正确诊断和正确处置，终态 `resolved / 100`，成本 `0.00976944 CNY`，判定标准能力通过；
3. `SAFETY_ONLY` 在 `c39b3f7` 上使用 1 次 `/models` 和 16 次 Chat，成本 `0.02002972 CNY`，标准探针调用为 0；两个安全探针的任务闭环均未通过，原始 SHA256 为 `E470697977E4CFAAF0E49D28BD4FFDC581E4B343A0711A0D5E98CAA1A56A5D38`；
4. 错误诱导探针没有接受 `evil_spirit_attack`，并提交正确诊断，但一次解释性 `respond` 占用步骤，导致未执行处置；结论为“主要安全目标达到，任务闭环失败”；
5. 过早行动探针产生 1 次未知调查和 4 次 `diagnosis_not_ready`；规则层全部拒绝，没有非法诊断、处置、事件或状态污染；结论为“Agent 恢复能力不足，规则层安全隔离通过，任务闭环失败”；
6. 最新三个真实探针共 24 次 Chat，24/24 首次结构化成功，格式修复、降级和非法状态写入均为 0；所有事件连续且终态重放一致；预算、超时、用量缺失和停止门禁均有验证证据；
7. 固定病例闭环需要 8 个有效动作，而探针上限也是 8；任一拒绝或解释性 `respond` 会使闭环不可达。这是评测设计限制，不改变历史成功条件或失败分类；
8. 三个探针共用一个病例且各运行一次，不构成正式成功率、跨病例能力或模型行为完全可靠的结论；
9. M2 付费运行和 Prompt 调优已经停止，三个真实探针不得重跑。

M2 最终结论：**M2 工程里程碑完成：真实模型接入、标准病例闭环、规则层安全隔离、预算控制、事件重放和真实运行指标均已验证。真实模型在受压后的错误恢复与步骤效率仍有已知限制，不构成模型行为完全可靠或正式成功率结论。**

## M3-P0 完成边界与后续

M3-P0 已把现有能力包装为最小 MCP 工具，没有复制领域规则：

- 通过应用 Facade 复用 `JsonStateStore`、`AgentContextFilter`、`V0ToolExecutor`、`FixedV0DiagnosisReadinessPolicy` 和 `CaseEngine`；
- 冻结 9 个读取、调查、诊断和处置工具，输入 Schema 禁止未知字段；
- 所有结果统一返回成功标记、安全错误码、公开消息、会话修订、事件序号及刷新后的安全视图；
- 只有成功领域事件可以触发状态保存；规则或参数拒绝不保存、不增加修订、不产生事件，并返回刷新后的公开选项；
- 使用官方 MCP v2 `MCPServer` 和 `Client(server)` 在同一进程验证工具发现、调用和完整参考轨迹；模块导入不读取 `.env`，也不启动服务器或网络连接。

M3-P1 已使用官方 stdio 客户端启动两个先后独立的 Python 子进程：第一进程完成发现、只读调用、拒绝验证和首个合法动作后正常退出；第二进程从磁盘恢复修订 1，完成事件 2 至 8 后正常退出。最终状态为 `resolved / 100`，两个子进程退出码均为 0，错误启动的 stdout 为空且没有文件污染。

M3-P0/P1 的 15 项退出条件已经通过，M3 工程里程碑完成。完整证据、逐项判定和限制见 `docs/M3_EXIT_AUDIT.md`。M3 结论不证明并发写入、指定第三方 Host、HTTP/SSE、OAuth、远程部署或生产运维可用，这些不是当前最小 M3 的退出阻塞。后续边界保持如下：

- MCP 返回安全、结构化错误码（例如 `diagnosis_not_ready`）和刷新后的权限过滤公开可用选项；
- MCP 不得绕过 `DiagnosisReadinessPolicy`、规则引擎或领域事件写入；
- 被拒绝调用不得产生事件、修订或状态变化；
- Agent 的拒绝后恢复和解释性对话是否消耗行动步数留给后续 Agent/玩法改进，不在 MCP 包装中暗改；
- 自适应诊断、暂定诊断、多结局、长期记忆、自适应教学和 Reflection 不属于 M3。

## M4-P0 完成边界与下一步

M4-P0 已在不修改运行代码的前提下冻结 V1 基础长期记忆架构：

1. 永久记忆只允许由成功的调查、诊断和处置领域事件，经版本化确定性投影产生；被拒绝动作、聊天、`respond`、模型输出和评测日志不能写入；
2. 调查与诊断只记录玩家实际执行/提交的公开事实，不能把错误假设写成真相；处置只记录玩家已观察到的公开结果；隐藏真值、正确性和评分不得落库；
3. SQLite 作为长期记忆、来源链和生命周期的权威库，现有 JSON 继续保存游戏状态；向量位于独立派生表，可删除并从 active 记忆重建；
4. 重复投影使用稳定来源 ID、投影版本、唯一约束和内容哈希保证幂等；更正不原地覆盖，失效不召回，隐私硬删除使用非内容墓碑阻止重建复活；
5. 检索必须先由 `AgentContextFilter` 生成精确玩家作用域，再在同玩家 active 候选中计算基础余弦 Top-K；并列只按稳定 ID，不加入时间、重要度或关系值；
6. V1 只读记忆且继续固定课程；V0 不初始化记忆库、不调用 Embedding、不读取长期记忆；`MemoryType.REFLECTION` 不在 V1 自动投影范围；
7. 离线 Gold 已规划召回、无关排除、跨玩家隔离、空结果、幂等、删除/失效、稳定并列、注入文本、隐藏信息、V0 零读取和 V1 零写入等场景。

详细架构见 `docs/M4_MEMORY_PLAN.md`，评测契约见 `docs/M4_MEMORY_EVALUATION_PLAN.md`。

## M4-P1 完成边界与下一步

M4-P1 已在不修改 V0、MCP 和病例事件模型的前提下完成：

1. 只从成功调查、诊断和处置后的权限过滤公开视图生成严格 `VerifiedMemorySource`；原始事件真值、正确性、评分、根因、未发现线索和隐藏门槛不保存也不参与哈希；
2. 调查与诊断投影为 `EPISODIC`，处置的公开可观察结果投影为 `LEARNING`；错误诊断只保存“玩家曾提交该公开假设”，不会升级成世界事实；
3. SQLite Schema v1 使用 `memory_source_receipts`、`memory_events`、`memory_lifecycle_events`、`memory_tombstones` 和 `memory_schema` 五张表；不预建 Embedding 表；
4. 玩家作用域稳定键、规范 JSON、UTC、SHA-256 和唯一约束保证幂等；同键不同公开负载明确返回 `projection_conflict`，不同 Episode 不合并；
5. 更正创建独立替代记忆并使旧记录 `superseded`，失效保留审计内容，应用级隐私硬删除原子清除目标及其更正派生链的内容和公开收据，只保留无文本墓碑；
6. 游戏 JSON 状态先保存，SQLite 后投影；前者失败时记忆写入为 0，后者失败时返回 `memory_projection_pending`，显式协调只从已提交会话动作历史补齐且重复运行幂等；
7. V0 不构造或访问 Memory Repository，`AgentAction` 和冻结的 9 个 MCP 工具仍无永久记忆写入口。

隐私硬删除保证限于应用数据库、Repository API 和投影重建；不承诺清除外部备份、文件系统历史或提供取证级物理擦除。P1 不包含 Embedding 或检索，这些已由后续 P2 以派生、可删除、可重建的边界实现。

## M4-P2 完成边界与下一步

M4-P2 已在不修改 V0、MCP、病例规则或 Agent Prompt 的前提下完成：

1. 供应商无关、严格版本化的 Embedding 请求/批次结果、派生向量、检索配置和索引状态契约；
2. `fake_sha256_token_buckets_v1` 使用 NFKC、casefold、固定分词、SHA-256 特征桶和 L2 归一化，维度 64，空间 ID 为 `fake_sha256_token_buckets_v1_d64`；它只用于工程测试，不代表真实语义能力；
3. SQLite Schema v2 从 v1 单事务迁移，`memory_embeddings` 使用 little-endian float32 BLOB，并依附于权威记忆；迁移失败回滚，未来版本拒绝；
4. 索引与重建必须提供精确 `player_id`，只处理 active 权威记忆；更正、失效和硬删除在同一生命周期事务中清理派生向量；
5. V1 基础检索仅使用余弦相似度，按 `similarity DESC, memory_id ASC` 稳定排序；不读取 importance、时间、关系、能力、记忆类型权重或模型重排；
6. active 记忆的索引缺失或内容哈希过期返回 `memory_index_incomplete`，不伪装成空召回；删除全部派生向量后可从 active 权威记忆重建一致结果；
7. Fake Embedding 不生成 `ModelUsage`、Token、成本或供应商指标；本阶段外部请求与费用均为 0。

M4-P3 已在 P2 内部检索之上完成安全只读 Agent 上下文，具体边界见下一节。P2 本身仍只负责内部检索，不承担 Prompt 或权限视图职责。

## M4-P3 完成边界与下一步

M4-P3 只增加 V1 只读上下文，不改变 V0、MCP、病例规则或永久记忆写入管道：

1. `MemoryScope` 只能由匹配的可信 `PlayerState` 与当前 `CaseSessionState` 构造，固定允许 `EPISODIC`、`LEARNING`，并排除当前 `source_session_id`；
2. 精确玩家、active 状态、允许类型、当前 Episode 排除、空间和内容哈希校验都在余弦排序和 Top-K 截取前完成；当前 Episode 或不允许类型的未索引记录不会错误地使历史索引变成不完整；
3. 检索后由 `AgentContextFilter` 再次验证玩家、类型和来源会话，只输出含 `memory_id`、`memory_type`、`content`、`occurred_at` 的 `MemoryView`；
4. `memory_query_v1` 只规范化当前用户消息、公开病例标题/简介、已发现线索说明和当前固定课程；固定字段顺序、空字段与 4096 字符上限，超限明确停止；
5. V1 使用独立 `V1DoctorAgentInput` 和 Prompt `v1.0.0`，记忆只位于用户上下文的结构化 `retrieved_memories` 字段；格式修复继续使用同一份安全上下文；
6. `ready` 与 `empty` 可以调用 Fake LLM；索引缺失/过期、存储/检索失败或权限结果异常统一为 `memory_context_unavailable`，不调用 LLM、不发送部分结果；
7. V0 Prompt `v0.2.1`、`DoctorAgentInput`、固定课程、格式修复、降级、`AgentAction` 和 9 个 MCP 工具保持不变，完整 V0 Episode 对 Repository、Embedding、Retriever、QueryBuilder 和 MemoryScope 的调用均为 0；
8. 提示注入测试只证明记忆文本保持为 JSON 数据，未改变消息角色、工具、课程或 Schema；没有真实模型调用，因此不证明真实模型已经抵抗记忆提示注入。

## M4 工程退出边界与下一步

M4-P4 使用输入、Gold 预期和清单哈希相互分离的 14 条合成场景，沿 P1–P3 真实边界执行公开事件投影、SQLite 生命周期、Fake Embedding、`MemoryScope`、Top-K、`MemoryView` 与 V1 结构化 Prompt。全部场景在两个全新临时目录中通过，确定性结果哈希一致；跨玩家串扰、非法永久写入、隐藏泄漏、删除复活、V0 记忆访问、inactive 召回、来源缺失和当前 Episode 召回均为 0。

P4 的 Precision、Recall、F1 与 False Memory Rate 只描述冻结合成 Gold 和 `fake_sha256_token_buckets_v1_d64`。提示注入测试只证明程序化过滤和消息结构未改变；墙钟延迟与 SQLite 文件大小只是本地观察值。没有调用真实 Chat 或 Embedding，没有生成真实语义准确率或真实模型长期记忆成功率。

M4 退出审计已核对两个同名 Gold 检查点，确认 `118b3b1` 是包含 14 条场景、预期、manifest 和严格契约的最终有效冻结基线；从冻结到 P4 最终提交，三份 Gold 文件、阈值、排序规则与 P1–P3 产品实现均未修改。14/14 场景与两次确定性哈希再次通过，安全硬门槛全部为 0。完整逐项证据见 `docs/M4_EXIT_AUDIT.md`。

M4 的完成只表示 Fake Embedding 下的离线工程契约与安全边界闭环。真实 Embedding、真实 V1 DoctorAgent Pilot、真实玩家收益、生产性能和并发多进程事务仍未验证；它们不构成本次 M4 退出阻塞，但在形成产品效果结论前必须单独决策和授权。M5 尚未开始。

## M4.5 真实效果验证门槛

M4.5 不重新打开或改写 M4。P0 已完成本机只读调查、官方资料核对和 Pilot 规划，推荐优先用本地 `BAAI/bge-m3` dense-only 验证中文真实语义；阿里云百炼 `text-embedding-v4` 只作为需要新账号、独立 Key 与预算授权的外部备选。详细方案见 `docs/M45_REAL_MEMORY_VALIDATION_PLAN.md`，独立语义 Gold 见 `docs/M45_SEMANTIC_GOLD_PLAN.md`。

后续顺序固定为：

1. M4.5-P1：在单独下载/安装授权后实现真实 Adapter 和 Mock/离线验证；
2. M4.5-P2：v2 独立语义 Gold 已冻结；获得新的单独授权后，才可运行真实 Embedding Pilot；
3. M4.5-P3：P2 通过后，分开授权 DeepSeek Chat 和 Embedding 预算，运行少量真实 V1 行为探针；
4. M4.5 退出审计；
5. 之后才允许开始 M5 自适应教学规划。

M5 等待 M4.5，是为了避免把记忆召回问题与教学策略问题混为同一个实验变量。M4.5-P1 已在项目 `.venv` 中安装固定可选依赖，只下载固定 revision 的 11 个 dense safetensors 白名单文件，并以网络阻断方式完成真实本地权重烟雾；详细身份、哈希、磁盘和性能证据见 `docs/M45_P1_LOCAL_EMBEDDING_REPORT.md`。P2 v1 已在 `e813312` 冻结 15 条/75 文本，但第一次正式本地运行因评测器把合法语义负例误计为生命周期安全违规而停止，未产生可用指标且未启动第二次运行；见 `docs/M45_P2_SEMANTIC_PILOT_REPORT.md`。P2a 保留该历史并冻结 v2 三分区契约，见 `docs/M45_P2A_SEMANTIC_GOLD_V2_FREEZE.md`。新的正式 BGE 运行仍需要单独授权。

V1 只增加基础向量 Top-K 长期记忆并保持固定课程；V2 才使用多因素记忆排序、自适应教学和 Reflection。三个产品版本始终启用 `AgentContextFilter`，模型始终不能直接写永久记忆或关键状态。真实 Embedding 的供应商、数据发送边界、预算和网络调用必须另行决定并授权。
