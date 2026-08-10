# M4.5 下一轮未见语义 Holdout 验证方案

## 1. 数据角色冻结

- 原 15 条 v2 场景永久转为 `observed_development_diagnostic_set`；
- 可以用它们验证代码没有退化并生成开发假设，但不得再次充当独立 test；
- 下一轮使用全新 `m45_semantic_holdout_v1`，在任何新 BGE 推理前提交输入、Gold、manifest、配置和 SHA；
- 新 holdout 失败后同样转为已观察数据，不允许改标签后重跑并继续称为未见 test。

## 2. 固定规模与划分

建议建立 36 条新场景，每条 4 个候选：

| 划分 | 场景数 | 有相关答案 | 空结果 | 用途 |
|---|---:|---:|---:|---|
| calibration | 12 | 8 | 4 | 只选择预注册阈值、分差和最大返回数 |
| final test | 24 | 20 | 4 | 只做一次正式质量判定；第二次仅核对重复性 |
| 合计 | 36 | 28 | 8 | 144 个候选，36 条查询 |

相关场景的主题构成为：更正替代 4、极短文本 4、否定/反义 4、高字面诱饵 4、中英混合实体 4、较长文本 2、多相关项 3、Prompt 注入文本 3，共 28 条。每类至少 1 条进入 calibration，其余进入 final test。8 条空结果在 calibration/test 各 4 条。

安全状态作为正交覆盖叠加到场景中：至少各 4 条包含跨玩家、当前 Episode、superseded、invalidated、hard-deleted 候选。所有安全项仍必须在余弦排序、Top-K、阈值和分差计算前过滤。

## 3. Gold 契约

每个候选继续且只能属于：

- `relevant_candidate_ids`；
- `semantic_negative_candidate_ids`；
- `safety_excluded_candidates`，并带精确原因。

Gold 必须覆盖：

- 同义和无字面重合；
- 更正后的当前有效事实与被替代旧事实；
- 极短记录与模板化负例；
- 否定、反义和行为方向相反；
- 高字面重合诱饵；
- 中英混合复合实体与只匹配局部实体的诱饵；
- 长文本和 512 Token 截断边界；
- 空结果；
- 一个查询对应多个相关历史；
- 作为普通数据的 Prompt 注入文本；
- 跨玩家、当前 Episode 和完整生命周期过滤。

错误诊断仍只能写为“玩家曾提交某公开假设”，不能写成世界事实。输入不得包含真实玩家、聊天原文、隐藏病例真相、评分、关系值、密钥或 Gold 标签。

## 4. 运行前冻结身份

建议新增并在任何新向量生成前提交：

- `data/evaluation/m45_semantic_holdout_inputs_v1.json`
- `data/evaluation/m45_semantic_holdout_expectations_v1.json`
- `data/evaluation/m45_semantic_holdout_manifest_v1.json`
- 严格 Pydantic 契约和人工边界审查记录
- `retrieval_query_v2` 身份与 SHA
- `embedding_document_v2` 身份与 SHA
- 新 `embedding_space_id`
- 模型 revision/manifest/依赖锁
- calibration/test 场景 ID
- 阈值、分差、最大返回数候选网格和确定性选择顺序
- 指标版本、重复性容差和停止条件

Gold 预期只能进入评测器。Adapter、QueryBuilder、文档派生器、Retriever、AgentContextFilter 和 Prompt 均不得读取相关性标签。

## 5. 参数选择隔离

1. 在创建任何新向量前冻结完整数据和参数候选网格；
2. 先运行 12 条 calibration；
3. 按冻结规则选择绝对阈值、最大返回数和相对分差；
4. 选择完成后锁定配置，评测器才允许解锁 24 条 final test；
5. final test 结果不得反向修改文本表示、网格、选择规则或 Gold；
6. 第二次 final test 只验证向量、排序和指标重复性，不用于择优；
7. 任一失败都如实保存，不自动运行第三次。

当前 P2b 观察到的 0.65、0.01 和 0.02 只能进入候选网格讨论，不能被直接指定为新策略参数。

## 6. 新指标与准入线

历史报告继续保留名称 `False Memory Rate = 5/13`，不得重命名或覆盖。新 holdout 对合法但无关召回使用：

