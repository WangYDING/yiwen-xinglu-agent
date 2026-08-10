# M4.5-P2c：V2 检索表示与新语义 Holdout 冻结

## 阶段结论

本检查点只完成离线产品契约、数据冻结和 Mock/固定排名验证。没有加载 BGE、生成真实向量、读取 API Key、访问网络或运行语义质量评测。旧 15 条场景继续是 `observed_development_diagnostic_set`，其语义质量未通过结论不变，也没有参与新参数选择。

## V1 与 V2 表示差异

| 边界 | v1 | v2 |
|---|---|---|
| 查询 | 用户消息、病例标题/简介、已发现线索、固定课程组成 JSON | 只有用户明确检索意图和已发现公开线索；无标题、简介、课程、JSON 字段名或 Prompt 指令 |
| 记忆文档 | 直接使用 SQLite 权威记忆原文 | 从匹配的公开来源收据派生；调查/更正不加固定前缀，诊断保留“玩家曾提交假设”，处置保留公开结果 |
| 权威数据 | 作为事实来源 | 完全不变；V2 文本与向量仍是可删除、可重建派生数据 |
| 空间 | `bge_m3_142964af7e05_dense_fp32_d1024_cuda_l512_v1` | `bge_m3_142964af_dense_fp32_d1024_cuda_l512_rq2_doc2_v1` |
| 索引状态 | 无记忆、完整、不完整 | `empty`、`ready`、`incomplete`、`stale_representation`；旧空间不得伪装为空结果 |

规范化固定为 NFKC、Unicode casefold、空白折叠；查询最大 2048 Unicode 码点，文档最大 4096 Unicode 码点，超长时取固定前缀。模型的 `max_length=512 Token` 是独立边界，正式运行必须另行记录 tokenizer 截断，不能把 Token 写成字符。

## 保守策略预注册

参数网格是 `min_similarity ∈ {0.45, 0.55, 0.65, 0.75}`、`max_results ∈ {1,2,3}`、`minimum_margin ∈ {0.00,0.03,0.06}`，共 36 组。只允许使用按固定顺序排列的 12 条 calibration 结果选择：安全计数为 0、empty accuracy 为 1、最大 macro F1、再最大 Recall@3/MRR、再最小 irrelevant retrieval rate；仍并列时依次选择更高绝对阈值、更小返回数和更大分差。没有参数满足硬门槛时返回 `fail_calibration`。24 条 final test 在参数锁定前不得进入选择器。

## 新 Holdout 身份

| 文件 | SHA-256 |
|---|---|
| `m45_semantic_holdout_inputs_v1.json` | `D5069516A76A95918CD12C13E193E256116A219788C5B2965E9F61EFCEBD0116` |
| `m45_semantic_holdout_expectations_v1.json` | `3DE2EDBBF949B9E3B887982F12605DFEEC772EC98AEE56D79A402AAD46D55D5D` |
| `m45_semantic_holdout_config_v1.json` | `F083F55E3DCA9A71F4B7E44423DD19E66645ABF437D34327AB893CB037DA2845` |
| `m45_semantic_holdout_manifest_v1.json` | `703593E8C18BD56FE8FCF8205CF38CE6CD77F9823522D835BD56FD6CBBA0AD47` |

- 36 条查询、每条 4 个原始候选，共 144 个唯一候选；
- calibration 12 条：8 条有相关答案、4 条正确空结果；
- final test 24 条：20 条有相关答案、4 条正确空结果；
- 覆盖更正、极短、否定/反义、高字面诱饵、中文同义、中英混合、长文本/截断、多相关项、空结果，以及注入数据、无字面重合、行为改写、错误诊断来源和五类安全排除；
- 新查询、候选公开行动句子和候选组合不复用旧 15 条；全部是公开、合成、架空文本。

Gold 只存在于 expectations 与评测边界，产品的 Adapter、Retriever、QueryBuilder、`AgentContextFilter` 和 Prompt 不导入相关/负例标签。

## 指标、准入与停止边界

排序报告 Recall@1、Recall@3、MRR；返回报告 macro/micro P/R/F1、`irrelevant_retrieval_rate = FP / (TP + FP)`、empty accuracy 和每场景返回数量。分母为 0 时保持 `undefined`。准入线固定为 Recall@1 ≥ 0.80、Recall@3 ≥ 0.90、MRR ≥ 0.85、macro/micro F1 ≥ 0.80、irrelevant retrieval rate ≤ 0.10、empty accuracy = 1、纠正与否定切片 FN = 0、安全计数全部为 0、两次排名/指标一致且向量最大差 ≤ `1e-6`。这些是合成语义 Pilot 门槛，不是游戏产品准确率或玩家收益。

下一次授权只允许一组两次本地 BGE 正式运行。通过后才进入 M4.5-P3；未通过则保留真实限制并关闭 Dense-only 优化。不得自动进入 reranker、其他模型、向量数据库或新大规模题库。

项目同时服务 Agent 应用岗与游戏 AI 产品岗。M4.5 收口后，主线必须转向至少两个新可玩病例、正式 V1 Episode Runner、跨 Episode 记忆产生/保存/召回/Agent 使用闭环和普通用户入口。M4.5-P3 与 M5 仍未开始。
