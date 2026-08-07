# M4 基础长期记忆架构规划

## 1. 文档身份

- **规划日期**：2026-08-07
- **规划基线**：`2c78dadbab19ee724bfc7595e2256b14314c427c`
- **适用版本**：V1（基础向量 Top-K 长期记忆 + 固定课程）
- **当前状态**：M4-P0、M4-P1、M4-P2 与 M4-P3 已完成；M4-P4 尚未开始
- **实现状态**：已实现确定性公开事件投影、SQLite Schema v2、生命周期、Fake Embedding、派生向量、按玩家余弦 Top-K 和 V1 Agent 安全只读上下文；尚未执行 P4 Gold 评测

M4 的目标是在不改变 V0 病例引擎、固定课程、工具和安全边界的前提下，为 V1 增加跨 Episode、来源可追溯的只读长期记忆。V1 不实现多因素排序、自适应课程、Reflection、关系或技能自动成长，也不允许模型直接写永久状态。

## 2. 仓库现状与设计约束

| 现有组件 | 当前事实 | 对 M4 的约束 |
|---|---|---|
| `MemoryEvent` | M0 预留模型保持不变；P1 新增严格 `AuthoritativeMemoryRecord`，补齐来源事件、来源会话、修订、投影版本、内容哈希和生命周期状态 | V1 自动投影不得使用关系影响或 `REFLECTION`；V0 序列化格式不变 |
| 病例领域事件 | 只有成功的调查、诊断和处置会产生事件；事件含 `session_id`、连续 `sequence` 和时间，没有独立事件 ID 或 `player_id` | 应由应用层结合已提交会话生成稳定来源 ID，不修改 V0 事件语义 |
| `CaseSessionState` | 保存 `player_id`、连续动作历史和 `revision`，可由领域事件重放 | 可用于核对来源玩家、会话和修订；拒绝动作没有事件，天然不能投影记忆 |
| `JsonStateStore` | 原子保存玩家与病例会话快照；没有跨 Episode 查询、唯一约束、迁移或记忆索引 | 继续作为 V0 游戏状态存储，不承担长期记忆查询；M4 另建 SQLite 记忆库 |
| `PlayerState` | 不包含永久记忆集合 | 不把记忆塞入玩家 JSON，避免扩大 V0 状态与迁移范围 |
| `AgentContextFilter` | 只生成安全的 `PlayerView` 和 `CaseObservation` | P3 在同一边界增加记忆作用域和只读 `MemoryView`，不能旁路过滤器 |
| `V1_CONFIG` | 已冻结为 `PERSISTENT_MEMORY + VECTOR_TOP_K + FIXED + Reflection disabled` | M4 不改变课程策略，不引入多因素排序或 Reflection |
| `AgentAction` / MCP | 没有 `record_memory`，只包含既有读、调查、诊断和处置工具 | M4 不增加任何模型可调用的永久记忆写工具 |

现有 `MemoryEvent` 仍是 M0 的预留模型。P1 没有修改它或 V0 状态格式，而是通过显式 V1 组装引入 `VerifiedMemorySource`、`AuthoritativeMemoryRecord` 和 `SQLiteMemoryRepository`；这避免了虚假的旧数据迁移，也保持 V0 行为不变。

### 2.1 M4-P1 实现检查点

- `DeterministicMemoryProjector` 只接受三类已提交领域事件，并先构造禁止未知字段的公开视图；
- `SQLiteMemoryRepository` 的 Schema 版本为 1，权威表为 `memory_schema`、`memory_source_receipts`、`memory_events`、`memory_lifecycle_events` 和 `memory_tombstones`；
- `V1MemoryCoordinator` 显式执行“JSON 状态成功保存 → SQLite 投影”，并提供从已提交会话动作历史补齐 pending 投影的协调边界；
- Schema v1 不包含 `memory_embeddings`，也没有 Embedding、Top-K、Prompt 或 MCP 记忆工具；这些仍属于后续阶段。

### 2.2 M4-P2 实现检查点

