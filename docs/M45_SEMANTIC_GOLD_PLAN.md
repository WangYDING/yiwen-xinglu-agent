# M4.5 真实语义 Gold 规划

> **历史与当前数据角色**：本文件原 15 条语义 Gold 已经完成真实运行并用于 P2b 根因分析，因此只能作为 `observed_development_diagnostic_set`，不能再次证明新方案通过。当前未见准入数据是 P2c 冻结的 36 条 holdout，身份与边界见 `docs/M45_P2C_SEMANTIC_HOLDOUT_FREEZE.md`；旧输入和失败记录保持不变。

## 1. 定位与冻结边界

本 Gold 专供 M4.5 真实 Embedding 与真实 V1 Pilot，不修改、不替代 M4 已冻结的 14 条 Fake Embedding 工程 Gold。

P0 只冻结设计，不创建场景数据或预填结果。P2 v1 已在提交 `e81331255945e3baba34a0525b3c2f338321d841` 冻结下列历史文件；第一次正式本地运行随后因评测器标签复用误触安全停止，未产生可用正式指标或重复性结果，详见 `M45_P2_SEMANTIC_PILOT_REPORT.md`：

- `m45_semantic_gold_inputs.json`：模型可见的合成公开输入；
- `m45_semantic_gold_expectations.json`：历史 v1 仅评测器可见的相关/歧义禁止集合与成功条件；
- `m45_semantic_gold_manifest.json`：场景版本、文件 SHA-256、Adapter 身份、Top-K、阈值策略和指标版本；
- 严格 Pydantic Schema 与契约测试，所有未知字段拒绝；
- 人工评审记录，确认没有真实身份、聊天原文、隐藏病例真相、评分、关系值或密钥。

P2a 保留所有 v1 文件与停止证据，复用完全相同的输入文件，并新增 `m45_semantic_gold_expectations_v2.json`、`m45_semantic_gold_manifest_v2.json`。v2 删除歧义字段 `forbidden_candidate_ids`，将每个候选完整划分为相关项、合法语义负例或带精确产品状态原因的安全排除项。详细迁移和 SHA 见 `M45_P2A_SEMANTIC_GOLD_V2_FREEZE.md`。

P2 v2 已在执行提交 `cad07ff42a5c665d49cdb25c2379f2026558554a` 上完成两次正式本地 BGE-M3 运行。两次排序、指标和向量完全一致，所有安全计数为 0；但 test Recall@3 为 0.8889、False Memory Rate 为 5/13，未达到本文件预注册的 P3 准入线。详见 `M45_P2_V2_SEMANTIC_PILOT_RESULT_20260810.md`。该负结果不修改本文件的 Gold、阈值或准入线。

冻结提交必须早于任何新的真实向量生成。运行后不得根据结果改写输入、Gold、阈值、排序或产品实现；确需修订时保留原提交和原结果，升级 Gold 版本并重新取得运行授权。

## 2. 数据规模与身份

- 场景数：15；
- 每场景：1 条查询、4 条候选记忆；
- 唯一文本总量：15 条查询 + 60 条记忆 = 75 条；
- 保守输入总上限：16,000 Token；
- 内容：全部人工编写、合成、公开、架空；
- 每条记忆仍由确定性 P1 投影或生命周期操作产生，不直接写入 Repository；
- Fake 与真实 Adapter 使用不同 `embedding_space_id`，同一 `memory_id` 可拥有不同空间的派生向量，但不得覆盖或混用；
- 正式 Pilot 每个 Adapter 只运行一次；本地重复性核对可在同一次授权窗口内按冻结方案执行第二次纯本地向量生成，不改变场景或参数。

## 3. 15 条场景设计

