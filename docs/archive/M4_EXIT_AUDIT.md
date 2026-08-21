# M4 工程里程碑退出审计

## 1. 审计身份与结论

- **审计日期**：2026-08-08
- **审计基线**：`48a1ffcf9542fbcc466405da6a1e11a74b40ef14`
- **最终 Gold 冻结基线**：`118b3b13f9558e5d8fbfb72180c807815772ad30`
- **审计方式**：仅使用确定性 Fake Embedding、Fake LLM、合成 Gold、临时 SQLite/JSON 和离线自动化测试
- **外部调用**：DeepSeek `/models` 0 次、Chat 0 次、真实 Embedding 0 次、费用 0 CNY
- **结论**：通过

> M4 工程里程碑完成：V1 已建立从已验证领域事件到可追溯 SQLite 权威记忆、可重建派生向量、基础余弦 Top-K、跨玩家及跨 Episode 权限过滤、只读 Agent 记忆上下文和确定性离线评测的完整闭环。14 条冻结合成 Gold 全部通过，跨玩家串扰、非法永久写入、隐藏泄漏和删除后复活均为 0。该结论只证明 Fake Embedding 下的离线工程契约与安全边界，不代表真实 Embedding 语义质量、真实模型使用记忆的效果、真实玩家收益或生产性能。

M4-P0 至 P4 的退出证据一致，未发现需要在审计中修复产品代码的缺口。M5 尚未开始。

## 2. Gold 冻结历史核对

仓库中存在两个相邻且提交说明相同的检查点，历史保持原样：

| 提交 | 实际内容 | 审计解释 |
|---|---|---|
| `82950266b7fb7dc12780b7e63cfff1f3e3cb7bea` | 仅把评测规划中的并列排序术语从错误的 `event_id ASC` 纠正为已实现的 `memory_id ASC`，1 个文档文件、1 增 1 删 | Gold 数据写入前的预运行契约文字修正；提交信息虽相同，但尚不包含场景、预期或冻结 Schema |
| `118b3b13f9558e5d8fbfb72180c807815772ad30` | 新增 14 条场景输入、Gold 预期、哈希清单、严格评测契约和契约测试，共 5 个文件 | 第一份内容完整且可由自动化校验的 Gold 检查点，因此是最终有效冻结基线 |

`8295026` 是 `118b3b1` 的直接历史祖先；两者反映一次先纠正文档契约、再写入完整冻结数据的提交顺序，不是删除、覆盖或重写历史。

从 `118b3b1` 到最终 P4 基线 `48a1ffc` 的核对结果：

- `memory_gold_inputs.json` 的 Git blob 始终为 `691502b8a012fdeebfa8830863bf656fa84896be`；14 条场景输入未修改；
- `memory_gold_expectations.json` 的 Git blob 始终为 `43b00530b00eeb89a945da776121b158e813ebf9`；Gold 预期未修改；
- `memory_gold_manifest.json` 的 Git blob 始终为 `844a5f94997fd20480c3bd0b5cf57e8e68fda848`；输入、预期和检索配置身份未修改；
- 输入 SHA-256 为 `6d1233c6392d9f89eccf9abbc7c937a82319bb29e2591327c5e55fc51612e483`，Gold SHA-256 为 `389b841f4f039c1fc076df7d9c206e6c040522bded3c471a8848ec5e8d732c49`，检索配置规范 SHA-256 为 `b0afa7f9726631d5a0d9f256c3b7ce3c70692c1302e71b8a5c59299daa284b6c`；
- 阈值配置仍为冻结的 `top_k` 1/20 与 `min_similarity` -1.0/1.0 组合，产品排序仍为 `similarity DESC, memory_id ASC`；
- P1–P3 的 `application`、`agents`、`domain`、`memory`、`storage` 和 `mcp_server` 产品目录在冻结后无差异；
- 冻结后只增加评测执行器、P4 测试、命令入口、结果记录，以及评测结果安全字段；
- 唯一确定性修复位于评测器：从临时 JSON 恢复严格状态类型后再规范排序集合。它没有修改 Gold、P1–P3 产品实现、产品 JSON 格式、阈值或排序规则。

因此没有发现根据运行结果修改 Gold、反向调整 P1–P3 产品实现或放宽安全门槛的行为。

## 3. P0～P4 分层退出审计

### 3.1 P0：V1 范围与单向写入边界

| 条件 | 证据与结论 |
|---|---|
| V1 只增加基础长期记忆并保持固定课程 | `HISTORICAL_AGENT_VARIANTS.md` 与配置边界固定 V1 为 Vector Top-K + Fixed Curriculum；通过 |
| 模型不能直接写永久记忆 | `AgentAction` 与九个 MCP 工具均无记忆写入口，写入只接受已验证来源；通过 |
| 多因素排序、自适应教学和 Reflection 不属于 M4 | 路线图、变体表和 ADR-034 一致保留在 V2/后续；通过 |

### 3.2 P1：投影、权威存储与生命周期

