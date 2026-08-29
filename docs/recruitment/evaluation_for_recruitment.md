# 《异闻行录》Agent Evaluation：招聘与面试说明

## 为什么这个项目需要评测

这个 Agent 不只是“生成一段看起来合理的回答”，而是要在多轮调查中维护 Goal/Plan、读取公开线索、选择合法工具、请求必要授权、诊断并执行治疗。单次演示无法回答三个关键问题：任务是否真的闭环、随机模型输出下是否稳定、Memory/Reflection 是否真实进入生产路径。因此项目把评测拆成任务结果、可靠性、安全、效率、行为遥测和跨会话机制证据，并对能说与不能说的结论设定边界。

## 最终做了哪些 Evaluation

| Evaluation | Metric | Meaning | Final Result | Can Claim | Cannot Claim |
|---|---|---|---|---|---|
| End-to-end Agent Task Benchmark | terminal success、diagnosis、treatment | Agent 能否沿真实 Runtime/Authority/CaseEngine 完成冻结任务 | E6 8/9；诊断 9/9；治疗 8/9 | 三个冻结病例上的端到端完成能力 | 泛化到任意病例或生产流量 |
| Multi-run reliability | 3 cases × 3 independent repeats、case/macro rate、failure distribution | 同一冻结协议下观察随机输出方差 | E3 6/9；E6 8/9 | E6 是当前描述性 reliability baseline | 统计显著性或 E5 的因果提升 |
| Safety / Authority | executed violations、rejected/bypass actions | 模型是否绕过授权、诊断或治疗边界 | E6 executed violations 0 | 九次正式 episode 中未观察到执行违规 | “系统绝不会违规” |
| Efficiency / cost | turns、tokens、requests、duration、CNY | 完成任务的交互与 API 成本 | mean 11.89 turns；约 155,953 tokens/episode；总成本约 ¥0.37 | 冻结配置下的实测成本画像 | 大规模线上成本预测 |
| Repair/fallback/alignment | repair、fallback、plan/action rejection、failure codes | 结构化输出失效时如何恢复并保持安全 | E6 repairs 14；fallbacks 2；alignment/authority rejection 0 | repair/fallback 路径有真实生产证据 | fallback 提升成功率的因果结论 |
| Cross-session Memory | persisted、candidate、selected、declared、accepted、Agent input | 历史 Memory 是否跨会话进入真实 Agent | E10 persisted/retrieved/selected/input PASS；declared/accepted 0 | real-Agent cross-session exposure proven | Memory 被模型使用或改善表现 |
| Reflection | trigger、generation、receipt、derived write/index/retrieval | Reflection 生命周期与派生 Memory 链是否工作 | deterministic mechanism PASS；E12 real trigger/generation PASS，但 safe `no_write` | 机制存在，真实模型触发/生成有证据 | 真实派生 Memory 稳健性或行为收益 |

## Benchmark 到底是什么

Benchmark 不是一个单独分数，而是一份冻结实验协议：

`cases + runtime/model config + player script + success rule + turn limit + repeat protocol + immutable artifacts`

本项目正式 task benchmark 固定三个病例、公开状态条件式 player script、确认策略、16-turn 上限、DeepSeek 模型参数、semantic Memory 与 Reflection wiring。每个 condition 独立保存 manifest、runtime hashes、逐 episode artifact 和 aggregate；不同 manifest 的 runs 不混入同一 aggregate。这样结果才可复查，失败也不能观察后重跑或删除。

## Agent 经历了怎样的提升

### A. Capability stabilization history

最初 frozen 3×1 为 0/3；经过 P0–P5 对 action recovery、诊断选择、Plan/Decision alignment、模型可见诊断契约、治疗契约和 executable-step commitment 的逐项稳定后，frozen 3×1 达到 3/3。

这说明 task path 从“不能闭环”变为“三个病例都观察到可闭环”。它是 capability stabilization，不是 statistical reliability；P0–P5 也是工程诊断历史，不应包装成独立统计实验。

### B. Formal multi-run reliability

| Metric | E3 pre-E5 | E6 post-E5 | Descriptive change |
|---|---:|---:|---:|
| Task success | 6/9 (66.67%) | 8/9 (88.89%) | +22.22 percentage points |
| Diagnosis accuracy | 9/9 (100%) | 9/9 (100%) | 0 pp |
| Treatment accuracy | 6/9 (66.67%) | 8/9 (88.89%) | +22.22 pp |
| Infrastructure failures | 1/9 | 0/9 | −1 observed failure |

E3 与 E6 是小样本、独立、随机模型 runs。可以说“observed descriptive change”，不能说“E5 causally improved success by 22.22pp”或“统计显著提升”。

## 最应该写进项目经历的数字

- 3 frozen cases × 3 independent repeats。
- Task success：8/9 = 88.89%。
- Diagnosis accuracy：100%。
- Treatment accuracy：88.89%。
- Executed safety violations：0。
- Infrastructure failures：0；provider aborts：0。
- Mean turns：11.89。
- Mean tokens/episode：约 155,953。
- 九次正式评测总估算 API 成本：约 CNY 0.37。

这些数字来自 E6 current reliability baseline；0/3→3/3 是 capability history，6/9→8/9 是描述性 reliability history，三者不要混写。

## Memory 最终证明了什么

| Evidence level | Result | Interpretation |
|---|---|---|
| 1 — Persisted/indexed | PROVEN | Session A 公开 committed event 通过 production coordinator 写入并建立向量索引 |
| 2 — Retrieved/exposed | PROVEN | 同 player/state-dir 的新 Session B 检索、projection selected，并进入 real `GameNPCAgentInput` |
| 3 — Declared-used | NOT OBSERVED | E10 real Agent 没有声明使用 expected Memory |
| 4 — Runtime accepted-used | NOT OBSERVED | 因未声明，accepted IDs 为空 |

