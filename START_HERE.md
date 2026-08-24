# 开始游戏

这里仅说明如何在 Windows + Python 3.12 上启动《异闻行录》本地 Clinic。正式主路线由 DeepSeek `GameNPCAgent` 驱动，需要 API Key 和显式付费授权；长期 Memory 与 Reflection 尚未接入正式路径。当前主路线是玩家与受约束的智能 NPC 组成调查搭档，共同处理六个古风志怪异案。

## 第一次安装

在项目根目录打开 PowerShell：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

## 启动

```powershell
New-Item -ItemType Directory -Force .\runtime_data\clinic | Out-Null
.\.venv\Scripts\yiwen-xinglu.exe --state-dir .\runtime_data\clinic --npc-mode llm --confirm-paid-agent --agent-budget-cny 1.00
```

启动前在项目根目录的 `.env` 中配置 `DEEPSEEK_API_KEY`。LLM 配置、模型发现、授权或预算校验失败时程序会拒绝启动，不会静默切换到离线 NPC。

仅用于离线、测试或调试的显式模式：

```powershell
.\.venv\Scripts\yiwen-xinglu.exe --state-dir .\runtime_data\clinic --npc-mode offline
```

终端会显示一个 `http://127.0.0.1:<端口>/` 地址。用浏览器打开它，创建玩家档案后即可进入 Clinic，与自主 NPC 协作调查案件。服务器只监听本机回环地址。

当前部分 retained teaching UI 仍沿用“弟子”“导师”等历史师承称谓；这些页面文字将在后续 presentation alignment 中处理，不改变本阶段的 Cooperative Game NPC 主定位。

## 保存、恢复与退出

- 页面操作会写入 `runtime_data/clinic/`，它不会进入 Git。
- 下次使用相同命令启动，即可从开始页恢复玩家档案。当前页面按钮可能仍显示历史称谓“恢复弟子”。
- 回到 PowerShell，按 `Ctrl+C` 正常退出。

## 入口边界

`yiwen-xinglu` 是正式玩家产品入口。`xuanyi-clinic` 仅作为旧安装命令的兼容别名保留。

| 类别 | 安装入口 | 边界 |
|---|---|---|
| 玩家 | `yiwen-xinglu` | 正式本地 Clinic；默认显式启用 LLM `GameNPCAgent` |
| 兼容别名 | `xuanyi-clinic` | deprecated alias；与正式命令使用同一 composition root |
| CLI | `xuanyi-play` | 手动玩法与工程调试 |
| MCP | `xuanyi-mcp-stdio` | 本地集成入口 |
| 验收 | `xuanyi-m5-acceptance`、`xuanyi-product-acceptance` | 离线确定性验收 |
| 历史实验 | `xuanyi-case-demo`、`xuanyi-deepseek-models`、`xuanyi-real-mentor-pilot` | 工程证据或显式受控实验，不是玩家入口 |

遇到问题请查看[用户指南](docs/product/R5_CLINIC_USER_GUIDE.md)。项目定位、架构和历史证据不在本页展开，可从 [README](README.md) 和[文档索引](docs/INDEX.md)进入。
