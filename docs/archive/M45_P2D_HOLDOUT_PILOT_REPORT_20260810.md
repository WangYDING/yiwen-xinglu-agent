# M4.5-P2d 新 Holdout 本地 BGE-M3 Pilot 结果

## 结论

本次唯一一组两次本地运行均完整结束，工程、安全和重复性门槛通过，但冻结的 final-test 语义质量门槛未全部通过。因此 M4.5-P2 的判定为：**语义质量未通过**。

按预注册停止规则，本轮 Dense-only 优化到此关闭：不自动增加 reranker、其他 Embedding 模型、向量数据库或新题库；不进入 M4.5-P3。下一主线转向多病例与游戏纵向切片规划。该结论不改写 M4 的 Fake Embedding 离线工程完成状态，也不代表游戏产品效果或玩家收益。

## 身份与执行历史

- Gold 与产品冻结提交：`98d08eef52bfb164f454bd50c08c0d3feab1bb26`
- runner 功能提交：`08f962417e54fd868b47485b2850c5440a2a6e4f`
- 精确执行提交：`ccf97ce0e5c29d6a8c0ce9d89f1f76e64b9a30a6`
- 功能提交后的预检曾发现 runner 把规范 JSON 身份哈希误当成文件字节哈希；正式 BGE 尚未加载。后续提交只纠正规范 manifest 身份核对并增加测试，不修改 Gold、模型、检索、参数或产品代码。
- 输入 SHA：`686508EAD3AC174DCD949ECA5E5051B5D137B50C796DBA52F34BDE26CE5141EA`
- expectations SHA：`9CAF5E4C7470F8F9C7BFBD29C0F8B60F1CC36558B19C98251E8BB0E03CBC8896`
- config SHA：`D119D075618744241BC54921FDE007E9DEFB96FB83D38E8129104D3E6DD679F0`
- manifest SHA：`44424FC212D382C98799B67CE0D70A222ACD4CF0E0809EBC0B4C070FB7F653C8`
- 模型：`BAAI/bge-m3@142964af7e05de16511657561de8e8750fc153a0`
- 空间：`bge_m3_142964af_dense_fp32_d1024_cuda_l512_rq2_doc2_v1`
- 设备与向量：CUDA、FP32、1024 维、dense-only、离线加载

从 `98d08ee` 到精确执行提交，冻结数据、P1–P4 产品实现、V2 检索实现、模型与依赖锁均未修改；非文档变化只有独立 holdout runner、离线测试及 runner 的规范 manifest 身份核对修复。

## Calibration 与策略锁定

12 条 calibration 首先独立执行，24 条 final-test Gold 在策略锁定前不可访问。36 组冻结参数全部评估后，唯一选择为：

```text
min_similarity = 0.75
max_results = 1
minimum_margin = 0.06
```

选择时的冻结指标为：macro F1 `0.9333333333`、Recall@3 `1.0`、MRR `1.0`、irrelevant retrieval rate `0/5 = 0`、empty accuracy `4/4 = 1.0`、安全总计 `0`。

完整 calibration 结果为：Recall@1 `0.9375`、Recall@3 `1.0`、MRR `1.0`；micro TP/FP/FN `5/0/4`，micro F1 `0.7142857143`。这些值只用于冻结策略选择和诊断，不与 final test 混合。

## Final-test 指标

| 指标 | 结果 | 门槛 | 判定 |
|---|---:|---:|---|
| Recall@1 | `0.90` | `>= 0.80` | 通过 |
| Recall@3 | `1.00` | `>= 0.90` | 通过 |
| MRR | `0.975` | `>= 0.85` | 通过 |
| Macro Precision | `1.00`（分母 11） | — | 记录 |
| Macro Recall | `0.50`（分母 20） | — | 记录 |
| Macro F1 | `0.9393939394`（分母 11） | `>= 0.80` | 通过 |
| Micro TP / FP / FN | `11 / 0 / 11` | — | 记录 |
| Micro Precision | `1.00` | — | 记录 |
| Micro Recall | `0.50` | — | 记录 |
| Micro F1 | `0.6666666667` | `>= 0.80` | **未通过** |
| Irrelevant retrieval rate | `0/11 = 0` | `<= 0.10` | 通过 |
| Empty accuracy | `4/4 = 1.0` | `1.0` | 通过 |
| 更正切片 FN | `1` | `0` | **未通过** |
| 否定/反义切片 FN | `0` | `0` | 通过 |

宏平均的 Precision/F1 只对分母已定义的场景求平均，因此不能替代 micro recall/F1。最终失败项严格是 `micro_f1` 与 `correction_false_negative`，没有通过改分母、降门槛或改 Gold 掩盖。