- `EmbeddingAdapter` 边界与请求、批次结果、派生向量、检索配置和索引状态都使用禁止未知字段的严格契约；
- `DeterministicFakeEmbedding` 的算法版本为 `fake_sha256_token_buckets_v1`，维度 64，空间 ID 为 `fake_sha256_token_buckets_v1_d64`，仅作工程测试；
- SQLite Schema v2 通过 v1→v2 原子迁移新增 `memory_embeddings`；向量使用 little-endian float32 BLOB，并保存权威内容哈希、维度、L2 norm 和生成时间；
- `MemoryIndexService` 只处理精确 `player_id` 的 active 记忆，支持幂等索引、全量派生删除后重建、缺失/过期状态识别；
- `BasicCosineMemoryRetriever` 仅按余弦相似度与 `memory_id` 稳定并列规则排序，只返回内部检索记录；没有 `MemoryView`、Prompt 或 MCP 记忆工具。

### 2.3 M4-P3 实现检查点

- `MemoryScope` 由可信玩家状态与当前病例会话构造，固定允许 `EPISODIC`、`LEARNING` 并排除当前 `source_session_id`；模型和普通参数不能扩大作用域；
- `BasicCosineMemoryRetriever.retrieve_scoped` 在索引完整性、余弦计算和 Top-K 前过滤玩家、active 状态、允许类型与当前 Episode；空间和内容哈希继续由 P2 门禁验证；
- `AgentContextFilter.memory_views` 对内部结果二次核对玩家、类型和来源会话，再只公开 `memory_id`、`memory_type`、`content`、`occurred_at`；
- `MemoryQueryBuilder` 冻结为 `memory_query_v1`，只使用当前消息、公开标题/简介、已发现线索说明和固定课程，使用 NFKC、casefold、空白折叠、固定 JSON 字段顺序及 4096 字符上限；
- V1 使用独立的 `V1DoctorAgentInput` 与 Prompt `v1.0.0`，记忆只作为用户上下文中的结构化 `retrieved_memories` 数据；一次格式修复复用同一安全上下文；
- 记忆上下文区分 `ready`、`empty`、`unavailable`。`unavailable` 统一返回安全码 `memory_context_unavailable`，不调用 LLM、不发送部分结果；
- V0 Prompt `v0.2.1` 与输入 Schema 的 Gold 哈希保持不变，完整 V0 Episode 的记忆 Repository、Embedding、Retriever、QueryBuilder 和 MemoryScope 调用均为 0；
- P3 只用 Fake Embedding 与 Fake LLM。注入测试证明程序化边界与消息结构未改变，不构成真实模型抗提示注入结论。

## 3. 冻结的单向安全管道

```text
已成功提交的领域事件
  -> 应用层构造权限过滤后的 VerifiedMemorySource
  -> 确定性 MemoryProjectionPolicy（版本化、默认拒绝未知事件）
  -> MemoryEvent（带完整来源链）
  -> SQLite 权威记忆存储
  -> AgentContextFilter 生成玩家专属候选作用域
  -> 基础向量余弦相似度 Top-K
  -> AgentContextFilter 输出只读 MemoryView
  -> V1 Prompt 的“非指令历史数据”区域
```

该管道只有从左向右的路径。模型输出、自然语言回复、原始聊天、工具错误和评测日志不能逆向或旁路写入永久记忆。

## 4. 允许投影的来源事件

M4-P1 初始投影采用显式允许列表；每个成功来源事件最多产生一条 V1 自动记忆。未来新增领域事件默认不投影，必须升级投影版本并增加测试。

| 来源事件 | V1 记忆类型 | 允许进入内容的公开事实 | 固定写入原因 | 禁止进入内容的字段 |
|---|---|---|---|---|
| `InvestigationCompletedEvent` | `EPISODIC` | 公开调查说明、执行动作、该事件新发现且在事后安全视图中可见的线索说明 | `verified_case_investigation` | 线索是否关键/误导、未发现线索、调查隐藏前提、病例真相 |
| `DiagnosisSubmittedEvent` | `EPISODIC` | “玩家提交了某公开假设”、公开候选说明、当时已发现且实际引用的证据说明 | `verified_diagnosis_submission` | 诊断正确性、`valid_diagnosis_ids`、根因、未引用或未发现证据、评分 |
| `TreatmentExecutedEvent` | `LEARNING` | 公开处置说明和玩家已经观察到的公开结果消息；表述必须限定在该病例经历，不提升为世界通则 | `verified_treatment_observation` | `diagnosis_correct`、数值评分、正确处置标记、隐藏门槛和因果链 |

