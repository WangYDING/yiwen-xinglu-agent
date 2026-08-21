# 演示素材来源、分类与隐私记录

本目录保存《异闻行录》作品集使用的 current architecture、retained compatibility presentation 与 historical engineering evidence。素材分类不改变其原始工程事实，也不把历史三案 CLI、Mentor progression 或离线验收提升为当前完整产品体验。

## 素材分类

| 素材 | 分类 | 展示内容与来源 | 面试使用边界 |
|---|---|---|---|
| `safe-agent-architecture.svg` | **Current** | 当前 Human-Agent Cooperative Game NPC 主链；手工维护的权威架构图 | 可用于说明 `GameNPCAgent`、玩家贡献、确定性验证与世界状态边界 |
| `demo-01-case-catalog.svg` | **Retained** | `xuanyi-play` 保留的三案 manual/demo compatibility route；由脱敏 transcript 确定性生成 | 可证明兼容 CLI、no-key 启动与三案资源，不代表六异案 Clinic Web 的完整目录 |
| `transcripts/01_case_catalog.txt` | **Retained source** | 三案兼容 CLI 的公开脱敏文本；banner 与 A3a 当前 CLI 一致 | 仅作为 `demo-01` 的生成源和兼容入口证据 |
| `campaign-flow.svg` | **Historical engineering evidence** | M5 三案 Campaign 连续性：公开知识投影、推荐与历史反应 | 可说明确定性跨 Episode 连续性；不是 current main gameplay flow，也不是 Mentor progression flow |
| `demo-03-acceptance-summary.svg` | **Historical engineering evidence** | M5 离线纵向切片验收摘要；由冻结 transcript 确定性生成 | 可说明有限工程验收，不能描述为生产成功率、统计显著性或玩家收益 |
| `transcripts/03_acceptance_summary.txt` | **Historical source** | M5 冻结离线验收摘要 | 数字和结论按历史形成时身份保留，不用于推导 current product success rate |

目录中的 `demo-02-campaign-continuity.svg` 及其 transcript 同样属于 M5 historical engineering evidence，继续保留原始来源和结论。

## Current cooperative architecture

`safe-agent-architecture.svg` 表达当前主链：

```text
Player
→ PlayerContribution
→ CooperativeRuntime
→ public Observation + Goal / Plan + scoped Memory
→ GameNPCAgent proposal
→ cooperative Decision
→ PublicActionContract / GoalPlanPolicy / Authority Policy
→ Tool
→ CaseEngine
→ Plan Evaluation / Replanning
→ Reflection
→ Experience Consolidation
```

图中明确：LLM proposes；deterministic system validates；`CaseEngine` owns world-state changes。`MentorAgent` 只作为 Retained Teaching / Presentation Branch，`DoctorAgent` 只作为 V0 Baseline；普通案中人物不是 Agent，系统不是 Multi-Agent architecture。

## 生成流程

1. 使用项目本地离线路径运行 retained CLI 或 acceptance command；
2. 只从 stdout 摘录公开内容，去除交互噪声、内部 ID 与本机目录；
3. 人工核对不含未发现线索、隐藏真值、完整 Prompt、请求 ID 或环境变量；
4. 运行 `python tools/release/render_demo_assets.py`，以标准库把 UTF-8 transcript 确定性渲染为 SVG；
5. 运行 `python tools/release/check_portfolio_docs.py`，复核哈希、SVG XML、链接与隐私哨兵。

`safe-agent-architecture.svg` 与 `campaign-flow.svg` 是仓库直接维护的图表 source-of-truth，不由终端 transcript 生成。前者描述 current architecture；后者保留 M5 Campaign historical evidence。

## 来源身份

| 素材 | Git 忽略原始 stdout SHA-256 | 已提交脱敏文本 SHA-256 | SVG SHA-256 |
|---|---|---|---|
| 三案兼容 CLI 目录与 no-key 启动 | 历史原始运行：`72F09294230D7F5BD7CF072372AF30D6E5FB15FA79CB46937F0D3C96AAAE9536` | `F122C78C5A1C31EB8704F5D48C55E815735287DE43EB688E971E24DB1CC673B5` | `7852E011446BB87F80B50B9658A21FE9E3D460640CFA80883A4DADAE296755FD` |
| 知识解锁与灰灶历史反应 | `E1ED88BF5AF1AB168BABF038D4E628822B46348AE064DD2682689648149B3694` | `09A6ABE61926E762E0B11667021B361A209E6050D6E17B264D2C5F874F106F59` | `6F55D2D050CE33476B271C40501A6221DA1AA7B426B0F5F84BE9BE864BE7690E` |
| M5 离线验收摘要 | `62E152984BCA849A0FB69B289F064816C5599FE759B39DE8AF4B192DC938A7B6` | `70184C1487266F3497E1DB728B1CFBC72EC0F400165293A095DD04C40D24259D` | `8DBBC41E1FE045E8F5EB1BFEF8170A9B6012E5F58F26E7DCE62AC63C5FDBB729` |

三案 transcript 在 A3a 后仅同步当前 CLI 的公开 banner；案件目录、推荐理由和 no-key 事实未改写。M5 acceptance transcript 与 SVG 字节保持不变。验收原始 JSON 位于 Git 忽略目录，SHA-256 为 `6870E3EA9BC43B40A9A33E92D84E4EE1C2B9F93F933852A46C6E0AD7B746BA23`，不进入图片或仓库。

## 证据限制

- Current architecture 图是系统边界可视化，不是运行截图。
- Retained CLI 图是确定性本地兼容入口的真实公开文本，不代表当前六异案 Clinic Web 的完整 UI。
- Historical acceptance 图只证明冻结范围内的工程验收，不证明生产分布成功率、跨模型泛化、统计显著性或玩家收益。
- 所有 benchmark 数字、真实模型结论与历史阶段身份必须回到对应冻结报告解释，不从展示图外推。

## 隐私与版权

- SVG 只使用文本、几何图形和通用系统字体栈，不含外部字体、图片、ICC/EXIF 或位置信息。
- 已提交素材不包含用户名、本机绝对路径、API Key、Authorization 头、供应商请求 ID、完整 Prompt 或真实玩家信息。
- 程序代码 `tools/release/render_demo_assets.py` 与 `tools/release/check_portfolio_docs.py` 适用仓库 Apache-2.0 代码许可证。
- 脱敏终端摘录、图表排版和演示素材为 `© 2026 WangYDING. All rights reserved.`；详见 [`../../../CONTENT_RIGHTS.md`](../../../CONTENT_RIGHTS.md)。
