# 玄医问道演示指南

本指南面向招聘者和不熟悉代码的试玩者。所有默认流程均为 `manual/off` 或 `fake/off`，无需 API Key，不调用 DeepSeek、BGE 或外部服务。真实终端素材见 [`assets/README.md`](assets/README.md)。

## 演示前准备

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
New-Item -ItemType Directory -Force .\runtime_data\play | Out-Null
```

普通试玩：

```powershell
.\.venv\Scripts\xuanyi-play.exe --state-dir .\runtime_data\play
```

离线 Fake 演示：

```powershell
.\.venv\Scripts\xuanyi-play.exe --state-dir .\runtime_data\play `
  --mode fake --semantic-shadow off
```

## 30 秒项目介绍

| 时间 | 镜头 / 终端操作 | 解说要点 | 预期输出 | 证据 | 离线备用 |
|---|---|---|---|---|---|
| 0:00–0:08 | README 标题与安全架构图 | “这是一个三个病例的师承型 NPC 纵向切片；模型只能提议，规则才改状态。” | 架构图显示 AgentAction、规则、事件与 MCP | [安全架构图](assets/safe-agent-architecture.svg) | 直接展示已提交 SVG |
| 0:08–0:20 | 三病例目录截图 | “无 Key 就能玩；三个病例支持调查、诊断和三种结局。” | CLI 显示三个病例与推荐下一案 | [真实目录素材](assets/demo-01-case-catalog.svg) | 展示对应[脱敏文本](assets/transcripts/01_case_catalog.txt) |
| 0:20–0:30 | 验收摘要与限制 | “跨案成长可重放；真实模型有正负案例，未过线的语义记忆默认关闭。” | 三案 8 事件、Campaign 1–3、外部调用 0 | [验收素材](assets/demo-03-acceptance-summary.svg) | 展示 [M5 退出审计](M5_EXIT_AUDIT.md) |

## 3 分钟通用快速演示

| 时间 | 镜头 / 终端操作 | 解说要点 | 预期输出 | 证据 | 失败时备用 |
|---|---|---|---|---|---|
| 0:00–0:25 | 启动 `xuanyi-play`，创建演示玩家 | “默认 manual/off；不读 Key、不加载模型。” | 启动页显示 manual、shadow 关闭、无需 API Key | [目录截图](assets/demo-01-case-catalog.svg) | 使用已提交 stdout 摘录 |
| 0:25–0:55 | 查看病例目录 | “病例来自包资源和严格 Schema，不在 CLI 硬编码答案。” | 三案稳定列出，旧纸伞标记推荐下一案 | [病例设计](M5_CASE_DESIGN.md) | 展示目录截图 |
| 0:55–1:30 | Fake 完成旧纸伞 | “Fake 只是可重复提案；8 个行动仍经正式工具和规则路径。” | 6 调查 + 诊断 + 处置，`resolved / 100` | [验收记录](VERIFICATION.md) | 展示验收素材 |
| 1:30–2:05 | 打开玩家历程，再进入灰灶 | “知识来自 CampaignEvent；后案只读公开事实，不改变答案。” | 解锁契物归属知识并出现灰灶历史反应 | [连续性截图](assets/demo-02-campaign-continuity.svg) | 展示对应脱敏文本 |
| 2:05–2:35 | 展示退出后重启恢复 | “每个成功行动原子保存；新进程恢复同一 Session。” | Session、修订与事件连续，无重复 Episode | [M5 退出审计](M5_EXIT_AUDIT.md) | 直接引用两进程证据 |
| 2:35–3:00 | 展示验收摘要 | “重放、双玩家隔离、拒绝零写入和 shadow 隔离都在无网络路径复验。” | 三案 / Campaign / 隔离全部通过 | [验收截图](assets/demo-03-acceptance-summary.svg) | 运行 `xuanyi-m5-acceptance` |

## 8 分钟 Agent 应用岗演示