投影出的 `importance` 由投影版本确定，但 V1 检索不得使用它排序。初始建议固定为调查 2、诊断 3、处置结果 4；这些值只用于审计和以后 V2 的候选研究，不构成 V1 的多因素排序。

V1 自动投影的 `relationship_impacts` 必须为空。关系、能力、技能和权限仍只能由未来独立的确定性规则及专用领域事件修改。

### 明确不保存的输入

- 任何被规则或策略拒绝的动作，因为它们没有领域事件；
- `respond`、Agent 的解释文本、原始对话、Prompt、模型输出和思维链；
- 只读工具调用、刷新视图、超时、降级、异常、日志和评测分类；
- `MemoryEvent` 自身，避免投影循环；
- 未进入允许列表的新事件类型；
- 病例 `root_cause`、`causal_chain`、`valid_diagnosis_ids`、正确性、评分、未发现线索、隐藏前置条件和关系原始值；
- 把错误诊断写成事实。已接受的错误诊断只能记录为“玩家曾提交该假设”；
- `MemoryType.RELATIONSHIP`、`COMMITMENT` 和 `REFLECTION` 的自动记录。前两者需要未来专用的已验证领域事件，`REFLECTION` 只属于 V2。

## 5. 来源链与幂等契约

P1 应扩展现有 `MemoryEvent` 或引入与之等价的严格版本化记录，至少包含：

| 字段 | 语义 |
|---|---|
| `event_id` | 记忆记录自身的稳定 ID；保留现有命名以减少迁移 |
| `player_id` | 记忆所属玩家，必须与来源会话一致 |
| `source_event_id` | 来源事件稳定 ID |
| `source_event_type` | 来源领域事件类型 |
| `source_session_id` | 来源 Episode/病例会话 ID |
| `source_revision` | 来源事件成功提交后的会话修订号，不能只假设它等于事件序号 |
| `source_sequence` | 来源事件在会话中的连续序号 |
| `projection_version` | 生成内容和重要度的确定性投影版本 |
| `write_reason` | 允许列表中的固定原因码，不接收自由模型文本 |
| `content_hash` | 对规范化公开记忆负载计算的 SHA-256 |
| `status` | `active`、`superseded` 或 `invalidated`；只有 `active` 可检索 |
| `supersedes_event_id` | 更正时指向被替代记忆；普通记录为空 |

当前病例事件没有独立 ID。P1 使用规范字符串 `event_type + session_id + sequence` 计算 UUIDv5，并编码为符合现有 `Identifier` 限制的 `ce_<32位小写十六进制>`。记忆 ID 使用 `player_id + source_event_id + projection_version + projection_ordinal` 计算为 `mem_<32位小写十六进制>`。初始投影的 `projection_ordinal` 固定为 0，但保留该维度以允许未来同一来源产生多条不同类型记忆。

幂等约束如下：

1. SQLite 对 `(player_id, source_event_id, projection_version, projection_ordinal)` 建立唯一约束；
2. 同一来源、版本和内容哈希再次投影时返回“已存在”，不新增记录；
3. 同一稳定 ID 对应不同内容哈希时返回明确的 `projection_conflict`，不得静默覆盖；
4. 不把不同 Episode 中语义相同的合法事件合并。它们是不同历史事实，只去除同一来源事件的重复消费；
5. 投影和来源收据在单个 SQLite 事务中写入，任一步失败则该记忆事务全部回滚。

## 6. 权威存储与提交顺序

### 6.1 推荐：SQLite 作为长期记忆权威库

采用 Python 标准库 `sqlite3`，不增加数据库服务。`JsonStateStore` 继续保存玩家与病例会话；SQLite 只保存跨 Episode 的记忆事实、来源收据、生命周期审计和派生向量元数据。

推荐最小表：

- `memory_source_receipts`：稳定来源 ID、玩家、会话、序号、修订、事件类型、允许列表后的公开规范负载、该公开负载的 SHA-256 和接收时间；不保存、序列化或哈希原始事件负载及隐藏字段；
- `memory_events`：权威 `MemoryEvent` 内容、来源链、状态、内容哈希和版本；
- `memory_lifecycle_events`：更正、失效和删除的追加式审计；
- `memory_tombstones`：隐私硬删除后只保留非内容 ID、哈希、原因码和时间，阻止重建时复活；
- `memory_embeddings`：P2 通过 Schema v1→v2 原子迁移新增的可删除、可重建派生向量，不是事实来源；P1 历史 Schema v1 不预建此表。

