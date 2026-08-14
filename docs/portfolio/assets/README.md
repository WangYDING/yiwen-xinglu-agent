# 演示素材来源与隐私记录

本目录中的三张终端图由项目在 2026-08-11 的真实本地离线运行输出生成，不是 AI 合成的运行画面。原始运行文件保留在 Git 忽略的 `results/`，仓库只保存逐行核对后的脱敏摘录、确定性 SVG 和来源哈希。

## 生成流程

1. 使用项目 `.venv` 和包内默认病例运行 `xuanyi-play` / `xuanyi-m5-acceptance`；
2. 只从 stdout 摘录公开内容，去除交互噪声、内部 ID 与本机目录；
3. 人工核对不含未发现线索、隐藏真值、完整 Prompt、请求 ID 或环境变量；
4. 运行 `python tools/release/render_demo_assets.py`，以标准库把 UTF-8 文本确定性渲染为 SVG；
5. 运行 `python tools/release/check_portfolio_docs.py`，复核哈希、SVG XML、链接与隐私哨兵。

## 来源身份

| 素材 | Git 忽略原始 stdout SHA-256 | 已提交脱敏文本 SHA-256 | SVG SHA-256 |
|---|---|---|---|
| 三病例目录与无 Key 启动 | `72F09294230D7F5BD7CF072372AF30D6E5FB15FA79CB46937F0D3C96AAAE9536` | `81AFD803C94298FBDB02E89722BD8C3C597CF068EF49CC2E7E12E9FAB5DD36FC` | `BD2CA006CEB1E1F6E0C2F068E5D5083C444A0A26C7478E8047A9E64F27946A3E` |
| 知识解锁与灰灶历史反应 | `E1ED88BF5AF1AB168BABF038D4E628822B46348AE064DD2682689648149B3694` | `09A6ABE61926E762E0B11667021B361A209E6050D6E17B264D2C5F874F106F59` | `6F55D2D050CE33476B271C40501A6221DA1AA7B426B0F5F84BE9BE864BE7690E` |
| M5 离线验收摘要 | `62E152984BCA849A0FB69B289F064816C5599FE759B39DE8AF4B192DC938A7B6` | `70184C1487266F3497E1DB728B1CFBC72EC0F400165293A095DD04C40D24259D` | `8DBBC41E1FE045E8F5EB1BFEF8170A9B6012E5F58F26E7DCE62AC63C5FDBB729` |

验收原始 JSON 位于 Git 忽略目录，SHA-256 为 `6870E3EA9BC43B40A9A33E92D84E4EE1C2B9F93F933852A46C6E0AD7B746BA23`。它不进入图片，也不提交仓库。

## 隐私与版权

- 三个 SVG 只使用文本、几何图形和通用系统字体栈，不含外部字体、图片、ICC/EXIF 或位置信息。
- 已提交素材不包含用户名、本机绝对路径、API Key、Authorization 头、供应商请求 ID、完整 Prompt 或真实玩家信息。
- 程序代码 `tools/release/render_demo_assets.py` 适用仓库 Apache-2.0 代码许可证。
- 脱敏终端摘录、图表排版和演示素材为 `© 2026 WangYDING. All rights reserved.`；详见 [`../../../CONTENT_RIGHTS.md`](../../../CONTENT_RIGHTS.md)。
