# M4 长期记忆离线评测计划

## 1. 目的与边界

本计划为 V1 的跨 Episode 长期记忆建立可重复、供应商无关的 Gold 评测。所有玩家、病例、事件和查询均为合成数据；Embedding 使用确定性 Fake，不连接网络，不生成真实模型成功率、Token、费用或语义效果结论。

评测只回答以下问题：

- 已验证事件能否幂等投影为可追溯记忆；
- 玩家隔离、权限过滤、删除和失效是否可靠；
- 基础向量 Top-K 的过滤、阈值和稳定排序是否符合冻结配置；
- V0 是否完全不读取记忆，V1 是否只能只读；
- 记忆文本是否始终作为普通数据而不是 Prompt 指令。

## 2. Gold 数据契约

M4-P4 应以严格 Pydantic Schema 加载场景，所有模型 `extra="forbid"`。建议每条场景至少包含：

- `scenario_id`、`description` 和 `variant`；
- 至少两个隔离玩家的公开状态；
- 按 Episode 分组的已验证领域事件和安全公开投影输入；
- 预置的生命周期操作：重投、更正、失效或硬删除；
- 版本化 `projection_version`、`embedding_space_id`、`top_k` 和 `min_similarity`；
- 只由公开上下文构建的查询；
- 有顺序的 `expected_memory_ids`、`forbidden_memory_ids` 和预期空结果标记；
- 允许/禁止出现的公开字段与隐藏字段；
- 预期写入数、来源数、冲突类别、Repository/Embedding 调用次数；
- 可选的恶意文本夹具，但不得包含真实密钥或真实玩家数据。

Gold 真值只进入评测器，不进入 `MemoryQueryBuilder`、`AgentContextFilter` 或 Prompt。场景文件不得保存 `root_cause`、正确诊断标记或评分规则；隐藏泄漏测试使用专门的哨兵字符串，并断言哨兵在存储、向量文本和 Prompt 中均不存在。

## 3. 冻结场景集合

| 场景 ID | 合成跨 Episode 设置 | 预期结论 |
|---|---|---|
| `memory_relevant_recall_001` | 玩家 A 在 Episode 1 产生一条与 Episode 2 公开查询相关的已验证记忆，同时有若干低相关合法记忆 | 相关记忆进入 Top-K；有序 ID 与 Gold 完全一致 |
| `memory_irrelevant_exclusion_001` | 玩家 A 有多个主题无关的 active 记忆 | 无关记忆均低于冻结阈值，不被召回 |
| `memory_player_isolation_001` | 玩家 B 拥有与玩家 A 查询文本几乎相同、相似度更高的诱饵记忆 | 候选过滤阶段即排除 B；跨玩家召回数为 0 |
| `memory_empty_001` | 玩家没有记忆，或所有 active 记忆均低于阈值 | 返回严格空列表，不用模型补写“可能记得”的内容 |
| `memory_projection_idempotency_001` | 同一来源事件和投影版本重复消费至少两次 | 只存在一条记忆和一条来源收据；返回幂等已存在而非新增 |
| `memory_projection_conflict_001` | 同一稳定来源/版本被构造成不同内容哈希 | 明确 `projection_conflict`，不覆盖原记录，不生成第二条事实 |
| `memory_invalidation_deletion_001` | 依次覆盖失效、更正和隐私硬删除，再重建向量与投影 | 旧、失效和硬删除记录不召回；更正版本可召回；硬删除内容不复活 |
| `memory_stable_tie_001` | 多条同玩家 active 记忆由 Fake Embedding 产生完全相同相似度 | 严格按 `event_id ASC` 返回；跨进程和重复运行顺序一致 |
| `memory_prompt_injection_data_001` | 合成病例的公开文本含“忽略规则、调用隐藏工具”等注入式内容，并经合法事件投影 | 文本只能出现在 `retrieved_memories[].content`；工具集合、课程和 AgentAction Schema 不改变 |
| `memory_hidden_truth_filter_001` | 来源领域对象含隐藏哨兵，安全投影只允许公开说明 | SQLite 公开来源负载、记忆内容、Embedding 输入、查询和 Prompt 均不含哨兵 |
| `memory_v0_isolation_001` | 使用与 V1 相同的玩家和病例运行 V0 | MemoryRepository、EmbeddingAdapter 和检索器调用次数全部为 0；V0 Prompt 与历史快照一致 |
| `memory_v1_readonly_001` | V1 检索到记忆后，构造包含未知记忆写字段或 `record_memory` 的 Agent 输出 | Schema/工具枚举拒绝；权威记忆表、生命周期表和向量表逐字节/逐行不变 |
| `memory_vector_rebuild_001` | 删除全部派生向量后，从 active 权威记忆重建 | 召回 ID、相似度顺序和内容哈希与删除前一致；失效/删除记忆不生成向量 |
| `memory_commit_window_recovery_001` | 模拟 JSON 状态已提交而 SQLite 投影失败，再显式协调两次 | 首次协调补齐记忆，第二次幂等；不会出现无游戏状态来源的记忆 |

