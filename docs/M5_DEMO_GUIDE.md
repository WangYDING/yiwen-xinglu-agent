# M5 三病例纵向切片演示指南

本指南面向不熟悉代码的试玩者和面试官。默认使用 `manual/off` 或 `fake/off`，不需要 API Key，不调用 DeepSeek、BGE 或外部服务。

## 演示前准备

在仓库根目录安装项目，并准备 Git 忽略的本地存档目录：

```powershell
New-Item -ItemType Directory -Force .\runtime_data\play | Out-Null
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
```

普通试玩入口：

```powershell
xuanyi-play --case-dir .\data\cases --state-dir .\runtime_data\play
```

离线自动演示入口：

```powershell
xuanyi-play --case-dir .\data\cases --state-dir .\runtime_data\play `
  --mode fake --semantic-shadow off
```

完整工程验收入口使用一个新的空目录，且不会读取 API Key：

```powershell
New-Item -ItemType Directory .\runtime_data\m5_acceptance | Out-Null
xuanyi-m5-acceptance `
  --run-id m5_acceptance_local `
  --case-dir .\data\cases `
  --state-dir .\runtime_data\m5_acceptance `
  --campaign-rules .\data\campaign\cross_episode_rules_v1.json `
  --output .\results\m5_acceptance_local.json `
  --p4b-result .\results\m5_p4b_campaign_20260811.json `
  --p4d-result .\results\m5_p4d_recovery_20260811.json
```

最后一条命令会核对本机 Git 忽略目录中的 P4 历史原始文件 SHA。新克隆若没有这些私有原始文件，仍可运行全部自动测试和普通试玩，但不能伪装成已经核验本机历史文件。

## 3 分钟快速演示

| 时间 | 画面 | 操作与解说 |
|---|---|---|
| 0:00–0:25 | CLI 首页和三个病例目录 | “这是无需 Key 的本地可玩入口。三个病例都由同一个严格病例引擎加载，不在菜单里硬编码答案。” |
| 0:25–1:05 | 选择旧纸伞，Fake 显示逐步公开行动 | “Fake Agent 只是一条演示脚本；每个行动仍通过 AgentAction、公开工具契约、规则引擎和原子存档。” |
| 1:05–1:35 | 玩家历程中出现“契物归属核验” | “成长来自已经提交的 CampaignEvent，不来自模型文本或向量相似度。” |
| 1:35–2:10 | 开始灰灶，展示旧纸伞前史反应和调查建议 | “NPC 会回应玩家已经做过的公开选择，但建议不替玩家执行，也不改变病例答案。” |
| 2:10–2:40 | 月井开场和第二项知识 | “三案可以按推荐顺序连续游玩，也可以无前史独立完成。” |
| 2:40–3:00 | 验收摘要 | “离线验收还会跨进程恢复、重放事件、检查玩家隔离和拒绝零写入；外部调用与费用都是零。” |

如果时间紧，只运行 `xuanyi-m5-acceptance` 并展示摘要；它会用独立子进程逐行动恢复，不依赖预先留在内存中的会话。

## 8～10 分钟面试演示

1. **产品入口（1 分钟）**：创建玩家，展示三个病例和推荐但不锁关的目录。强调用户不需要编辑 JSON、运行测试或配置密钥。
2. **正式状态路径（1.5 分钟）**：manual 执行一个调查，退出；用第二个进程恢复相同玩家和 Session。指出修订与事件没有重复。
3. **三病例 Campaign（2 分钟）**：用 Fake/off 完成旧纸伞、灰灶和月井，展示两项知识、两处历史反应、CampaignEvent 1–3 和 `resolved / 100`。
4. **Agent 安全边界（1 分钟）**：解释模型只能提出 `AgentAction`。参数错误、过早诊断、重复调查和跨玩家恢复均无事件、无修订、文件逐字节不变；MCP 的 9 个工具也复用同一应用边界。
5. **真实模型的诚实迭代（1.5 分钟）**：P4b 中灰灶只完成两个调查后停滞，月井未运行；根因分为通用工具参数契约缺口、拒绝反馈不足和模型策略问题。P4c 增加通用公开行动契约与一次有界修复，不写病例特例。P4d 单次真实案例触发 5 次契约修复且 5 次成功，三案闭环。强调这不是正式成功率。
6. **RAG 负结果与降级（1 分钟）**：M4.5 的本地 BGE 排名主要门槛较好，但返回门禁 micro F1 `0.6667`、更正切片漏召回，因此正式 Prompt 默认关闭语义记忆，只保留 record-only shadow。未通过能力不会污染玩家体验。
7. **可重复证据（1 分钟）**：运行 M5 验收摘要，展示事件重放、跨进程恢复、双玩家隔离、shadow off/on 一致及 P4 历史 SHA 不变。

## 录屏镜头清单

- 仓库 README 的“普通用户交互式游玩”命令；
- CLI 启动画面中的 `manual`、shadow 关闭和“无需 API Key”；
- 三病例目录与推荐下一案；
- 一个调查成功后修订从 0 变为 1；
- 关闭窗口后重新启动，出现“已恢复未完成病例”；
- Fake 每步的公开工具名和执行结果；
- 旧纸伞完成后的“契物归属核验”；
- 灰灶开场的旧案反应；
- 灰灶完成后的“交接顺序核验”；
- 月井开场的灰灶反应；
- M5 验收摘要；
- P4b/P4d 和 M4.5 报告的结论段，避免展示完整 Prompt、供应商请求 ID 或本地路径。

录屏时使用专门的演示玩家，不展示 `.env`、`results/` 原始文件、真实 API Key、供应商请求 ID或个人目录。

## 脱敏示例输出

```text
M5 离线纵向切片验收：通过
- 三病例：均为 8 个连续事件，resolved / 100
- 跨案连续性：Campaign 事件 1–3，两项公开知识已解锁
- 恢复与隔离：独立子进程恢复、双玩家隔离、拒绝零写入均通过
- semantic shadow：record-only 不影响请求、行动或状态
- 外部调用：0；费用：0 CNY
```

## 备用离线方案

如果面试环境不能访问网络，直接使用 manual、Fake 和 M5 验收入口；它们本来就不需要网络。如果显卡或本地 BGE 不可用，不要临时安装模型：展示 M4.5 已保存的脱敏负结果和 shadow 默认关闭决策即可。如果命令入口未刷新，使用 `python -m xuanyi_npc.cli.play` 和 `python -m xuanyi_npc.evaluation.m5_acceptance`，功能相同。

当前演示证明的是本地三病例工程纵向切片，不证明生产并发、网页交付、真实玩家留存、教学收益或真实模型稳定成功率。
