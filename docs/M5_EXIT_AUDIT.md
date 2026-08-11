# M5 工程纵向切片退出审计

## 审计结论

M5 的 13 项最低验收条件全部通过。M5 工程纵向切片完成：项目已经形成一个包含三个病例、确定性跨案连续性、可见成长、结构化 Agent 工具、安全恢复、持久化重放和普通用户 CLI 的本地游戏 AI 纵向切片。

本结论不表示项目已达到生产级游戏，也不表示真实模型具有稳定成功率、语义长期记忆已投入正式玩法、真实玩家留存或教学收益已验证，亦不包含网页、远程部署或大规模并发。

## 自动验收身份

- 入口：`xuanyi-m5-acceptance` / `python -m xuanyi_npc.evaluation.m5_acceptance`
- Schema：`m5_acceptance_v1`，禁止未知字段；输出为脱敏 JSON 和易读摘要。
- 正式路径：Fake 参考 Agent → `ModeAwareEpisodeRunner` → `MultiCaseEpisodeService` → `V0ToolExecutor` / `CaseEngine` → 原子存档 → Campaign 协调。
- 恢复方法：每个有效行动由新的独立 Python 子进程重新加载磁盘 Session 后提交；验收代码不复制病例评分、正确性或 Campaign 规则。
- 外部依赖：无需 API Key，不初始化 DeepSeek、Torch、BGE 或 Embedding；网络请求与费用均为 0。
- 历史完整性：P4b 原始 SHA-256 `EFDC6B37692CAA117B352DD199B52AAFF20D765945E5C8FB585994453B712C2B`；P4d 原始 SHA-256 `24B4105E1607F84FA0E1D15810BAF9051FBAADCEF3D90470411EB7A0543BADD8`。验收只核对，不修改或重跑。
- 本地验收结果：最终代码对应的 Git 忽略文件 `results/m5_acceptance_final_20260811.json`，SHA-256 `4D7A16D6F570FC2854D2D4A3C94B9F7B5FF562210ECE4FCC147F452771536315`。

## 13 项退出条件

| # | 条件 | 结论 | 证据 | 已知限制 |
|---|---|---|---|---|
| 1 | 同一新玩家依次完成三个病例 | 通过 | 自动验收按旧纸伞→灰灶→月井执行；每案 8 个连续事件、`completed / resolved / 100` | 使用冻结 Fake 参考 Agent，不代表真实模型成功率 |
| 2 | 多种合法调查选择，不是硬编码产品路径 | 通过 | 三案初始公开选项均至少 3 个；P2 测试冻结两种合法调查顺序；验收只调用公开服务 | 自动演示本身使用一条参考轨迹 |
| 3 | 至少两个后续场景响应已提交事件 | 通过 | 灰灶引用旧纸伞公开历史，月井引用灰灶公开历史；两处都由 Campaign 规则产生 | 反应是确定性文本，不是生成式自适应剧情 |
| 4 | 退出、重启恢复未完成和已完成进度 | 通过 | 每个行动跨独立子进程恢复；另以两次真实 CLI 进程完成创建、行动、退出和同 Session 恢复 | 尚未验证异常断电后的文件系统级耐久性 |
| 5 | Case/Campaign 事件连续且可重放 | 通过 | 三案各重放 1–8；主 Campaign 从空状态重放 1–3 后与磁盘相同 | 单机 JSON，不是分布式事件系统 |
| 6 | 玩家完全隔离 | 通过 | 第二玩家无前史直接月井并使用中性开场；知识、推荐、Session 分离；越权恢复拒绝且文件不变 | 未验证并发多进程写入竞争 |
| 7 | 参数、规则和重复拒绝零写入 | 通过 | 参数错误、`diagnosis_not_ready`、重复调查和跨玩家恢复均零事件、零修订、文件逐字节不变 | 未穷举所有未来工具类型 |
| 8 | 三病例无 LLM 路径完整运行 | 通过 | Fake 离线三案闭环；manual 可启动；worker 未加载 Torch/BGE | Fake 是回归/演示资产，不是玩家决策模型 |
| 9 | README 提供普通用户 CLI | 通过 | 实际执行 README 的 `xuanyi-play` manual/fake 命令；无需编辑 JSON、测试或 Key | 当前只有本地中文终端界面 |
| 10 | 完整演示或录屏方案 | 通过 | `docs/M5_DEMO_GUIDE.md` 包含 3 分钟、8–10 分钟、镜头、解说、脱敏示例和离线备用方案 | 本阶段未实际录制视频 |
| 11 | 双岗位证据分列 | 通过 | `docs/M5_PORTFOLIO_EVIDENCE.md` 区分工程事实、单次真实案例、合成评测和未验证项 | 尚无外部招聘方或玩家反馈 |
| 12 | 语义记忆默认关闭，shadow 不影响正式路径 | 通过 | off/on 的 Agent 请求字节、行动、事件、Episode 和 Campaign 相同；记录固定三个 `false` | 只证明程序化隔离，不证明模型抵抗注入 |
| 13 | 确定性成长可恢复和重放 | 通过 | `contract_provenance_check`、`handoff_sequence_check` 只由 CampaignEvent 解锁；重启与重放一致 | 当前成长限于两项公开知识，不含关系/技能数值成长 |

