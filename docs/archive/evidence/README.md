# 实验数据与历史证据迁移索引

根目录 `data/` 已取消。历史冻结文档中的旧路径按形成时原文保留；当前路径按以下规则解析：

- `data/evaluation/` 中的离线评测、Gold、Holdout 和行为探针 → `tools/experiments/data/evaluation/`
- `data/pilot/` 中的旧价格与策略快照 → `tools/experiments/data/pilot_snapshots/`
- `data/evaluation/` 中的脱敏真实运行结果 → `docs/archive/evidence/model_runs/`

正式产品资源的唯一真源仍为 `src/xuanyi_npc/resources/`。本次迁移未改变下列文件的内容或 SHA-256：

| 原路径 | 当前路径 | SHA-256 |
|---|---|---|
| `data/evaluation/deepseek_pilot_v021_review_20260807T024907Z_sanitized.json` | `model_runs/deepseek_pilot_v021_review_20260807T024907Z_sanitized.json` | `41fd0c8c014d6a7ed78fba8dda0741b84172e2366debdc7b2ba22a1abacc2641` |
| `data/evaluation/deepseek_safety_only_c39b3f7_20260807_sanitized.json` | `model_runs/deepseek_safety_only_c39b3f7_20260807_sanitized.json` | `6329e1d77e2858768eb07c72fe57dd839062c300c30393fa2cd2343fa61ba462` |
| `data/evaluation/pilot_run_001_sanitized.json` | `model_runs/pilot_run_001_sanitized.json` | `b17a0a90c1031f99095b45b323a9a87bf21484b967edaafb8ebed518800a6d0b` |
| `data/evaluation/dev_scenarios.json` | `../../../tools/experiments/data/evaluation/dev_scenarios.json` | `62d6c0d2a8db71b20f6a2ed173c976eb4581b022cd4ab72b10365544f8f35b9f` |
| `data/evaluation/m45_semantic_gold_expectations.json` | `../../../tools/experiments/data/evaluation/m45_semantic_gold_expectations.json` | `ee68a03de2e4a3adbd6fd81d9f751a94f1f504e37cf7e33573a7fcb0ae79ef80` |
| `data/evaluation/m45_semantic_gold_expectations_v2.json` | `../../../tools/experiments/data/evaluation/m45_semantic_gold_expectations_v2.json` | `2ce0c4ab316243b06be7a80a5b3617f26b06545a736202bd27ebf24490b9d8d0` |
| `data/evaluation/m45_semantic_gold_inputs.json` | `../../../tools/experiments/data/evaluation/m45_semantic_gold_inputs.json` | `ca55bebdafaa59c06eab156c44316c2f862264e9082c71b768ab54d867674f3d` |
| `data/evaluation/m45_semantic_gold_manifest.json` | `../../../tools/experiments/data/evaluation/m45_semantic_gold_manifest.json` | `9c17fbcc4f5f867ddcf40cf4ef056ab5299d65173595910d3312c97b4cccb9ef` |
| `data/evaluation/m45_semantic_gold_manifest_v2.json` | `../../../tools/experiments/data/evaluation/m45_semantic_gold_manifest_v2.json` | `4479ca16df1457782fd94af919da1942ca87619d080a2f0e339779e83447aa61` |
| `data/evaluation/m45_semantic_holdout_config_v1.json` | `../../../tools/experiments/data/evaluation/m45_semantic_holdout_config_v1.json` | `d119d075618744241bc54921fde007e9defb96fb83d38e8129104d3e6dd679f0` |
| `data/evaluation/m45_semantic_holdout_expectations_v1.json` | `../../../tools/experiments/data/evaluation/m45_semantic_holdout_expectations_v1.json` | `9caf5e4c7470f8f9c7bfbd29c0f8b60f1cc36558b19c98251e8bb0e03cbc8896` |
| `data/evaluation/m45_semantic_holdout_inputs_v1.json` | `../../../tools/experiments/data/evaluation/m45_semantic_holdout_inputs_v1.json` | `686508ead3ac174dcd949eca5e5051b5d137b50c796dba52f34bde26ce5141ea` |
| `data/evaluation/m45_semantic_holdout_manifest_v1.json` | `../../../tools/experiments/data/evaluation/m45_semantic_holdout_manifest_v1.json` | `44424fc212d382c98799b67ce0d70a222acd4cf0e0809ebc0b4c070fb7f653c8` |
| `data/evaluation/memory_gold_expectations.json` | `../../../tools/experiments/data/evaluation/memory_gold_expectations.json` | `389b841f4f039c1fc076df7d9c206e6c040522bded3c471a8848ec5e8d732c49` |
| `data/evaluation/memory_gold_inputs.json` | `../../../tools/experiments/data/evaluation/memory_gold_inputs.json` | `6d1233c6392d9f89eccf9abbc7c937a82319bb29e2591327c5e55fc51612e483` |
| `data/evaluation/memory_gold_manifest.json` | `../../../tools/experiments/data/evaluation/memory_gold_manifest.json` | `b5d5fb11a8a24dc3f9c736223df9c645ad5a5950e58e7739e93513ac217dde89` |
| `data/evaluation/pilot_behavior_probes.json` | `../../../tools/experiments/data/evaluation/pilot_behavior_probes.json` | `3de6a43c217774a839cd3e96bbc201e1a560ef9af9bea67836cecd895b6612aa` |
| `data/pilot/deepseek_v4_flash_pilot_policy_2026-08-06.json` | `../../../tools/experiments/data/pilot_snapshots/deepseek_v4_flash_pilot_policy_2026-08-06.json` | `f77fe4e573747ba76fa49d528fc8c3d564f7b565f7c4b035a2f81472aa829c4e` |
| `data/pilot/deepseek_v4_flash_pricing_2026-08-04.json` | `../../../tools/experiments/data/pilot_snapshots/deepseek_v4_flash_pricing_2026-08-04.json` | `f51c286eff99ed7ba836474c0e53bdec194f1e95153242942abbee442b440927` |

旧 `data/README.md` 已由本索引、`tools/README.md` 和包资源边界测试取代。