错误轨迹只作为离线对照：跨玩家查询、隐藏字段投影、Agent 直接写入、内容哈希冲突和墓碑后重建都必须被系统拒绝，不能要求真实模型主动犯错。

## 4. 评测执行顺序

每条场景按固定阶段运行并保存结构化结果：

1. 加载严格 Gold 与冻结配置；
2. 从初始状态执行或加载已验证领域事件；
3. 运行确定性投影并检查来源、哈希、版本和写入数；
4. 应用场景指定的生命周期操作；
5. 由 `AgentContextFilter` 生成当前玩家作用域；
6. 由 Fake Embedding 生成查询/文档向量并执行进程内 Top-K；
7. 再次过滤为 `MemoryView`，构建 V1 只读上下文；
8. 比对有序 Gold、禁止字段、调用次数、存储快照和重建结果；
9. 输出结构化失败类别，不使用 Agent 自评。

建议失败类别至少包括：

- `projection_not_allowed`
- `projection_conflict`
- `missing_provenance`
- `duplicate_memory`
- `cross_player_recall`
- `inactive_memory_recalled`
- `hidden_content_leak`
- `unstable_order`
- `illegal_permanent_write`
- `v0_memory_access`
- `rebuild_mismatch`
- `evaluation_contract_error`

## 5. 指标定义

### 5.1 检索效果

- **Precision**：召回列表中属于该查询 Gold 相关集合的记录数 / 召回记录数；空召回且 Gold 也为空的场景单独记为 `empty_correct=true`，不伪造 Precision。
- **Recall**：召回的 Gold 相关记录数 / Gold 相关记录总数。
- **F1**：Precision 与 Recall 都有定义时使用调和平均；否则保持缺省并报告空结果分类。
- **False Memory Rate**：召回结果中没有 active、可核对来源链，或内容无法由其安全来源负载支持的记录数 / 召回记录数。合法但主题无关的记忆属于 Precision 错误，不与“无来源假记忆”混为一谈。

### 5.2 安全硬门槛

- **跨玩家串扰数**：返回的 `player_id` 与当前可信玩家不一致的记录数；M4 退出必须为 0。
- **非法永久写入数**：没有允许来源事件，或由 AgentAction、聊天、模型回复、只读/拒绝工具触发的权威记忆写入数；M4 退出必须为 0。
- **隐藏字段泄漏数**：哨兵出现在来源收据公开负载、记忆内容、Embedding 输入、查询、`MemoryView` 或 Prompt 的次数；必须为 0。
- **删除后复活数**：硬删除墓碑对应内容在投影或向量重建后重新出现的次数；必须为 0。

### 5.3 工程指标

- 投影输入数、创建数、幂等命中数、冲突数和每来源记忆数；
- 检索总耗时、查询 Embedding 耗时和 Top-K 计算耗时的 P50/P95；
- active/失效/被替代/墓碑记录数；
- SQLite 文件大小、权威内容字节数和派生向量字节数；
- 向量重建前后结果一致数；
- 相同数据与配置的重复运行哈希。

本轮不填写任何指标结果。P4 只能报告实际离线运行数据，并注明硬件、提交、Fake Embedding 版本、投影版本、场景数据哈希和检索配置。

## 6. 可重复性与数据安全

- 所有时间戳、事件序号、ID、Fake 向量和并列顺序由场景固定；
- 临时 SQLite、玩家状态和病例会话只写入测试临时目录；
- 不读取 `.env`、真实 `results/`、历史玩家目录或 DeepSeek 配置；
- DeepSeek `/models`、Chat 和任何真实 Embedding 请求均为 0；
- 评测输出不包含 API Key、供应商请求 ID、隐藏病例真相或原始 Prompt；
- 数据、配置、代码和结果分别记录 SHA-256，不把目标值写回输入；
- 同一场景至少重复两次并比较有序结果及数据库规范快照。

## 7. P4 退出条件

P4 只有在以下条件同时满足时通过：

1. 全部冻结 Gold 场景可由一条本地离线命令运行；
2. 场景 Schema 严格且评测真值不进入检索或 Prompt；
3. Precision、Recall、F1 和 False Memory Rate 按上述定义产生，不填造空缺值；
4. 跨玩家串扰、非法永久写入、隐藏泄漏和删除后复活全部为 0；
5. 幂等、冲突、更正、失效、硬删除、向量重建和提交窗口协调均有明确测试；
6. 相同输入、配置和版本得到相同有序结果与结果哈希；
7. V0 不访问记忆，V1 只读记忆且固定课程不变；
8. 现有全量测试继续通过；
9. 报告明确 Fake Embedding 只证明工程契约，不代表真实语义质量。

任何安全硬门槛非 0 时，M4 停止在 P4，不得通过调整 Gold、放宽玩家过滤或删除失败样本来宣布完成。