## 分层结果

### 游戏与 Campaign

- 主玩家三案分别为事件 1–8、`resolved / 100`；CampaignEvent 为 1–3。
- 解锁两项公开知识：“契物归属核验”和“交接顺序核验”。
- 灰灶和月井各出现一处安全、公开、确定性的前史反应。
- 第二玩家没有前史即可直接完成月井，使用中性开场且不会获得其他玩家知识。

### 恢复与重放

- 三案共 24 个主玩家行动、第二玩家月井 8 个行动，全部由独立 worker 子进程逐步加载和提交；所有进程正常结束。
- 另以两个不同 CLI 子进程验证：第一个创建玩家、开始病例、提交一次调查并退出；第二个恢复同一 Session 和修订，没有重复 Episode 或丢失事件。
- Case 和 Campaign 均从空初态重放到与磁盘完全相同的终态。

### 安全与 shadow

- 四类拒绝检查都满足零事件、零修订和文件逐字节不变。
- record-only shadow 与 off 的请求、行动、Episode 和 Campaign 一致；唯一额外产物是 Git 忽略目录中的脱敏记录。
- 验收 JSON 不包含病例根因、正确性、未发现线索、完整 Prompt、密钥、供应商请求 ID 或真实玩家数据。

## P4 历史边界

P4b 保持“工程与规则安全通过、灰灶行为未完成、月井未运行”；P4d 保持“单次真实案例触发 5 次行动契约修复并完成三案”。P5 没有调用或重跑 DeepSeek，不能用离线 Fake 验收覆盖 P4b，也不能把 P4d 写成正式成功率。

M4.5 的真实 Dense 结论继续为 `closed_with_known_dense_retrieval_limitations`。语义向量记忆默认关闭，只能 record-only shadow；M5 的正式连续性完全来自确定性 Campaign 事件。

## 已知限制

- 本地 JSON/SQLite 不支持并发多进程事务；
- 未验证第三方 MCP Host、HTTP/SSE、认证、远程部署、备份恢复和生产运维；
- 未进行真实玩家测试、可用性研究、留存或教学收益评估；
- DeepSeek 只有少量冻结单次案例，没有正式成功率；
- Fake/BGE 合成 Gold 不代表游戏产品效果；
- 语义记忆未进入正式 Agent Prompt；
- 没有网页、游戏引擎 UI、自适应教学、Reflection 或多 Agent。

## 最终状态

全量 `482 passed`；M5-P2～P5 专项 `91 passed`（P5 `6 passed`）；MCP P0/P1 `22 passed`；V0 Agent、dev 与事件重放组合 `34 passed`。P0 Fake dev、无 LLM Demo、`pip check`、`git diff --check`、敏感信息与运行文件跟踪检查全部通过。

M5-P1～P5 已完成，M5 工程纵向切片关闭。后续阶段尚未开始，必须由新的产品目标和授权单独启动。
