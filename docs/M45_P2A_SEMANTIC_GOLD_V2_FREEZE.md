# M4.5-P2a 语义 Gold v2 冻结记录

## 1. 历史与当前身份

- v1 Gold 冻结提交：`e81331255945e3baba34a0525b3c2f338321d841`
- v1 停止记录提交：`41a5bdf254d964b35993809a86a01b75141d1381`
- v1 失败检查点 SHA-256：`6B7E35CD8A8F712061FA0576E7B6352F061C1494E8455008EB75893B6C7C1BA5`
- v1 输入 SHA-256（v2 继续复用）：`ca55bebdafaa59c06eab156c44316c2f862264e9082c71b768ab54d867674f3d`
- v1 expectations SHA-256：`ee68a03de2e4a3adbd6fd81d9f751a94f1f504e37cf7e33573a7fcb0ae79ef80`
- v1 manifest SHA-256：`9c17fbcc4f5f867ddcf40cf4ef056ab5299d65173595910d3312c97b4cccb9ef`
- v2 expectations SHA-256：`2ce0c4ab316243b06be7a80a5b3617f26b06545a736202bd27ebf24490b9d8d0`
- v2 manifest SHA-256：`4479ca16df1457782fd94af919da1942ca87619d080a2f0e339779e83447aa61`
- 不变配置 SHA-256：`1c302cb2155260812278a70defae23d869aee094b1a28523210fb826a332fda8`

v1 的输入、expectations、manifest、冻结提交、停止报告和忽略目录失败检查点都保留不变。v2 新增 `m45_semantic_gold_expectations_v2.json` 与 `m45_semantic_gold_manifest_v2.json`，不覆盖历史文件。本轮没有读取失败检查点中的排序、向量、相似度、阈值或指标，也没有加载 BGE。

## 2. v1 → v2 逐字段迁移

| v1 字段 | v2 字段 | 语义 |
|---|---|---|
| `relevant_candidate_ids` | `relevant_candidate_ids` | 保持不变；合法且与查询语义相关 |
| 无 | `semantic_negative_candidate_ids` | 新增；合法、active、同玩家、历史 Episode，但语义不相关或为错误诱饵 |
| `forbidden_candidate_ids` | 删除 | v1 混合了语义错误与安全排除，不能继续使用 |
| 无 | `safety_excluded_candidates[]` | 新增；每项含候选 ID 与严格的产品状态原因 |
| `expected_empty` | `expected_empty` | 保持不变，由相关集合是否为空决定 |

安全原因只允许 `cross_player`、`current_episode`、`superseded`、`invalidated` 和 `hard_deleted`。冻结输入中的更正候选 ID 表示 active 替代记忆，因此仍是相关候选；被替代的 superseded 权威记录继续由实际 SQLite 生命周期审计，但没有被伪造为另一条冻结候选。

## 3. v2 完整分区

15 个场景的 60 个候选均已验证：每场景 4 个候选全部且只属于 relevant、semantic negative、safety excluded 三类之一，三类两两不交叠。合法语义候选均为当前玩家、历史 Episode、active 且可索引；安全排除原因与输入中的玩家、会话和生命周期操作逐项一致。

`semantic_lexical_distractor_001` 的高字面重合候选 `cand_lexical_distractor_2` 是合法 semantic negative。它进入 Top-3 时计普通 FP，降低 Precision/F1；如果排在相关项之前，还会影响 MRR，但安全计数保持 0。

## 4. 运行时安全与语义指标分离

评测器按实际 Repository/检索状态核对玩家、来源会话、权威状态和墓碑：

- 其他玩家或当前 Episode 实际进入候选/结果，分别增加对应安全计数；
- superseded/invalidated 实际进入候选/结果，增加 inactive 计数；
- 已硬删除内容实际复活，增加 deletion resurrection；
- semantic negative 无论相似度多高都不会被映射为安全错误；
- safety excluded 正常在排序前过滤时，不进入语义 TP/FP/FN 分母；若实际越界则触发安全停止。

语义指标只在合法排名候选中计算：相关返回为 TP，semantic negative 返回为 FP，相关未返回为 FN。空结果场景允许存在合法 semantic negatives，只有它们都低于冻结阈值时才判定 empty 正确。

## 5. 冻结边界与下一步

本次只纠正评测契约与评测器。15 条查询、60 条候选文本、calibration/test 划分、BGE revision、空间、FP32/CUDA/1024 维、Top-K、阈值网格、选择规则、排序和 P1–P4 产品实现均未调整。没有产生或读取任何 BGE 指标。

M4.5-P2 仍未完成。任何新的正式 BGE 运行和第二次重复性核对都需要基于本 v2 冻结检查点获得新的单独授权；M4.5-P3 与 M5 尚未开始。