| 场景 ID | 目的 | 关键 Gold |
|---|---|---|
| `semantic_zh_synonym_001` | 中文同义改写 | 无完全相同关键词时仍把同义历史排在 Top-K |
| `semantic_action_paraphrase_001` | 不同措辞描述同一历史行为 | 召回语义等价的玩家行动，不依赖固定句式 |
| `semantic_lexical_distractor_001` | 相似词但含义不同 | 高字面重合的干扰记忆不得压过真正相关项 |
| `semantic_wrong_diagnosis_provenance_001` | 错误诊断的来源语义 | 可召回“玩家曾提交某假设”的历史，但公开内容不得把它写成世界事实或正确结论 |
| `semantic_current_episode_exclusion_001` | 当前 Episode 排除 | 当前会话高相似记忆在余弦排序前候选数为 0 |
| `semantic_player_isolation_001` | 玩家隔离 | 其他玩家最高相似诱饵在候选阶段为 0 |
| `semantic_empty_001` | 空结果 | 索引完整但没有合法相关历史时返回 empty，不伪装 unavailable |
| `semantic_correction_001` | 更正 | 旧记忆不召回，替代记忆可按语义召回 |
| `semantic_invalidation_001` | 失效 | invalidated 记忆不索引、不召回 |
| `semantic_hard_delete_001` | 删除与墓碑 | 权威内容和向量删除后不召回，重建不复活 |
| `semantic_prompt_injection_data_001` | 提示注入文本 | 注入式文本只作为 MemoryView JSON 字符串；不改变作用域、工具、课程或 Schema |
| `semantic_mixed_language_entity_001` | 中英文混合实体 | 例如架空药材名与英文别名能按语义关联，不靠真实医疗知识 |
| `semantic_short_text_001` | 极短公开记忆 | 短文本非空且可稳定检索，不因长度产生异常 |
| `semantic_long_text_001` | 较长公开记忆 | 接近项目 4096 字符上限时仍遵守截断/拒绝契约和批次稳定性 |
| `semantic_no_lexical_overlap_001` | 无字面重合的语义关系 | 查询和相关记忆不共享关键词，真实模型仍应给出合理排名 |

所有场景都要有至少一个明确错误候选。合法、active、同玩家、历史 Episode 的错误诱饵属于 semantic negative，只影响语义指标；当前 Episode、其他玩家、inactive 和删除项属于排序前安全排除。Gold 声明必须与输入及实际 Repository 生命周期一致，运行时安全计数仍以实际产品状态为准，不能仅凭 Gold 标签推断。

## 4. 输入与 Gold 隔离

Adapter、Retriever、`AgentContextFilter`、QueryBuilder 和 Prompt 只能看到场景输入。Gold 预期只允许评测器在获得实际结果后读取。

输入侧允许：

- 合成 `player_id` / `session_id` 供本地确定性过滤使用；
- 当前公开病例标题、简介、已发现线索和固定课程；
- 合成公开 Memory 内容及其领域事件来源；
- 当前合成用户消息。

输入侧禁止：

- `expected_memory_ids`、相关性标签、预期顺序、阈值通过标记；
- root cause、正确诊断/处置、正确性、评分或隐藏门槛；
- 其他玩家内容进入当前玩家的 QueryBuilder/Prompt；
- 用 Gold 标签修改模型查询、向量或候选集合。

错误诊断场景的 Memory 内容必须使用行为表述，例如“玩家曾提交过公开假设 X，并引用了公开证据 Y”；不得写成“X 是病因”或包含正确性标记。

## 5. 检索配置与阈值冻结

真实模型运行前冻结两个互补视图：

1. **排序视图**：`top_k=3`、`min_similarity=-1.0`，用于 Recall@1、Recall@3、MRR、Precision/Recall/F1 和 Fake/真实排序差异；
2. **空结果视图**：使用预注册的 `min_similarity`，用于 empty/abstention 正确率。阈值只能由冻结的 calibration 子集按确定性规则选择，再一次性应用到 test 子集；不能查看 test Gold 后调阈值。

在 Gold manifest 中提前固定：

- 哪些场景属于 calibration，哪些属于 test；
- 阈值候选网格；
- 选择规则与并列处理；
- `similarity DESC, memory_id ASC` 的产品排序；
- Top-K、查询模板、模型空间、维度和指标版本。