选择 SQLite 的原因：当前阶段数据量小，但需要跨 Episode 查询、唯一约束、事务、版本迁移和删除审计；这些能力不适合继续叠加在 JSON 快照目录上。SQLite 已能满足需求，无需向量数据库、消息队列或数据库服务。

### 6.2 JSON 状态与 SQLite 之间的一致性

不引入分布式事务。V1 应采用“先提交游戏状态，后以至少一次方式投影记忆”的顺序：

1. `CaseEngine` 产生领域事件和新会话；
2. `JsonStateStore` 成功保存新会话；
3. 应用层把已提交事件与安全事后视图交给投影服务；
4. SQLite 以幂等事务写来源收据和记忆。

如果第 2 步失败，不得产生记忆；如果第 4 步失败，游戏状态保持已提交，返回可审计的 `memory_projection_pending`，由显式离线协调命令按会话动作历史重投。该选择避免出现“状态未落盘但永久记忆已存在”。P1 必须测试两个故障窗口和重复协调，不引入后台队列。

## 7. 更正、撤销、删除和重建语义

所有生命周期操作都来自受信任的应用/管理边界或未来专用领域事件，绝不来自 AgentAction 或模型工具。

- **更正**：不原地改写内容，也不复用原来源 ID。每次更正由可信应用/管理边界提交稳定且唯一的 `operation_id`、固定原因码、目标玩家和被替代记忆 ID；创建具有独立稳定 ID 的替代记忆，设置 `supersedes_event_id`，并在同一事务中把旧记录标记为 `superseded`。相同操作 ID 重放幂等，不同操作不得共用 ID；两条记录和更正原因都可审计，只有新记录可读取为 active。
- **撤销/失效**：把目标记录标记为 `invalidated`，追加固定原因码和来源；保留内容供审计，但检索必须排除。
- **普通删除**：等同失效，适用于业务撤回且允许保留审计内容的情况。
- **隐私硬删除**：从应用 SQLite 数据库删除权威内容、允许列表后的公开来源负载、关联实体及未来派生内容；Repository API 不再可读取，只保留不含文本的墓碑 ID/哈希/时间/固定原因码。重建必须识别墓碑，不能恢复被删除内容。该保证只覆盖应用数据库和 Repository 行为，不承诺清除外部备份、文件系统历史，也不提供取证级物理擦除。
- **向量重建**：可随时删除 `memory_embeddings`，从所有 `active` 权威记忆按指定 `embedding_space_id` 重算；不能从向量反推记忆事实。
- **投影重建**：只从未被硬删除的安全来源收据，以指定 `projection_version` 重跑到空的记忆表；ID 和顺序必须与首次投影一致。来源缺失时停止并报告不完整，禁止由模型补写。

## 8. Embedding 与基础 Top-K

### 8.1 可替换 Adapter

P2 定义供应商无关的 `EmbeddingAdapter` 协议。输入是版本化、规范化的公开文本批次，输出包括向量、维度和 `embedding_space_id`；业务层不依赖 SDK、模型名或网络实现。查询向量和文档向量必须来自同一空间，不匹配时明确拒绝。

离线实现使用确定性 `FakeEmbedding`：固定分词、SHA-256 特征桶、固定维度和 L2 归一化，不使用受进程随机种子影响的 Python `hash()`。Gold 数据只验证检索、顺序和安全契约，不把 Fake 结果冒充真实语义效果。

真实 Embedding 必须另行选择供应商和模型，单独确认数据发送边界、价格快照、预算、密钥、超时和网络授权。现有 DeepSeek Chat 授权不自动扩展到 Embedding，也不得默认复用其 Key 或预算。

### 8.2 向量格式

向量保存在独立派生表 `memory_embeddings`：

- 主键：`(memory_id, embedding_space_id)`；
- 向量：固定维度、little-endian float32 BLOB；
- 元数据：维度、L2 norm、来源 `content_hash`、生成时间；
- 使用时必须核对 `content_hash`，过期向量不可参与召回；
- 更正、失效或删除记忆时同步删除对应向量；索引可整体重建。

### 8.3 小规模 Top-K 算法