| 时间 | 镜头 / 终端操作 | 解说要点 | 预期输出 | 证据 | 失败时备用 |
|---|---|---|---|---|---|
| 0:00–0:45 | 安全架构图 | 模型、公开视图、行动契约、规则和事件职责分离 | 明确“模型无状态写入口” | [架构图](assets/safe-agent-architecture.svg) | 静态 SVG |
| 0:45–1:35 | Fake 逐步执行旧纸伞 | `AgentAction` 严格校验；合法行动才产生一个事件 | 8 步、事件 1–8、`resolved / 100` | [模式说明](M5_AGENT_MODES.md) | [验收摘要](assets/demo-03-acceptance-summary.svg) |
| 1:35–2:25 | MCP 说明或 `xuanyi-mcp-stdio --help` | 9 个工具复用应用 Facade；拒绝不保存 | 工具发现、stdio、重启恢复证据 | [M3 退出审计](M3_EXIT_AUDIT.md) | 只展示报告，不启动 Host |
| 2:25–3:15 | 展示错误行动用例 | 参数、过早诊断、重复调查均返回公开错误，零事件零修订 | 文件逐字节不变 | [P4c 审计](M5_P4C_AGENT_CONTRACT_AUDIT.md) | 使用离线测试输出 |
| 3:15–4:35 | P4b → P4c → P4d | 真实失败分成契约缺口、反馈不足与模型策略；通用修复不写病例特例 | P4b 未闭环；P4d 单次 5/5 修复、三案闭环 | [P4b](M5_P4B_DEEPSEEK_CAMPAIGN_PILOT_20260811.md) · [P4d](M5_P4D_DEEPSEEK_RECOVERY_VALIDATION_20260811.md) | 展示脱敏报告，不展示 Prompt/请求 ID |
| 4:35–5:25 | 预算和错误边界 | 每请求预留、Token/费用核对、超时即停、无隐式重试 | P4d 费用 `0.02345744 CNY` 可追溯 | [P4d 用量](M5_P4D_DEEPSEEK_RECOVERY_VALIDATION_20260811.md) | 只读报告 |
| 5:25–6:20 | M4/M4.5 记忆决策 | 可信事件→SQLite→派生向量；真实 Dense 返回门禁未过线 | `Recall@3=1.00`，micro F1 `0.6667`，正式注入关闭 | [M4.5 终止审计](M45_TERMINATION_AUDIT.md) | 展示指标表 |
| 6:20–7:15 | 重放与玩家隔离 | Case/Campaign 从空状态重放；跨玩家候选和状态污染为 0 | CampaignEvent 1–3、两玩家隔离 | [M5 退出审计](M5_EXIT_AUDIT.md) | 验收摘要 |
| 7:15–8:00 | 证据分级与限制 | 工程事实、单次模型案例、合成评测、未验证项分开 | 不声称稳定成功率或生产能力 | [Agent 岗证据](M5_PORTFOLIO_EVIDENCE.md#agent-应用岗证据) | README 限制段 |

## 8 分钟游戏 AI 产品岗演示

| 时间 | 镜头 / 终端操作 | 解说要点 | 预期输出 | 证据 | 失败时备用 |
|---|---|---|---|---|---|
| 0:00–0:45 | 三病例目录 | 志怪道医题材；每案是完整调查闭环，不是四选一 Embedding 题 | 三案可独立开始 | [病例设计](M5_CASE_DESIGN.md) | 目录截图 |
| 0:45–1:45 | manual 执行一项调查 | 玩家选择公开行动；CLI 不提示正确答案 | 公开线索、修订和可用选项刷新 | [P1/P2 验证](VERIFICATION.md) | 使用脱敏终端记录 |
| 1:45–2:40 | 展示两种调查顺序与三类结局 | 调查依赖无环、至少三项初始可选；处置可解决、压制或恶化 | 正确和失败轨迹都可重放 | [病例设计](M5_CASE_DESIGN.md) | 打开参考轨迹表 |
| 2:40–3:35 | 退出并用第二进程恢复 | 存档是产品流程，不要求用户编辑 JSON | 恢复同一 Episode，无重复和丢失 | [M5 退出审计](M5_EXIT_AUDIT.md) | 引用两进程测试 |
| 3:35–4:50 | Fake 完成旧纸伞并进入灰灶 | 跨案反应来自玩家已完成的公开选择 | 契物归属知识、灰灶历史反应 | [连续性素材](assets/demo-02-campaign-continuity.svg) | 静态图 + 文本 |
| 4:50–5:55 | 灰灶→月井 Campaign 图 | 两项成长、两处反应；推荐顺序但不锁关 | CampaignEvent 1–3 连续 | [Campaign 图](assets/campaign-flow.svg) | [连续性文档](M5_CAMPAIGN_CONTINUITY.md) |
| 5:55–6:45 | 第二玩家直接进入月井 | 无前史时使用中性开场，仍可完成；不同玩家完全隔离 | 知识、推荐、Session 不串扰 | [验收审计](M5_EXIT_AUDIT.md) | 验收摘要 |
| 6:45–7:25 | 展示 semantic shadow 关闭 | 未过线能力不会污染正式体验；连续性由确定性规则保障 | off / record-only 行动和终态一致 | [M4.5 决策](M45_TERMINATION_AUDIT.md) | 静态架构图 |
| 7:25–8:00 | 产品边界与下一步 | 当前是本地纵向切片，不是生产游戏；未做网页与真实玩家研究 | 清楚区分已完成和未验证 | [游戏 AI 岗证据](M5_PORTFOLIO_EVIDENCE.md#游戏-ai-产品岗证据) | README 限制段 |

## 录屏镜头清单

- README 首屏、中英文摘要和两个岗位入口；
- CLI 的 manual / fake、shadow 关闭和“无需 API Key”；
- 三病例目录与推荐下一案；
- 一个调查后修订从 0 到 1；
- 关闭窗口、重新启动、恢复同一 Session；
- Fake 每步公开工具名；
- 两项知识和两处跨案反应；
- M5 验收摘要；
- P4b/P4d 与 M4.5 结论段（不展示完整 Prompt、请求 ID 或本地路径）。

## 备用原则

面试环境无网络时直接使用 manual、Fake 和 M5 验收入口；它们本来就不需要网络。命令入口未刷新时，使用 `python -m xuanyi_npc.cli.play` 和 `python -m xuanyi_npc.evaluation.m5_acceptance`。如果显卡或 BGE 不可用，不临时安装模型，只展示已提交的 M4.5 脱敏负结果和默认关闭决策。

当前演示证明的是 Windows / Python 3.12 下的本地三病例工程纵向切片，不证明生产并发、网页交付、真实玩家留存、教学收益或真实模型稳定成功率。