`irrelevant_retrieval_rate = 返回的 semantic negative 数 / 返回的全部合法记录数`

建议 final test 准入线：

| 指标 | 门槛 | 分母与产品风险依据 |
|---|---:|---|
| Recall@1 | ≥ 0.80 | 至少 20 个相关 test 场景；控制最小上下文中首条历史错误 |
| Recall@3 | ≥ 0.90 | 至少 20 个相关 test 场景；漏掉超过约 1/10 的相关历史会削弱长期记忆可用性 |
| MRR | ≥ 0.85 | 相关历史应靠前，避免把 Agent 上下文预算消耗在负例上 |
| macro F1 | ≥ 0.80 | 逐场景等权，防止大类掩盖困难切片 |
| micro F1 | ≥ 0.80 | 按全部 TP/FP/FN 核对总体返回质量 |
| irrelevant retrieval rate | ≤ 0.10 | 分母为全部返回的合法记录；至多约每 10 条出现 1 条普通无关历史 |
| empty accuracy | = 1.0 | test 4 条空结果必须全部为空，避免凭空提供历史 |
| correction 与否定切片 FN | = 0 | 被更正事实或相反行为误召回会直接误导 Agent，属于高风险切片 |
| 安全泄漏计数 | 全部 = 0 | 跨玩家、当前 Episode、inactive、删除复活、隐藏泄漏不可容忍 |
| 两次重复性 | 排序/指标一致，向量差 ≤ 1e-6 | 第二次只核对确定性，不能择优 |

这些门槛依据上下文污染、错误历史和权限风险定义，不是为了让当前 `5/13` 恰好通过。所有指标必须同时报告原始分子、分母和缺省值；合成结果仍不得称为产品准确率。

## 7. 停止条件

出现以下任一情况立即停止：

- 数据、Gold、manifest、配置、模型或依赖 SHA 漂移；
- final test 在参数锁定前被读取或计算；
- 使用已观察 15 条作为新 test；
- 跨玩家、当前 Episode、inactive 或硬删除内容进入排序候选；
- 隐藏内容进入查询、派生文档或结果；
- 新派生文本修改权威记忆；
- Embedding 空间混用、索引不完整伪装 empty；
- 网络尝试、CPU 回退、非有限/零范数/维度异常；
- 根据 final test 调参、自动重跑或创建第三次运行。

## 8. 下一阶段预计修改文件

获得实施授权后，最小预期范围为：

- `src/xuanyi_npc/application/memory_context.py`：新增独立 `retrieval_query_v2`，V1 Prompt 的完整安全上下文保持不变；
- `src/xuanyi_npc/memory/embedding_text.py`：新增版本化 `embedding_document_v2` 派生器；
- `src/xuanyi_npc/application/memory_retrieval.py`：索引时注入派生文本构造器，权限/生命周期过滤顺序不变；
- `src/xuanyi_npc/memory/embeddings.py`：冻结查询/文档文本版本和新的空间身份；
- `src/xuanyi_npc/storage/sqlite_memory.py`：如需审计派生文本哈希，进行最小 Schema 迁移；权威内容哈希语义不变；
- `src/xuanyi_npc/evaluation/semantic_memory_contracts.py` 与新的 holdout runner：严格数据、参数锁定和 final-test 解锁契约；
- `data/evaluation/m45_semantic_holdout_*_v1.json`：全新输入、Gold 和 manifest；
- 对应 P1/P2/P3/V0/MCP 回归测试与新 holdout 契约测试。

不得新增永久记忆写工具、改变 `AgentAction`、扩展 MCP、引入向量数据库、自适应课程或 Reflection。

## 9. 网络、模型和费用

推荐的 A/B/C 路线继续使用现有本地 BGE-M3，不需要新增模型下载、外部 API、账号或费用。实施阶段需要重新生成新空间的派生向量，但必须获得单独本地运行授权。

只有选择 D 的额外 reranker 时，才可能需要新依赖、模型下载、许可证审查、磁盘和显存预算；这些必须在独立 P0 调查后由用户授权。本规划不下载模型、不访问网络，费用为 0 CNY。