## 36 条逐项有序结果

分数保留 6 位小数；“返回”是锁定策略实际交给上层的结果，不等于用于 Recall@3 的完整 Top-3 排名。

| 场景 | 分组 | Top-3（候选:相似度） | 返回 | Gold relevant |
|---|---|---|---|---|
| `cal_01_correction` | calibration | h01_1:0.810107, h01_2:0.693358, h01_4:0.664963 | h01_1 | h01_1 |
| `cal_02_short` | calibration | h02_1:0.626891, h02_3:0.534200, h02_4:0.497097 | 空 | h02_1 |
| `cal_03_negation` | calibration | h03_1:0.843577, h03_2:0.764974, h03_4:0.682238 | h03_1 | h03_1 |
| `cal_04_lexical` | calibration | h04_1:0.837498, h04_2:0.765938, h04_3:0.627031 | h04_1 | h04_1 |
| `cal_05_synonym` | calibration | h05_1:0.734908, h05_4:0.547686, h05_2:0.534669 | 空 | h05_1 |
| `cal_06_mixed` | calibration | h06_1:0.752981, h06_2:0.576366, h06_3:0.451877 | h06_1 | h06_1 |
| `cal_07_long` | calibration | h07_1:0.688562, h07_4:0.609876, h07_2:0.551607 | 空 | h07_1 |
| `cal_08_multi` | calibration | h08_1:0.769703, h08_2:0.711524, h08_4:0.508185 | h08_1 | h08_1, h08_2 |
| `cal_09_empty_injection` | calibration | h09_1:0.656413, h09_4:0.616051, h09_3:0.543672 | 空 | 空 |
| `cal_10_empty_cross` | calibration | h10_3:0.535911, h10_2:0.515538, h10_1:0.473531 | 空 | 空 |
| `cal_11_empty_current` | calibration | h11_1:0.556328, h11_3:0.490066, h11_2:0.482659 | 空 | 空 |
| `cal_12_empty_invalidated` | calibration | h12_1:0.684443, h12_3:0.551494, h12_2:0.464431 | 空 | 空 |
| `test_01_correction` | final | h13_1:0.809720, h13_2:0.697527, h13_4:0.585535 | h13_1 | h13_1 |
| `test_02_correction` | final | h14_1:0.704161, h14_2:0.639260, h14_3:0.568955 | 空 | h14_1 |
| `test_03_short` | final | h15_1:0.786092, h15_3:0.554348, h15_2:0.489955 | h15_1 | h15_1 |
| `test_04_short` | final | h16_1:0.612960, h16_2:0.529506, h16_4:0.448286 | 空 | h16_1 |
| `test_05_negation` | final | h17_1:0.827668, h17_2:0.737369, h17_3:0.571630 | h17_1 | h17_1 |
| `test_06_negation` | final | h18_1:0.797019, h18_2:0.668507, h18_3:0.542082 | h18_1 | h18_1 |
| `test_07_lexical` | final | h19_1:0.801882, h19_2:0.713452, h19_3:0.611808 | h19_1 | h19_1 |
| `test_08_lexical` | final | h20_1:0.775127, h20_2:0.721518, h20_3:0.624308 | h20_1 | h20_1 |
| `test_09_synonym` | final | h21_1:0.795238, h21_2:0.593545, h21_3:0.585734 | h21_1 | h21_1 |
| `test_10_synonym` | final | h22_1:0.696330, h22_2:0.493815, h22_3:0.481824 | 空 | h22_1 |
| `test_11_mixed` | final | h23_1:0.743702, h23_2:0.473597, h23_3:0.388330 | 空 | h23_1 |
| `test_12_mixed` | final | h24_1:0.770102, h24_2:0.568410, h24_4:0.498228 | h24_1 | h24_1 |
| `test_13_long` | final | h25_1:0.722444, h25_3:0.627823, h25_4:0.520281 | 空 | h25_1 |
| `test_14_long` | final | h26_1:0.670306, h26_2:0.540724, h26_4:0.477696 | 空 | h26_1 |
| `test_15_multi` | final | h27_2:0.831772, h27_1:0.647623, h27_4:0.471353 | h27_2 | h27_1, h27_2 |
| `test_16_multi` | final | h28_1:0.752027, h28_2:0.616896, h28_3:0.429847 | h28_1 | h28_1, h28_2 |
| `test_17_injection` | final | h29_2:0.731647, h29_1:0.663286, h29_4:0.525757 | 空 | h29_1 |
| `test_18_no_overlap` | final | h30_1:0.669285, h30_2:0.599943, h30_3:0.423082 | 空 | h30_1 |
| `test_19_paraphrase` | final | h31_1:0.729225, h31_2:0.547501, h31_3:0.514866 | 空 | h31_1 |
| `test_20_diagnosis` | final | h32_1:0.800039, h32_4:0.551265, h32_2:0.543088 | h32_1 | h32_1 |
| `test_21_empty_cross` | final | h33_1:0.623087, h33_3:0.401125, h33_2:0.378292 | 空 | 空 |
| `test_22_empty_current` | final | h34_1:0.674661, h34_3:0.566722, h34_2:0.468092 | 空 | 空 |
| `test_23_empty_superseded` | final | h35_1:0.677992, h35_3:0.499382, h35_2:0.496120 | 空 | 空 |
| `test_24_empty_deleted` | final | h36_1:0.672483, h36_2:0.550507, h36_3:0.455284 | 空 | 空 |