推荐预注册阈值网格为 `0.20, 0.25, ..., 0.80`；在 calibration 上先最大化空结果正确率，再最大化 macro F1，仍并列时选更高阈值。该程序必须在真实运行前实现并测试，运行时不能人工挑选。M4 的原阈值、排序和 14 条 Gold 不受影响。

## 6. 指标与建议准入线

P2 必须报告原始计数和分母，不只报告小数：

- Recall@1、Recall@3；
- MRR；
- macro/micro Precision、Recall、F1；
- 空结果正确数/总数；
- False Memory Rate 的分子/分母；
- Fake 与真实的 Top-K overlap、发生排序变化的场景数和相关项平均名次变化；
- 冷启动、热运行和批次延迟；
- 请求/批次数、Token 或计费单位、人民币费用；
- 跨玩家串扰、当前 Episode 召回、hidden 泄漏、inactive 召回和删除复活。

建议在 P2 数据冻结提交中采用以下准入线；它们是进入 P3 的研究门槛，不是产品准确率：

- test `Recall@3 >= 0.90`；
- test `MRR >= 0.75`；
- test macro F1 `>= 0.75`；
- 空结果正确率 `= 1.0`；
- False Memory Rate `= 0`；
- 跨玩家串扰、当前 Episode 召回、隐藏泄漏、inactive 召回、删除复活均 `= 0`；
- 两次本地运行的有序结果和指标完全一致，向量差异不超过预先冻结容差。

如果场景划分使分母无法表达上述阈值，必须在任何真实运行前修订规划版本并重新冻结，不能运行后改分母。空集合指标继续保持缺省，不能用 0 或 1 伪填。

## 7. Fake 与真实空间比较

Fake 只作为工程对照，不作为语义老师：

- 先在新语义 Gold 上用冻结 Fake Adapter 得到对照排序；
- 再在独立真实空间运行相同输入；
- 比较有序 Top-K、相关项名次和 empty 判断；
- 不能因为真实结果与 Fake 不同就判错，最终真值来自人工 Gold；
- 不能把真实向量写入 `fake_sha256_token_buckets_v1_d64`，也不能把 Fake 向量写入真实空间；
- Adapter 失败时不混合两个空间补齐缺失向量。

## 8. 安全场景的可证明边界

P2 可以证明：候选过滤、生命周期清理、玩家/会话隔离、内容白名单、派生空间和检索顺序在真实向量下仍成立。

P2 不能证明：真实 DoctorAgent 会正确解释检索结果、忽略注入文本或从记忆中获得教学收益。这些只在 P3 的真实 V1 Agent 行为探针中验证，且单次小样本仍不能形成正式成功率。

## 9. 结果保存与重复性

- 原始向量、供应商响应和请求 ID 放入 Git 忽略目录；
- 仓库只保存场景/Gold/manifest SHA、模型 full revision、逐文件 SHA、依赖锁、空间 ID、脱敏有序结果、指标和原始结果 SHA；
- 本地模型要求 `local_files_only=True`，正式运行时禁用下载；
- API 模型若不提供不可变 snapshot 或 fingerprint，必须记录为供应商漂移风险，不能声称跨时间可复现；
- SQLite 原始文件字节不作为稳定证据，继续比较规范逻辑快照；
- 任一正式失败保留，不自动重跑或覆盖。

## 10. P2 停止条件

出现以下任一项，保存现有检查点并停止：

- Gold/manifest SHA 与冻结提交不一致；
- 模型 revision、文件 SHA、模型名或维度漂移；
- 跨玩家、当前 Episode、inactive、失效或已删除内容实际进入候选/结果；合法 semantic negative 进入排序不属于安全停止；
- 输入含隐藏哨兵或禁止发送字段；
- 索引缺失/过期却被报告为空历史；
- 返回数量/顺序错误、NaN、无穷、零范数或维度不符；
- 本地 OOM/超时，或 API 预算拒绝、用量缺失、费用无法核对；
- 原始结果无法安全写入忽略目录；
- 程序尝试自动换模型、调阈值、重跑或混合 embedding space。
