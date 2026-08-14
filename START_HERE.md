# 开始游戏

这里仅说明如何在 Windows + Python 3.12 上启动本地医馆。核心游戏不需要 API Key、GPU、Torch 或 BGE。

## 第一次安装

在项目根目录打开 PowerShell：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

## 启动本地医馆

```powershell
New-Item -ItemType Directory -Force .\runtime_data\clinic | Out-Null
.\.venv\Scripts\xuanyi-clinic.exe --state-dir .\runtime_data\clinic
```

终端会显示一个 `http://127.0.0.1:<端口>/` 地址。用浏览器打开它，创建弟子后即可进入医馆。服务器只监听本机回环地址。

## 保存、恢复与退出

- 页面操作会写入 `runtime_data/clinic/`，它不会进入 Git。
- 下次使用相同命令启动，即可从开始页恢复弟子。
- 回到运行医馆的 PowerShell，按 `Ctrl+C` 正常退出。

## 可选：CLI 工程入口

```powershell
New-Item -ItemType Directory -Force .\runtime_data\play | Out-Null
.\.venv\Scripts\xuanyi-play.exe --state-dir .\runtime_data\play
```

选择 `manual` 由玩家亲自操作；Fake 自动路线只用于回归和演示，不代表真人游玩。

遇到问题请查看[医馆用户指南](docs/product/R5_CLINIC_USER_GUIDE.md)。项目定位、架构和历史证据不在本页展开，可从 [README](README.md) 和[文档索引](docs/INDEX.md)进入。