因此可说“真实跨会话 Memory exposure 已证明”；不能说“Memory 被模型使用”“改善工具选择”或“提升任务成功率”。E10 的 irrelevant Memory 也出现过 false-positive exposure，但未被声明/接受使用；empty-history control 为零 exposure。

## Reflection 最终证明了什么

- Deterministic E11：trigger→validated proposal→receipt/write→index→later retrieval 的机制已证明，且 OFF condition 保留 ordinary semantic Memory。
- Real E12：真实 trigger 与 production Reflection generation 已证明；初始 grounding failure 经 bounded repair 后得到合法空 lesson，安全 `no_write`。
- 单次 frozen real run 没有派生 Memory，因此 real-model derived-memory write/exposure robustness 未证明。
- 未观察 declared/accepted Reflection Memory use，也未证明 behavioral benefit。

这不是需要掩盖的“失败”：它展示了保守 grounding、repair 和 no-write 边界。E13 未发现 schema/validator/consolidation correctness bug，因此项目在这里诚实封版。

## 简历三行版本

- 为多轮工具型 Agent 构建冻结评测协议（3 cases × 3 independent repeats），覆盖任务结果、Authority safety、repair/fallback、效率与成本遥测。
- 将 capability path 从初始 0/3 稳定到 3/3；正式 E6 达成 8/9 task success、100% diagnosis、88.89% treatment，0 executed safety violations / infrastructure failures。
- 实现跨会话 semantic Memory 与 Reflection evaluation：证明 Memory 可持久化、检索并进入真实 Agent；对未观察到的 use/benefit 与 Reflection `no_write` 明确限定结论。

## 简历四行版本

- 设计 production-equivalent Agent benchmark，冻结 cases、player script、success rule、runtime hashes、repeat protocol 与 immutable artifacts。
- 通过 P0–P5 structured repair/fallback/alignment telemetry 定位并稳定 task path：0/3→3/3。
- 在 3×3 reliability evaluation 中获得 8/9 success、100% diagnosis、88.89% treatment、0 safety/infrastructure failures，成本约 ¥0.37。
- 构建 cross-session Memory/Reflection harness；真实验证 Memory exposure，同时保留 declared-use、causal benefit 与 Reflection robustness 的证据边界。

## 30 秒项目介绍

“这是一个带 Goal/Plan、工具调用、Authority gate、长期 Memory 和 Reflection 的多轮调查 Agent。我没有只展示成功 demo，而是冻结三个病例、player script、成功规则和 runtime hashes，做了 3×3 独立重复。最终 baseline 是 8/9 完成、诊断 100%、治疗 88.89%，没有执行安全违规或基础设施失败。Memory 还做了跨会话真实模型验证，证明历史内容确实进入 Agent input；但模型没有声明使用，所以我没有夸大成性能提升。”

## 2 分钟 Evaluation 介绍

“评测分三层。第一层是 capability stabilization：最初三个冻结病例 0/3，借助结构化 repair、fallback、Plan/Decision alignment 和 action-contract telemetry，把 task path 稳定到 3/3；这只说明能闭环。第二层是 reliability：同一正式协议对三个病例各跑三次，E3 是 6/9，E6 是 8/9，诊断一直 100%，治疗从 66.67% 到 88.89%，E6 没有 safety、provider 或 infrastructure failure。因为样本小且模型随机，我只称它为描述性变化。第三层是机制评测：普通 task benchmark 的 Memory exposure 为零，所以我另建 same-player/same-repository 的跨会话 suite。真实 Agent 中验证到 persisted、retrieved、selected 和 input exposure，但没有 declared/accepted use。Reflection 的 deterministic 链完整通过；真实 run 触发并生成后选择了安全 no-write，因此机制成立但真实派生 Memory 稳健性没有被证明。这套边界本身也是评测工程的一部分。”

## 面试标准回答

### “你这个 Agent 怎么评测的？”

“我把 benchmark 定义成冻结协议而不是一个分数：固定病例、runtime/model config、player script、成功规则、turn limit、重复次数和 artifacts。指标同时看 task success、诊断/治疗、Authority violations、repair/fallback、turns/tokens/cost。正式 baseline 是三个病例各三次，另外用独立 cross-session suite 测 Memory/Reflection，因为普通 benchmark 的 episode 隔离使 Memory candidate 为零。”

### “相比最初提升了多少？”

“Capability 阶段是 0/3 到 3/3，表示任务路径从不能闭环到能闭环。正式多轮证据是 E3 6/9 到 E6 8/9，观察上 +22.22pp；治疗也是 66.67% 到 88.89%，诊断保持 100%。但两批是小样本随机 runs，我不会把 +22.22pp 归因给某个单一修复，也不声称统计显著。”

### “Memory/Reflection 真的有用吗？”

“Memory 的 persistence、retrieval、projection 和 real-Agent input exposure 是实证通过的；模型没有声明使用，runtime 也没有 accepted use，所以行为收益没证明。Reflection 的 deterministic mechanism 和真实 trigger/generation 通过，但唯一冻结真实 run 最终安全 no-write，没有派生 Memory exposure。准确结论是系统路径存在且保守边界有效，不是已经证明它们提升成功率。”

## Evidence map

- Capability：`docs/frozen_3x1_final_acceptance_report.md`、P0–P5 reports。
- Reliability：`docs/e3_frozen_3x3_statistical_evaluation_report.md`、`docs/e6_post_e5_frozen_3x3_reliability_report.md`。
- Memory：E9 implementation、E10 pilot report/artifacts。
- Reflection：E11 implementation、E12 pilot、E13 root-cause audit。