| 条件 | 证据与结论 |
|---|---|
| 投影来源允许列表 | 自动投影只接受成功调查、成功诊断提交和成功处置；未知事件默认拒绝；通过 |
| 禁止来源零写入 | 聊天、`respond`、规则拒绝、只读调用、模型输出、超时与日志不产生权威记忆；专项与 Gold 的非法永久写入数为 0；通过 |
| 来源链与公开哈希 | 每条权威记录携带玩家、会话、事件类型、序号、修订、投影版本/序号、固定原因、公开负载哈希和内容哈希；通过 |
| 隐藏字段不落库 | 正确性、数值评分、根因、未发现线索和隐藏门槛不进入收据、内容或哈希输入；隐藏泄漏数为 0；通过 |
| SQLite 权威语义 | Schema v1 的来源收据、权威记忆、生命周期审计和非内容墓碑支持幂等、冲突、更正、失效与应用级硬删除；通过 |
| 删除与重建 | 硬删除移除应用数据库中的内容和公开负载，只留非内容墓碑；投影重建不能复活；删除后复活数为 0；通过 |
| 两个提交故障窗口 | JSON 保存失败时 SQLite 写入为 0；JSON 已保存而投影失败时明确 `memory_projection_pending`，显式协调可补齐且重跑幂等；通过 |
| 玩家隔离 | Repository 操作要求精确玩家，玩家 A 不能写入或修改玩家 B；跨玩家串扰为 0；通过 |

应用级硬删除保证不延伸到外部备份、文件系统历史或取证级物理擦除。

### 3.3 P2：派生向量与基础 Top-K

| 条件 | 证据与结论 |
|---|---|
| Schema v1→v2 | 原子迁移保留既有数据、生命周期与墓碑，失败回滚，未来未知版本安全拒绝；通过 |
| Fake Embedding 身份 | `fake_sha256_token_buckets_v1`、64 维、空间 `fake_sha256_token_buckets_v1_d64`；固定规范化、分词、SHA-256 特征桶和 L2 归一化；通过 |
| 向量契约 | little-endian float32 BLOB，严格校验维度、长度、有限值、非零范数、空间和内容哈希；通过 |
| 排序前过滤 | 候选先按精确玩家、active 状态、允许类型和排除当前会话过滤，再检查空间/哈希并计算相似度；通过 |
| 单一排序因子 | V1 仅用余弦相似度，稳定顺序为 `similarity DESC, memory_id ASC`；importance、时间、关系和能力不参与；通过 |
| 索引完整性 | 缺失或过期索引明确报不完整，不伪装为空召回；通过 |
| 生命周期与重建 | 更正、失效和硬删除同步清理向量；删除派生向量后可由 active 权威记忆重建相同结果；通过 |

### 3.4 P3：只读 Agent 记忆上下文

| 条件 | 证据与结论 |
|---|---|
| 可信作用域 | `MemoryScope` 只能由匹配的 `PlayerState` 与当前 `CaseSessionState` 生成，字段为可信玩家、允许类型和排除会话；通过 |
| 最小公开视图 | `MemoryView` 只有 `memory_id`、`memory_type`、`content`、`occurred_at`；不含玩家、分数、哈希、来源链、importance 或生命周期；通过 |
| 双重隔离 | 当前 Episode、其他玩家和不允许类型在 Top-K 前排除，检索后再次校验；通过 |
| 查询公开性 | `memory_query_v1` 只使用当前用户消息、病例公开标题/简介、已发现公开线索和固定课程；通过 |
| 上下文状态 | `ready` 与 `empty` 可继续；`unavailable` 在 LLM 调用前返回 `memory_context_unavailable`，不发送部分结果；通过 |
| Prompt 边界 | 记忆仅作为用户 JSON 的 `retrieved_memories` 历史数据，不改变 system message、工具、课程或动作 Schema；通过 |
| 公共行为不变 | `AgentAction`、九个 MCP 工具和固定课程不变；V0 Prompt、输入 Schema 与执行路径不变；通过 |
| V0 零记忆访问 | 完整 V0 Episode 对 Repository、Embedding、Retriever、QueryBuilder 和 MemoryScope 调用均为 0；通过 |

提示注入测试只证明程序化过滤、JSON 数据边界和消息结构没有被改变；没有真实模型调用，不能证明模型会忽略记忆中的恶意文本。

### 3.5 P4：冻结 Gold、指标与可重复性

