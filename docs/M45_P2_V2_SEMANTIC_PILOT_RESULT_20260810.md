# M4.5-P2 v2 本地 BGE-M3 正式语义 Pilot 结果

## 1. 结论

M4.5-P2 的两次正式本地运行均完整结束，工程、安全和重复性门禁通过，但**语义质量未通过**预注册准入线。test `Recall@3` 为 `0.8888888889 < 0.90`，False Memory Rate 为 `5/13 = 0.3846153846`，因此不得进入 M4.5-P3。

这是 15 条冻结合成语义场景的一次小型本地 Pilot，不是产品准确率，也不证明真实 DoctorAgent 已会正确使用记忆或抵抗记忆中的提示注入。

## 2. 冻结身份与执行身份

| 项目 | 身份 |
|---|---|
| Gold v2 原始冻结提交 | `b78033099663464bf3d7790c6fef5d4b973dc692` |
| 本次精确执行提交 | `cad07ff42a5c665d49cdb25c2379f2026558554a` |
| 输入 SHA-256 | `CA55BEBDAFAA59C06EAB156C44316C2F862264E9082C71B768AB54D867674F3D` |
| expectations v2 SHA-256 | `2CE0C4AB316243B06BE7A80A5B3617F26B06545A736202BD27EBF24490B9D8D0` |
| manifest v2 SHA-256 | `4479CA16DF1457782FD94AF919DA1942CA87619D080A2F0E339779E83447AA61` |
| 预注册配置 SHA-256 | `1C302CB2155260812278A70DEFAE23D869AEE094B1A28523210FB826A332FDA8` |
| 依赖锁 SHA-256 | `8E4179D4177FBAFB62D6E1E17878CA7A71BB12C2D3D7D2747CF7AB83A1FFC0A6` |
| 主权重 SHA-256 | `993B2248881724788DCAB8C644A91DFD63584B6E5604FF2037CB5541E1E38E7E` |
| 模型与 revision | `BAAI/bge-m3@142964af7e05de16511657561de8e8750fc153a0` |
| Embedding 空间 | `bge_m3_142964af7e05_dense_fp32_d1024_cuda_l512_v1` |
| 运行设备 | RTX 4070 SUPER，CUDA 12.6，FP32，1024 维 |

执行提交没有重新冻结或调优 Gold。相对 `b780330`，受保护的非文档差异只有 `_peak_working_set_bytes()` 的 Windows 64 位 API 声明和 5 个离线回归测试；输入、Gold、配置、模型、Adapter、阈值、Top-K、排序和 P1–P4 产品代码均未改变。

## 3. 历史停止记录

历史事实均保留，未覆盖或改写：

| 检查点 | 事实 | 原始检查点 SHA-256 |
|---|---|---|
| v1：`41a5bdf254d964b35993809a86a01b75141d1381` | 歧义的 `forbidden_candidate_ids` 将合法语义负例误作安全违规；未形成可用指标 | `6B7E35CD8A8F712061FA0576E7B6352F061C1494E8455008EB75893B6C7C1BA5` |
| v2 启动停止：`f573e036d456e54e5c770014e49f7af66aa32ba9` | 本地 console entry 尚未安装 | `4C76415D1789D9CE5BEA4AA93E5418670C2976FD1AB732133791EFEFB88531AF` |
| v2 身份停止：`0ed89c15dfbb3dcb6a637813fabef205ffc1229e` | 执行 HEAD 与传入冻结提交不一致 | `628C24576585ACBFF2DFB6035F326FEA6B207442F0C50D73ECA01B9ADD1B0D19` |
| v2 遥测停止：`f36b3dbcbc839d5dff92d885bcfa0fd774c5fa0f` | Windows `GetProcessMemoryInfo` 句柄宽度未声明，正式 JSON 未序列化 | `D853266CAA8C24D0F37A705F8EC5B3C1784E63EDBB24140C6933AA3E1B431517` |

后三项是 v2 的三次诚实工程停止；第一项是更早的 v1 契约停止历史。

## 4. 正式原始结果

原始向量和完整结果只保存在 Git 忽略的 `results/`：

| 运行 | 路径 | 文件字节 | SHA-256 |
|---|---|---:|---|
| run1 | `results/m45_p2_v2_telemetryfix_run1_20260810.json` | 2,268,961 | `DD3B8482D3929B6A8F9F2B9C5D4BA0609CF2D3FA433C72E3F194E90A2D8CD6AE` |
| run2 | `results/m45_p2_v2_telemetryfix_run2_20260810.json` | 2,268,963 | `FD61EC0535621975DE4CFE63A4F6550EAEBBD06EE9CCFAAABDAAB99E665AB2B7` |

两次文件 SHA 不同是因为 `run_id` 和实测资源值不同；用于重复性判断的有序结果哈希和向量载荷哈希相同。

## 5. 阈值选择

calibration 固定为 5 条场景，test 固定为 10 条。阈值只在 calibration 上按“先最大化 empty accuracy，再最大化 macro F1，仍并列取更高阈值”选择：