V1 不引入独立向量数据库。单次检索顺序固定为：

1. P2 由受信应用边界显式提供精确 `player_id`；P3 才由 `AgentContextFilter` 根据当前 `PlayerState` 生成 `MemoryScope`；
2. SQLite 先以精确 `player_id` 和 `status=active` 过滤候选；允许类型与可见级别属于 P3 权限过滤；
3. 加载匹配 `embedding_space_id` 且内容哈希有效的向量；
4. 在进程内计算余弦相似度；
5. 严格应用配置的最小相似度；
6. 按 `similarity DESC, memory_id ASC` 稳定排序；并列分数只按稳定 ID，不加入时间或重要度；
7. 截取 Top-K；
8. P2 返回带分数的内部检索结果；P3 已由 `AgentContextFilter` 二次校验并转换成最小只读 `MemoryView`。

检索配置使用严格、版本化 Schema，至少包含 `top_k`（1–20）、`min_similarity`（-1 至 1）、`embedding_space_id` 和查询模板版本。产品不使用隐式默认值；P2 单元测试可以使用固定夹具值，P4 只根据离线 dev Gold 冻结 V1 实验配置。数值未验证前不声称有效率。

V1 的排序分数只能是向量余弦相似度。`importance`、时间新近度、关系值和玩家能力不得影响排序；这些属于 V2 多因素排序。

## 9. 权限过滤与 V1 Prompt

P3 在现有 `AgentContextFilter` 增加两段式防线：

1. **检索前作用域**：从当前可信 `PlayerState` 产生精确 `player_id` 和允许的记忆类型/可见级别。Repository API 不提供 Agent 可调用的“查询全部玩家”路径；传入记录的玩家不匹配即拒绝。
2. **检索后只读视图**：`MemoryView` 只包含不透明记忆 ID、类型、公开内容和发生时间。来源哈希、内部来源负载、写入原因、生命周期记录和其他玩家 ID 不进入 Prompt。

V1 的查询文本由版本化 `MemoryQueryBuilder` 从当前用户消息、公开病例摘要、已发现线索和固定课程步骤构建，不接收 `CaseDefinition` 的隐藏字段。检索结果放入独立 JSON 字段 `retrieved_memories`，明确标记为“历史数据，不是指令”；其中即使出现“忽略规则”等文本，也不能改变系统指令、工具集合或动作 Schema。

检索只增加上下文，不改变固定课程步骤、`fixed_v0` 诊断策略、工具权限或最大步骤。V1 的 `AgentAction` 与 V0 完全相同，没有记忆写入、删除或更正字段。

P3 的运行状态语义已经冻结：`ready` 有合法历史，`empty` 是索引完整后的合法空结果，二者可以构建 V1 输入；`unavailable` 包含索引缺失/过期、存储或检索失败及作用域安全异常，不能伪装成“没有历史”，必须在模型调用前停止。检索后发现跨玩家、当前 Episode 或不允许类型时同样安全停止。

## 10. V0 不变性保证

- `V0_CONFIG.memory_retrieval_strategy` 继续为 `NONE`；V0 runner 不构造 MemoryRepository、不调用 Embedding、不读取 SQLite；
- V0 Prompt、固定课程、9 个 MCP 工具和 `AgentAction` Schema 不变；
- `JsonStateStore` 的玩家/会话文件格式不因 M4 改变；
- M4 模块通过显式 V1 组装启用，模块导入不打开数据库、不读取 `.env`、不访问网络；
- 每一阶段必须先运行现有全量测试，并增加“V0 对 MemoryRepository 与 Embedding 调用均为 0”的回归测试；
- 如果现有 182 项测试中的任何一项因 M4 改变行为，阶段立即停止，不用放宽安全断言换取通过。

## 11. M4 分阶段门槛