| 条件 | 证据与结论 |
|---|---|
| 14 条冻结场景实际执行 | 单命令在两个独立临时根目录运行 14/14 通过；通过 |
| 输入与真值隔离 | 输入、Gold 预期和 manifest 分文件，严格 Schema 禁止未知字段；Gold 不进入 QueryBuilder、过滤器或 Prompt；通过 |
| 指标与分母 | macro P/R/F1 只平均 11 条有定义场景；micro TP/FP/FN 为 13/0/0；3 条真空场景的无分母指标保持缺省；通过 |
| False Memory Rate | 分子为无 active 可核对来源或内容无来源支持的召回，分母为召回总数；本次为 `0/13 = 0.0`；通过 |
| 可重复性 | 两次独立运行哈希均为 `01ecf59b42e37dc2c898fd893fc0234c3d9ff18701c22f77a31bed06511cb44e`；通过 |
| 快照语义 | 比较规范化、排序后的 SQLite/JSON 逻辑状态，不比较 SQLite 原始文件字节；通过 |
| 评测器修复边界 | 集合排序缺陷只在评测代码中修复，产品与 Gold 未改；通过 |
| 安全硬门槛 | 跨玩家串扰、非法永久写入、隐藏泄漏、删除后复活均为 0；扩展计数也全部为 0；通过 |

## 4. 14 条 Gold 场景复核

以下场景在本次审计中全部实际执行并通过：

1. `memory_relevant_recall_001`：相关历史正确召回；
2. `memory_irrelevant_exclusion_001`：无关历史按阈值排除；
3. `memory_player_isolation_001`：其他玩家高相似诱饵在候选阶段排除；
4. `memory_empty_001`：无合法历史时返回严格空结果；
5. `memory_projection_idempotency_001`：重复投影不产生重复事实；
6. `memory_projection_conflict_001`：同稳定键不同内容明确冲突且不覆盖；
7. `memory_invalidation_deletion_001`：更正、失效、硬删除和墓碑语义成立；
8. `memory_stable_tie_001`：同分按 `memory_id ASC` 稳定排序；
9. `memory_prompt_injection_data_001`：注入文本只作为结构化数据；
10. `memory_hidden_truth_filter_001`：隐藏哨兵不进入存储、向量文本、查询或 Prompt；
11. `memory_v0_isolation_001`：V0 对记忆组件访问为 0；
12. `memory_v1_readonly_001`：Agent 写记忆入口不存在且表状态不变；
13. `memory_vector_rebuild_001`：派生向量删除与重建前后结果一致；
14. `memory_commit_window_recovery_001`：提交故障窗口可显式协调，第二次运行幂等。

汇总结果：macro Precision / Recall / F1 为 `1.0 / 1.0 / 1.0`（各 11 条有定义场景）；micro Precision / Recall / F1 为 `1.0 / 1.0 / 1.0`（TP/FP/FN `13/0/0`）；False Memory Rate 为 `0/13`；3 条空结果场景正确。`1.0` 是冻结合成 Gold 的工程符合率，不是产品准确率、真实语义效果或正式成功率。

安全硬门槛均为 0：跨玩家串扰、非法永久写入、隐藏字段泄漏、删除后复活。扩展检查中的 V0 记忆访问、inactive 召回、来源缺失、当前 Episode 召回和 Prompt 边界违规也均为 0。

## 5. 重新验证证据

| 验证项 | 结果 |
|---|---|
| 14 条 Gold 单命令评测 | 14/14 通过；双运行哈希一致 |
| M4-P1 专项 | 44 passed |
| M4-P2 专项 | 26 passed |
| M4-P3 专项 | 20 passed |
| M4-P4 专项 | 15 passed |
| V0 Agent/Prompt Gold | 16 passed |
| M3 MCP P0/P1 | 22 passed |
| 全量测试 | 287 passed |
| P0 Fake LLM | 3 场景、6 条参考/错误轨迹符合预期 |
| 无 LLM Demo | `completed / resolved / 100` |
| `git diff --check` | 通过 |
| 敏感信息与运行文件跟踪检查 | `.env`、`results/`、数据库和运行状态未被跟踪；未发现密钥 |

## 6. 已验证能力、未验证能力与已知限制

已验证的是 Fake Embedding 下的离线工程闭环：确定性公开事件投影、来源审计、SQLite 权威存储、生命周期与协调恢复、可重建派生向量、玩家/会话/类型过滤、余弦 Top-K、只读 V1 Agent 上下文、V0 隔离和可重复 Gold 评测。

以下限制必须保留：

- Fake Embedding 不具备可宣称的真实语义效果；冻结 Gold 的 `1.0` 不是产品准确率；
- 未运行真实 V1 DoctorAgent Pilot，也未验证真实模型能否正确使用记忆；
- 提示注入测试只证明程序化边界，未验证真实模型抵抗记忆中提示注入的行为；
- SQLite 与 JSON 不支持并发多进程事务；
- 未验证真实数据规模、生产延迟、备份恢复或长期运行；
- 未实现自适应教学、Reflection、关系/能力成长、界面、多 Agent 或新玩法；
- DeepSeek 当前没有用于本项目的已验证 Embedding 端点；
- 未来真实 Embedding 需要新的供应商或本地模型决策、可发送数据授权、密钥与独立预算。

真实 Embedding 不构成本次离线 M4 工程退出阻塞，但在任何产品体验或真实 V1 效果结论之前，必须作为独立验证门槛完成。M5 尚未开始。