| 阈值 | calibration empty accuracy | calibration macro F1 | 说明 |
|---:|---:|---:|---|
| `0.20`–`0.55` | `0.0` | `0.3333333333` | empty 未通过 |
| `0.60` | `1.0` | `0.3333333333` | 候选 |
| `0.65` | `1.0` | `0.3333333333` | 与 0.60 并列，按规则取更高阈值 |
| `0.70`–`0.80` | `1.0` | 缺省 | 无有效 macro F1 分母 |

最终冻结阈值为 `0.65`，随后一次性应用于 test；没有查看 test 后调参。

## 6. 15 条场景逐项结果

下表是两次运行完全一致的 BGE 排序。括号内为余弦相似度；“阈值返回”使用 `0.65`。

| 场景 | 划分 | BGE Top-3 | 相关项名次 | 阈值返回 |
|---|---|---|---:|---|
| `semantic_zh_synonym_001` | calibration | `cand_zh_synonym_1` (0.681927), `cand_zh_synonym_2` (0.646652), `cand_zh_synonym_4` (0.632344) | 1 | `cand_zh_synonym_1` |
| `semantic_action_paraphrase_001` | test | `cand_action_paraphrase_1` (0.686647), `cand_action_paraphrase_4` (0.637056), `cand_action_paraphrase_3` (0.625889) | 1 | `cand_action_paraphrase_1` |
| `semantic_lexical_distractor_001` | calibration | `cand_lexical_distractor_2` (0.682341), `cand_lexical_distractor_1` (0.611513), `cand_lexical_distractor_3` (0.605115) | 2 | `cand_lexical_distractor_2`（普通语义 FP） |
| `semantic_wrong_diagnosis_provenance_001` | test | `cand_wrong_diagnosis_provenance_1` (0.731844), `cand_wrong_diagnosis_provenance_4` (0.648243), `cand_wrong_diagnosis_provenance_3` (0.636522) | 1 | `cand_wrong_diagnosis_provenance_1` |
| `semantic_current_episode_exclusion_001` | test | `cand_current_episode_exclusion_2` (0.696156), `cand_current_episode_exclusion_3` (0.637505), `cand_current_episode_exclusion_4` (0.595942) | 1 | `cand_current_episode_exclusion_2` |
| `semantic_player_isolation_001` | test | `cand_player_isolation_2` (0.685190), `cand_player_isolation_4` (0.615155), `cand_player_isolation_3` (0.610859) | 1 | `cand_player_isolation_2` |
| `semantic_empty_001` | calibration | `cand_empty_3` (0.595217), `cand_empty_1` (0.582099), `cand_empty_4` (0.571331) | — | 空 |
| `semantic_correction_001` | test | `cand_correction_2` (0.662104), `cand_correction_3` (0.654114), `cand_correction_4` (0.645599) | 未进入 Top-3 | `cand_correction_2`, `cand_correction_3`（2 个普通语义 FP） |
| `semantic_invalidation_001` | calibration | `cand_invalidation_2` (0.596892), `cand_invalidation_4` (0.590550), `cand_invalidation_3` (0.572289) | — | 空 |
| `semantic_hard_delete_001` | test | `cand_hard_delete_3` (0.620853), `cand_hard_delete_2` (0.603828), `cand_hard_delete_4` (0.601475) | — | 空 |
| `semantic_prompt_injection_data_001` | test | `cand_prompt_injection_data_1` (0.713269), `cand_prompt_injection_data_3` (0.653236), `cand_prompt_injection_data_2` (0.641378) | 1 | `cand_prompt_injection_data_1`, `cand_prompt_injection_data_3`（1 个普通语义 FP） |
| `semantic_mixed_language_entity_001` | test | `cand_mixed_language_entity_1` (0.751464), `cand_mixed_language_entity_4` (0.675312), `cand_mixed_language_entity_3` (0.664709) | 1 | `cand_mixed_language_entity_1`, `cand_mixed_language_entity_4`, `cand_mixed_language_entity_3`（2 个普通语义 FP） |
| `semantic_short_text_001` | calibration | `cand_short_text_2` (0.680751), `cand_short_text_4` (0.676144), `cand_short_text_3` (0.665747) | 未进入 Top-3 | `cand_short_text_2`, `cand_short_text_4`, `cand_short_text_3`（3 个普通语义 FP） |
| `semantic_long_text_001` | test | `cand_long_text_1` (0.680326), `cand_long_text_2` (0.544818), `cand_long_text_3` (0.522450) | 1 | `cand_long_text_1` |
| `semantic_no_lexical_overlap_001` | test | `cand_no_lexical_overlap_1` (0.657351), `cand_no_lexical_overlap_3` (0.634971), `cand_no_lexical_overlap_2` (0.629945) | 1 | `cand_no_lexical_overlap_1` |

长文本为 3,532 字符、分词前 3,170 Token，并按冻结配置截断为 512 Token。

## 7. 指标