表中候选缩写 `hNN_K` 对应原始 `hNN_candidate_K`。合法语义负例实际返回数为 0，故 final-test 普通语义 FP 为 0；安全排除对象不进入该表的排序候选。

## 切片与安全结果

- 更正：2 场，FN `1`；这是硬门槛失败项。
- 否定/反义：2 场，FN `0`。
- 极短文本：2 场，FN `1`。
- 中英混合：2 场，FN `1`。
- 长文本：2 场，FN `2`。
- 多相关项：2 场，Recall@1 `0.5`、Recall@3 `1.0`、FN `2`。
- Prompt 注入数据：相关项在 Top-3，但排名第 2，锁定门禁返回空；这只证明程序化边界未改变，不证明真实 Chat 模型抵抗注入。
- 4 条 empty 场景全部正确返回空。

两次运行的以下安全计数均为 0：跨玩家召回、当前 Episode 召回、superseded 召回、invalidated 召回、删除复活、隐藏内容泄漏、Prompt 边界改变、Embedding 修改权威记忆、空间混用、索引缺失/过期伪装为空。

## 重复性与资源

- 两次策略一致：是。
- 两次有序结果 SHA：均为 `3967a22a1a734f6bc2f1632285780743119d6eab803d0829b7237a7f2efd54e8`。
- 两次向量载荷 SHA：均为 `cd9cc7c8498e03352bfd578cdd4bd0e5ab039abded2c527fcd1f3bfc5c8243fe`。
- 记录向量数：每次 `173`；最大逐元素差：`0.0`，通过 `1e-6` 容差。
- run1：冷加载 `6128.550 ms`，首批 `180.897 ms`，其余 Embedding `1173.846 ms`，总 Embedding `1354.743 ms`；峰值工作集 `3,358,445,568` 字节；CUDA allocated/reserved `2,302,747,648 / 2,338,324,480` 字节。
- run2：冷加载 `5793.551 ms`，首批 `159.042 ms`，其余 Embedding `1176.269 ms`，总 Embedding `1335.311 ms`；峰值工作集 `3,357,782,016` 字节；CUDA allocated/reserved `2,302,747,648 / 2,338,324,480` 字节。
- 每次模型加载 `1`，本地物理批次 `72`，实际生成文本向量 `173`。
- 网络尝试 `0`，外部 API 请求 `0`，DeepSeek `/models` 与 Chat `0`，外部 Embedding API `0`，费用 `0 CNY`。

## 原始结果

原始向量和完整结果仅位于 Git 忽略目录：

- `results/m45_holdout_v1_run1_20260810.json`：`85C9B3A6109A2BDEF42DB1DB38E62EC976CA08933B882EED07A68197ECE44248`，`5,237,063` 字节。
- `results/m45_holdout_v1_run2_20260810.json`：`E376F58F61E53EF09F002B1AAD7C21FFDE83821B2FCCA956512326CC1525310C`，`5,237,064` 字节。

原始文件、真实向量、临时 SQLite、模型和机器隐私信息均不提交。两次运行后没有第三次运行、自动重试、调参、Gold 修改或产品代码修改。

## 阶段边界

M4.5-P2 的 Dense-only 验证以“工程/安全/重复性通过，语义质量未通过”收口。M4.5-P3 与 M5 均未开始。后续若要研究 reranker 或其他 Embedding，必须先单独论证岗位展示收益、依赖、时间和产品必要性并重新授权；当前推荐主线是新增至少两个可玩病例、正式 V1 Episode Runner、跨 Episode 记忆闭环与普通用户入口。