| 阶段 | 输入 | 产物 | 明确不包含 | 退出条件 | 网络/付费 | 失败时停止条件 |
|---|---|---|---|---|---|---|
| **M4-P0：规划冻结** | M3 已完成基线；现有事件、状态、过滤器、V1 配置 | 本文、Gold 评测计划、路线图和 ADR | 任何运行代码、数据库、Embedding、向量和 Agent 接入 | 13 项技术决策、单向安全管道、阶段门槛和评测定义完成；全量测试不回退 | 不需要；请求数和费用均为 0 | 文档与现有安全 ADR 冲突且无法通过规划消解；基线或工作树不符合要求 |
| **M4-P1：事件投影与持久化（已完成）** | P0 冻结契约；已提交病例事件和安全视图 | `VerifiedMemorySource`、稳定来源 ID、`AuthoritativeMemoryRecord`、SQLite Repository、生命周期与协调测试 | Embedding、Top-K、Prompt、Agent/MCP 记忆工具、关系/技能更新 | 允许列表、隐藏字段排除、幂等、冲突、故障窗口、更正/失效/硬删除/重建和玩家隔离全部离线通过；V0 回归通过 | 不需要；实际请求与费用为 0 | 任一无来源写入、重复记忆、跨玩家写入、隐藏字段落库、删除后复活或 V0 行为变化 |
| **M4-P2：Embedding 与基础检索（已完成）** | P1 的 active 权威记忆和严格检索配置 | 可替换 Adapter、确定性 Fake、派生向量表、进程内余弦 Top-K、稳定并列和重建测试 | 真实供应商调用、多因素排序、Agent Prompt、向量数据库 | 同空间校验、阈值、Top-K、稳定排序、失效排除、向量重建和无网络测试通过；跨玩家候选为 0 | 不需要；实际请求与费用为 0 | 向量成为唯一事实来源、排序混入重要度/时间、用量不明、网络未授权或不可重复 |
| **M4-P3：V1 安全上下文集成（已完成）** | P2 检索器；现有 `AgentContextFilter`、DoctorAgent 与固定课程 | `MemoryScope`、`MemoryView`、版本化查询构建、V1 只读 Prompt 集成 | 自适应课程、Reflection、关系/能力更新、新工具、真实 LLM 调用 | 检索前玩家隔离、检索后最小视图、注入文本作为数据、V0 零读取、V1 零写入、固定课程不变 | 离线 Fake 不需要；实际外部请求和费用为 0 | 任何真值泄漏、跨玩家召回、AgentAction 写记忆、课程顺序受记忆暗改或 V0 Prompt 改变 |
| **M4-P4：离线 Gold 与指标** | P1–P3 能力；合成跨 Episode Gold | 严格场景 Schema、确定性评测器、Precision/Recall/F1/FMR、安全与规模报告 | 真实成功率、付费模型数据、自适应教学或 Reflection | 全部 Gold 可重复；跨玩家串扰=0、非法永久写入=0；失败分类、延迟和存储规模可审计；不预填效果 | 不需要 | 安全硬门槛非 0、同输入结果不稳定、评测真值进入 Prompt 或 Fake 指标被写成真实效果 |
| **M4 退出审计** | P1–P4 已提交证据 | 逐项审计、能力边界、已知限制和最终结论 | 顺手修功能、真实供应商扩权、M5 代码 | 全量与专项测试、Gold、重建、安全检查和文档一致；明确真实 Embedding 是否未验证 | 审计本身不需要 | 证据与实现不一致时停止，不能靠审计修改代码掩盖缺口 |

## 12. M4 退出时仍不应声称的能力

- 真实 Embedding 的语义效果、价格、延迟或供应商稳定性，除非之后另行授权并保存真实证据；
- 多因素排序、自适应教学、Reflection、暂定诊断、多结局或玩家能力画像；
- 模型能够写入、纠正或删除永久记忆；
- SQLite 或 `JsonStateStore` 已支持并发多进程写入；
- HTTP 服务、远程数据库、生产运维、多 Agent 或界面已经完成。

## 13. 后续需要用户决定的事项

M4-P2 的离线实现没有外部决策阻塞。以下事项只在准备真实 Embedding 时需要用户单独决定并授权：

1. Embedding 供应商、准确模型与服务区域；不得从 DeepSeek Chat 配置推断；
2. 哪些公开记忆文本允许发送给外部供应商，以及日志/保留策略；
3. API Key 环境变量、日期化价格快照、总预算、每次请求上限、超时和停止条件；
4. M4 退出是否只证明离线工程契约，还是另外增加一次真实 Embedding 小型 Pilot。后者不是 P1–P4 的隐式授权。

在这些选择发生前，确定性 Fake Embedding 足以实现和验收存储、隔离、Top-K、排序、删除、重建及离线 Gold，不产生任何真实效果数据。