### 排序指标

| 划分 | 场景 | 有相关项场景 | Recall@1 | Recall@3 | MRR |
|---|---:|---:|---:|---:|---:|
| calibration | 5 | 3 | 0.3333333333 | 0.6666666667 | 0.5 |
| test | 10 | 9 | 0.8888888889 | 0.8888888889 | 0.8888888889 |

### 阈值分类指标

| 指标 | calibration | test |
|---|---:|---:|
| macro Precision（分母） | 0.3333333333 (3) | 0.7592592593 (9) |
| macro Recall（分母） | 0.3333333333 (3) | 0.8888888889 (9) |
| macro F1（分母） | 0.3333333333 (3) | 0.7962962963 (9) |
| micro TP / FP / FN | 1 / 4 / 2 | 8 / 5 / 1 |
| micro Precision | 0.2 | 0.6153846154 |
| micro Recall | 0.3333333333 | 0.8888888889 |
| micro F1 | 0.25 | 0.7272727273 |
| 正确 empty | 2 / 2 | 1 / 1 |
| False Memory Rate | 4 / 5 = 0.8 | 5 / 13 = 0.3846153846 |

test 的 5 个普通语义 FP 来自 correction 2 个、prompt injection data 1 个、mixed-language 2 个；它们不属于安全违规。

## 8. 安全硬门槛

两次运行的以下计数均为 0：

- `cross_player_recall`
- `current_episode_recall`
- `inactive_memory_recall`（superseded/invalidated）
- `deletion_resurrection`
- `hidden_content_leak`
- `prompt_boundary_violation`
- `authority_write_by_embedding`
- `embedding_space_mixing`
- `incomplete_index_as_empty`

实际候选阶段排除了 1 个跨玩家记录、1 个当前 Episode 记录、1 个 invalidated 记录和 1 个 hard-deleted 记录；更正流程产生的 superseded 旧记录也未进入结果。合法 active 语义负例只计普通 FP。BGE 只写派生向量，没有修改权威记忆。

## 9. Fake 与 BGE 的同口径差异

15/15 场景的有序 Top-3 发生变化；平均 Top-3 集合重合为 `2.4666666667 / 3`。在 test 的 9 个有相关项场景中：

- Fake Recall@1：`0.2222222222`；BGE Recall@1：`0.8888888889`；
- Fake Recall@3：`0.8888888889`；BGE Recall@3：`0.8888888889`；
- 使用“Top-3 外记为第 4 名”的预注册比较口径，BGE 相关项平均名次比 Fake 改善 1.0 位。

Fake 只是确定性工程对照；排序不同本身不是错误，语义结论由人工 Gold 判定。

## 10. 两次运行重复性与资源

| 项目 | run1 | run2 |
|---|---:|---:|
| 有序结果 SHA-256 | `6f3efbd0...d9f1` | `6f3efbd0...d9f1` |
| 向量载荷 SHA-256 | `2010c84f...8204` | `2010c84f...8204` |
| 向量最大逐元素绝对差 | 0.0 | 0.0 |
| 冻结容差 | 1e-6 | 1e-6 |
| 冷加载 | 6,069.699 ms | 6,157.138 ms |
| 首批 | 872.604 ms | 821.489 ms |
| 热批 | 27.588 ms | 24.942 ms |
| Embedding 总耗时 | 1,555.269 ms | 1,492.781 ms |
| 模型加载次数 | 1 | 1 |
| 本地物理批次数 / 处理文本数 | 41 / 148 | 41 / 148 |
| 进程峰值 working set | 3,362,037,760 B | 3,362,414,592 B |
| CUDA 峰值 allocated | 2,472,674,304 B | 2,472,674,304 B |
| CUDA 峰值 reserved | 2,600,468,480 B | 2,600,468,480 B |
| 网络尝试 / API 请求 / 费用 | 0 / 0 / 0 CNY | 0 / 0 / 0 CNY |

两次有序排名、相似度、阈值、指标和安全计数一致；向量差异 `0.0 <= 1e-6`。现有本地模型白名单占 2,293,250,249 字节；两份原始结果合计 4,537,924 字节，临时 SQLite 未保留。

## 11. 准入判断

| P3 建议门槛 | 实测 | 结果 |
|---|---:|---|
| test Recall@3 ≥ 0.90 | 0.8888888889 | 未通过 |
| test MRR ≥ 0.75 | 0.8888888889 | 通过 |
| test macro F1 ≥ 0.75 | 0.7962962963 | 通过 |
| empty accuracy = 1.0 | 1 / 1 | 通过 |
| False Memory Rate = 0 | 5 / 13 | 未通过 |
| 所有安全计数 = 0 | 全部 0 | 通过 |
| 两次有序结果和指标一致 | 一致 | 通过 |
| 向量差异 ≤ 1e-6 | 0.0 | 通过 |

最终判定：**M4.5-P2 两次正式运行与安全验证完成，但语义质量未通过；M4.5-P3 和 M5 均未开始。**
