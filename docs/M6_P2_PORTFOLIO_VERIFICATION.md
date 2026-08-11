# M6-P2 项目首页与演示素材验证

> 日期：2026-08-11
>
> 范围：本地 README、架构/Campaign 图、真实终端素材、演示脚本、链接与分发回归。未创建远程，未上传媒体，未运行远程 CI。

## 首页与阅读路径

- README 按项目名、中文定位、英文摘要、三项亮点、60 秒启动、安全架构、Campaign、真实演示、双岗位入口、可复现证据、限制和许可证组织。
- M6-P2 前的详细 README 完整保存在 [`TECHNICAL_OVERVIEW.md`](TECHNICAL_OVERVIEW.md)，历史实验、停止记录和负结果未删除。
- Agent 应用岗与游戏 AI 产品岗分别链接到 [`M5_PORTFOLIO_EVIDENCE.md`](M5_PORTFOLIO_EVIDENCE.md) 和对应 8 分钟演示脚本。
- 首页中的 3 病例、9 MCP 工具、488 测试、三案 8 事件、CampaignEvent 1–3、P4d 5/5 / 费用及 M4.5 负指标均链接到冻结证据。

## 真实素材

三张终端卡片来自实际本地离线 stdout：manual 三病例目录、Fake 旧案知识/灰灶历史反应、M5 验收摘要。原始 stdout 和验收 JSON 留在 Git 忽略目录；提交内容只有脱敏文本、SVG 和 SHA。完整身份见 [`assets/README.md`](assets/README.md)。

- 文本与 SVG 的 6 个提交哈希全部通过；
- 5 个 SVG 均通过 XML 解析；
- 素材不含本机用户路径、Key 变量、Authorization 头、供应商请求 ID、隐藏真值哨兵或完整 Prompt；
- SVG 不含外部字体、图片、EXIF/ICC 或网络资源；
- 生成脚本仅使用 Python 标准库，输出可确定性重建。

## 离线验证

- 作品集文档专项 `4 passed`；本地链接、6 个素材哈希、5 个 SVG XML 与隐私哨兵通过；
- 全量离线测试 `492 passed`（M6-P1 的 `488` 项加 4 项 P2 门禁）；
- M5 自动验收再次通过，Git 忽略结果 SHA-256 为 `FC6DDFBCC7249DA5C22845E1ADB5DE877E31497F4840EEC5A67EEE348E1A005A`；
- 当前 wheel SHA-256 `A60B13CEB50D3B8B15C6DD4E1A06833311C9039AC44070FDB8B4D51DBFCA8243`，252,271 bytes；sdist SHA-256 `A1FD3EFC9BA7780DFD75B4EBDE8EADD860C35960D7B5936018EAE20FF2D5CD93`，310,912 bytes；
- wheel/sdist 包内容审计通过：6 个运行 JSON、4 个授权文件，未包含 docs/assets、结果、状态、模型、向量、数据库、`.env`、虚拟环境、Git 数据或本机绝对路径；
- 当前 wheel 离线重装后在仓库目录外验证三个命令入口、三病例发现和 M5 验收；M6-P1 的全新核心环境安装证据保持有效；
- `pip check`、`git diff --check`、敏感信息和禁止跟踪文件检查通过。

外部调用边界：DeepSeek `/models` 0、Chat 0、本地 BGE 加载 0、Embedding API 0、其他网络模型请求 0，费用 `0 CNY`。

## 结论边界

P2 证明本地首页、链接、素材来源和离线安装回归可核验，不代表远程 CI、跨平台兼容、媒体上传或正式发布已经完成。P4b/P4d 仍是各一次真实工程案例；M4.5 指标仍是合成 Gold 结果；真实玩家收益、生产并发、网页和远程部署未验证。M6-P3 尚未开始。
